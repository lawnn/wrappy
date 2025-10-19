# markets.py
# だれでも共通のマーケット定義。スケール不明は None にしておき、後から追記。
# manage_market() は ["index", "price_scale", "base_scale"] の順で値を返す。
# 使い方:
#   from markets import index_of, symbol_of, get_scales, set_scales, is_configured
#   base_scale, price_scale = get_scales("ETH")  # (10000, 100)
#   set_scales("SOL", price_scale=100, base_scale=100_000)  # ランタイムで追記
#
# 注意:
# - get_scales(strict=True) は price_scale/base_scale が None の場合 ValueError を送出します。
# - 別名(エイリアス)にも対応。例: 1000BONK → kBONK

from __future__ import annotations
from typing import Dict, List, Tuple, Union, Optional
import warnings

IndexLike = Union[int, str]

# 入力のゆらぎを吸収するエイリアス（必要に応じて拡張）
ALIASES: Dict[str, str] = {
    "1000BONK": "kBONK",
    # 例: "1000TOSHI": "kTOSHI",  # 公式呼称が決まったら有効化
}

def manage_market() -> Dict[str, List[Optional[int]]]:
    # ["index", "price_scale", "base_scale"]
    return {
        "MARKETS": ["index", "price_scale", "base_scale"],
        "0G": [84, 10_000, 100],
        "2Z": [88, 100_000, 10],
        "AAVE": [27, 1_000, 1_000],
        "ADA": [39, 100_000, 10],
        "AERO": [65, 100_000, 10],
        "AI16Z": [22, 100_000, 10],
        "APEX": [86, 100_000, 10],
        "APT": [31, 10_000, 100],
        "ARB": [50, 100_000, 10],
        "ASTER": [83, 100_000, 10],
        "AVAX": [9, 10_000, 100],
        "AVNT": [82, 100_000, 10],
        "BCH": [58, 1_000, 1_000],
        "BERA": [20, 100_000, 10],
        "BNB": [25, 10_000, 100],
        "BTC": [1, 10, 100_000],
        "CRO": [73, 100_000, 10],
        "CRV": [36, 100_000, 10],
        "DOGE": [3, 1_000_000, 1],
        "DOLO": [75, 100_000, 10],
        "DOT": [11, 100_000, 10],
        "DYDX": [62, 100_000, 10],
        "EDEN": [89, 100_000, 10],
        "EIGEN": [49, 100_000, 10],
        "ENA": [29, 100_000, 10],
        "ETH": [0, 100, 10_000],
        "ETHFI": [64, 100_000, 10],
        "FARTCOIN": [21, 100_000, 10],
        "FF": [87, 100_000, 10],
        "GMX": [61, 10_000, 100],
        "GRASS": [52, 100_000, 10],
        "HBAR": [59, 100_000, 10],
        "HYPE": [24, 10_000, 100],
        "IP": [34, 10_000, 100],
        "JUP": [26, 100_000, 10],
        "KAITO": [33, 100_000, 10],
        "KBONK": [18, 1_000_000, 1],
        "KFLOKI": [19, 1_000_000, 1],
        "KPEPE": [4, 1_000_000, 1],
        "KSHIB": [17, 1_000_000, 1],
        "KTOSHI": [81, 10_000, 100],
        "LAUNCHCOIN": [54, 1_000_000, 1],
        "LDO": [46, 100_000, 10],
        "LINEA": [76, 1_000_000, 1],
        "LINK": [8, 100_000, 10],
        "LTC": [35, 1_000, 1_000],
        "MKR": [28, 100, 10_000],
        "MNT": [63, 100_000, 10],
        "MON": [91, 100_000, 10],
        "MORPHO": [68, 100_000, 10],
        "MYX": [80, 10_000, 100],
        "NEAR": [10, 100_000, 10],
        "NMR": [74, 10_000, 100],
        "ONDO": [38, 100_000, 10],
        "OP": [55, 100_000, 10],
        "PAXG": [48, 100, 10_000],
        "PENDLE": [37, 10_000, 100],
        "PENGU": [47, 1_000_000, 1],
        "POL": [14, 1_000_000, 1],
        "POPCAT": [23, 100_000, 10],
        "PROVE": [57, 100_000, 10],
        "PUMP": [45, 1_000_000, 1],
        "PYTH": [78, 100_000, 10],
        "RESOLV": [51, 1_000_000, 1],
        "S": [40, 100_000, 10],
        "SEI": [32, 100_000, 10],
        "SKY": [79, 1_000_000, 1],
        "SOL": [2, 1_000, 1_000],
        "SPX": [42, 100_000, 10],
        "STBL": [85, 100_000, 10],
        "SUI": [16, 100_000, 10],
        "SYRUP": [44, 100_000, 10],
        "TAO": [13, 1_000, 1_000],
        "TIA": [67, 100_000, 10],
        "TON": [12, 100_000, 10],
        "TRUMP": [15, 10_000, 100],
        "TRX": [43, 100_000, 10],
        "UNI": [30, 10_000, 100],
        "USELESS": [66, 100_000, 10],
        "VIRTUAL": [41, 100_000, 10],
        "VVV": [69, 10_000, 100],
        "WIF": [5, 100_000, 10],
        "WLD": [6, 100_000, 10],
        "WLFI": [72, 100_000, 10],
        "XMR": [77, 1_000, 1_000],
        "XPL": [71, 100_000, 10],
        "XRP": [7, 1_000_000, 1],
        "YZY": [70, 100_000, 10],
        "ZEC": [90, 1_000, 1_000],
        "ZK": [56, 1_000_000, 1],
        "ZORA": [53, 1_000_000, 1],
        "ZRO": [60, 100_000, 10],
    }

# ---- 内部レジストリ構築 ----
_REG = manage_market()
_HDR = _REG["MARKETS"]  # ["index", "price_scale", "base_scale"]
_SYMBOLS: Dict[str, List[Optional[int]]] = {
    (k.upper()): v for k, v in _REG.items() if k != "MARKETS"
}
# エイリアス適用（別名キー → 正規キー）
for alias, target in list(ALIASES.items()):
    a, t = alias.upper(), target.upper()
    if t in _SYMBOLS and a not in _SYMBOLS:
        _SYMBOLS[a] = _SYMBOLS[t]

_INDEX_TO_SYMBOL: Dict[int, str] = {}
for sym, vals in _SYMBOLS.items():
    idx = int(vals[0])  # type: ignore[arg-type]
    # 重複 index があれば正規名側を優先（先勝ち）
    _INDEX_TO_SYMBOL.setdefault(idx, sym)

# ---- パブリック API ----
def index_of(symbol: str) -> int:
    sym = str(symbol).upper()
    if sym not in _SYMBOLS:
        raise ValueError(f"Unknown symbol: {symbol}")
    return int(_SYMBOLS[sym][0])  # type: ignore[return-value]

def symbol_of(index: int) -> str:
    if index not in _INDEX_TO_SYMBOL:
        raise ValueError(f"Unknown market index: {index}")
    return _INDEX_TO_SYMBOL[index]

def is_configured(x: IndexLike) -> bool:
    """price_scale/base_scale が None でない（=発注可）なら True"""
    try:
        bs, ps = get_scales(x, strict=False)
        return (bs is not None) and (ps is not None)
    except Exception:
        return False

def get_scales(x: IndexLike, *, strict: bool = True,
               default_base_scale: Optional[int] = None,
               default_price_scale: Optional[int] = None) -> Tuple[Optional[int], Optional[int]]:
    """
    戻り値は (base_scale, price_scale)。
    strict=True かつ未設定(None)なら ValueError を送出。
    strict=False の場合、default_* が与えられていればそれを返す（与えられなければ None を返す）。
    """
    if isinstance(x, int):
        sym = symbol_of(x).upper()
    else:
        sym = str(x).upper()
        if sym not in _SYMBOLS:
            raise ValueError(f"Unknown symbol: {x}")

    _, price_scale, base_scale = _SYMBOLS[sym]
    if (base_scale is None or price_scale is None) and strict:
        raise ValueError(
            f"Scales not set for {sym} (index={_SYMBOLS[sym][0]}). "
            f"Set via markets.set_scales('{sym}', price_scale=..., base_scale=...)"
        )

    # strict=False のとき
    if base_scale is None:
        base_scale = default_base_scale
        if base_scale is not None:
            warnings.warn(f"[markets] base_scale for {sym} is not configured; using default {base_scale}.")
    if price_scale is None:
        price_scale = default_price_scale
        if price_scale is not None:
            warnings.warn(f"[markets] price_scale for {sym} is not configured; using default {price_scale}.")

    return (base_scale, price_scale)  # type: ignore[return-value]

def set_scales(x: IndexLike, *, price_scale: int, base_scale: int) -> None:
    """ランタイムでスケールを設定（プロセス内のみ反映。恒久化はファイルを編集してください）。"""
    if isinstance(x, int):
        sym = symbol_of(x).upper()
    else:
        sym = str(x).upper()

    if sym not in _SYMBOLS:
        raise ValueError(f"Unknown symbol: {x}")

    idx = int(_SYMBOLS[sym][0])  # type: ignore[arg-type]
    _SYMBOLS[sym] = [idx, int(price_scale), int(base_scale)]
    # index→symbol の逆引きは変わらない（indexは不変）

def find_by_symbol(symbol: str):
    d = manage_market()
    row = d.get(symbol.upper())
    if not row: return None
    keys = d["MARKETS"]
    return dict(zip(keys, row))

def find_by_index(index: int):
    d = manage_market()
    keys = d["MARKETS"]
    for sym, row in d.items():
        if sym == "MARKETS": continue
        rec = dict(zip(keys, row))
        if rec.get("index") == index:
            rec["symbol"] = sym
            return rec
    return None