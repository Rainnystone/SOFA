import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from capability_policy import recommendation_for_missing


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/capability_check.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capability_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCapabilityCheck(unittest.TestCase):
    def test_scan_environment_never_exposes_secret_values(self):
        module = load_module()
        env = {
            "EXA_API_KEY": "exa-secret-value",
            "TAVILY_API_KEY": "tavily-secret-value",
            "WIND_API_KEY": "wind-secret-value",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env=env)

        payload = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("exa-secret-value", payload)
        self.assertNotIn("tavily-secret-value", payload)
        self.assertNotIn("wind-secret-value", payload)

    def test_env_present_marks_exa_tavily_and_wind_configured(self):
        module = load_module()
        env = {
            "EXA_API_KEY": "exa-secret-value",
            "TAVILY_API_KEY": "tavily-secret-value",
            "WIND_API_KEY": "wind-secret-value",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env=env)

        search_chain = {entry["name"]: entry for entry in result["search_chain"]}
        self.assertTrue(search_chain["Exa MCP server"]["configured"])
        self.assertTrue(search_chain["Tavily"]["configured"])
        self.assertTrue(result["finance"]["wind"]["configured"])

    def test_empty_env_uses_strict_search_chain_order(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env={})

        names = [entry["name"] for entry in result["search_chain"]]
        self.assertEqual(
            ["AnySearch skill", "Exa MCP server", "Tavily", "Host-agent built-ins"],
            names,
        )

    def test_recommendations_cover_optional_capabilities(self):
        module = load_module()
        original_module_present = module._module_present
        module._module_present = lambda name: False
        self.addCleanup(setattr, module, "_module_present", original_module_present)
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env={})

        text = "\n".join(result["recommendations"])
        self.assertIn("AnySearch", text)
        self.assertIn("Exa", text)
        self.assertIn("Tavily", text)
        self.assertIn("Wind", text)
        self.assertIn("yfinance", text)

    def test_configured_capabilities_are_not_recommended(self):
        module = load_module()
        original_module_present = module._module_present
        module._module_present = lambda name: name == "yfinance"
        self.addCleanup(setattr, module, "_module_present", original_module_present)

        env = {
            "EXA_API_KEY": "exa-secret-value",
            "TAVILY_API_KEY": "tavily-secret-value",
            "WIND_API_KEY": "wind-secret-value",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / ".agents/skills/anysearch").mkdir(parents=True)
            result = module.scan_environment(home=home, env=env)

        self.assertEqual([], result["recommendations"])

    def test_search_chain_entries_carry_policy_provider_ids(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env={})

        self.assertEqual(
            ["anysearch", "exa", "tavily", "host_builtin"],
            [entry["id"] for entry in result["search_chain"]],
        )
        self.assertEqual("1.1", result["schema_version"])

    def test_recommendation_text_renders_from_policy(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result = module.scan_environment(home=Path(temp_dir), env={})

        by_id = {entry["id"]: entry for entry in result["search_chain"]}
        for provider_id in ("anysearch", "exa", "tavily"):
            self.assertEqual(
                recommendation_for_missing(provider_id),
                by_id[provider_id]["recommendation"],
            )
        self.assertEqual(
            recommendation_for_missing("wind"),
            result["finance"]["wind"]["recommendation"],
        )
        self.assertEqual(
            recommendation_for_missing("yfinance"),
            result["finance"]["yfinance"]["recommendation"],
        )


if __name__ == "__main__":
    unittest.main()
