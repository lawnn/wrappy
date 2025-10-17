from __future__ import annotations

"""
wrappy.lighter.ws — WebSocket helper for Lighter

- 10分WSトークンの自動発行&更新 (LighterWsTokenManager)
- 購読トークンの“上書き再購読”（接続維持のまま auth 更新）
- position の追従
- orders ストリームを用いた **COI-only 運用**（client_order_index を主キーに扱う）
- Dealer 等の外部へ渡す on_orders / on_trades / on_public_trades フック（async/sync両対応）
- COI の上限を deque(maxlen) で制限（O(1) evict）
- **public trades（trade/<market_id>）のサポート**: LTP（last traded price）と直近のパブリック約定を保持
- **改良点（本版）**:
  - aclose() による明示終了
  - 指数バックオフ再接続
  - COIごとの待機（Condition+version、リーク無し）
  - 終了系をdequeに入れない
  - 引数優先のオーバーライド（symbol/market_id/base_url/account/api_key を引数で指定）
  - keepaliveの共通化
  - finallyでの確実なタスク/リソース解放
  - Token更新通知を Condition + version で多待機者対応
  - tradesリスト容量を引数で調整可 + 軽量スナップショットAPI

依存: pybotters, lighter, 標準 logging
"""

import asyncio
import contextlib
import logging
import random
import time
from collections import deque
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Set

import lighter
import pybotters

# Lighter メインネット WS エンドポイント
WS_URL = "wss://mainnet.zklighter.elliot.ai/stream"


# -------------------------
# config loader helpers
# -------------------------

def _read_lighter_config(path: str = "config.json", logger: Optional[object] = None) -> Dict[str, Any]:
    """config.json から Lighter セクションを読み出す（トップ/{"Lighter": {...}} 両対応）。"""
    cfg_dict: Dict[str, Any]
    if logger is not None and hasattr(logger, "config"):
        cfg_dict = getattr(logger, "config")
    else:
        try:
            from ..log import Log as _Log  # wrappy がある場合
            _tmp = _Log(path)
            cfg_dict = _tmp.config
        except Exception as e:
            logging.getLogger("wrappy.lighter.ws").debug(f"_read_lighter_config: fallback json load due to {e!r}")
            import json
            with open(path, "r", encoding="utf-8") as f:
                cfg_dict = json.load(f)
    return cfg_dict.get("Lighter", cfg_dict)


def _resolve_market_index_from_any(
    *, cfg: Optional[Dict[str, Any]] = None, symbol: Optional[str] = None, market_id: Optional[int] = None
) -> int:
    """優先順位: 引数 market_id > 引数 symbol > cfg.market_index > cfg.symbol > 既定0"""
    if market_id is not None:
        return int(market_id)
    try:
        from . import markets as mkt  # 相対 import（無ければフォールバック）
    except Exception:
        mkt = None  # type: ignore
    if symbol and mkt:
        try:
            rec = mkt.find_by_symbol(str(symbol))
            if rec and rec.get("index") is not None:
                return int(rec["index"])
        except Exception:
            pass
    if cfg:
        if cfg.get("market_index") is not None:
            return int(cfg["market_index"])
        sym = cfg.get("symbol")
        if sym and mkt:
            try:
                rec = mkt.find_by_symbol(str(sym))
                if rec and rec.get("index") is not None:
                    return int(rec["index"])
            except Exception:
                pass
    return 0


def _pick_api_key(cfg: Dict[str, Any], *, api_key_index: Optional[int] = None,
                  api_key_private_key: Optional[str] = None) -> Tuple[int, str]:
    """引数があればそれを優先し、無ければ config の先頭を採用。"""
    if api_key_index is not None and api_key_private_key is not None:
        return int(api_key_index), str(api_key_private_key)
    apis = cfg.get("api_keys") or []
    if not apis:
        raise ValueError("config.json の api_keys が空です（引数で api_key_index/private_key を指定することも可能）")
    first = apis[0]
    return int(first["api_key_index"]), str(first["api_key_private_key"])


async def _maybe_await(fn: Optional[Callable[[List[dict]], Any]], payload: List[dict]) -> None:
    if fn is None:
        return
    try:
        ret = fn(payload)
        if asyncio.iscoroutine(ret):
            await ret  # type: ignore[func-returns-value]
    except Exception:
        # フックは落としてもWSを止めない
        logging.getLogger("wrappy.lighter.ws").debug("hook error", exc_info=True)


class LighterWsTokenManager:
    """Lighter の 10分 WS トークンを自動発行＆更新するヘルパー（多待機者対応）。"""

    def __init__(
        self,
        *,
        base_url: str,
        account_index: int,
        api_key_index: int,
        api_key_private_key: str,
        renew_leeway_sec: int = 120,
        jitter_sec: Tuple[int, int] = (3, 12),
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = base_url
        self.account_index = account_index
        self.api_key_index = api_key_index
        self.api_key_private_key = api_key_private_key
        self.renew_leeway_sec = max(0, renew_leeway_sec)
        self.jitter_sec = jitter_sec
        self.log = logger or logging.getLogger("LighterWsTokenManager")

        self._signer: Optional[lighter.SignerClient] = None
        self._token: Optional[str] = None
        self._expires_at_epoch: Optional[int] = None

        # バージョン化された更新通知（多待機者安全）
        self._tok_lock = asyncio.Lock()
        self._tok_cond = asyncio.Condition(self._tok_lock)
        self._tok_version = 0

        self._bg_task: Optional[asyncio.Task] = None
        self._closed = False

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    async def start(self) -> None:
        if self._bg_task:
            return
        self._closed = False  # 再始動可
        self._signer = lighter.SignerClient(
            url=self.base_url,
            private_key=self.api_key_private_key,
            account_index=self.account_index,
            api_key_index=self.api_key_index,
        )
        err = self._signer.check_client()
        if err:
            raise RuntimeError(f"SignerClient configuration error: {err}")

        await self._issue_new_token()
        self._bg_task = asyncio.create_task(self._refresh_loop(), name="lighter-ws-token-refresh")

    async def stop(self) -> None:
        self._closed = True
        if self._bg_task:
            self._bg_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._bg_task
            self._bg_task = None
        if self._signer:
            with contextlib.suppress(Exception):
                ret = self._signer.close()
                if asyncio.iscoroutine(ret):
                    await ret
            self._signer = None

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def expires_at(self) -> Optional[int]:
        return self._expires_at_epoch

    @property
    def version(self) -> int:
        return self._tok_version

    async def wait_for_refresh(self, timeout: Optional[float] = None, since: Optional[int] = None) -> Optional[str]:
        """`since` で指定したバージョンより新しいトークンが出るまで待つ。
        `since` 未指定なら、未発行時のみ初回発行を待つ。既に発行済みなら**即時**返す。"""
        async with self._tok_lock:
            end_at = None if timeout is None else time.time() + timeout

            # since 未指定: 初回発行を安全に待つ
            if since is None:
                if self._token is not None:
                    return self._token
                # 初回発行待ちループ（タイムアウト対応）
                while True:
                    rem = None if end_at is None else max(0.0, end_at - time.time())
                    if rem is not None and rem <= 0:
                        return None
                    try:
                        await asyncio.wait_for(self._tok_cond.wait(), timeout=rem)
                    except asyncio.TimeoutError:
                        return None
                    if self._token is not None:
                        return self._token

            # since 指定あり: バージョン前進を待つ
            while True:
                if self._tok_version > since:
                    return self._token
                rem = None if end_at is None else max(0.0, end_at - time.time())
                try:
                    await asyncio.wait_for(self._tok_cond.wait(), timeout=rem)
                except asyncio.TimeoutError:
                    return None

    async def _refresh_loop(self) -> None:
        while not self._closed:
            now = time.time()
            target = (self._expires_at_epoch or int(now) + 480) - self.renew_leeway_sec
            jitter = random.uniform(self.jitter_sec[0], self.jitter_sec[1])
            sleep_for = max(1.0, target - now + jitter)
            try:
                await asyncio.sleep(sleep_for)
                await self._issue_new_token()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.log.warning(f"token refresh failed: {e!r}; retry in 15s")
                await asyncio.sleep(15.0)

    async def _issue_new_token(self) -> None:
        assert self._signer is not None
        token, err = self._signer.create_auth_token_with_expiry(
            lighter.SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY
        )
        if err:
            raise RuntimeError(f"failed to create auth token: {err}")

        async with self._tok_lock:
            self._token = token
            self._expires_at_epoch = int(time.time()) + 600
            self._tok_version += 1
            self._tok_cond.notify_all()
        ttl = (self._expires_at_epoch or 0) - int(time.time())
        logging.getLogger("LighterWsTokenManager").debug(f"WS auth token issued (~{ttl}s valid)")


# -------------------------
# WsInfo
# -------------------------


class WsInfo:
    """WSメッセージの最小まとめ（COI-first）。"""

    def __init__(
        self,
        *,
        coi_capacity: int = 8192,
        acct_trades_capacity: int = 4096,
        public_trades_capacity: int = 2048,
    ) -> None:
        self.pos = Decimal("0")

        # COI→注文 の軽量キャッシュ（cancel を COI だけで行う運用に最適化）
        self.order_by_coi: Dict[int, dict] = {}
        # OID→注文（任意）
        self.orders_by_index: Dict[int, dict] = {}

        # 到着順の COI リングバッファ（上限）
        self._coi_queue: deque[int] = deque(maxlen=coi_capacity)

        # 直近の（自口座）trades（任意・分析用）
        self.recent_trades: deque[dict] = deque(maxlen=acct_trades_capacity)

        # 直近の（パブリック）trades と LTP
        self.public_trades: deque[dict] = deque(maxlen=public_trades_capacity)
        self.ltp: Optional[Decimal] = None

        # 競合制御 / COI更新通知（Condition + version）。同一ロックで整合。
        self._lock = asyncio.Lock()
        self._coi_cond = asyncio.Condition(self._lock)
        self._coi_version: Dict[int, int] = {}

        # 外部フック（async/sync両対応）
        self.on_orders: Optional[Callable[[List[dict]], Awaitable[None] | None]] = None
        self.on_trades: Optional[Callable[[List[dict]], Awaitable[None] | None]] = None
        self.on_public_trades: Optional[Callable[[List[dict]], Awaitable[None] | None]] = None

        # バックグラウンドタスク管理
        self._tasks: Set[asyncio.Task] = set()

    # ---------- lifecycle ----------
    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()

    # ---------- convenience (no-config) ----------
    @classmethod
    async def run_overlay(
        cls,
        *,
        account_index: int,
        api_key_index: int,
        api_key_private_key: str,
        symbol: Optional[str] = None,
        market_id: Optional[int] = None,
        base_url: str = "https://mainnet.zklighter.elliot.ai",
        coi_capacity: int = 8192,
        acct_trades_capacity: int = 4096,
        public_trades_capacity: int = 2048,
        ping_interval: float = 25.0,
    ) -> "WsInfo":
        mid = _resolve_market_index_from_any(symbol=symbol, market_id=market_id)
        ws = cls(coi_capacity=coi_capacity,
                 acct_trades_capacity=acct_trades_capacity,
                 public_trades_capacity=public_trades_capacity)
        ws._spawn(ws._account_stream_loop(
            market_id=mid,
            account_index=int(account_index),
            base_url=base_url,
            api_key_index=int(api_key_index),
            api_key_private_key=str(api_key_private_key),
            ping_interval=ping_interval,
        ), name="lighter_ws_account")
        return ws

    @classmethod
    async def run_public_trades_simple(
        cls,
        *,
        symbol: Optional[str] = None,
        market_id: Optional[int] = None,
        coi_capacity: int = 8192,
        acct_trades_capacity: int = 4096,
        public_trades_capacity: int = 2048,
        ping_interval: float = 25.0,
    ) -> "WsInfo":
        mid = _resolve_market_index_from_any(symbol=symbol, market_id=market_id)
        ws = cls(coi_capacity=coi_capacity,
                 acct_trades_capacity=acct_trades_capacity,
                 public_trades_capacity=public_trades_capacity)
        ws._spawn(ws._public_trades_loop(market_id=mid, ping_interval=ping_interval),
                  name="lighter_ws_public_trades")
        return ws

    # ---------- convenience (config.json with overrides) ----------
    @classmethod
    async def run_overlay_from_config(
        cls,
        path: str = "config.json",
        *,
        # overrides（引数があればconfigより優先）
        symbol: Optional[str] = None,
        market_id: Optional[int] = None,
        base_url: Optional[str] = None,
        account_index: Optional[int] = None,
        api_key_index: Optional[int] = None,
        api_key_private_key: Optional[str] = None,
        coi_capacity: int = 8192,
        acct_trades_capacity: int = 4096,
        public_trades_capacity: int = 2048,
        ping_interval: float = 25.0,
        logger: Optional[object] = None,
    ) -> "WsInfo":
        cfg = _read_lighter_config(path, logger=logger)
        mid = _resolve_market_index_from_any(cfg=cfg, symbol=symbol, market_id=market_id)
        burl = base_url or cfg.get("base_url", "https://mainnet.zklighter.elliot.ai")
        acct = int(account_index if account_index is not None else cfg["account_index"])
        k_index, k_priv = _pick_api_key(cfg, api_key_index=api_key_index, api_key_private_key=api_key_private_key)
        ws = cls(coi_capacity=coi_capacity,
                 acct_trades_capacity=acct_trades_capacity,
                 public_trades_capacity=public_trades_capacity)
        ws._spawn(ws._account_stream_loop(
            market_id=mid,
            account_index=acct,
            base_url=burl,
            api_key_index=k_index,
            api_key_private_key=k_priv,
            ping_interval=ping_interval,
        ), name="lighter_ws_account")
        return ws

    @classmethod
    async def run_public_trades_from_config(
        cls,
        path: str = "config.json",
        *,
        # overrides
        symbol: Optional[str] = None,
        market_id: Optional[int] = None,
        coi_capacity: int = 8192,
        acct_trades_capacity: int = 4096,
        public_trades_capacity: int = 2048,
        ping_interval: float = 25.0,
        logger: Optional[object] = None,
    ) -> "WsInfo":
        cfg = _read_lighter_config(path, logger=logger)
        mid = _resolve_market_index_from_any(cfg=cfg, symbol=symbol, market_id=market_id)
        ws = cls(coi_capacity=coi_capacity,
                 acct_trades_capacity=acct_trades_capacity,
                 public_trades_capacity=public_trades_capacity)
        ws._spawn(ws._public_trades_loop(market_id=mid, ping_interval=ping_interval),
                  name="lighter_ws_public_trades")
        return ws


    async def run_public_trades(self, market_id: int, ping_interval: float = 25.0) -> None:
        await self._public_trades_loop(market_id=market_id, ping_interval=ping_interval)

    # ---------- lightweight snapshot APIs ----------
    def get_ltp(self) -> Optional[Decimal]:
        return self.ltp

    def get_recent_trades(self, n: int = 50, *, public: bool = False) -> List[dict]:
        dq = self.public_trades if public else self.recent_trades
        # ロック不要：deque は append専用、読み出しはコピー
        if n <= 0:
            return []
        # 末尾 n 件をリスト化
        return list(dq)[-n:]

    async def get_order_by_coi(self, client_order_index: int) -> Optional[dict]:
        async with self._lock:
            return self.order_by_coi.get(int(client_order_index))

    async def wait_order_by_coi(self, client_order_index: int, timeout: Optional[float] = None) -> Optional[dict]:
        coi = int(client_order_index)
        async with self._lock:
            o = self.order_by_coi.get(coi)
            if o is not None:
                return o
            version0 = self._coi_version.get(coi, 0)
        end_at = None if timeout is None else time.time() + timeout
        while True:
            remaining = None if end_at is None else max(0.0, end_at - time.time())
            try:
                async with self._coi_cond:
                    await asyncio.wait_for(self._coi_cond.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            async with self._lock:
                if self._coi_version.get(coi, 0) != version0:
                    return self.order_by_coi.get(coi)

    # ---------- helpers ----------
    def _spawn(self, coro: Awaitable[Any], *, name: str) -> None:
        t = asyncio.create_task(coro, name=name)
        self._tasks.add(t)
        def _done(_):
            self._tasks.discard(t)
        t.add_done_callback(_done)

    def _start_keepalive(self, ping_interval: float, send_fn: Callable[[], Awaitable[Any]]) -> asyncio.Task:
        async def keepalive() -> None:
            if ping_interval <= 0:
                return
            while True:
                await asyncio.sleep(ping_interval)
                try:
                    await send_fn()
                except Exception:
                    break
        return asyncio.create_task(keepalive(), name="ws-keepalive")

    # ---------- internal loops ----------
    async def _account_stream_loop(
        self,
        *,
        market_id: int,
        account_index: int,
        base_url: str,
        api_key_index: int,
        api_key_private_key: str,
        ping_interval: float = 25.0,
    ) -> None:
        log = logging.getLogger("WS.account")
        backoff = 1.0
        while True:
            try:
                async with LighterWsTokenManager(
                    base_url=base_url,
                    account_index=account_index,
                    api_key_index=api_key_index,
                    api_key_private_key=api_key_private_key,
                    renew_leeway_sec=120,
                ) as auth:
                    # 初回トークンは即取得
                    token = auth.token or await auth.wait_for_refresh(timeout=10.0)
                    if not token:
                        raise RuntimeError("no token")

                    que = pybotters.WebSocketQueue()
                    async with pybotters.Client(apis={}) as client:
                        runner = await client.ws_connect(
                            WS_URL,
                            send_json={
                                "type": "subscribe",
                                "channel": f"account_market/{market_id}/{account_index}",
                                "auth": token,
                            },
                            hdlr_json=que.onmessage,
                        )
                        send_lock = asyncio.Lock()
                        last_ver = auth.version

                        async def resubscribe_with_latest_token() -> None:
                            nonlocal last_ver
                            latest = await auth.wait_for_refresh(timeout=10.0, since=last_ver)
                            if not latest:
                                log.warning("token refresh awaited but still None")
                                return
                            last_ver = auth.version
                            try:
                                async with send_lock:
                                    await runner.ws.send_json({
                                        "type": "subscribe",
                                        "channel": f"account_market/{market_id}/{account_index}",
                                        "auth": latest,
                                    })
                                log.info("re-subscribed with UPDATED auth token (connection kept)")
                            except Exception:
                                with contextlib.suppress(Exception):
                                    await runner.ws.close()

                        async def overlay_refresher() -> None:
                            while True:
                                await resubscribe_with_latest_token()

                        async def send_ping() -> None:
                            async with send_lock:
                                await runner.ws.send_json({"type": "ping"})

                        async def consume() -> None:
                            async for msg in que:
                                if not isinstance(msg, dict):
                                    continue
                                mtype = msg.get("type")
                                if mtype in ("ping", "connected"):
                                    continue
                                # orders
                                ords = msg.get("orders")
                                if isinstance(ords, list) and ords:
                                    await self._update_orders_cache(ords)
                                    await _maybe_await(self.on_orders, ords)
                                # trades（口座側）
                                trds = msg.get("trades")
                                if isinstance(trds, list) and trds:
                                    self.recent_trades.extend(trds)
                                    await _maybe_await(self.on_trades, trds)
                                # position
                                pos = msg.get("position")
                                if isinstance(pos, dict):
                                    try:
                                        sign = Decimal(str(pos.get("sign")))
                                        qty = Decimal(str(pos.get("position")))
                                        self.pos = sign * qty
                                    except Exception:
                                        pass

                        t_consume = asyncio.create_task(consume(), name="ws-consumer")
                        t_overlay = asyncio.create_task(overlay_refresher(), name="ws-overlay-auth")
                        t_keep = self._start_keepalive(ping_interval, send_ping)
                        try:
                            await asyncio.wait({t_consume, t_keep}, return_when=asyncio.FIRST_COMPLETED)
                        finally:
                            for t in (t_consume, t_keep, t_overlay):
                                t.cancel()
                            with contextlib.suppress(Exception):
                                await runner.ws.close()

                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"account stream error: {e!r}; retry in {backoff:.1f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    async def _public_trades_loop(self, *, market_id: int, ping_interval: float = 25.0) -> None:
        log = logging.getLogger("WS.public")
        backoff = 1.0
        while True:
            try:
                que = pybotters.WebSocketQueue()
                async with pybotters.Client(apis={}) as client:
                    runner = await client.ws_connect(
                        WS_URL,
                        send_json={"type": "subscribe", "channel": f"trade/{market_id}"},
                        hdlr_json=que.onmessage,
                    )
                    send_lock = asyncio.Lock()

                    async def send_ping() -> None:
                        async with send_lock:
                            await runner.ws.send_json({"type": "ping"})

                    async def consume() -> None:
                        async for msg in que:
                            if not isinstance(msg, dict):
                                continue
                            mtype = msg.get("type")
                            if mtype in ("ping", "connected"):
                                continue
                            trades = msg.get("trades")
                            if isinstance(trades, list) and trades:
                                last = trades[-1]
                                p: Optional[Decimal] = None
                                v = last.get("price")
                                if v is not None:
                                    try:
                                        p = Decimal(str(v))
                                    except Exception:
                                        p = None
                                async with self._lock:
                                    if p is not None:
                                        self.ltp = p
                                    self.public_trades.extend(trades)
                                await _maybe_await(self.on_public_trades, trades)

                    t_consume = asyncio.create_task(consume(), name="ws-public-consumer")
                    t_keep = self._start_keepalive(ping_interval, send_ping)
                    try:
                        await asyncio.wait({t_consume, t_keep}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for t in (t_consume, t_keep):
                            t.cancel()
                        with contextlib.suppress(Exception):
                            await runner.ws.close()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"public trades error: {e!r}; retry in {backoff:.1f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    # ---------- cache update ----------
    async def _update_orders_cache(self, orders: List[dict]) -> None:
        if not orders:
            return
        changed_cois: Set[int] = set()
        async with self._lock:
            for o in orders:
                # COI 取得
                try:
                    coi = int(o.get("client_order_index") or o.get("client_order_id"))
                except Exception:
                    continue
                if coi is None:
                    continue

                # 終了系は deque に入れず、両キャッシュ/バージョンから削除
                status = (o.get("status") or "").lower()
                if status in ("filled", "cancelled", "canceled", "closed", "expired"):
                    prev = self.order_by_coi.pop(coi, None)
                    if prev is not None:
                        with contextlib.suppress(Exception):
                            old_oid = int(prev.get("order_index") or prev.get("order_id"))
                            self.orders_by_index.pop(old_oid, None)
                    # deque先頭から無効COIを掃除
                    while self._coi_queue and self._coi_queue[0] not in self.order_by_coi:
                        self._coi_queue.popleft()
                    # versionも掃除
                    self._coi_version.pop(coi, None)
                    changed_cois.add(coi)
                    continue

                # ここから open/更新系：evict を先に決定
                evict_coi = None
                if (
                    self._coi_queue.maxlen is not None
                    and len(self._coi_queue) == self._coi_queue.maxlen
                    and coi not in self.order_by_coi
                ):
                    evict_coi = self._coi_queue[0]

                # 追加/更新
                self._coi_queue.append(coi)
                self.order_by_coi[coi] = o

                # OID 側
                with contextlib.suppress(Exception):
                    oid = int(o.get("order_index") or o.get("order_id"))
                    self.orders_by_index[oid] = o

                # evict 反映
                if evict_coi is not None:
                    old = self.order_by_coi.pop(evict_coi, None)
                    if old is not None:
                        with contextlib.suppress(Exception):
                            old_oid = int(old.get("order_index") or old.get("order_id"))
                            self.orders_by_index.pop(old_oid, None)
                    self._coi_version.pop(evict_coi, None)
                    changed_cois.add(evict_coi)

                changed_cois.add(coi)

            # version をインクリメント（削除は pop 済み）
            for coi in changed_cois:
                self._coi_version[coi] = self._coi_version.get(coi, 0) + 1
            # 同一ロック下で通知
            self._coi_cond.notify_all()


# -------------------------
# サンプル実行
# -------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def main():
        # 例1: 完全に引数で起動（config不要）
        ws1 = await WsInfo.run_overlay(
            account_index=10000,
            api_key_index=2,
            api_key_private_key="",
            symbol="ETH",  # または market_id=0
        )
        # public trades だけ
        ws_pub = await WsInfo.run_public_trades_simple(symbol="ETH")

        await asyncio.sleep(3)
        await ws1.aclose(); await ws_pub.aclose()

    asyncio.run(main())
