# AGENTS.md

## Purpose

This repository provides async helper classes for crypto trading bots.

When acting as an AI coding agent in this repo, optimize for:

- Keeping `import wrappy` safe without optional extras
- Preserving stable public imports documented in `README.md`
- Adding or updating regression tests under `tests/agent/` for any bug fix
- Avoiding assumptions that optional Lighter or analytics dependencies are installed

## Primary Validation Command

Run this before considering changes complete:

```bash
python scripts/verify_agent_ready.py
```

## Public API Rules

- Preferred exchange imports:
  - `from wrappy import GMO, BitBank, BitFlyer, CoinCheck`
- Preferred Lighter imports:
  - `from wrappy.lighter import LighterDealer, DealerConfig, WsInfo`
- Prefer `wrappy.BitFlyer` over the older `wrappy.bitflyer` alias in new code.
- Do not add unconditional imports of optional dependencies to `wrappy/__init__.py`.

## Optional Dependency Rules

- `lighter-sdk` is optional and only required for `wrappy.lighter`
- analytics packages are optional and only required for analytics helpers in `wrappy.util`
- optional features should fail with an explicit installation hint, not by breaking package import

## Test Scope

Tracked automated tests live in:

- `tests/agent/test_public_api.py`
- `tests/agent/test_base_runtime.py`
- `tests/agent/test_exchange_wrappers.py`

Files under `tests/` outside `tests/agent/` are not the canonical CI suite.

## Documentation Sources

- Human-oriented usage: `README.md`
- LLM-oriented repo summary: `LLM_REPO_GUIDE.md`
- Lighter-specific usage: `wrappy/Lighter/README.md`

Keep those aligned with real exported symbols and supported installation paths.
