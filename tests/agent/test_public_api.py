import asyncio
import importlib.util
import json
import tempfile
import unittest

import wrappy


class PublicApiSmokeTest(unittest.TestCase):
    def test_core_package_imports_without_optional_lighter_sdk(self):
        self.assertEqual(wrappy.__version__, "0.6.0")
        self.assertIs(wrappy.BitFlyer, wrappy.bitflyer)
        self.assertTrue(callable(wrappy.now_jst))
        self.assertTrue(callable(wrappy.GMO))

    def test_analytics_helper_import_does_not_require_polars_for_numpy_only_usage(self):
        self.assertTrue(callable(wrappy.np_shift))

        if importlib.util.find_spec("numpy") is None:
            return

        import numpy as np

        shifted = wrappy.np_shift(np.array([1, 2, 3]), num=1, fill_value=0)
        self.assertEqual(shifted.tolist(), [0, 1, 2])

    def test_missing_lighter_dependency_has_install_hint(self):
        if importlib.util.find_spec("lighter") is not None:
            self.skipTest("lighter-sdk is installed in this environment")

        with self.assertRaises(ModuleNotFoundError) as ctx:
            _ = wrappy.LighterDealer

        self.assertIn('wrappy[lighter]', str(ctx.exception))

    def test_lowercase_lighter_markets_import_path_is_supported(self):
        from wrappy.lighter import markets

        self.assertEqual(markets.index_of("ETH"), 0)
        self.assertEqual(markets.symbol_of(0), "ETH")

    def test_notify_without_channels_skips_cleanly(self):
        cfg = {
            "exchange_name": "demo",
            "bot_name": "agent",
            "log_dir": "log",
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as fh:
            json.dump(cfg, fh)
            fh.flush()
            notifier = wrappy.Notify(fh.name)
            result = asyncio.run(notifier.statusNotify("hello"))

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
