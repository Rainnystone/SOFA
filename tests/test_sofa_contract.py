import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sofa_contract import ContractIssue, ContractProfile, ContractResult
from sofa_contract.workspace import iter_jsonl_records, read_json_file, read_text_file


class TestContractResultModel(unittest.TestCase):
    def test_contract_result_groups_failures_and_warnings(self):
        result = ContractResult()
        result.fail(
            code="SEARCH_LOG_EMPTY",
            message="search log has no completed records",
            path="search_log.jsonl",
            evidence="0 valid records",
        )
        result.warn(
            code="LEGACY_SEARCH_LOG",
            message="legacy Markdown search log was used",
            path="search_log.md",
            evidence="1 table row",
        )

        self.assertFalse(result.passed)
        self.assertEqual(["SEARCH_LOG_EMPTY"], [issue.code for issue in result.failures])
        self.assertEqual(["LEGACY_SEARCH_LOG"], [issue.code for issue in result.warnings])
        self.assertIn("SEARCH_LOG_EMPTY", result.failures[0].display())
        self.assertIn("search_log.jsonl", result.failures[0].display())

    def test_contract_profile_records_validation_target(self):
        profile = ContractProfile(
            mode="ticker",
            target="final_report",
            from_stage="stage_5",
            to_stage="stage_6",
        )

        self.assertEqual("ticker", profile.mode)
        self.assertEqual("final_report", profile.target)
        self.assertEqual("stage_5", profile.from_stage)
        self.assertEqual("stage_6", profile.to_stage)


class TestWorkspaceReaders(unittest.TestCase):
    def test_json_and_text_readers_return_none_for_missing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            self.assertIsNone(read_text_file(workspace / "missing.md"))
            self.assertIsNone(read_json_file(workspace / "missing.json"))

    def test_json_reader_rejects_non_object_top_level_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata.json"
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"metadata\.json.*JSON file must be an object"):
                read_json_file(path)

    def test_jsonl_reader_skips_blank_lines_and_preserves_line_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "search_log.jsonl"
            path.write_text(
                "\n".join(
                    [
                        "",
                        json.dumps({"query": "first"}),
                        json.dumps({"query": "second"}),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            records = list(iter_jsonl_records(path))

            self.assertEqual(
                [
                    (2, {"query": "first"}),
                    (3, {"query": "second"}),
                ],
                records,
            )


from sofa_contract import evaluate_workspace


def write_base_workspace(workspace: Path, *, stages_completed=None, current_stage="stage_0"):
    stages = stages_completed or []
    (workspace / "state.json").write_text(
        json.dumps(
            {
                "subject": "TEST",
                "mode": "ticker",
                "current_stage": current_stage,
                "loop_count": 0,
                "stages_completed": stages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (workspace / "research_workflow.md").write_text(
        "\n".join(
            [
                "# Research Workflow",
                "",
                "## Stage Progress",
                "| Stage | Status | Output Files | Notes |",
                "|-------|--------|--------------|-------|",
                "| Stage 0: Intake + Framing | complete | | |",
                "| Stage 1: Provisional Frontier Plan | complete | | |",
                "| Stage 2: Evidence Frontier Loops | complete | evidence_ledger.md | |",
                "| Stage 3: Thesis + Financial Bridge | complete | financials/ | |",
                "| Stage 4: Formal Red Team | complete | redteam/ | |",
                "| Stage 5: Final Verdict | pending | reports/ | |",
                "| Stage 6: Watch Protocol | pending | | |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (workspace / "evidence_ledger.md").write_text("# Evidence Ledger\n", encoding="utf-8")


class TestWorkspaceStateAndReportContract(unittest.TestCase):
    def test_early_stage_transition_does_not_require_final_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2"],
                current_stage="stage_3",
            )

            result = evaluate_workspace(
                workspace,
                ContractProfile(mode="ticker", target="stage_transition", from_stage="stage_2", to_stage="stage_3"),
            )

            self.assertNotIn("FINAL_REPORT_MISSING", [issue.code for issue in result.failures])
            self.assertTrue(result.passed)

    def test_state_completed_stage_conflicts_with_workflow_pending_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2", "stage_3", "stage_4", "stage_5"],
                current_stage="stage_6",
            )

            result = evaluate_workspace(
                workspace,
                ContractProfile(mode="ticker", target="stage_transition", from_stage="stage_5", to_stage="stage_6"),
            )

            self.assertFalse(result.passed)
            self.assertIn("STATE_WORKFLOW_STAGE_CONFLICT", [issue.code for issue in result.failures])

    def test_final_report_missing_watch_protocol_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2", "stage_3", "stage_4", "stage_5"],
                current_stage="stage_6",
            )
            reports = workspace / "reports"
            reports.mkdir()
            (reports / "final.md").write_text(
                "\n".join(
                    [
                        "# Final Report",
                        "Conclusion: research status is constructive watch.",
                        "Confidence: medium.",
                        "Time horizon: 12 months.",
                        "Top supporting evidence: evidence_ledger.md#loop-1.",
                        "Strongest counter evidence: customer qualification risk.",
                        "Evidence map: evidence_ledger.md.",
                        "Financial bridge: revenue bridge is constrained by qualification timing.",
                        "Catalyst clock: next filing and customer update.",
                        "Red-team results: unresolved substitution risk.",
                        "Invalidation triggers: lost customer qualification.",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="final_report"))

            self.assertFalse(result.passed)
            self.assertIn("FINAL_REPORT_MISSING_WATCH_PROTOCOL", [issue.code for issue in result.failures])

    def test_sector_report_allows_buyer_qualification_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"],
                current_stage="stage_5",
            )
            reports = workspace / "reports"
            reports.mkdir()
            (reports / "sector.md").write_text(
                "\n".join(
                    [
                        "# Sector Report",
                        "Conclusion: sector map remains incomplete.",
                        "Confidence: medium.",
                        "Time horizon: 12 months.",
                        "Top supporting evidence: evidence_ledger.md#loop-1.",
                        "Strongest counter evidence: buyer qualification remains uneven.",
                        "Evidence map: evidence_ledger.md.",
                        "Financial bridge: revenue bridge is constrained by qualification timing.",
                        "Catalyst clock: next filing and customer update.",
                        "Red-team results: unresolved substitution risk.",
                        "Invalidation triggers: weaker demand.",
                        "Watch protocol: monitor customer updates.",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="final_report"))

            self.assertNotIn("SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE", [issue.code for issue in result.failures])
            self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
