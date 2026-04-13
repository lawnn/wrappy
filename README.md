# wrappy

`wrappy` は、暗号資産 bot を作るときに毎回書きがちな処理をまとめた非同期 Python ライブラリです。

たとえば次のような用途を想定しています。

- bot 共通のログ出力
- Discord / LINE への通知
- GMO / BitBank / BitFlyer / CoinCheck の API ラッパー
- Lighter 向けの補助機能
- bot 開発時に使う一部の分析ユーティリティ

## まず最初に読む場所

人間向けの概要と使い方:

- この `README.md`

LLM に読ませるためのリポジトリ要約:

- [LLM_REPO_GUIDE.md](LLM_REPO_GUIDE.md)

AI コーディングエージェント向けの運用ルール:

- [AGENTS.md](AGENTS.md)

AI エージェントにこのリポジトリを触らせる場合は、少なくとも `LLM_REPO_GUIDE.md` と `AGENTS.md` を先に読ませるのが安全です。

## このリポジトリで現在サポートしているもの

- 共通基盤: `Log`, `Notify`, `BotBase`
- 取引所ラッパー: `GMO`, `BitBank`, `BitFlyer`, `CoinCheck`
- オプション機能:
  - `wrappy.lighter`
  - `wrappy.util` の分析用関数

この README では、実際にこのリポジトリに存在する API だけを説明します。

## インストール

コア機能だけ使う場合:

```bash
pip install -U git+https://github.com/lawnn/wrappy.git
```

Lighter も使う場合:

```bash
pip install -U "wrappy[lighter] @ git+https://github.com/lawnn/wrappy.git"
```

分析ユーティリティも使う場合:

```bash
pip install -U "wrappy[analytics] @ git+https://github.com/lawnn/wrappy.git"
```

Lighter と分析ユーティリティをまとめて使う場合:

```bash
pip install -U "wrappy[full] @ git+https://github.com/lawnn/wrappy.git"
```

`full` は `lighter` と `analytics` をまとめた extras です。

## import の考え方

`wrappy` は、オプション依存が入っていなくてもトップレベル import が壊れないようにしてあります。

基本的には次の使い分けで考えると分かりやすいです。

- 取引所ラッパーを使う:
  - `from wrappy import GMO, BitBank, BitFlyer, CoinCheck`
- Lighter を使う:
  - `from wrappy.lighter import LighterDealer, DealerConfig, WsInfo`
- 分析関数を使う:
  - `from wrappy import simple_regression, trades_to_historical`
  - ただし `analytics` extra が必要

もしオプション依存が足りない状態で該当 API を触ると、`wrappy` は「何を install すべきか」を含んだエラーメッセージを返します。

## 設定ファイル

まず `config.json` を用意します。

最小構成の例:

```json
{
  "exchange_name": "demo",
  "bot_name": "sample-bot",
  "log_level": "INFO",
  "log_dir": "log"
}
```

実運用に近い例:

```json
{
  "exchange_name": "gmo",
  "bot_name": "sample-bot",
  "log_level": "INFO",
  "log_dir": "log",
  "line_notify_token": "",
  "discordWebhook": "",
  "gmocoin": ["API_KEY", "API_SECRET"],
  "bitbank": ["API_KEY", "API_SECRET"],
  "bitbank_keys": [
    ["API_KEY", "API_SECRET"]
  ],
  "bitflyer": ["API_KEY", "API_SECRET"]
}
```

各キーの意味:

- `exchange_name`
  - ログファイル名などに使う識別子です。
- `bot_name`
  - bot 名です。ログ出力やファイル名に使われます。
- `log_level`
  - `DEBUG`, `INFO` などの標準的なログレベルです。
- `log_dir`
  - ログファイルの出力先ディレクトリです。
- `line_notify_token`, `discordWebhook`
  - 通知先です。どちらも未設定なら通知は送られず、warning ログだけ出ます。
- `gmocoin`
  - `GMO` を使うときに必要です。
- `bitbank` または `bitbank_keys`
  - `BitBank` を使うときに必要です。`bitbank_keys` は複数 key をローテーションしたいときに使います。
- `bitflyer`
  - `BitFlyer` を使うときに必要です。

## 何が便利なのか

このライブラリは「bot ごとに毎回ゼロから API ラッパーや通知まわりを書く」手間を減らすためのものです。

たとえば、普通なら次のような作業を bot ごとに書くことになります。

- 設定ファイルを読み込む
- logger を初期化する
- Discord や LINE に稼働通知を送る
- 各取引所ごとに違う REST API のエンドポイントを叩く
- 失敗時の例外処理を書く

`wrappy` を使うと、このあたりを共通化した状態から bot ロジックだけに集中できます。

## 使い方の例

### 1. ログと通知だけ使う

これは「取引はまだしないが、bot の起動・停止・例外通知だけ欲しい」というケースです。

```python
import asyncio
from wrappy import BotBase


async def main():
    bot = BotBase("config.json")
    bot.log_info("starting")
    await bot.statusNotify("bot started")


if __name__ == "__main__":
    asyncio.run(main())
```

この例で分かること:

- `BotBase` だけでも logger を使えます。
- 通知先が未設定でもクラッシュせず、warning だけ出して継続します。

### 2. GMO で指値注文する

たとえば「BTC_JPY に 0.01 の指値売買を出したい」という最小例です。

```python
import asyncio
from wrappy import GMO


async def main():
    bot = GMO("config.json", "BTC_JPY")
    result = await bot.limit_order("BUY", 0.01, 100)
    bot.log_info(result)


if __name__ == "__main__":
    asyncio.run(main())
```

この例で分かること:

- `GMO("config.json", "BTC_JPY")` のように、設定ファイルと銘柄を渡して使います。
- 高レベルメソッドは内部で GMO の対応エンドポイントに変換されます。

### 3. BitFlyer で成行注文する

```python
import asyncio
from wrappy import BitFlyer


async def main():
    bot = BitFlyer("config.json", "FX_BTC_JPY")
    result = await bot.market_order("BUY", 0.01)
    bot.log_info(result)


if __name__ == "__main__":
    asyncio.run(main())
```

この例でのポイント:

- 新しいコードでは `BitFlyer` を使うのを推奨します。
- 旧来互換として `wrappy.bitflyer` も残していますが、README では `BitFlyer` を正規名として扱います。

### 4. Lighter を使う

```python
import asyncio
from wrappy.lighter import LighterDealer, WsInfo


async def main():
    ws = await WsInfo.run_overlay_from_config("config.json", overrides={"symbol": "ETH"})
    dealer = await LighterDealer.from_config("config.json", symbol="ETH")

    async with dealer:
        order = await dealer.create_limit_order(price=3000.0, size=0.005)
        print(order)

    await ws.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

この例でのポイント:

- Lighter は optional 機能です。`lighter-sdk` が必要です。
- 新しいコードでは `wrappy.lighter` から import してください。
- Lighter の詳しい説明は [wrappy/Lighter/README.md](wrappy/Lighter/README.md) を参照してください。

## 公開 API

`wrappy` から直接使う公開 API:

- `Log`, `Notify`, `BotBase`
- `GMO`, `BitBank`, `BitFlyer`, `CoinCheck`
- `APIException`, `RequestException`
- `now_jst`, `now_jst_str`, `now_utc`, `now_utc_str`, `now_gmt`, `now_gmt_str`, `fromISOformat`
- `simple_regression`, `plot_corrcoef`, `np_shift`, `np_stack`, `resample_ohlc`, `df_list`, `trades_to_historical`, `Objective`

`wrappy.lighter` から使う公開 API:

- `LighterDealer`, `DealerConfig`, `WsInfo`
- `wrappy.lighter.markets`

## 検証方法

AI エージェント運用も含めた基本検証は、次の 1 コマンドで回せます。

```bash
python scripts/verify_agent_ready.py
```

このコマンドでは次を確認します。

- `wrappy` と `tests/agent` の bytecode compile
- `tests/agent` 配下の回帰テスト
- 一時ディレクトリへのローカル install
- install 後の `import wrappy` と `from wrappy import *`

短い別名コマンドもあります。

```bash
make agent-check
```

## 人間向けの読み方

このリポジトリを初めて読むなら、次の順番が分かりやすいです。

1. `README.md`
2. `config.json` の実例を作る
3. 自分が使いたい取引所クラスを 1 つ選ぶ
4. まずは「ログだけ」「通知だけ」「ticker 取得だけ」など小さい例から試す
5. 問題なければ注文系メソッドに進む

たとえば GMO を使うなら、いきなり複雑な bot ロジックを書くよりも、まずは次の順で確認すると安全です。

1. `GMO("config.json", "BTC_JPY")` が作れる
2. `bot.log_info("hello")` が出る
3. `await bot.statusNotify("hello")` が動く
4. `await bot.fetch_my_position()` のような読み取り系を試す
5. その後で `market_order()` や `limit_order()` に進む

## 制約と注意点

- 取引所 API は外部サービスなので、将来仕様変更される可能性があります。
- Lighter を使うには `lighter-sdk` が必要です。
- 分析関数を使うには `analytics` extra が必要です。
- 両方まとめて入れるなら `full` extra が使えます。
- README にある例は「入口としての最小例」です。実運用では例外処理、レート制限、ポジション管理を別途検討してください。
