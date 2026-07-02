import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from worker_role_catalog import (
    ACTION_CLASS_LANGUAGE,
    all_worker_roles,
    forbidden_output_violations,
    has_required_output_marker,
    has_source_trace,
    normalize_role_slug,
    role_for_delivery_path,
    role_for_slug,
    validate_catalog,
)


EXPECTED_ROLES = {
    "frontier_scout": {
        "prompt": "scripts/prompts/scout_prompt.md",
        "delivery": "scouts",
        "modes": ("ticker",),
        "required_cards": ("supply-chain-mapping", "customer-graph-discovery"),
        "requires_source_trace": True,
        "forbidden_outputs": (ACTION_CLASS_LANGUAGE,),
    },
    "challenge_probe": {
        "prompt": "scripts/prompts/challenge_prompt.md",
        "delivery": "challenges",
        "modes": ("ticker",),
        "required_cards": ("red-team", "supply-chain-mapping", "customer-graph-discovery"),
        "requires_source_trace": False,
        "forbidden_outputs": (),
    },
    "sector_mapper": {
        "prompt": "scripts/prompts/sector_mapper_prompt.md",
        "delivery": "maps",
        "modes": ("sector",),
        "required_cards": ("supply-chain-mapping", "customer-graph-discovery"),
        "requires_source_trace": True,
        "forbidden_outputs": (ACTION_CLASS_LANGUAGE,),
    },
    "coverage_challenge": {
        "prompt": "scripts/prompts/coverage_challenge_prompt.md",
        "delivery": "coverage",
        "modes": ("sector",),
        "required_cards": ("supply-chain-mapping", "customer-graph-discovery"),
        "requires_source_trace": False,
        "forbidden_outputs": (),
    },
    "supply_chain_mapper": {
        "prompt": "scripts/prompts/supply_chain_prompt.md",
        "delivery": "maps",
        "modes": ("ticker", "sector", "ultra"),
        "required_cards": ("supply-chain-mapping",),
        "requires_source_trace": True,
        "forbidden_outputs": (),
    },
    "customer_graph_mapper": {
        "prompt": "scripts/prompts/customer_graph_prompt.md",
        "delivery": "maps",
        "modes": ("ticker", "sector", "ultra"),
        "required_cards": ("customer-graph-discovery",),
        "requires_source_trace": True,
        "forbidden_outputs": (),
    },
    "financial_bridge": {
        "prompt": "scripts/prompts/financial_bridge_prompt.md",
        "delivery": "financials",
        "modes": ("ticker", "sector", "ultra"),
        "required_cards": ("financial-bridge",),
        "requires_source_trace": False,
        "forbidden_outputs": (),
    },
    "red_team": {
        "prompt": "scripts/prompts/red_team_prompt.md",
        "delivery": "redteam",
        "modes": ("ticker", "sector", "ultra"),
        "required_cards": ("red-team",),
        "requires_source_trace": False,
        "forbidden_outputs": (),
    },
}


class TestWorkerRoleCatalog(unittest.TestCase):
    def test_catalog_contains_existing_sofa_worker_roles(self):
        roles = {role.slug: role for role in all_worker_roles()}

        self.assertEqual(set(EXPECTED_ROLES), set(roles))
        for slug, expected in EXPECTED_ROLES.items():
            with self.subTest(slug=slug):
                role = roles[slug]
                self.assertEqual(expected["prompt"], role.prompt_template)
                self.assertEqual(expected["delivery"], role.delivery_folder)
                self.assertEqual(expected["modes"], role.modes)
                self.assertEqual(expected["required_cards"], role.required_method_cards)
                self.assertEqual(expected["requires_source_trace"], role.requires_source_trace)
                self.assertEqual(expected["forbidden_outputs"], role.forbidden_output_classes)
                self.assertIn("Method cards loaded", role.required_output_markers)

    def test_catalog_paths_exist_relative_to_repo_root(self):
        issues = validate_catalog(ROOT)

        self.assertEqual([], issues)

    def test_role_lookup_and_delivery_path_mapping(self):
        self.assertEqual("frontier_scout", role_for_slug("frontier_scout").slug)
        self.assertEqual("frontier_scout", role_for_delivery_path("scouts").slug)
        self.assertEqual("frontier_scout", role_for_delivery_path("scouts/loop_1_scout.md").slug)
        self.assertEqual("challenge_probe", role_for_delivery_path("challenges/loop_1_challenge.md").slug)
        self.assertEqual("coverage_challenge", role_for_delivery_path("coverage/coverage_1.md").slug)
        self.assertEqual("financial_bridge", role_for_delivery_path("financials/bridge.md").slug)
        self.assertEqual("red_team", role_for_delivery_path("redteam/round1_redteam.md").slug)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            role_for_delivery_path("maps/mapping_1.md")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            role_for_delivery_path("maps/customer_graph_v1.md")

    def test_dispatch_aliases_normalize_to_canonical_slugs(self):
        cases = {
            "scout": "frontier_scout",
            "frontier scout": "frontier_scout",
            "challenges": "challenge_probe",
            "challenge": "challenge_probe",
            "mapper": "sector_mapper",
            "coverage": "coverage_challenge",
            "financial": "financial_bridge",
            "financial screen": "financial_bridge",
            "redteam": "red_team",
            "red team": "red_team",
            "thesis-revision": "red_team",
        }
        for alias, expected_slug in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(expected_slug, normalize_role_slug(alias))

    def test_dispatch_alias_must_match_delivery_folder_when_path_is_known(self):
        self.assertEqual(
            "frontier_scout",
            normalize_role_slug("scout", delivery_path="scouts/loop_1_scout.md"),
        )
        self.assertEqual("frontier_scout", normalize_role_slug("scout", delivery_path="scouts"))
        self.assertEqual(
            "sector_mapper",
            normalize_role_slug("sector_mapper", delivery_path="maps/mapping_1.md"),
        )
        self.assertEqual(
            "supply_chain_mapper",
            normalize_role_slug("supply_chain_mapper", delivery_path="maps/supply_chain_v1.md"),
        )
        self.assertEqual(
            "customer_graph_mapper",
            normalize_role_slug("customer_graph_mapper", delivery_path="maps/customer_graph_v1.md"),
        )

        with self.assertRaisesRegex(ValueError, "does not match delivery path"):
            normalize_role_slug("financial", delivery_path="scouts/loop_1_scout.md")
        with self.assertRaisesRegex(ValueError, "ambiguous|unambiguous"):
            normalize_role_slug(None, delivery_path="maps/supply_chain_v1.md")
        with self.assertRaisesRegex(ValueError, "Unknown SOFA worker role alias"):
            normalize_role_slug("maps", delivery_path="maps/customer_graph_v1.md")

    def test_short_list_phrase_does_not_trigger_action_language_violation(self):
        role = role_for_slug("sector_mapper")
        text = (
            "# Output\n\n"
            "Method cards loaded: supply-chain-mapping, customer-graph-discovery.\n\n"
            "Sources consulted: short list of candidate suppliers.\n"
        )

        self.assertEqual([], forbidden_output_violations(role, text))

    def test_required_output_marker_and_source_trace_helpers(self):
        role = role_for_slug("frontier_scout")
        good_text = (
            "# Scout\n\n"
            "Method cards loaded: supply-chain-mapping, customer-graph-discovery.\n\n"
            "Sources consulted: company filing.\n"
        )
        missing_trace = "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n"

        self.assertTrue(has_required_output_marker(good_text, "Method cards loaded"))
        self.assertTrue(has_source_trace(good_text, role))
        self.assertFalse(has_source_trace(missing_trace, role))

    def test_forbidden_action_language_uses_role_facts(self):
        scout = role_for_slug("frontier_scout")
        sector_mapper = role_for_slug("sector_mapper")
        financial = role_for_slug("financial_bridge")
        text = (
            "# Output\n\n"
            "Method cards loaded: supply-chain-mapping.\n\n"
            "Sources consulted: company filing.\n\n"
            "Action Class: buy.\n"
        )

        self.assertEqual(
            ["SCOUT_FORBIDDEN_CONCLUSION"],
            [issue.issue_code for issue in forbidden_output_violations(scout, text)],
        )
        self.assertEqual(
            ["WORKER_FORBIDDEN_CONCLUSION"],
            [issue.issue_code for issue in forbidden_output_violations(sector_mapper, text)],
        )
        self.assertEqual([], forbidden_output_violations(financial, text))


if __name__ == "__main__":
    unittest.main()
