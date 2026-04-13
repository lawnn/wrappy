"""Public package exports for wrappy.

The package keeps optional dependencies lazy so `import wrappy` works even when
exchange-specific or analytics extras are not installed.
"""

from importlib import import_module

__version__ = "0.6.0"

_ATTRS = {
    "Log": ("wrappy.log", "Log"),
    "Notify": ("wrappy.notify", "Notify"),
    "BotBase": ("wrappy.base", "BotBase"),
    "GMO": ("wrappy.gmo", "GMO"),
    "BitBank": ("wrappy.bitbank", "BitBank"),
    "bitflyer": ("wrappy.bitflyer", "bitflyer"),
    "BitFlyer": ("wrappy.bitflyer", "bitflyer"),
    "CoinCheck": ("wrappy.coincheck", "CoinCheck"),
    "LighterDealer": ("wrappy.Lighter.dealer", "LighterDealer"),
    "DealerConfig": ("wrappy.Lighter.dealer", "DealerConfig"),
    "WsInfo": ("wrappy.Lighter.ws", "WsInfo"),
    "APIException": ("wrappy.exceptions", "APIException"),
    "RequestException": ("wrappy.exceptions", "RequestException"),
    "now_jst": ("wrappy.time_util", "now_jst"),
    "now_jst_str": ("wrappy.time_util", "now_jst_str"),
    "now_utc": ("wrappy.time_util", "now_utc"),
    "now_utc_str": ("wrappy.time_util", "now_utc_str"),
    "now_gmt": ("wrappy.time_util", "now_gmt"),
    "now_gmt_str": ("wrappy.time_util", "now_gmt_str"),
    "fromISOformat": ("wrappy.time_util", "fromISOformat"),
    "simple_regression": ("wrappy.util", "simple_regression"),
    "plot_corrcoef": ("wrappy.util", "plot_corrcoef"),
    "np_shift": ("wrappy.util", "np_shift"),
    "np_stack": ("wrappy.util", "np_stack"),
    "resample_ohlc": ("wrappy.util", "resample_ohlc"),
    "df_list": ("wrappy.util", "df_list"),
    "trades_to_historical": ("wrappy.util", "trades_to_historical"),
    "Objective": ("wrappy.util", "Objective"),
}

_INSTALL_HINTS = {
    "aiohttp": "pip install aiohttp",
    "lighter": 'pip install "wrappy[lighter]"',
    "matplotlib": 'pip install "wrappy[analytics]"',
    "numpy": 'pip install "wrappy[analytics]"',
    "pandas": 'pip install "wrappy[analytics]"',
    "polars": 'pip install "wrappy[analytics]"',
    "pybotters": "pip install pybotters",
}

__all__ = sorted(
    name for name in _ATTRS if name not in {"DealerConfig", "LighterDealer", "WsInfo"}
)

try:
    from .bitflyer import bitflyer as bitflyer
except ModuleNotFoundError:
    pass


def _missing_dependency_message(name: str, exc: BaseException) -> str:
    dep_name = getattr(exc, "name", None)
    hint = _INSTALL_HINTS.get(dep_name)
    if hint:
        return f"`{name}` requires the optional dependency `{dep_name}`. Install it with `{hint}`."
    if isinstance(exc, RuntimeError) and "lighter SDK" in str(exc):
        hint = _INSTALL_HINTS["lighter"]
        return f"`{name}` requires the optional Lighter SDK. Install it with `{hint}`."
    return str(exc)


def __getattr__(name):
    if name not in _ATTRS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _ATTRS[name]
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(_missing_dependency_message(name, exc)) from exc
    except RuntimeError as exc:
        raise ModuleNotFoundError(_missing_dependency_message(name, exc)) from exc

    value = getattr(module, attribute_name)
    if name == "BitFlyer":
        globals()["bitflyer"] = value
    elif name == "bitflyer":
        globals()["BitFlyer"] = value
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
