import pathlib
import unittest

import wrappy


ROOT = pathlib.Path(__file__).resolve().parents[2]


class DocsContractTest(unittest.TestCase):
    def test_verification_command_is_documented_consistently(self):
        expected = "python scripts/verify_agent_ready.py"

        for rel_path in ["README.md", "AGENTS.md", "LLM_REPO_GUIDE.md"]:
            text = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn(expected, text, rel_path)

    def test_documented_public_api_names_resolve(self):
        names = [
            "Log",
            "Notify",
            "BotBase",
            "GMO",
            "BitBank",
            "BitFlyer",
            "CoinCheck",
            "APIException",
            "RequestException",
            "now_jst",
            "now_jst_str",
            "now_utc",
            "now_utc_str",
            "now_gmt",
            "now_gmt_str",
            "fromISOformat",
            "simple_regression",
            "plot_corrcoef",
            "np_shift",
            "np_stack",
            "resample_ohlc",
            "df_list",
            "trades_to_historical",
            "Objective",
        ]

        for name in names:
            self.assertTrue(hasattr(wrappy, name), name)

    def test_star_import_is_safe_for_top_level_package(self):
        namespace = {}
        exec("from wrappy import *", namespace, namespace)
        self.assertIn("BitFlyer", namespace)
        self.assertIn("GMO", namespace)
        self.assertNotIn("LighterDealer", namespace)


if __name__ == "__main__":
    unittest.main()
