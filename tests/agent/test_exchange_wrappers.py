import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from wrappy.bitbank import BitBank
from wrappy.bitflyer import bitflyer as BitFlyer
from wrappy.coincheck import CoinCheck
from wrappy.exceptions import APIException, RequestException
from wrappy.gmo import GMO


class _DummyResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload


class _ClientFactory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        factory = self

        class _Client:
            async def __aenter__(self):
                factory.calls.append(kwargs)
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, method, url, params=None, data=None):
                response = factory.responses.pop(0)
                factory.calls[-1] = {
                    **factory.calls[-1],
                    "method": method,
                    "url": url,
                    "params": params,
                    "data": data,
                }
                return response

        return _Client()


class _ConfigMixin:
    def make_config_path(self, payload):
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        json.dump(payload, fh)
        fh.flush()
        fh.close()
        self.addCleanup(lambda: os.path.exists(fh.name) and os.unlink(fh.name))
        return fh.name


class BitBankRequestTest(_ConfigMixin, unittest.IsolatedAsyncioTestCase):
    async def test_requests_notifies_and_raises_on_server_error(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitbank",
                "bot_name": "agent",
                "log_dir": "log",
                "bitbank": ["KEY", "SECRET"],
            }
        )
        bot = BitBank(config_path, "btc_jpy")
        bot.statusNotify = AsyncMock()

        factory = _ClientFactory([_DummyResponse(500, {"error": "server"})])
        with patch("wrappy.bitbank.pybotters.Client", factory):
            with self.assertRaises(APIException):
                await bot._requests("GET", "/user/assets")

        bot.statusNotify.assert_awaited_once_with("Status 500 Error")

    async def test_requests_rotate_keys_when_multiple_keys_are_configured(self):
        keys = [["KEY1", "SECRET1"], ["KEY2", "SECRET2"]]
        config_path = self.make_config_path(
            {
                "exchange_name": "bitbank",
                "bot_name": "agent",
                "log_dir": "log",
                "bitbank_keys": keys,
            }
        )
        bot = BitBank(config_path, "btc_jpy")

        payload = {"success": 1, "data": {"ok": True}}
        factory = _ClientFactory([_DummyResponse(200, payload), _DummyResponse(200, payload)])
        with patch("wrappy.bitbank.pybotters.Client", factory):
            await bot._requests("GET", "/user/assets")
            await bot._requests("GET", "/user/assets")

        self.assertEqual(factory.calls[0]["apis"], {"bitbank": keys[0]})
        self.assertEqual(factory.calls[1]["apis"], {"bitbank": keys[1]})

    async def test_market_and_spot_orders_build_expected_payloads(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitbank",
                "bot_name": "agent",
                "log_dir": "log",
                "bitbank": ["KEY", "SECRET"],
            }
        )
        bot = BitBank(config_path, "btc_jpy")
        bot._requests = AsyncMock(return_value={"ok": True})

        await bot.market_order("buy", "0.1")
        await bot.spot_market_order("sell", "0.2")

        first_call = bot._requests.await_args_list[0]
        second_call = bot._requests.await_args_list[1]

        self.assertEqual(first_call.args, ("POST",))
        self.assertEqual(first_call.kwargs["url"], "/user/spot/order")
        self.assertEqual(
            first_call.kwargs["data"],
            {
                "pair": "btc_jpy",
                "amount": "0.1",
                "side": "buy",
                "position_side": "long",
                "type": "market",
                "post_only": False,
            },
        )

        self.assertEqual(second_call.kwargs["url"], "/user/spot/order")
        self.assertEqual(
            second_call.kwargs["data"],
            {
                "pair": "btc_jpy",
                "amount": "0.2",
                "side": "sell",
                "type": "market",
                "post_only": False,
            },
        )


class CoinCheckTest(_ConfigMixin, unittest.IsolatedAsyncioTestCase):
    async def test_fetch_ticker_retries_then_returns(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "coincheck",
                "bot_name": "agent",
                "log_dir": "log",
            }
        )
        bot = CoinCheck(config_path, "btc_jpy")
        bot._requests = AsyncMock(side_effect=[RuntimeError("temporary"), {"last": 123}])

        with patch("wrappy.coincheck.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            result = await bot.fetch_ticker()

        self.assertEqual(result, {"last": 123})
        self.assertEqual(bot._requests.await_count, 2)
        sleep_mock.assert_awaited_once_with(1)

    async def test_fetch_ticker_raises_after_five_failures(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "coincheck",
                "bot_name": "agent",
                "log_dir": "log",
            }
        )
        bot = CoinCheck(config_path, "btc_jpy")
        bot._requests = AsyncMock(side_effect=[RuntimeError("boom")] * 5)
        bot.log_error = MagicMock()

        with patch("wrappy.coincheck.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            with self.assertRaises(RuntimeError):
                await bot.fetch_ticker()

        self.assertEqual(bot._requests.await_count, 5)
        self.assertEqual(sleep_mock.await_count, 4)
        self.assertGreaterEqual(bot.log_error.call_count, 2)


class GMOTest(_ConfigMixin, unittest.IsolatedAsyncioTestCase):
    async def test_requests_returns_data_payload(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "gmo",
                "bot_name": "agent",
                "log_dir": "log",
                "gmocoin": ["KEY", "SECRET"],
            }
        )
        bot = GMO(config_path, "BTC_JPY")

        factory = _ClientFactory(
            [_DummyResponse(200, {"status": 0, "data": {"orderId": 123}, "responsetime": "x"})]
        )
        with patch("wrappy.gmo.pybotters.Client", factory):
            result = await bot._requests("GET", "/private/v1/orders")

        self.assertEqual(result, {"orderId": 123})
        self.assertEqual(factory.calls[0]["apis"], {"gmocoin": ["KEY", "SECRET"]})

    async def test_requests_raises_even_when_messages_are_missing(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "gmo",
                "bot_name": "agent",
                "log_dir": "log",
                "gmocoin": ["KEY", "SECRET"],
            }
        )
        bot = GMO(config_path, "BTC_JPY")

        factory = _ClientFactory([_DummyResponse(200, {"status": 7})])
        with patch("wrappy.gmo.pybotters.Client", factory):
            with self.assertRaises(RequestException) as ctx:
                await bot._requests("GET", "/private/v1/orders")

        self.assertIn("[Error code] 7", str(ctx.exception))

    async def test_order_methods_compact_none_fields_and_route_to_expected_endpoints(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "gmo",
                "bot_name": "agent",
                "log_dir": "log",
                "gmocoin": ["KEY", "SECRET"],
            }
        )
        bot = GMO(config_path, "BTC_JPY")
        bot._requests = AsyncMock(return_value={"ok": True})

        await bot.market_order("BUY", "0.01")
        await bot.limit_order("SELL", "0.02", 123456, losscut_price="120000")
        await bot.settle_limit("BUY", "0.03", 120000, 42)
        await bot.cancel_all_orders()
        await bot.edit_order(10, 999999)

        market_call = bot._requests.await_args_list[0]
        limit_call = bot._requests.await_args_list[1]
        settle_call = bot._requests.await_args_list[2]
        cancel_all_call = bot._requests.await_args_list[3]
        edit_call = bot._requests.await_args_list[4]

        self.assertEqual(market_call.args, ("POST",))
        self.assertEqual(market_call.kwargs["url"], "/private/v1/order")
        self.assertEqual(
            market_call.kwargs["data"],
            {
                "symbol": "BTC_JPY",
                "side": "BUY",
                "executionType": "MARKET",
                "cancelBefore": False,
                "size": "0.01",
            },
        )

        self.assertEqual(limit_call.kwargs["url"], "/private/v1/order")
        self.assertEqual(
            limit_call.kwargs["data"],
            {
                "symbol": "BTC_JPY",
                "side": "SELL",
                "executionType": "LIMIT",
                "losscutPrice": "120000",
                "cancelBefore": False,
                "size": "0.02",
                "price": "123456",
            },
        )

        self.assertEqual(settle_call.kwargs["url"], "/private/v1/closeOrder")
        self.assertEqual(
            settle_call.kwargs["data"],
            {
                "symbol": "BTC_JPY",
                "side": "BUY",
                "executionType": "LIMIT",
                "cancelBefore": False,
                "settlePosition": [{"positionId": 42, "size": "0.03"}],
                "price": "120000",
            },
        )

        self.assertEqual(
            cancel_all_call.kwargs["data"],
            {"symbols": ["BTC_JPY"]},
        )
        self.assertEqual(
            edit_call.kwargs["data"],
            {"orderId": 10, "price": 999999},
        )


class BitFlyerTest(_ConfigMixin, unittest.IsolatedAsyncioTestCase):
    async def test_cancel_order_raises_on_http_error(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitflyer",
                "bot_name": "agent",
                "log_dir": "log",
                "bitflyer": ["KEY", "SECRET"],
            }
        )
        bot = BitFlyer(config_path, "FX_BTC_JPY")
        bot.api_call_count_from_private = 0

        factory = _ClientFactory([_DummyResponse(400, {"status": -1, "error_message": "bad request"})])
        with patch("wrappy.bitflyer.pybotters.Client", factory):
            with self.assertRaises(RequestException) as ctx:
                await bot.cancel_order("JRF-test")

        self.assertIn("400 Error", str(ctx.exception))
        self.assertEqual(bot.api_call_count_from_private, 0)

    async def test_cancel_all_orders_counts_successful_call(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitflyer",
                "bot_name": "agent",
                "log_dir": "log",
                "bitflyer": ["KEY", "SECRET"],
            }
        )
        bot = BitFlyer(config_path, "FX_BTC_JPY")

        factory = _ClientFactory([_DummyResponse(200, {"result": "ok"})])
        with patch("wrappy.bitflyer.pybotters.Client", factory):
            await bot.cancel_all_orders()

        self.assertEqual(bot.api_call_count_from_private, 1)
        self.assertEqual(bot.api_call_count_from_order, 1)

    async def test_fetch_my_position_aggregates_decimal_size(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitflyer",
                "bot_name": "agent",
                "log_dir": "log",
                "bitflyer": ["KEY", "SECRET"],
            }
        )
        bot = BitFlyer(config_path, "FX_BTC_JPY")
        bot._fetch_position = AsyncMock(
            return_value=[
                {"side": "BUY", "size": 0.01},
                {"side": "BUY", "size": "0.02"},
            ]
        )

        position = await bot.fetch_my_position()

        self.assertEqual(position["side"], "BUY")
        self.assertEqual(str(position["size"]), "0.03")

    async def test_order_methods_build_expected_payloads(self):
        config_path = self.make_config_path(
            {
                "exchange_name": "bitflyer",
                "bot_name": "agent",
                "log_dir": "log",
                "bitflyer": ["KEY", "SECRET"],
            }
        )
        bot = BitFlyer(config_path, "FX_BTC_JPY")

        bot._requests = AsyncMock(
            side_effect=[
                _DummyResponse(200, {"child_order_acceptance_id": "A"}),
                _DummyResponse(200, {"child_order_acceptance_id": "B"}),
            ]
        )

        await bot.market_order("BUY", 0.01)
        await bot.limit_order("SELL", 0.02, 123456, minute_to_expire=60, time_in_force="IOC")

        market_call = bot._requests.await_args_list[0]
        limit_call = bot._requests.await_args_list[1]

        self.assertEqual(market_call.args, ("POST",))
        self.assertEqual(market_call.kwargs["url"], "/v1/me/sendchildorder")
        self.assertEqual(
            market_call.kwargs["data"],
            {
                "product_code": "FX_BTC_JPY",
                "child_order_type": "MARKET",
                "side": "BUY",
                "size": 0.01,
                "minute_to_expire": 43200,
                "time_in_force": "GTC",
            },
        )

        self.assertEqual(limit_call.kwargs["url"], "/v1/me/sendchildorder")
        self.assertEqual(
            limit_call.kwargs["data"],
            {
                "product_code": "FX_BTC_JPY",
                "child_order_type": "LIMIT",
                "side": "SELL",
                "size": 0.02,
                "minute_to_expire": 60,
                "time_in_force": "IOC",
                "price": 123456,
            },
        )


if __name__ == "__main__":
    unittest.main()
