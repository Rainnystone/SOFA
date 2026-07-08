import sys
import unittest
from pathlib import Path, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workspace_contract import (
    all_worker_output_directories,
    artifact_contract_for_mode,
    core_required_files,
    is_main_thread_artifact,
    managed_block_for_name,
    normalize_mode,
    replace_managed_block,
)


class TestWorkspaceArtifactContract(unittest.TestCase):
    def test_ticker_contract_exposes_common_scaffold_without_sector_only_artifacts(self):
        contract = artifact_contract_for_mode("ticker")

        self.assertEqual("ticker", contract.mode)
        self.assertIn("research_workflow.md", contract.common_files)
        self.assertIn("evidence_ledger.md", contract.common_files)
        self.assertIn("search_log.jsonl", contract.machine_ledgers)
        self.assertIn("dispatch_log.jsonl", contract.machine_ledgers)
        self.assertIn("scouts", contract.common_directories)
        self.assertIn("maps", contract.common_directories)
        self.assertNotIn("coverage", contract.mode_directories)
        self.assertNotIn("maps/dependency_ladder.md", contract.mode_artifacts)
        self.assertNotIn("coverage", contract.all_scaffold_paths())

    def test_sector_contract_exposes_coverage_and_dependency_ladder_scaffold(self):
        contract = artifact_contract_for_mode("sector")

        self.assertEqual("sector", contract.mode)
        self.assertIn("coverage", contract.mode_directories)
        self.assertIn("maps/dependency_ladder.md", contract.mode_artifacts)
        self.assertIn("coverage", contract.all_scaffold_paths())
        self.assertIn("maps/dependency_ladder.md", contract.all_scaffold_paths())
        self.assertIn("coverage/", contract.created_artifact_labels())
        self.assertIn("maps/dependency_ladder.md", contract.created_artifact_labels())

    def test_dependency_ladder_is_main_thread_artifact_not_worker_output(self):
        contract = artifact_contract_for_mode("sector")

        self.assertTrue(is_main_thread_artifact("maps/dependency_ladder.md"))
        self.assertFalse(contract.is_worker_output_path("maps/dependency_ladder.md"))
        self.assertTrue(contract.is_worker_output_path("maps/sector_mapper_loop1.md"))
        self.assertTrue(contract.is_worker_output_path("coverage/coverage_loop1.md"))

    def test_resolve_rejects_paths_outside_workspace(self):
        contract = artifact_contract_for_mode("sector")
        workspace_root = Path("/workspace/research")

        with self.assertRaisesRegex(ValueError, "workspace-relative path"):
            contract.resolve(workspace_root, "/tmp/outside.md")

        windows_absolute_paths = (
            PureWindowsPath("C:/tmp/outside.md"),
            PureWindowsPath(r"\\server\share\outside.md"),
            PureWindowsPath(r"\tmp\outside.md"),
        )
        for path in windows_absolute_paths:
            with self.subTest(path=str(path)):
                with self.assertRaisesRegex(ValueError, "workspace-relative path"):
                    contract.resolve(workspace_root, path)

        with self.assertRaisesRegex(ValueError, "workspace-relative path"):
            contract.resolve(workspace_root, "../outside.md")

    def test_path_normalization_preserves_main_thread_artifact_classification(self):
        contract = artifact_contract_for_mode("sector")

        self.assertFalse(
            contract.is_worker_output_path("maps/../maps/dependency_ladder.md")
        )
        self.assertTrue(is_main_thread_artifact("./maps/../maps/dependency_ladder.md"))

    def test_worker_output_directories_are_available_as_union_for_workspace_scans(self):
        self.assertEqual(
            ("scouts", "challenges", "maps", "coverage", "financials", "redteam"),
            all_worker_output_directories(),
        )

    def test_core_required_files_are_shared_with_sofa_contract(self):
        self.assertEqual(
            ("state.json", "research_workflow.md", "evidence_ledger.md"),
            core_required_files(),
        )

    def test_normalize_mode_rejects_unknown_modes(self):
        self.assertEqual("ticker", normalize_mode(" TICKER "))
        self.assertEqual("sector", normalize_mode("sector"))

        with self.assertRaisesRegex(ValueError, "Unsupported SOFA workspace mode"):
            normalize_mode("ultra")


class TestFramingContractArtifactAndManagedBlocks(unittest.TestCase):
    def test_framing_contract_is_machine_artifact_with_managed_block(self):
        contract = artifact_contract_for_mode("ticker")
        # framing_contract.json is a common file and a machine ledger.
        self.assertIn("framing_contract.json", contract.common_files)
        self.assertIn("framing_contract.json", contract.machine_ledgers)
        # The framing-contract block is registered (tuple lookup, not dict).
        self.assertTrue(
            any(block.name == "framing-contract" for block in contract.managed_blocks),
            "framing-contract managed block is not registered",
        )
        block = managed_block_for_name("framing-contract")
        self.assertEqual(block.heading, "Framing Intent Contract")
        self.assertEqual(block.start_marker, "<!-- SOFA:framing-contract:start -->")
        self.assertEqual(block.end_marker, "<!-- SOFA:framing-contract:end -->")
        # ManagedBlock has no path field; the file it renders into is the
        # caller's responsibility (research_workflow.md owns this block).

    def test_source_cache_artifacts_are_registered(self):
        contract = artifact_contract_for_mode("ticker")
        self.assertIn("sources", contract.common_directories)
        self.assertIn("sources_index.jsonl", contract.common_files)
        self.assertIn("sources_index.jsonl", contract.machine_ledgers)
        # sources/ holds main-thread archived excerpts; it must never be a
        # worker output directory or find_worker_outputs would drag archived
        # excerpts into worker-output compliance checks.
        self.assertNotIn("sources", contract.worker_output_directories)
        sector = artifact_contract_for_mode("sector")
        self.assertNotIn("sources", sector.worker_output_directories)

    def test_managed_block_for_name_rejects_unknown_block(self):
        with self.assertRaises(ValueError):
            managed_block_for_name("does-not-exist")

    def test_replace_managed_block_uses_registered_markers(self):
        original = "\n".join(
            [
                "# Workflow",
                "## Framing Intent Contract",
                "<!-- SOFA:framing-contract:start -->",
                "old",
                "<!-- SOFA:framing-contract:end -->",
                "## Stage Progress",
                "",
            ]
        )
        updated = replace_managed_block(original, "framing-contract", "new\n")
        self.assertIn("<!-- SOFA:framing-contract:start -->\nnew\n<!-- SOFA:framing-contract:end -->", updated)
        self.assertNotIn("old", updated)

    def test_replace_managed_block_rejects_unknown_block(self):
        with self.assertRaises(ValueError):
            replace_managed_block("text", "unknown-block", "new")

    def test_replace_managed_block_rejects_missing_markers(self):
        # Markers absent → ValueError (not silent passthrough).
        with self.assertRaises(ValueError):
            replace_managed_block("# no markers here\n", "framing-contract", "new")

    def test_replace_managed_block_rejects_duplicate_markers(self):
        # Preserve the duplicate-marker coverage the frontier_lifecycle
        # implementation already provided. Two start markers is ambiguous
        # and must fail rather than silently replacing the first match.
        duplicate = "\n".join(
            [
                "<!-- SOFA:framing-contract:start -->",
                "first",
                "<!-- SOFA:framing-contract:start -->",
                "second",
                "<!-- SOFA:framing-contract:end -->",
            ]
        )
        with self.assertRaises(ValueError):
            replace_managed_block(duplicate, "framing-contract", "new")

    def test_replace_managed_block_rejects_misordered_markers(self):
        misordered = "\n".join(
            [
                "<!-- SOFA:framing-contract:end -->",
                "<!-- SOFA:framing-contract:start -->",
                "first",
            ]
        )
        with self.assertRaises(ValueError):
            replace_managed_block(misordered, "framing-contract", "new")

    def test_replace_managed_block_supports_frontier_review_log_block(self):
        # The frontier-review-log block must still render through the migrated
        # helper. This locks the cross-domain migration: frontier_review.py
        # imports the same helper and its registered block name.
        original = "\n".join(
            [
                "# Workflow",
                "<!-- SOFA:frontier-review-log:start -->",
                "old",
                "<!-- SOFA:frontier-review-log:end -->",
            ]
        )
        updated = replace_managed_block(original, "frontier-review-log", "new content")
        self.assertIn(
            "<!-- SOFA:frontier-review-log:start -->\nnew content\n<!-- SOFA:frontier-review-log:end -->",
            updated,
        )


if __name__ == "__main__":
    unittest.main()
