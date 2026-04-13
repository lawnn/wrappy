# wrappy

`wrappy` is an async helper library for crypto trading bots.

The repository currently supports:

- Common bot infrastructure: `Log`, `Notify`, `BotBase`
- Exchange wrappers: `GMO`, `BitBank`, `BitFlyer`, `CoinCheck`
- Optional Lighter integration: `wrappy.lighter`
- Optional analytics helpers in `wrappy.util`

This README is intentionally narrow: it documents only the APIs that exist in this repository today.

## Installation

Core package:

```bash
pip install -U git+https://github.com/lawnn/wrappy.git
```

With Lighter support:

```bash
pip install -U "wrappy[lighter] @ git+https://github.com/lawnn/wrappy.git"
```

With analytics helpers:

```bash
pip install -U "wrappy[analytics] @ git+https://github.com/lawnn/wrappy.git"
```

## Agent-Friendly Import Rules

The package is designed so that `import wrappy` works even if optional dependencies are not installed.

- Use `from wrappy import GMO, BitBank, BitFlyer, CoinCheck` for exchange wrappers
- Use `from wrappy.lighter import LighterDealer, DealerConfig, WsInfo` for Lighter
- Use `from wrappy import simple_regression, trades_to_historical` only if the analytics extra is installed

If an optional dependency is missing, `wrappy` raises an explicit install hint instead of failing during the top-level import.

## Config File

Create a JSON file such as `config.json`.

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

Notes:

- `line_notify_token` and `discordWebhook` are optional
- `statusNotify()` will log a warning and skip notification if neither is configured
- `bitbank_keys` is optional and only needed for key rotation

## Quick Start

### Logging and notifications

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

### GMO limit order

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

### Lighter

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

Lighter-specific details live in [wrappy/Lighter/README.md](wrappy/Lighter/README.md).

## Public API

Stable exports from `wrappy`:

- `Log`, `Notify`, `BotBase`
- `GMO`, `BitBank`, `BitFlyer`, `CoinCheck`
- `APIException`, `RequestException`
- `now_jst`, `now_jst_str`, `now_utc`, `now_utc_str`, `now_gmt`, `now_gmt_str`, `fromISOformat`
- `simple_regression`, `plot_corrcoef`, `np_shift`, `np_stack`, `resample_ohlc`, `df_list`, `trades_to_historical`, `Objective`

Stable exports from `wrappy.lighter`:

- `LighterDealer`, `DealerConfig`, `WsInfo`
- `wrappy.lighter.markets`

## Validation

The repository includes smoke tests aimed at package usability:

```bash
python -m unittest discover -s tests/agent -v
```

## Known Limits

- Exchange APIs are third-party systems and can still change underneath this package
- Lighter support requires `lighter-sdk`
- Analytics helpers require their extra dependencies
