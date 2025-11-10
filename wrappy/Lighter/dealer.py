# lighter_dealer.py
# - async with 対応 / 高低レベル両対応 / バッチ送信 / markets.py 連携
# - markets.py があれば market_index / price_scale / size_scale を自動補完（size_scale/base_scale 両対応）
# - 指値は order_expiry を付けない（取引所仕様に合わせる）
# - バッチは SDK の send_tx_batch を使用（内部的には REST）
from __future__ import annotations

import aiohttp
import asyncio
import contextlib
import dataclasses
import inspect
import json
import random
import time
from decimal import Decimal
from collections import deque
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

# ---- lighter SDK ----
try:
    import lighter  # type: ignore
except ImportError as e:
    raise RuntimeError(
        "lighter SDK が見つかりません。'pip install lighter-sdk' で導入してください。"
    ) from e

# ---- markets ----
from . import markets as mkt

import logging


class SafeLogger:
    """wrappy.Log / logging.Logger / 任意オブジェクトをラップして log_* API を提供。"""
    def __init__(self, base: Optional[object] = None, name: str = "LighterDealer"):# wrappy があれば使う
        self._base = base
        self._pylog = logging.getLogger(name)
        if not self._pylog.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            self._pylog.addHandler(h)
            self._pylog.setLevel(logging.INFO)

    def _call(self, method: str, fallback_level: int, msg: str):
        # wrappy.Log 互換
        if self._base and hasattr(self._base, method):
            try:
                getattr(self._base, method)(msg)  # log_info/log_warning/log_error/log_debug
                return
            except Exception:
                pass
        # Python logging 互換
        if fallback_level == logging.INFO:
            self._pylog.info(msg)
        elif fallback_level == logging.WARNING:
            self._pylog.warning(msg)
        elif fallback_level == logging.ERROR:
            self._pylog.error(msg)
        else:
            self._pylog.debug(msg)

    def log_info(self, msg: str): self._call("log_info", logging.INFO, msg)
    def log_warning(self, msg: str): self._call("log_warning", logging.WARNING, msg)
    def log_error(self, msg: str): self._call("log_error", logging.ERROR, msg)
    def log_debug(self, msg: str): self._call("log_debug", logging.DEBUG, msg)


# ===== 抽象インタフェース（既存互換） =====
class DealerBase(object):
    def __init__(self, config, logger: Optional[object] = None):
        self.config = config
        self.logger = SafeLogger(logger)

    async def fetch_order(self, order_id): ...
    async def fetch_open_orders(self): ...
    async def fetch_my_balance(self): ...
    async def fetch_my_position(self): ...
    async def cancel_order(self, order_id): ...
    async def cancel_all_orders(self, except_order_ids=None): ...
    async def create_market_order(self, size): ...
    async def create_limit_order(self, price, size): ...
    async def update_order(self, order_id, price=None, quantity=None): ...
    async def aclose(self): ...


# ===== 設定 =====
@dataclasses.dataclass
class DealerConfig:
    base_url: str
    account_index: int
    l1_private_key: str
    api_keys: List[Dict[str, Any]]  # { api_key_index:int, api_key_private_key:str }

    # 実行モード（バッチ挙動）
    use_websocket: bool = True
    max_ws_batch: int = 20

    # レート制御
    standard_account: bool = True
    ip_weight_per_minute: Optional[int] = None
    jitter_ms: Tuple[int, int] = (50, 150)

    # マーケット
    market_index: Optional[int] = 0  # symbol 指定があれば _ensure_market_index で上書き
    symbol: Optional[str] = None

    # スケール（未指定なら markets.py で補完）
    size_scale: Optional[int] = None
    price_scale: Optional[int] = None

    # 高レベルAPI優先（Signer 経由の create_order 等）
    prefer_high_level: bool = False


class RateLimiter:
    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_per_sec = refill_per_sec
        self.updated_at = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, cost: int) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
                lack = cost - self.tokens
                wait_sec = max(lack / self.refill_per_sec, 0.00001)
                await asyncio.sleep(wait_sec)


class NoncePool:
    """API キーごとに nonce を管理（署名時に“先取り”インクリメント）。"""
    def __init__(self, client: "lighter.ApiClient", account_index: int, apis: List[Dict[str, Any]]):
        self.client = client
        self.account_index = account_index
        self._pool: deque[Dict[str, Any]] = deque()
        for item in apis:
            self._pool.append({
                "api_key_index": int(item["api_key_index"]),
                "api_key_private_key": str(item["api_key_private_key"]),
                "nonce": None,
            })
        self._lock = asyncio.Lock()

    async def take_nonce(self, tx_api: "lighter.TransactionApi", idx: int) -> int:
        async with self._lock:
            item = self._pool[idx]
            if item["nonce"] is None:
                res = await tx_api.next_nonce(
                    account_index=self.account_index,
                    api_key_index=int(item["api_key_index"]),
                )
                cur = int(res["nonce"]) if isinstance(res, dict) else int(getattr(res, "nonce"))
                item["nonce"] = cur
            ret = int(item["nonce"])
            item["nonce"] = ret + 1
            return ret

    async def ensure_nonce(self, tx_api: "lighter.TransactionApi", idx: int) -> int:
        return await self.take_nonce(tx_api, idx)

    def rotate(self) -> int:
        self._pool.rotate(-1); return 0

    def current(self) -> Tuple[int, Dict[str, Any]]:
        return 0, self._pool[0]

    def invalidate(self, idx: int) -> None:
        self._pool[idx]["nonce"] = None


class LighterDealer(DealerBase):
    WEIGHT_SEND = 1

    def __init__(self, config: DealerConfig, logger, client: "lighter.ApiClient"):
        super().__init__(config, logger)
        self.client = client
        self.account_api = lighter.AccountApi(client)  # type: ignore
        self.order_api = lighter.OrderApi(client)      # type: ignore
        self.tx_api = lighter.TransactionApi(client)   # type: ignore
        self._signers: Dict[int, Any] = {}

        # レート上限（体感基準）。standard_account=True はかなり低い。
        weight_per_min = 4000 if not config.standard_account else 60
        self.limiter = RateLimiter(weight_per_min, weight_per_min / 60.0)
        self.nonces = NoncePool(client, config.account_index, config.api_keys)

        # バッチ（use_websocket=True のとき活用。内部的には REST の batch を叩く）
        self._batch_types: List[int] = []
        self._batch_infos: List[Dict[str, Any]] = []
        self._batch_owner_indices: List[int] = []
        self._batch_lock = asyncio.Lock()

        # symbol -> market_index -> scales の順で補完
        self._ensure_market_index()
        self._ensure_scales()

        self._rest_auth_token: Optional[str] = None
        self._rest_auth_expiry: Optional[float] = None  # epoch seconds

        # ---- 追加: バッチ凍結フラグ（自動フラッシュ抑止）----
        self._batch_freeze: bool = False

        # COI -> order_index の簡易キャッシュ
        self._coi_to_order_index: dict[int, int] = {}
        self._coi_lock = asyncio.Lock()

    # ---------- async context ----------
    async def __aenter__(self) -> "LighterDealer":
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    # ---------- lifecycle ----------
    @classmethod
    async def create(cls, cfg: DealerConfig, logger: Optional[object] = None) -> "LighterDealer":
        """ApiClient/SafeLogger を生成して LighterDealer を返すコンストラクタヘルパ。"""
        slogger = SafeLogger(logger)
        configuration = lighter.Configuration(cfg.base_url)
        client = lighter.ApiClient(configuration)
        inst = cls(cfg, slogger, client)
        return inst

    @classmethod
    async def from_config(cls, path: str = "config.json", symbol: str = "ETH", logger: Optional[object] = None):
        # wrappy の Log/Notify を使って JSON を読む
        cfg_dict = None
        if logger is not None and hasattr(logger, "config"):
            cfg_dict = logger.config
        else:
            try:
                from ..log import Log as _Log
                _tmp = _Log(path)
                cfg_dict = _tmp.config
                cfg_dict = cfg_dict.get("Lighter", cfg_dict)  # セクション対応
                logger = logger or _tmp
            except Exception:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    cfg_dict = json.load(f)
                    cfg_dict = cfg_dict.get("Lighter", cfg_dict)  # セクション対応

        dc = DealerConfig(
            base_url      = cfg_dict.get("base_url", "https://mainnet.zklighter.elliot.ai"),
            account_index = int(cfg_dict["account_index"]),
            l1_private_key= cfg_dict["l1_private_key"],
            api_keys      = cfg_dict["api_keys"],
            symbol        = cfg_dict.get("symbol", symbol),
            market_index  = cfg_dict.get("market_index", 0),
            max_ws_batch  = cfg_dict.get("max_ws_batch", 50),
            use_websocket = cfg_dict.get("use_websocket", True),
            prefer_high_level = cfg_dict.get("prefer_high_level", False),
            standard_account = cfg_dict.get("standard_account", True),
            price_scale   = cfg_dict.get("price_scale"),
            size_scale    = cfg_dict.get("size_scale"),
        )
        return await cls.create(dc, logger)

    async def aclose(self):
        # 送信キューが残っていれば送る
        with contextlib.suppress(Exception):
            if self._batch_types:
                await self._flush_batch()

        # Signer のクローズ
        with contextlib.suppress(Exception):
            for s in list(self._signers.values()):
                fn = getattr(s, "close", None)
                if callable(fn):
                    ret = fn()
                    if inspect.isawaitable(ret):
                        await ret
        self._signers.clear()

        # ApiClient 側
        with contextlib.suppress(Exception):
            fn = getattr(self.client, "close", None)
            if callable(fn):
                ret = fn()
                if inspect.isawaitable(ret):
                    await ret

        await asyncio.sleep(0)

    # ---------- public API ----------
    async def fetch_order(self, order_id: str | int) -> Dict[str, Any]:
        await self._sleep_jitter(); await self.limiter.acquire(1)
        req = None
        with contextlib.suppress(Exception):
            req = lighter.ReqGetOrderBookOrders(market_id=self.config.market_index)  # type: ignore
        if req is None:
            req = lighter.ReqGetOrderBookOrders(market_index=self.config.market_index)  # type: ignore
        res = await self.order_api.order_book_orders(req)
        orders = res.get("orders", []) if isinstance(res, dict) else getattr(res, "orders", [])
        oid = str(order_id)
        for o in orders:
            if str(o.get("order_id") or o.get("orderIndex") or o.get("client_order_index")) == oid:
                return o
        return {}

    async def fetch_open_orders(self, market_index: Optional[int] = None) -> List[Dict[str, Any]]:
        await self._sleep_jitter(); await self.limiter.acquire(1)
        auth = await self._get_rest_auth()

        params = {
            "account_index": str(self.config.account_index),
        }
        # サーバ側が market_id フィルタをサポートしているなら付ける（任意）
        if market_index is not None:
            params["market_id"] = str(int(market_index))
        else:
            params["market_id"] = str(int(self.config.market_index))
        params.setdefault("auth", auth)

        url = f"{self.config.base_url}/api/v1/accountActiveOrders"
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url, params=params, headers={"accept": "application/json"}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"activeOrders failed {resp.status}: {text}")
                data = await resp.json()

        # 返却形式に合わせて正規化（docs名的には list を返す想定）
        # 例: {"orders": [...]} or [...]
        orders = data.get("orders", data)

        # ★ ここで COI -> order_index を更新（WSでも同様の更新を入れるとさらに堅牢）
        try:
            async with self._coi_lock:
                for o in orders:
                    coi = o.get("client_order_index") or o.get("client_order_id")
                    oid = o.get("order_index") or o.get("order_id")
                    if coi is not None and oid is not None:
                        self._coi_to_order_index[int(coi)] = int(oid)
        except Exception:
            pass
        return orders

    async def fetch_my_balance(self) -> Dict[str, Any] | str:
        await self._sleep_jitter(); await self.limiter.acquire(1)
        res = await self.account_api.account(by="index", value=str(self.config.account_index))
        data = res if isinstance(res, dict) else json.loads(res.to_json())
        return data['accounts'][0].get("collateral", {})

    async def fetch_my_position(self, symbol: str | None = None) -> Dict[str, Any] | Decimal | None:
        await self._sleep_jitter(); await self.limiter.acquire(1)
        res = await self.account_api.account(by="index", value=str(self.config.account_index))
        data = res if isinstance(res, dict) else json.loads(res.to_json())
        if symbol is None:
            return data['accounts'][0]['positions']
        for p in data['accounts'][0]['positions']:
            if p.get("symbol") == symbol:
                return p["sign"] * Decimal(p["position"])

    async def cancel_order(self, client_order_index: str | int) -> Dict[str, Any]:
        if self.config.prefer_high_level:
            try:
                signer = self._get_signer_from_pool()
                await self._sleep_jitter(); await self.limiter.acquire(self.WEIGHT_SEND)
                return await signer.cancel_order(client_order_index=int(client_order_index))
            except Exception as e:
                self.logger.log_warning(f"high-level cancel 失敗。low-level にフォールバック: {e}")
        idx, key = self.nonces.current()
        nonce = await self.nonces.take_nonce(self.tx_api, idx)
        tx_type, tx_info = self._sign_cancel_order_lowlevel(key, nonce, client_order_index)
        return await self._send_or_enqueue(idx, tx_type, tx_info)

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """
        全銘柄の全注文をキャンセルします.
        """
        # 低レベル署名 → 送信
        idx, key = self.nonces.current()
        nonce = await self.nonces.take_nonce(self.tx_api, idx)
        tx_type, tx_info = self._sign_cancel_all_orders_lowlevel(key, nonce)
        return await self._send_or_enqueue(idx, tx_type, tx_info)

    async def create_market_order(self, size: float, avg_execution_price: Optional[float] = None) -> Dict[str, Any]:
        is_ask = (size < 0)
        qty_int = self._to_base_int(abs(size))
        # 約定価格は片側極端値（実質 IOC 成功を狙うダミー）
        if avg_execution_price is None:
            price_int = 1 if is_ask else 99999999
        else:
            price_int = self._to_price_int(avg_execution_price)
        signer = self._get_signer_from_pool()
        await self._sleep_jitter(); await self.limiter.acquire(self.WEIGHT_SEND)
        return await signer.create_market_order(
            market_index=self.config.market_index,
            client_order_index=self._gen_client_order_index(),
            base_amount=qty_int,
            avg_execution_price=price_int,
            is_ask=is_ask,
            )

    async def create_limit_order(
        self, price: float, size: float, *, nonce_override: Optional[int] = None
        ) -> Dict[str, Any]:
        is_ask = (size < 0)
        qty_int = self._to_base_int(abs(size))
        price_int = self._to_price_int(price)
        coi = self._gen_client_order_index()

        # 高レベル優先
        if nonce_override is None and self.config.prefer_high_level:
            signer = self._get_signer_from_pool()
            try:
                await self._sleep_jitter(); await self.limiter.acquire(self.WEIGHT_SEND)
                order_type = getattr(signer, "ORDER_TYPE_LIMIT", 0)
                tif = getattr(signer, "ORDER_TIME_IN_FORCE_GOOD_TILL_TIME", 1)
                res = await signer.create_order(
                    market_index=self.config.market_index,
                    client_order_index=coi,
                    base_amount=qty_int,
                    price=price_int,
                    is_ask=is_ask,
                    order_type=order_type,
                    time_in_force=tif,
                    reduce_only=False,
                    trigger_price=0,
                )
                r = self._normalize_response(res)
                # 返り値に必ず COI を載せる
                r.setdefault("client_order_index", coi)
                return r
            except Exception as e:
                self.logger.log_warning(f"high-level create_order 失敗。low-level にフォールバック: {e}")

        # 低レベル署名 → 送信
        idx, key = self.nonces.current()
        nonce = nonce_override if nonce_override is not None else await self.nonces.take_nonce(self.tx_api, idx)
        tx_type, tx_info = self._sign_limit_order_lowlevel(
            key, nonce, is_ask, price_int, qty_int, coi
        )
        send_res = await self._send_or_enqueue(idx, tx_type, tx_info)
        r = self._normalize_response(send_res)
        # キュー結果などでも COI を返して呼び出し側が把握できるようにする
        r.setdefault("client_order_index", coi)
        return r

    async def update_order(
        self, order_id: str | int, price: Optional[float], quantity: Optional[float], trigger_price: Optional[float] = None
    ) -> Dict[str, Any]:
        idx, key = self.nonces.current()
        nonce = await self.nonces.take_nonce(self.tx_api, idx)
        price_int = self._to_price_int(price)
        qty_int = self._to_base_int(abs(quantity))
        trigger_price_int = None if trigger_price is None else self._to_price_int(trigger_price)
        tx_type, tx_info = self._sign_update_order_lowlevel(key, nonce, order_id, price_int, qty_int, trigger_price_int)
        return await self._send_or_enqueue(idx, tx_type, tx_info)

    async def get_next_nonce(self, api_key_index: Optional[int] = None) -> int:
        idx, key = self.nonces.current()
        if api_key_index is not None:
            for i, it in enumerate(self.nonces._pool):
                if it["api_key_index"] == api_key_index:
                    idx = i; key = it; break
        res = await self.tx_api.next_nonce(
            account_index=self.config.account_index,
            api_key_index=int(key["api_key_index"]),
        )
        return int(res["nonce"]) if isinstance(res, dict) else int(getattr(res, "nonce"))

    async def _get_rest_auth(self) -> str:
        """REST用の10分Authトークンを取得（キャッシュ＆自動更新）"""
        now = time.time()
        # 期限の60秒前に更新
        if self._rest_auth_token and self._rest_auth_expiry and now < (self._rest_auth_expiry - 60):
            return self._rest_auth_token

        # どのAPIキーで作ってもOK。ここでは現在のプール先頭を利用
        _, key = self.nonces.current()
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        auth, err = signer.create_auth_token_with_expiry(lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY)
        if err:
            raise RuntimeError(f"failed to create auth token: {err}")

        # トークン文字列（Bearerは不要。docsの例では Authorization: <token>）
        self._rest_auth_token = auth
        self._rest_auth_expiry = now + 600  # 目安（SDKが正確なexpiryを返すならそれを使う）
        return self._rest_auth_token

    # ---------- 低レベル署名 ----------
    def _sign_limit_order_lowlevel(
        self,
        key: Dict[str, Any],
        nonce: int,
        is_ask: bool,
        price_int: int,
        qty_int: int,
        coi: int
    ):
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        order_type = getattr(signer, "ORDER_TYPE_LIMIT", 1)
        tif = getattr(signer, "ORDER_TIME_IN_FORCE_GOOD_TILL_TIME", 1)

        tx_info, error = signer.sign_create_order(
            market_index=self.config.market_index,
            client_order_index=coi,
            base_amount=qty_int,
            price=price_int,
            is_ask=is_ask,
            order_type=order_type,
            time_in_force=tif,
            reduce_only=False,
            trigger_price=0,
            nonce=nonce,
        )
        if error:
            raise RuntimeError(f"sign_create_order error: {error}")

        tx_type = getattr(signer, "TX_TYPE_CREATE_ORDER", None)
        if tx_type is None:
            raise RuntimeError("SignerClient に TX_TYPE_CREATE_ORDER が見つかりません。SDK バージョンを確認してください。")

        self._debug_tx_preview("Create Order", tx_type, tx_info)
        return int(tx_type), tx_info

    async def _sign_market_order_lowlevel(
        self, key: Dict[str, Any], nonce: int, is_ask: bool, qty_int: int, avg_execution_price: int,
        reduce_only: bool = False, api_key_index: int = -1
    ):
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        tx_info = await signer.create_order(
            market_index=self.config.market_index,
            client_order_index=self._gen_client_order_index(),
            base_amount=qty_int,
            avg_execution_price=avg_execution_price,
            is_ask=is_ask,
            order_type=signer.ORDER_TYPE_MARKET,
            time_in_force=signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
            order_expiry=signer.DEFAULT_IOC_EXPIRY,
            reduce_only=reduce_only,
            nonce=nonce,
            api_key_index=api_key_index,
        )
        tx_type = getattr(signer, "TX_TYPE_CREATE_ORDER", None)
        if tx_type is None:
            raise RuntimeError("SignerClient に TX_TYPE_CREATE_ORDER が見つかりません。")
        self._debug_tx_preview("Create Market", tx_type, tx_info)
        return int(tx_type), tx_info

    def _sign_cancel_order_lowlevel(self, key: Dict[str, Any], nonce: int, order_id: str | int):
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        tx_info, error = signer.sign_cancel_order(
            market_index=self.config.market_index,
            order_index=int(order_id),
            nonce=nonce,
        )
        if error:
            raise RuntimeError(f"sign_cancel_order error: {error}")
        tx_type = getattr(signer, "TX_TYPE_CANCEL_ORDER", 15)
        if tx_type is None:
            raise RuntimeError("SignerClient に TX_TYPE_CANCEL_ORDER が見つかりません。")
        self._debug_tx_preview("Cancel Order", tx_type, tx_info)
        return int(tx_type), tx_info

    def _sign_cancel_all_orders_lowlevel(self, key: Dict[str, Any], nonce: int):
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        tx_info, error = signer.sign_cancel_all_orders(
            time_in_force=0,
            time=0,
            nonce=nonce,
        )
        if error:
            raise RuntimeError(f"sign_cancel_all_orders error: {error}")
        tx_type = getattr(signer, "TX_TYPE_CANCEL_ALL_ORDERS", 16)
        if tx_type is None:
            raise RuntimeError("SignerClient に TX_TYPE_CANCEL_ALL_ORDERS が見つかりません。")
        self._debug_tx_preview("Cancel All Orders", tx_type, tx_info)
        return int(tx_type), tx_info

    def _sign_update_order_lowlevel(self, key: Dict[str, Any], nonce: int, order_id: str | int,
                                    price_int: Optional[int], qty_int: Optional[int], trigger_price: int = 0):
        signer = self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])
        tx_info, error = signer.sign_modify_order(
            market_index=self.config.market_index,
            order_index=int(order_id),
            base_amount=qty_int if qty_int is not None else 0,
            price=price_int if price_int is not None else 0,
            trigger_price=trigger_price if trigger_price is not None else 0,
            nonce=nonce,
        )
        if error:
            raise RuntimeError(f"sign_modify_order error: {error}")
        tx_type = getattr(signer, "TX_TYPE_MODIFY_ORDER", 17)
        if tx_type is None:
            raise RuntimeError("SignerClient に TX_TYPE_MODIFY_ORDER が見つかりません。")
        self._debug_tx_preview("Modify Order", tx_type, tx_info)
        return int(tx_type), tx_info

    # ---------- 送信 ----------
    async def _send_or_enqueue(self, pool_idx: int, tx_type: int, tx_info: Dict[str, Any]) -> Dict[str, Any]:
        # 高レベル優先モード中の低レベルフォールバックは即送信
        if self.config.prefer_high_level or not self.config.use_websocket:
            await self._sleep_jitter(); await self.limiter.acquire(self.WEIGHT_SEND)
            return await self._send_rest(pool_idx, tx_type, tx_info)

        # WS バッチ（※SDK の send_tx_batch を使うため、内部でも最終的には REST 送信）
        async with self._batch_lock:
            self._batch_types.append(tx_type)
            self._batch_infos.append(tx_info)
            self._batch_owner_indices.append(pool_idx)
            # ★ batch() 中は自動flushを抑止
            if (len(self._batch_types) >= self.config.max_ws_batch) and (not self._batch_freeze):
                return await self._flush_batch()
            else:
                return {"queued": True, "count": len(self._batch_types)}

    async def flush(self):
        if not self._batch_types:
            return {"flushed": 0}
        async with self._batch_lock:
            return await self._flush_batch()

    async def _flush_batch(self) -> Dict[str, Any]:
        if not self._batch_types:
            return {"flushed": 0}
        types = self._batch_types; infos = self._batch_infos
        owners = self._batch_owner_indices
        self._batch_types, self._batch_infos, self._batch_owner_indices = [], [], []
        await self._sleep_jitter(); await self.limiter.acquire(self.WEIGHT_SEND)
        return await self._send_batch(types, infos, owners)

    async def _send_rest(self, pool_idx: int, tx_type: int, tx_info: Dict[str, Any]) -> Dict[str, Any]:
        # 単発でも batch エンドポイントで送る（公式サンプル準拠）
        return await self._send_batch([tx_type], [tx_info], [pool_idx])

    async def _send_batch(self, tx_types: List[int], tx_infos: List[Dict[str, Any]], owners: List[int]) -> Dict[str, Any]:
        tx_types_js = json.dumps(tx_types)
        tx_infos_js = json.dumps(tx_infos)
        res = None
        try:
            res = await self.tx_api.send_tx_batch(tx_types=tx_types_js, tx_infos=tx_infos_js)
            self.logger.log_debug(f"Batch {len(tx_types)} transaction successful: {res}")
        except Exception as e:
            self.logger.log_error(f"Error sending batch transaction {len(tx_types)}: {self._trim_exception(e)}")
        return self._normalize_response(res)

    # =========================================================
    # 追加: 明示的な“1回だけ flush”のためのバッチ・コンテキスト
    # =========================================================
    @asynccontextmanager
    async def batch(self, *, auto_flush: bool = True):
        """
        例:
          async with dealer.batch():
              await dealer._enqueue_cancel_by_order_index(123)
              await dealer._enqueue_limit(price, size)
          # ここで1回だけ flush
        """
        prev = self._batch_freeze
        self._batch_freeze = True
        try:
            yield
        finally:
            self._batch_freeze = prev
            if auto_flush:
                await self.flush()

    # =========================================================
    # 追加: バッチ用の低レベル enqueue ヘルパー（キャンセル/指値）
    # =========================================================
    async def _enqueue_cancel_by_order_index(self, order_index: int) -> Dict[str, Any]:
        """low-level 署名で cancel を“キュー積み”だけ行う（flush はしない）"""
        idx, key = self.nonces.current()
        nonce = await self.nonces.take_nonce(self.tx_api, idx)
        tx_type, tx_info = self._sign_cancel_order_lowlevel(key, nonce, order_index)
        return await self._send_or_enqueue(idx, tx_type, tx_info)

    async def _enqueue_limit(self, price: float, size: float) -> Dict[str, Any]:
        """low-level 署名で指値を“キュー積み”だけ行う（flush はしない）"""
        is_ask = (size < 0)
        qty_int = self._to_base_int(abs(size))
        price_int = self._to_price_int(price)
        coi = self._gen_client_order_index()

        idx, key = self.nonces.current()
        nonce = await self.nonces.take_nonce(self.tx_api, idx)
        tx_type, tx_info = self._sign_limit_order_lowlevel(
            key, nonce, is_ask, price_int, qty_int, coi
        )
        res = await self._send_or_enqueue(idx, tx_type, tx_info)
        r = self._normalize_response(res)
        r.setdefault("client_order_index", coi)
        return r

    # =========================================================
    # 追加: 複数キャンセル＋複数新規指値を“1回のバッチ”で送る高レベル関数
    # =========================================================
    async def batch_cancel_and_create(
        self,
        *,
        cancel_order_indices: Optional[List[int | str]] = None,
        cancel_client_order_indices: Optional[List[int | str]] = None,
        new_limit_orders: Optional[List[Tuple[float, float]]] = None,  # [(price, size), ...]
        fetch_if_unresolved: bool = True,
    ) -> Dict[str, Any]:
        """
        - cancel_order_indices: 取引所の order_index の配列
        - cancel_client_order_indices: COI の配列（内部で order_index に解決）
        - new_limit_orders: [(price, size), ...]（size>0=BUY, size<0=SELL）
        返り値: {"cancels": [...], "creates": [...], "flushed": {...}}
        """
        cancels: List[Dict[str, Any]] = []
        creates: List[Dict[str, Any]] = []

        # 1回の send_tx_batch にまとめる
        async with self.batch(auto_flush=False):
            # 1) COI -> order_index 解決
            resolved_oids: List[int] = []
            if cancel_client_order_indices:
                for coi_raw in cancel_client_order_indices:
                    coi = int(coi_raw)
                    oid = None
                    async with self._coi_lock:
                        oid = self._coi_to_order_index.get(coi)
                    if (oid is None) and fetch_if_unresolved:
                        # 最新 open を取得してから再解決
                        await self.fetch_open_orders()
                        async with self._coi_lock:
                            oid = self._coi_to_order_index.get(coi)
                    if oid is not None:
                        resolved_oids.append(int(oid))
                    else:
                        cancels.append({"client_order_index": coi, "error": "not_found"})

            # 2) 明示の order_index と合流
            if cancel_order_indices:
                resolved_oids.extend(int(x) for x in cancel_order_indices)

            # 3) 先に cancel をキューへ
            for oid in resolved_oids:
                r = await self._enqueue_cancel_by_order_index(int(oid))
                cancels.append({"order_index": int(oid), **r})

            # 4) 次に create をキューへ
            if new_limit_orders:
                for price, size in new_limit_orders:
                    r = await self._enqueue_limit(float(price), float(size))
                    creates.append(r)

            # 5) ここで一発 flush
            flushed = await self.flush()

        return {"cancels": cancels, "creates": creates, "flushed": flushed}

    async def feed_ws_orders(self, orders: list[dict]) -> None:
        """WSで観測した orders を渡すと COI->OID キャッシュを更新"""
        if not orders:
            return
        try:
            async with self._coi_lock:
                for o in orders:
                    coi = o.get("client_order_index") or o.get("client_order_id")
                    oid = o.get("order_index") or o.get("order_id")
                    if coi is not None and oid is not None:
                        self._coi_to_order_index[int(coi)] = int(oid)
        except Exception:
            pass

    async def _resolve_oid_by_coi(self, client_order_index: int, *, fetch_if_unresolved: bool = True) -> Optional[int]:
        coi = int(client_order_index)
        async with self._coi_lock:
            oid = self._coi_to_order_index.get(coi)
        if (oid is None) and fetch_if_unresolved:
            # どうしても無ければ 1 回だけ REST で温める（以後は WS で同期）
            await self.fetch_open_orders()
            async with self._coi_lock:
                oid = self._coi_to_order_index.get(coi)
        return oid

    async def cancel_order_by_coi(self, client_order_index: int, *, fetch_if_unresolved: bool = True):
        oid = await self._resolve_oid_by_coi(client_order_index, fetch_if_unresolved=fetch_if_unresolved)
        if oid is None:
            return {"error": "order_not_found_by_coi", "client_order_index": int(client_order_index)}
        return await self.cancel_order(int(oid))

    async def update_order_by_coi(
        self,
        client_order_index: int,
        price: Optional[float],
        quantity: Optional[float],
        trigger_price: Optional[float] = None,
        *,
        fetch_if_unresolved: bool = True,
    ):
        oid = await self._resolve_oid_by_coi(client_order_index, fetch_if_unresolved=fetch_if_unresolved)
        if oid is None:
            return {"error": "order_not_found_by_coi", "client_order_index": int(client_order_index)}
        return await self.update_order(int(oid), price, quantity, trigger_price)

    # ---------- util ----------
    def _get_signer_from_pool(self):
        _, key = self.nonces.current()
        return self._get_signer(int(key["api_key_index"]), key["api_key_private_key"])

    def _get_signer(self, api_key_index: int, api_key_private_key: str):
        s = self._signers.get(api_key_index)
        if s is None:
            s = lighter.SignerClient(
                url=self.config.base_url,
                private_key=api_key_private_key,
                account_index=self.config.account_index,
                api_key_index=api_key_index,
            )
            self._signers[api_key_index] = s
        return s

    def get_market_info(self, symbol: str, index: bool = True) -> int:
        if index:
            return mkt.find_by_symbol(str(symbol)).get("index", None)
        return mkt.find_by_symbol(str(symbol))

    def _ensure_market_index(self):
        # symbol が指定されていれば優先的に market_index を上書き
        if self.config.symbol and mkt:
            rec = None
            with contextlib.suppress(Exception):
                rec = mkt.find_by_symbol(str(self.config.symbol))
            if rec and rec.get("index") is not None:
                self.config.market_index = int(rec["index"])
        # 最終的な安全デフォルト
        if self.config.market_index is None:
            self.config.market_index = 0

    def _ensure_scales(self):
        """price_scale/size_scale が None のとき markets.py で補完（size_scale/base_scale 両対応）。"""
        ps = self.config.price_scale
        ss = self.config.size_scale
        if (ps is not None) and (ss is not None):
            return
        rec = None
        if mkt:
            with contextlib.suppress(Exception):
                rec = mkt.find_by_index(int(self.config.market_index))  # type: ignore
        if rec:
            if ps is None and rec.get("price_scale") is not None:
                ps = int(rec["price_scale"])
            if ss is None:
                val = rec.get("size_scale", rec.get("base_scale"))
                if val is not None:
                    ss = int(val)
        if ps is None:
            raise ValueError("price_scale が指定されておらず、markets.py でも補完できません。")
        if ss is None:
            raise ValueError("size_scale が指定されておらず、markets.py でも補完できません。")
        self.config.price_scale = ps
        self.config.size_scale = ss
        self.logger.log_info(f"scale set: market_index={self.config.market_index} price_scale={ps} size_scale={ss}")

    async def _sleep_jitter(self):
        lo, hi = self.config.jitter_ms
        await asyncio.sleep(random.uniform(lo, hi) / 1000.0)

    def _to_base_int(self, qty: float) -> int:
        val = int(round(qty * int(self.config.size_scale or 1)))
        if val == 0 and qty > 0:
            self.logger.log_warning("size_scale が小さすぎる可能性があります。")
        return val

    def _to_price_int(self, price: float) -> int:
        val = int(round(price * int(self.config.price_scale or 1)))
        if val == 0 and price > 0:
            self.logger.log_warning("price_scale が小さすぎる可能性があります。")
        return val

    def _gen_client_order_index(self) -> int:
        # 48-bit 制約に収まる COI（上位38bit=時刻ms, 下位10bit=乱数）
        now_ms = int(time.time() * 1000)
        upper = (now_ms & ((1 << 38) - 1)) << 10
        lower = random.getrandbits(10)
        return upper | lower

    def _normalize_response(self, res: Any) -> Dict[str, Any]:
        if isinstance(res, dict):
            return res
        if hasattr(res, "to_json"):
            try:
                return json.loads(res.to_json())  # type: ignore
            except Exception:
                pass
        return {"response": str(res)}

    def _debug_tx_preview(self, title: str, tx_type: Any, tx_info: Dict[str, Any]):
        try:
            logging.getLogger("LighterDealer.tx").debug(
                f"{title} tx_type={tx_type} tx_info={json.dumps(tx_info, ensure_ascii=False)}"
            )
        except Exception:
            pass

    @staticmethod
    def _trim_exception(e: Exception) -> str:
        return str(e).strip().split("\n")[-1]
