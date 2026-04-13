import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from wrappy.bitbank import BitBank
from wrappy.coincheck import CoinCheck
from wrappy.exceptions import APIException


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


if __name__ == "__main__":
    unittest.main()
