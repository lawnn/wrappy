# wrappy.lighter — LighterDealer

Lighter の売買・キャンセル・状態取得を **最小コード** で扱える薄いアダプタです。内部では Lighter SDK の High/Low レベル API、簡易レート制御、ノンス管理、バッチ送信（REST batch）をまとめています。

> **ロギング**: `lighter` は **標準ライブラリ `logging`** を使用します（独自ロガーは DI で注入可）。

---

## 1. 導入方法（Installation）

### 必要要件

* Python 3.11 以上推奨
* 依存: `lighter-sdk`, `aiohttp`

```bash
pip install lighter-sdk aiohttp
```

> wrappy に内包して使う場合は、プロジェクトのセットアップに従ってインストールしてください（例: `pip install "wrappy[lighter]"`）。

### 位置づけ

```
wrappy/
  └─ lighter/
      ├─ dealer.py   # LighterDealer / DealerConfig（本READMEの対象）
      ├─ markets.py  # 市場定義とスケール管理
      └─ ws.py       # WebSocket ヘルパ（任意）
```

---

## 2. すべてのメソッド（名前と役割）

### 2.1 DealerConfig（dataclass）

LighterDealer の構成情報。

| フィールド                  | 型             |          既定 | 役割                                                       |
| ---------------------- | ------------- | ----------: | -------------------------------------------------------- |
| `base_url`             | str           |           – | Lighter API ベース URL                                      |
| `account_index`        | int           |           – | あなたの Lighter アカウント index                                 |
| `l1_private_key`       | str           |           – | L1 秘密鍵（SDK 初期化に必要な場合あり）                                  |
| `api_keys`             | List[Dict]    |           – | `{"api_key_index": int, "api_key_private_key": str}` の配列 |
| `use_websocket`        | bool          |      `True` | 低レベル署名→**キュー**→`flush()` で送信（実体は REST batch）             |
| `max_ws_batch`         | int           |        `20` | 自動 `flush` 閾値（キュー件数）                                     |
| `standard_account`     | bool          |      `True` | 内部 RateLimiter の目安（`True` は低レート想定）                       |
| `ip_weight_per_minute` | Optional[int] |      `None` | 内部レートを外から上書きしたい場合                                        |
| `jitter_ms`            | (int, int)    | `(50, 150)` | 呼び出し分散の揺らぎ（ms）                                           |
| `market_index`         | Optional[int] |         `0` | 取引銘柄 index（`symbol` 指定時は自動上書き）                           |
| `symbol`               | Optional[str] |      `None` | シンボル指定（`markets.py` から index/scale を補完）                  |
| `size_scale`           | Optional[int] |      `None` | 未指定時は `markets.py` で補完（`base_scale` 互換）                  |
| `price_scale`          | Optional[int] |      `None` | 同上                                                       |
| `prefer_high_level`    | bool          |     `False` | `True`: 高レベル API で**即時送信** / `False`: 低レベル署名→バッチ         |

---

### 2.2 LighterDealer（主要クラス）

#### ライフサイクル

* `@classmethod async create(cfg: DealerConfig, logger: Optional[object] = None) -> LighterDealer`

  * インスタンス生成。`logger` 未指定なら `logging.getLogger("LighterDealer")` に出力。
* `@classmethod async from_config(path: str = "config.json", symbol: str = "ETH", logger: Optional[object] = None) -> LighterDealer`

  * JSON から `DealerConfig` を構築して `create()`。`{"Lighter": {...}}` セクションにも対応。
* `async def aclose(self) -> None`

  * バッチ残があれば `flush()`、Signer/Client をクローズ。`async with` で自動実行。
* `async def __aenter__/__aexit__`

  * `async with` をサポート。

#### 情報取得

* `async def fetch_order(self, order_id: str | int) -> Dict[str, Any]`

  * 板/一覧から該当 ID をざっくり検索して返します（自注文専用 API の代替ではありません）。
* `async def fetch_open_orders(self, market_index: Optional[int] = None) -> List[Dict[str, Any]]`

  * アクティブ注文を返却。内部で **COI → order_index** マッピングを更新します。
* `async def fetch_my_balance(self) -> Dict[str, Any] | str`

  * 残高（collateral）を返します。
* `async def fetch_my_position(self, symbol: str | None = None) -> Dict[str, Any] | Decimal | None`

  * 全ポジション or 指定シンボルの符号付き数量を返します。

#### 発注・キャンセル・更新

* `async def create_limit_order(self, price: float, size: float, *, nonce_override: Optional[int] = None) -> Dict[str, Any]`

  * 指値。`size>0`=BUY、`size<0`=SELL。`prefer_high_level=True` なら高レベルで即送信、それ以外は低レベル署名→キュー。戻り値には **`client_order_index` (COI)** を含みます。
* `async def create_market_order(self, size: float, avg_execution_price: Optional[float] = None) -> Dict[str, Any]`

  * 成行相当（IOC）。`avg_execution_price` 未指定時は片側極端価格で IOC 成功を狙います。
* `async def cancel_order(self, order_id: str | int) -> Dict[str, Any]`

  * 個別キャンセル。高レベル優先が有効ならまず高レベルを試行、失敗時は低レベルへフォールバック。
* `async def cancel_all_orders(self) -> Dict[str, Any]`

  * **全銘柄の全注文**をキャンセルします（除外指定なし版）。
* `async def update_order(self, order_id: str | int, price: Optional[float], quantity: Optional[float], trigger_price: Optional[float] = None) -> Dict[str, Any]`

  * 価格/数量/トリガー価格の変更（いずれかを指定）。低レベル署名→キュー。

#### 送信・バッチ

* `async def flush(self) -> Dict[str, Any]`

  * キューに積んだトランザクションを **REST batch** で一括送信します。
* `@asynccontextmanager async def batch(self, *, auto_flush: bool = True)`

  * `async with dealer.batch(): ...` のブロック中は自動 `flush` を抑止。ブロック終了時に 1 回だけ `flush`（`auto_flush=False` で明示制御も可）。
* `async def batch_cancel_and_create(self, *, cancel_order_indices: Optional[List[int | str]] = None, cancel_client_order_indices: Optional[List[int | str]] = None, new_limit_orders: Optional[List[Tuple[float, float]]] = None, fetch_if_unresolved: bool = True) -> Dict[str, Any]`

  * **複数キャンセル**＋**複数新規指値**を **1 回の batch** にまとめて送信。COI 指定のキャンセルは内部で `order_index` に解決（未解決なら `fetch_open_orders()` で取得→再解決）。

#### ユーティリティ

* `async def get_next_nonce(self, api_key_index: Optional[int] = None) -> int`

  * 指定 API キーの `next_nonce` を REST で取得します。

> ※ 内部メソッド（例: `_enqueue_cancel_by_order_index`, `_enqueue_limit`）は **バッチ用ヘルパ**ですが通常は直接呼びません。`batch()` / `batch_cancel_and_create()` を利用してください。

---

## 3. いろいろな使いかた（サンプル / Helper 含む）

### 3.1 クイックスタート（明示構成）

```python
import asyncio, logging
from wrappy import LighterDealer, DealerConfig

logging.basicConfig(level=logging.INFO)

cfg = DealerConfig(
    base_url="https://mainnet.zklighter.elliot.ai",
    account_index=123456,
    l1_private_key="0x...",
    api_keys=[{"api_key_index": 2, "api_key_private_key": "0x..."}],
    symbol="ETH",              # ここから market_index / scale を自動補完
    prefer_high_level=False,    # 低レベル署名→バッチ
    use_websocket=True,
    max_ws_batch=50,
)

async def main():
    dealer = await LighterDealer.create(cfg)
    async with dealer:
        await dealer.create_limit_order(price=3800.05, size=+0.0001)  # BUY
        await dealer.create_limit_order(price=4400.00, size=-0.0001)  # SELL
        r = await dealer.flush()
        print("batch result:", r)

asyncio.run(main())
```

### 3.2 `from_config`（設定ファイルから一発起動）

`config.json` は **トップレベル**または **`{"Lighter": {...}}` セクション**のどちらでも可。

```jsonc
// 例1: トップレベル
{
  "base_url": "https://mainnet.zklighter.elliot.ai",
  "account_index": 123456,
  "l1_private_key": "0x...",
  "api_keys": [{"api_key_index": 2, "api_key_private_key": "0x..."}],
  "symbol": "ETH",
  "use_websocket": true,
  "prefer_high_level": false,
  "max_ws_batch": 50
}
```

```jsonc
// 例2: セクション（wrappy 併用時に便利）
{
  "Lighter": {
    "base_url": "https://mainnet.zklighter.elliot.ai",
    "account_index": 123456,
    "l1_private_key": "0x...",
    "api_keys": [{"api_key_index": 2, "api_key_private_key": "0x..."}],
    "symbol": "ETH"
  }
}
```

```python
import asyncio
from wrappy import LighterDealer

async def main():
    dealer = await LighterDealer.from_config("config.json")
    async with dealer:
        await dealer.create_limit_order(3805.0, +0.0002)
        await dealer.flush()

asyncio.run(main())
```

### 3.3 バッチコンテキスト（1 回だけ flush）

```python
async with (await LighterDealer.from_config("config.json")) as dealer:
    async with dealer.batch():
        await dealer.create_limit_order(3800.0, +0.0001)
        await dealer.create_limit_order(4399.0, -0.0001)
    # ここで 1 回だけ flush が走る
```

### 3.4 複数キャンセル＋複数新規を 1 バッチで送る

```python
res = await dealer.batch_cancel_and_create(
    cancel_client_order_indices=[123456789012],  # COI 指定（内部で order_index に解決）
    cancel_order_indices=[4567, 4568],          # 直指定も可
    new_limit_orders=[(3810.0, +0.0002), (4390.0, -0.0002)],
)
print(res)  # {"cancels":[...], "creates":[...], "flushed":{...}}
```

### 3.5 `update_order` の活用

```python
# 価格だけ変更
await dealer.update_order(order_id=4567, price=3812.0, quantity=None)

# 数量だけ変更（絶対値で指定）
await dealer.update_order(order_id=4567, price=None, quantity=0.0003)

# 価格＋数量＋トリガー価格（任意）
await dealer.update_order(order_id=4567, price=3815.0, quantity=0.0002, trigger_price=3810.0)
```

### 3.6 成行相当（IOC）

```python
# SELL（size<0）。avg_execution_price を省略すると片側極端値を使って IOC を狙います。
await dealer.create_market_order(size=-0.0005)
```

### 3.7 並列発注（TaskGroup）＋最後に flush

```python
import asyncio

async with (await LighterDealer.from_config("config.json")) as dealer:
    async def place_pair(i: int):
        await dealer.create_limit_order(3800.0 + i, +0.0001)
        await dealer.create_limit_order(4400.0 - i, -0.0001)

    async with asyncio.TaskGroup() as tg:
        for i in range(50):
            tg.create_task(place_pair(i))

    await dealer.flush()
```

### 3.8 QPS を概ね守る（簡易スロットリング）

```python
import time

qps = 5
interval = 1.0 / qps
next_at = time.monotonic()

for _ in range(30):
    await dealer.create_limit_order(999999.0, -0.0001)
    next_at += interval
    await asyncio.sleep(max(0.0, next_at - time.monotonic()))

await dealer.flush()
```

---

## ベストプラクティス & 注意事項

* **レート制御**: `standard_account=True` のとき内部 RateLimiter は保守的（目安）。外側でも `Semaphore` / `TaskGroup` 等で並列度を制限してください。
* **スケール補完**: `price_scale` / `size_scale` 未指定時は `markets.py` から補完。桁ズレが生じる場合は `markets.py` を更新。
* **期限系**: 指値は通常 `order_expiry` を付けません。IOC（成行相当）は短い期限設定。
* **COI 解決**: COI→order_index の解決は `fetch_open_orders()` 実行時に内部キャッシュを更新します。
* **ログ**: 既定で `logging.getLogger("LighterDealer")` に出力。必要に応じて `logging.basicConfig` やハンドラを設定。

## 代表的なエラーとヒント

* `invalid expiry`: 期限設定が長すぎる/過ぎている。limit では期限を付けない、IOC は短め。
* `unsupported tx type: for batch operation`: SDK とサーバの型ズレ。Signer の定数を参照し正しく署名。
* **桁ズレ**: `price_scale` / `size_scale` が未対応。`markets.py` を更新。
* **常に即送信される**: `prefer_high_level=True` のまま。バッチしたい場合は `False` に。

---

**Happy hacking & safe trading!**
