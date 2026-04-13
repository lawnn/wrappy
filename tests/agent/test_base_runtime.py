import asyncio
import json
import logging
import os
import tempfile
import unittest
import uuid

from wrappy.base import BotBase
from wrappy.log import Log


class _DummyStore:
    def onmessage(self, message):
        return message


class _DummyClient:
    def __init__(self):
        self.called = False
        self.kwargs = None

    async def ws_connect(self, url, **kwargs):
        self.called = True
        self.kwargs = {"url": url, **kwargs}
        return "connected"


class _DummyBot(BotBase):
    async def _run_logic(self):
        return None


class BaseRuntimeTest(unittest.TestCase):
    def _config_path(self):
        cfg = {
            "exchange_name": "demo",
            "bot_name": f"agent-{uuid.uuid4().hex}",
            "log_dir": "log",
        }
        fh = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        json.dump(cfg, fh)
        fh.flush()
        fh.close()
        self.addCleanup(lambda: os.path.exists(fh.name) and os.unlink(fh.name))
        return fh.name

    def test_ws_base_awaits_client_connection(self):
        bot = _DummyBot(self._config_path())
        client = _DummyClient()
        store = _DummyStore()

        asyncio.run(bot.ws("wss://example.test/ws", client, store, [{"channel": "ticker"}]))

        self.assertTrue(client.called)
        self.assertEqual(client.kwargs["url"], "wss://example.test/ws")
        self.assertEqual(client.kwargs["send_json"], [{"channel": "ticker"}])
        self.assertTrue(callable(client.kwargs["hdlr_json"]))

    def test_log_initializes_its_own_handlers_even_if_root_has_handlers(self):
        root = logging.getLogger()
        root_handler = logging.StreamHandler()
        root.addHandler(root_handler)
        root_level = root.level

        try:
            log = Log(self._config_path())
            self.assertFalse(log.logger.propagate)
            self.assertGreaterEqual(len(log.logger.handlers), 1)
        finally:
            root.removeHandler(root_handler)
            root.setLevel(root_level)


if __name__ == "__main__":
    unittest.main()
