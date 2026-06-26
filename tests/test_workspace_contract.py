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
    normalize_mode,
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


if __name__ == "__main__":
    unittest.main()
