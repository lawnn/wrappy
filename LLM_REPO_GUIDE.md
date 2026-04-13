# LLM Repo Guide

## Metadata

```yaml
repo: wrappy
language: python
python: ">=3.10"
package_version: "0.6.0"
primary_goal: "Async helper library for crypto trading bots"
safe_top_level_import: true
optional_dependencies:
  lighter:
    package: "lighter-sdk"
    install: "pip install 'wrappy[lighter]'"
  analytics:
    packages: ["numpy", "pandas", "polars", "matplotlib", "pytz"]
    install: "pip install 'wrappy[analytics]'"
  full:
    includes: ["lighter", "analytics"]
    install: "pip install 'wrappy[full]'"
validation:
  - "python scripts/verify_agent_ready.py"
```

## What Exists

- Core infrastructure:
  - `wrappy.Log`
  - `wrappy.Notify`
  - `wrappy.BotBase`
- Exchange wrappers:
  - `wrappy.GMO`
  - `wrappy.BitBank`
  - `wrappy.BitFlyer`
  - `wrappy.CoinCheck`
- Optional Lighter integration:
  - `wrappy.lighter.LighterDealer`
  - `wrappy.lighter.DealerConfig`
  - `wrappy.lighter.WsInfo`
  - `wrappy.lighter.markets`
- Optional analytics helpers:
  - `wrappy.simple_regression`
  - `wrappy.plot_corrcoef`
  - `wrappy.np_shift`
  - `wrappy.np_stack`
  - `wrappy.resample_ohlc`
  - `wrappy.df_list`
  - `wrappy.trades_to_historical`
  - `wrappy.Objective`

## Import Rules

- `import wrappy` is intended to succeed without `lighter-sdk` or analytics packages.
- Accessing optional symbols should fail with an install hint instead of breaking the package import.
- Prefer `wrappy.lighter` over `wrappy.Lighter` in new code.
- `wrappy.BitFlyer` is the preferred public name. `wrappy.bitflyer` remains as a compatibility alias.

## Config Expectations

The library expects a JSON config file.

Minimum safe shape for common usage:

```json
{
  "exchange_name": "demo",
  "bot_name": "sample-bot",
  "log_level": "INFO",
  "log_dir": "log"
}
```

Additional keys by adapter:

- `GMO`: `gmocoin`
- `BitBank`: `bitbank` or `bitbank_keys`
- `BitFlyer`: `bitflyer`
- `Notify`: `line_notify_token` and/or `discordWebhook`
- `Lighter`: `Lighter` section or top-level equivalent consumed by `wrappy.lighter`

## Safe Usage Guidance For Agents

- Read `AGENTS.md` first when operating as a coding agent.
- Do not assume Lighter support is installed. Check for `lighter-sdk` if using `wrappy.lighter`.
- Do not assume analytics dependencies are installed just because `wrappy` imports successfully.
- If both optional feature sets are needed, `wrappy[full]` is the supported combined install path.
- Prefer README examples that use `limit_order`, not undocumented methods.
- Treat files under `tests/agent/` as the current tracked smoke and regression suite.
- Treat files under `tests/` outside `tests/agent/` as local examples or ad hoc scripts, not canonical automated tests.

## Known Constraints

- Exchange wrappers still depend on third-party HTTP and WS APIs that may change independently of this repo.
- The repo favors async method surfaces and many methods call live services directly.
- There is no fully isolated mock suite for every exchange endpoint; current tracked tests focus on package usability and selected regression risks.
- Notifications are optional. If neither Discord nor LINE is configured, `statusNotify()` logs a warning and returns without sending.

## Current Regression Coverage

- Top-level import without optional dependencies
- Lowercase `wrappy.lighter` compatibility imports
- Optional dependency error messaging
- Notification behavior when channels are unconfigured
- `BotBase.ws()` awaiting the WS client connection
- Logger initialization even when root logging already has handlers
- `BitBank._requests()` notification on server error
- `BitBank` API key rotation when `bitbank_keys` is configured
- `BitBank` margin and spot order payload shapes
- `CoinCheck.fetch_ticker()` retry and failure behavior
- `GMO._requests()` success parsing and fallback error formatting
- `GMO` order, settle, bulk cancel, and edit payload compaction
- `BitFlyer` cancel endpoints propagating HTTP failures
- `BitFlyer.fetch_my_position()` decimal aggregation behavior
- `BitFlyer` market and limit order payload shapes
- single-command repository verification via `scripts/verify_agent_ready.py`
- documentation and export contract checks for `README.md`, `AGENTS.md`, and `LLM_REPO_GUIDE.md`

## When Modifying This Repo

- Preserve the invariant that `import wrappy` should not require optional extras.
- Add tests under `tests/agent/` for any public API regression or bug fix.
- Keep README and this file aligned with real exported symbols.
- Prefer explicit install hints when optional features are unavailable.
