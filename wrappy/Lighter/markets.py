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

        # 代表例（既知スケール）
        "ETH": [0, 100, 10_000],        # 最小price 0.01, 最小size 0.005
        "BTC": [1, 10, 100_000],        # 最小price 0.1 , 最小size 0.0002
        "SOL": [2, 1_000, 1_000],
        "DOGE": [3, None, None],
        "kPEPE": [4, None, None],
        "WIF": [5, None, None],
        "WLD": [6, None, None],
        "XRP": [7, None, None],
        "LINK": [8, None, None],
        "AVAX": [9, None, None],
        "NEAR": [10, None, None],
        "DOT": [11, None, None],
        "TON": [12, None, None],
        "TAO": [13, None, None],
        "POL": [14, None, None],
        "TRUMP": [15, None, None],
        "SUI": [16, None, None],
        "kSHIB": [17, None, None],
        "kBONK": [18, None, None],      # ← 1000BONK の別名
        "kFLOKI": [19, None, None],
        "BERA": [20, None, None],
        "FARTCOIN": [21, None, None],
        "AI16Z": [22, None, None],
        "POPCAT": [23, None, None],
        "HYPE": [24, 100_00, 100],
        "BNB": [25, 100_00, 100],
        "AAVE": [27, None, None],
        "MKR": [28, None, None],
        "SEI": [32, None, None],
        "KAITO": [33, None, None],
        "LTC": [35, None, None],
        "ONDO": [38, None, None],
        "S": [40, None, None],
        "VIRTUAL": [41, None, None],
        "SPX": [42, None, None],
        "TRX": [43, None, None],
        "SYRUP": [44, None, None],
        "LDO": [46, None, None],
        "PENGU": [47, None, None],
        "PAXG": [48, None, None],
        "EIGEN": [49, None, None],
        "ARB": [50, None, None],
        "RESOLV": [51, None, None],
        "GRASS": [52, None, None],
        "ZORA": [53, None, None],
        "LAUNCHCOIN": [54, None, None],
        "PROVE": [57, None, None],
        "DYDX": [62, None, None],
        "MNT": [63, None, None],
        "ETHFI": [64, None, None],
        "USELESS": [66, None, None],
        "TIA": [67, None, None],
        "XPL": [71, None, None],
        "WLFI": [72, None, None],
        "NMR": [74, None, None],
        "DOLO": [75, None, None],
        "XMR": [77, None, None],
        "SKY": [79, None, None],
        "MYX": [80, None, None],
        "1000TOSHI": [81, None, None],  # 公式の kTOSHI 相当ならエイリアス追加を検討
        "ASTER": [83, None, None],
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