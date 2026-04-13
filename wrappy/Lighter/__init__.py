"""Compatibility exports for the original capitalized Lighter package."""

from importlib import import_module

__all__ = ["DealerConfig", "LighterDealer", "WsInfo"]


def __getattr__(name):
    if name in __all__:
        return getattr(import_module("wrappy"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
