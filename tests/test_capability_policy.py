import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capability_policy import (
    DEAD_END_CATEGORIES,
    FINANCE_CAPABILITIES,
    RESULT_STATUS_COMPLETED,
    RESULT_STATUS_DEGRADED,
    SEARCH_CHAIN,
    STAGE0_LOOP_ID,
    missing_tool_confidence_language,
    provider_for_id,
    recommendation_for_missing,
    render_chain_arrow,
    render_finance_summary,
    render_setup_recommendation_lines,
    validate_policy,
)


class TestSearchChainFacts(unittest.TestCase):
    def test_chain_order_ids_and_labels(self):
        self.assertEqual(
            ["anysearch", "exa", "tavily", "host_builtin"],
            [provider.provider_id for provider in SEARCH_CHAIN],
        )
        self.assertEqual(
            ["AnySearch skill", "Exa MCP server", "Tavily", "Host-agent built-ins"],
            [provider.display_label for provider in SEARCH_CHAIN],
        )
        self.assertEqual(
            [1, 2, 3, 4],
            [provider.chain_position for provider in SEARCH_CHAIN],
        )

    def test_recommendations_carry_install_pointers(self):
        self.assertIn(
            "https://github.com/anysearch-ai/anysearch-skill",
            recommendation_for_missing("anysearch"),
        )
        self.assertIn(
            "https://github.com/exa-labs/exa-mcp-server",
            recommendation_for_missing("exa"),
        )
        self.assertIn(
            "https://github.com/tavily-ai/skills",
            recommendation_for_missing("tavily"),
        )

    def test_provider_lookup_rejects_unknown_id(self):
        self.assertEqual("anysearch", provider_for_id("anysearch").provider_id)
        with self.assertRaises(ValueError):
            provider_for_id("bing")


class TestFinanceFacts(unittest.TestCase):
    def test_finance_ids_and_recommendations(self):
        finance = {entry.provider_id: entry for entry in FINANCE_CAPABILITIES}
        self.assertEqual({"wind", "yfinance"}, set(finance))
        self.assertIn("aifinmarket.wind.com.cn", finance["wind"].recommendation)
        self.assertIn("pip install yfinance", finance["yfinance"].recommendation)
        self.assertIn("not an authoritative filing source", finance["yfinance"].recommendation)

    def test_confidence_language_names_the_rule(self):
        text = missing_tool_confidence_language()
        self.assertIn("lower", text)
        self.assertIn("confidence", text)


class TestRecordVocabulary(unittest.TestCase):
    def test_status_constants_match_existing_literals(self):
        self.assertEqual("completed", RESULT_STATUS_COMPLETED)
        self.assertEqual("degraded_approved", RESULT_STATUS_DEGRADED)

    def test_stage0_loop_id(self):
        self.assertEqual("stage_0", STAGE0_LOOP_ID)

    def test_dead_end_categories_are_exactly_the_approved_three(self):
        self.assertEqual(
            ("no_result", "tool_degraded", "blocked_source"),
            DEAD_END_CATEGORIES,
        )


class TestRenderHelpers(unittest.TestCase):
    def test_chain_arrow_is_byte_identical_to_current_scaffold(self):
        self.assertEqual(
            "AnySearch -> Exa -> Tavily -> host-agent built-ins",
            render_chain_arrow(),
        )

    def test_finance_summary_is_byte_identical_to_current_scaffold(self):
        self.assertEqual(
            "Wind for Chinese data; yfinance for English/global public-market data",
            render_finance_summary(),
        )

    def test_setup_recommendation_lines_match_init_workspace_output(self):
        self.assertEqual(
            (
                "SOFA recommends AnySearch -> Exa -> Tavily -> host-agent built-ins for general search.",
                "SOFA recommends Wind for Chinese financial data and yfinance for English/global public-market data.",
            ),
            render_setup_recommendation_lines(),
        )


class TestPolicyValidation(unittest.TestCase):
    def test_package_namespace_import_works_from_repo_root(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import scripts.capability_policy as policy; "
                "print(policy.STAGE0_LOOP_ID)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertEqual("stage_0", result.stdout.strip())

    def test_validate_policy_reports_no_issues(self):
        self.assertEqual([], validate_policy())

    def test_rendered_output_never_contains_secret_values(self):
        # The policy is static facts with no environment access; this locks
        # that guarantee structurally against future edits.
        import os

        secret = "sk-secret-value-should-never-render"
        original = dict(os.environ)
        os.environ.update(
            {"EXA_API_KEY": secret, "TAVILY_API_KEY": secret, "WIND_API_KEY": secret}
        )
        try:
            rendered = "\n".join(
                [
                    render_chain_arrow(),
                    render_finance_summary(),
                    *render_setup_recommendation_lines(),
                    missing_tool_confidence_language(),
                    *[provider.recommendation for provider in SEARCH_CHAIN],
                    *[entry.recommendation for entry in FINANCE_CAPABILITIES],
                ]
            )
        finally:
            os.environ.clear()
            os.environ.update(original)

        self.assertNotIn(secret, rendered)


if __name__ == "__main__":
    unittest.main()
