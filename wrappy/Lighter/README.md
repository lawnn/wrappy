# Lighter / wrappy 拡張 README（ws.py & LighterDealer 最新版）

`wrappy` に統合された **LighterDealer** と、WebSocketヘルパー **ws.py（`wrappy.lighter.ws`）** の実運用向けガイドです。複数Bot運用時に **config.jsonの書き換えを最小化** し、**COI（client_order_index）中心の売買制御**、**RESTバッチ送信**、**WSの自動トークン更新**、**公開トレードのLTP取得** を簡潔に組み込めます。ロギングは標準 `logging` に一本化（wrappyの Log/Notify と相互運用）。

---

## 目次

1. インストール / 要件
2. 何が新しい？（要点）
3. アーキテクチャ概要
4. クイックスタート（最小例）
5. API リファレンス（必要最小）
6. 公開トレード（LTP）活用
7. COIファースト運用とWSキャッシュ
8. レート制限 / ネットワーク / パフォーマンス
9. ベストプラクティス
10. 追加サンプル集（マルチBot・バッチ・待機）
11. 設定と上書き（config最小化・引数優先・環境変数）
12. トラブルシューティング / FAQ
13. テスト・検証のヒント
14. 変更履歴（抜粋）

---

## 1) インストール / 要件

```bash
pip install lighter-sdk pybotters
# wrappy を自分のプロジェクトにインストール/参照（例）
# pip install wrappy  または  プロジェクト内に配置
```

* Python 3.10+ を推奨
* ネットワーク越しのREST/WSアクセスが可能であること
* `markets.py` がある場合は、`symbol` だけ渡せば `market_index/price_scale/size_scale` を自動補完（`size_scale/base_scale` 両対応）

> 既定の logger は Python 標準 `logging`（`SafeLogger`）が利用されます。wrappy の `Log/Notify` を渡すと同じインターフェイスで動作します。

---

## 2) 何が新しい？（要点）

### ws.py（`wrappy.lighter.ws`）

* **引数だけでWS起動**：`run_overlay(...)`（`symbol`/`market_id`/`account_index`/`api_key_index`/`private_key`）
* **config最小運用**：`run_overlay_from_config(overrides=…)` で重要情報（account/key等）だけ config に置き、残りは呼び出し引数で上書き
* **COI-firstキャッシュ**：`orders` ストリームから `client_order_index → 注文` を保持。`filled/cancelled` は自動掃除
* **公開トレード購読**：`run_public_trades_simple()` → `get_ltp()` / `get_recent_trades(public=True)`
* **堅牢なトークン更新**：`Condition + version` により初回発行/更新レースを解消
* **keepalive / 自動再接続**：指数バックオフ、`finally` クリーンアップ徹底

### LighterDealer

* **COI専用API**：`cancel_order_by_coi()` / `update_order_by_coi()` / `feed_ws_orders()`
* **バッチ一括**：`batch_cancel_and_create()` で複数キャンセル＋複数新規を **1回の send_tx_batch** に集約
* **レート制限の厳格化**：`nextNonce` は `_take_nonce()` を経由し limiter で保護。`send_tx_batch`/`fetch_*` も既にカウント
* **マーケット補完**：`symbol` 指定だけで index/scale を自動解決（`markets.py` が無い場合は明示指定）
* **Authトークン生成はローカル署名**：レートカウント対象外

---

## 3) アーキテクチャ概要

```
┌─────────────┐   orders/trades    ┌──────────────┐
│  ws.WsInfo   ├──────────────────▶│  COI Cache    │
│  (overlay)   │◀──────────────────┤  (in ws)      │
└─────┬────────┘   token refresh   └───────┬────────┘
      │ subscribe/ping                              │ feed_ws_orders()
      ▼                                             ▼
┌─────────────┐   REST batch (send_tx_batch)  ┌──────────────┐
│  Lighter    │──────────────────────────────▶│ Lighter node │
│  Dealer     │◀──────────────────────────────┤  (REST/WS)   │
└─────────────┘   fetch_* / nextNonce          └──────────────┘
```

* WSは **COIキャッシュ** と **LTP等の補助データ** を供給
* Dealerは **送信の集約（バッチ）** と **レート制御** を担当
* COI-only運用：UI/戦略は *COI* を主キーとして、必要時のみRESTで最小補完

---

## 4) クイックスタート（最小例）

### 4.1 config.json を小さく（重要情報のみ）

```jsonc
{
  "Lighter": {
    "base_url": "https://mainnet.zklighter.elliot.ai",
    "account_index": 123456,
    "l1_private_key": "YOUR_L1_KEY",
    "api_keys": [
      {"api_key_index": 2, "api_key_private_key": "YOUR_L2_API_KEY"}
    ]
  }
}
```

### 4.2 WSを引数だけで起動、Dealerはconfigから（symbolは引数）

```python
import asyncio
from wrappy import LighterDealer, DealerConfig
from wrappy.lighter.ws import WsInfo

async def main():
    ws = await WsInfo.run_overlay(
        account_index=123456,
        api_key_index=2,
        api_key_private_key="YOUR_L2_API_KEY",
        symbol="ETH",  # または market_id=0
    )

    dealer = await LighterDealer.from_config("config.json", symbol="ETH")
    ws.on_orders = dealer.feed_ws_orders  # COI→OID解決のウォームアップ

    async with dealer:
        res = await dealer.create_limit_order(price=3000.05, size=+0.005)
        coi = res["client_order_index"]
        await dealer.flush()

        await dealer.update_order_by_coi(coi, price=2999.99, quantity=0.006)
        await dealer.flush()

        await dealer.cancel_order_by_coi(coi)
        await dealer.flush()

    await ws.aclose()

asyncio.run(main())
```

---

## 5) API リファレンス（必要最小）

### ws.py（`wrappy.lighter.ws` → `WsInfo`）

* `run_overlay(account_index, api_key_index, api_key_private_key, *, symbol|market_id, base_url=..., ...) -> WsInfo`

  * 引数のみで口座WS購読。トークン自動更新 / keepalive / 再接続
* `run_overlay_from_config(path="config.json", overrides=...) -> WsInfo`

  * config重要情報 + 引数上書きで購読
* `run_public_trades_simple(symbol|market_id, ...) -> WsInfo`

  * 公開トレード購読。`get_ltp()` / `get_recent_trades(public=True)`
* `get_order_by_coi(coi)`, `wait_order_by_coi(coi, timeout)`

  * COIキャッシュ取得 / 到着待ち
* `on_orders`, `on_trades`, `on_public_trades`

  * 非同期/同期フック（例：`ws.on_orders = dealer.feed_ws_orders`）
* `aclose()`

  * バックグラウンドタスクの安全停止

### LighterDealer

* 生成

  * `await LighterDealer.from_config(path="config.json", symbol="ETH")`
  * `await LighterDealer.create(DealerConfig(..., symbol="ETH"))`
* 主要メソッド

  * `create_limit_order(price, size)` / `create_market_order(size, avg_execution_price=None)`
  * `cancel_order_by_coi(coi)` / `update_order_by_coi(coi, price=None, quantity=None, trigger_price=None)`
  * `batch_cancel_and_create(cancel_client_order_indices=[...], new_limit_orders=[(price,size), ...])`
  * `fetch_open_orders(market_index=None)` / `fetch_my_balance()` / `fetch_my_position(symbol=None)`
  * `flush()` / `aclose()`
* 補助

  * `feed_ws_orders(orders)`：WSの `orders` を渡すと **COI→OID** キャッシュが温まる（`filled/cancelled` 自動掃除）

> 注：`cancel_order(order_index)` / `update_order(order_index, ...)` はCOI-first運用では非推奨。COI専用APIの使用を推奨します。

---

## 6) 公開トレード（LTP）活用

```python
import asyncio
from wrappy.lighter.ws import WsInfo

async def main():
    ws_pub = await WsInfo.run_public_trades_simple(symbol="ETH")
    await asyncio.sleep(1.5)
    print("LTP:", ws_pub.get_ltp())
    print("Recent:", ws_pub.get_recent_trades(5, public=True))
    await ws_pub.aclose()

asyncio.run(main())
```

* `trade/<market>` の `trades` から最新価格を抽出
* LTP更新はWSイベント駆動。RESTポーリング不要 → レート節約

---

## 7) COIファースト運用とWSキャッシュ

* **COI（client_order_index）を主キーに**：新規時にCOIを発行し、WS `orders` 到着でCOI→注文情報をキャッシュ
* **掃除の自動化**：`filled/cancelled/expired` で辞書から即時削除、容量は `deque(maxlen)` でO(1)エビクト
* **待機ユーティリティ**：`wait_order_by_coi(coi, timeout=…)` でWS経由の到着を待つ
* **Dealerとの連携**：`ws.on_orders = dealer.feed_ws_orders` を一度設定すると、RESTの `fetch_order()` を濫用せずに済む

---

## 8) レート制限 / ネットワーク / パフォーマンス

* **カウント対象**：`send_tx_batch`、`fetch_*`、`nextNonce`（※ `_take_nonce()` で必ず limiter 経由）
* **非対象**：Authトークン生成（`create_auth_token_with_expiry` はローカル署名）
* 既定の `standard_account=True` は **~60 weight/min**。厳しい場合は `jitter_ms=(50,150)` の幅拡大、`max_ws_batch` を増やし `flush()` の回数を減らす
* **同時実行の制御**：高頻度更新系は `asyncio.Semaphore` で並列度を制限。例：送信前に `await sem.acquire()` → `finally: sem.release()`
* **丸め精度**：整数スケール変換（`price_scale/size_scale`）を前提に、丸め/切上げ/切下げの戦略を一貫させる

---

## 9) ベストプラクティス

* **COI-first**：RESTの `fetch_order()` は最後の手段。WSキャッシュを優先
* **markets.pyの自動補完**：`symbol` 指定 → index/scale 自動解決。無い環境では `DealerConfig` に `price_scale/size_scale` を明示
* **バッチ送信の活用**：`async with dealer.batch(): ...` で明示的にフラッシュタイミングを制御
* **公開トレードでLTP**：価格参照はWSで取得し、RESTコールを削減
* **キー管理**：APIキーは環境変数や秘密管理を使用し、configへの直書きを避ける

---

## 10) 追加サンプル集

### 10.1 まとめてキャンセル＋新規を1バッチで

```python
result = await dealer.batch_cancel_and_create(
    cancel_client_order_indices=[coi1, coi2],
    new_limit_orders=[(3123.45, +0.005), (3650.00, -0.005)],
)
print(result)
```

### 10.2 バッチコンテキスト（明示フラッシュ）

```python
async with dealer.batch():
    await dealer._enqueue_limit(3001.0, +0.005)
    await dealer._enqueue_limit(2998.0, -0.005)
# ここで自動 flush()
```

### 10.3 COIの到着待ち → 更新 → キャンセル

```python
o = await ws.wait_order_by_coi(coi, timeout=2.0)
if o:
    await dealer.update_order_by_coi(coi, price=3002.0, quantity=0.004)
    await dealer.flush()
    await dealer.cancel_order_by_coi(coi)
    await dealer.flush()
```

### 10.4 マルチBot（config共通・引数差替え）

```python
symbols = ["ETH", "BTC", "SOL"]
for sym in symbols:
    ws = await WsInfo.run_overlay(account_index=ACC, api_key_index=KI, api_key_private_key=KEY, symbol=sym)
    dealer = await LighterDealer.from_config("config.json", symbol=sym)
    ws.on_orders = dealer.feed_ws_orders
    # 各Bot専用の戦略タスクを起動...
```

---

## 11) 設定と上書き（config最小化・引数優先・環境変数）

* **基本方針**：configは *重要情報のみ*（`base_url` / `account_index` / `l1_private_key` / `api_keys`）。`symbol` や `market_id` は **引数で渡す**
* **環境変数例**：

```bash
export LIGHTER_BASE_URL=https://mainnet.zklighter.elliot.ai
export LIGHTER_ACCOUNT_INDEX=123456
export LIGHTER_L1_KEY=...
export LIGHTER_API_KEY_INDEX=2
export LIGHTER_API_KEY=...
```

* **読み込みヒント**：自前で `os.getenv()` → `DealerConfig` へ流し込むか、`from_config()` を使ってから上書き

---

## 12) トラブルシューティング / FAQ

**Q. `order_not_found_by_coi` が出る**
A. WSキャッシュ未同期の可能性。`ws.on_orders = dealer.feed_ws_orders` を設定、もしくは起動直後に1回だけ `fetch_open_orders()` でウォームアップ。

**Q. `price_scale/size_scale が None` エラー**
A. `markets.py` が無い/未対応。`DealerConfig` に `price_scale/size_scale` を明示するか、`symbol` をサポートする `markets.py` を配置。

**Q. HTTP 429（レート制限）**
A. `jitter_ms` を広げる、`max_ws_batch` を増やす、`flush()` の頻度を落とす、`standard_account=False` を検討。

**Q. WSが時々切れる**
A. 既定で指数バックオフ再接続＆keepaliveを送信。プロキシやFWのアイドルタイムアウトがある場合、`ping_interval` を短く。

---

## 13) テスト・検証のヒント

* **ドライラン**：`prefer_high_level=True` にしてSDK経由の高レベル呼び出し挙動を確認
* **送信の可視化**：`logging.getLogger("LighterDealer.tx").setLevel(logging.DEBUG)` でシリアライズ前プレビュー
* **WSの疑似入力**：`ws.on_orders` にテスト用の `orders` 配列を流し、COIキャッシュの掃除/更新を検証
* **丸め誤差テスト**：`price_scale/size_scale` が極端に大きい/小さいケースで数量/価格変換の境界をチェック

---

## 14) 変更履歴（抜粋）

* ws.py: 公開トレード購読とLTP追加、トークン待機のレース解消、COIキャッシュ掃除、指数バックオフ、finallyクリーンアップ
* Dealer: COI専用API追加、`nextNonce` の limiter 統一、バッチAPIの整備、markets補完のログ整備、SafeLoggerの標準化

---

> 本READMEは実運用の観点から **レート制限の回避・COI-first設計・バッチ送信** を重視しています。必要に応じて、最小サンプルを自分の戦略骨格（エントリー/エグジット/リスク管理）に貼り付け、WSキャッシュとDealerのフックを接続するだけで、すぐに検証を始められます。
