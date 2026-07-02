import contextlib
import io
import json
import subprocess
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
    def test_sofa_contract_does_not_own_worker_output_directory_facts(self):
        import sofa_contract.workspace as workspace_module

        self.assertFalse(hasattr(workspace_module, "WORKER_OUTPUT_DIRS"))

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


def write_valid_search_log(workspace: Path):
    # A workspace that claims loop_count=3 must have one valid search record
    # per loop, so this helper writes all three. Tests that intentionally
    # want incomplete coverage must construct their own partial log.
    records = []
    for loop_id, query in (
        ("loop_1", "customer qualification"),
        ("loop_2", "supply chain mapping"),
        ("loop_3", "competitive landscape"),
    ):
        records.append(
            json.dumps(
                {
                    "loop_id": loop_id,
                    "actor": "main",
                    "tool_tier": "AnySearch",
                    "query": query,
                    "result_status": "completed",
                    "evidence_refs": [f"evidence_ledger.md#{loop_id}"],
                }
            )
        )
    (workspace / "search_log.jsonl").write_text(
        "\n".join(records) + "\n",
        encoding="utf-8",
    )


def write_valid_dispatch_log(workspace: Path):
    (workspace / "dispatch_log.jsonl").write_text(
        json.dumps(
            {
                "dispatch_id": "dispatch_0001",
                "loop_id": "loop_1",
                "role": "scout",
                "mechanism": "host_subagent",
                "delivery_path": "scouts/loop_1_scout.md",
                "status": "delivered",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def write_workflow_with_subagent_dispatch_claim(workspace: Path):
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
                "",
                "## Evidence Loop Tracker",
                "| Loop | Status | Notes |",
                "|------|--------|-------|",
                "| Loop 1 | complete | main-thread evidence only |",
                "",
                "## Subagent Dispatch Log",
                "| Dispatch ID | Loop | Role | Mechanism | Delivery Path | Status |",
                "|-------------|------|------|-----------|---------------|--------|",
                "| dispatch_0001 | loop_1 | scout | host_subagent | scouts/loop_1_scout.md | delivered |",
                "",
                "## Decision Log",
                "- Continue evidence loop.",
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestWorkspaceStateAndReportContract(unittest.TestCase):
    def test_early_stage_transition_does_not_require_final_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2"],
                current_stage="stage_3",
            )
            write_valid_search_log(workspace)

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
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            state["mode"] = "sector"
            (workspace / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            write_valid_search_log(workspace)
            reports = workspace / "reports"
            reports.mkdir()
            # Sector Hunt report following the sector-hunt-guide template. The
            # body intentionally mentions "buyer qualification" — the substring
            # "buy" must NOT be flagged as action-class language because the
            # forbidden-language check uses word boundaries (\bbuy\b).
            (reports / "sector.md").write_text(
                "\n".join(
                    [
                        "# Sector Hunt Report: Test Theme",
                        "",
                        "### Architecture Shift",
                        "Stage 0 architecture shift brief summary.",
                        "",
                        "### Layered Dependency Map",
                        "Stage 2 accumulated dependency ladder summary.",
                        "Buyer qualification remains uneven across the cohort.",
                        "",
                        "### Chokepoint Scoring Matrix",
                        "Stage 3 full 12-dimension scoring table.",
                        "",
                        "### Ranked Candidate Queue",
                        "Tier 1 / Tier 2 / Tier 3 ranked candidates.",
                        "",
                        "### Red Team Summary",
                        "Stage 4 key findings and revisions.",
                        "",
                        "### Recommended Next Steps",
                        "- Priority Ticker Dive targets: list.",
                        "",
                        "### Dive Readiness Score",
                        "- Evidence sufficiency: ready.",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="final_report"))

            self.assertNotIn("SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE", [issue.code for issue in result.failures])
            self.assertTrue(result.passed, [issue.display() for issue in result.failures])

    def test_split_report_fragments_do_not_satisfy_final_report_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace)
            reports = workspace / "reports"
            reports.mkdir()
            (reports / "summary.md").write_text(
                "\n".join(
                    [
                        "# Final Report Summary",
                        "Conclusion: research status is constructive watch.",
                        "Confidence: medium.",
                        "Time horizon: 12 months.",
                        "Top supporting evidence: evidence_ledger.md#loop-1.",
                        "Strongest counter evidence: customer qualification risk.",
                    ]
                ),
                encoding="utf-8",
            )
            (reports / "appendix.md").write_text(
                "\n".join(
                    [
                        "# Final Report Appendix",
                        "Evidence map: evidence_ledger.md.",
                        "Financial bridge: revenue bridge is constrained by qualification timing.",
                        "Catalyst clock: next filing and customer update.",
                        "Red-team results: unresolved substitution risk.",
                        "Invalidation triggers: lost customer qualification.",
                        "Watch protocol: monitor customer updates.",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="final_report"))

            self.assertFalse(result.passed)
            self.assertIn("FINAL_REPORT_MISSING_CONCLUSION", [issue.code for issue in result.failures])


def write_completed_loop_workspace(workspace: Path):
    write_base_workspace(
        workspace,
        stages_completed=["stage_0", "stage_1", "stage_2"],
        current_stage="stage_3",
    )
    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    state["loop_count"] = 3
    (workspace / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    (workspace / "scouts").mkdir()
    (workspace / "scouts" / "loop_1_scout.md").write_text(
        "# Scout\n\nMethod cards loaded: supply-chain-mapping\n\nSources consulted: company filing.\n",
        encoding="utf-8",
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
                "Watch protocol: monitor customer updates.",
            ]
        ),
        encoding="utf-8",
    )


class TestSearchAndDispatchContract(unittest.TestCase):
    def test_completed_loops_without_search_log_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_legacy_markdown_search_log_warns_but_does_not_satisfy_search_compliance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            (workspace / "search_log.md").write_text(
                "\n".join(
                    [
                        "# Search Log",
                        "| Time | Query | Tool Tier | Result | Notes |",
                        "|------|-------|-----------|--------|-------|",
                        "| 2026-06-26 | customer qualification | AnySearch | completed | evidence_ledger.md#loop-1 |",
                    ]
                ),
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])
            self.assertIn("LEGACY_SEARCH_LOG_USED", [issue.code for issue in result.warnings])

    def test_malformed_search_jsonl_returns_missing_failure_and_legacy_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_dispatch_log(workspace)
            (workspace / "search_log.jsonl").write_text("{not valid json\n", encoding="utf-8")
            (workspace / "search_log.md").write_text(
                "\n".join(
                    [
                        "# Search Log",
                        "| Time | Query | Tool Tier | Result | Notes |",
                        "|------|-------|-----------|--------|-------|",
                        "| 2026-06-26 | customer qualification | AnySearch | completed | evidence_ledger.md#loop-1 |",
                    ]
                ),
                encoding="utf-8",
            )

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])
            self.assertIn("LEGACY_SEARCH_LOG_USED", [issue.code for issue in result.warnings])

    def test_non_object_search_jsonl_record_returns_missing_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_dispatch_log(workspace)
            (workspace / "search_log.jsonl").write_text(json.dumps([1, 2, 3]) + "\n", encoding="utf-8")

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_valid_first_search_jsonl_line_with_later_malformed_line_returns_missing_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_dispatch_log(workspace)
            (workspace / "search_log.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "loop_id": "loop_1",
                                "actor": "main",
                                "tool_tier": "AnySearch",
                                "query": "customer qualification",
                                "result_status": "completed",
                                "evidence_refs": ["evidence_ledger.md#loop-1"],
                            }
                        ),
                        "{not valid json",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_valid_first_search_jsonl_line_with_later_non_object_line_returns_missing_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_dispatch_log(workspace)
            (workspace / "search_log.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "loop_id": "loop_1",
                                "actor": "main",
                                "tool_tier": "AnySearch",
                                "query": "customer qualification",
                                "result_status": "completed",
                                "evidence_refs": ["evidence_ledger.md#loop-1"],
                            }
                        ),
                        json.dumps([1, 2, 3]),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_completed_loop_workspace_with_valid_search_jsonl_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            write_valid_dispatch_log(workspace)

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertTrue(result.passed)

    def test_worker_output_without_dispatch_ledger_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            (workspace / "search_log.jsonl").write_text(
                json.dumps(
                    {
                        "loop_id": "loop_1",
                        "actor": "main",
                        "tool_tier": "AnySearch",
                        "query": "customer qualification",
                        "result_status": "completed",
                        "evidence_refs": ["evidence_ledger.md#loop-1"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_degraded_single_agent_cannot_be_labeled_subagent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            (workspace / "search_log.jsonl").write_text(
                json.dumps(
                    {
                        "loop_id": "loop_1",
                        "actor": "main",
                        "tool_tier": "AnySearch",
                        "query": "customer qualification",
                        "result_status": "completed",
                        "evidence_refs": ["evidence_ledger.md#loop-1"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "degraded_single_agent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                        "degraded_mode_approved": True,
                        "label": "subagent dispatch",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("DEGRADED_MODE_MISLABELED", [issue.code for issue in result.failures])

    def test_completed_search_record_requires_binding_and_trace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            (workspace / "search_log.jsonl").write_text(
                json.dumps(
                    {
                        "degraded_reason": "tool unavailable",
                        "result_status": "completed",
                        "gaps": ["missing customer qualification trace"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])

    def test_degraded_dispatch_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "degraded_single_agent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("DEGRADED_MODE_NOT_APPROVED", [issue.code for issue in result.failures])

    def test_dispatch_record_without_identity_fields_does_not_count_as_proof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            failure_codes = [issue.code for issue in result.failures]
            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_RECORD_INCOMPLETE", failure_codes)
            self.assertIn("WORKER_OUTPUT_WITHOUT_DISPATCH", failure_codes)

    def test_host_subagent_dispatch_requires_core_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            failure_codes = [issue.code for issue in result.failures]
            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_RECORD_INCOMPLETE", failure_codes)
            self.assertIn("WORKER_OUTPUT_WITHOUT_DISPATCH", failure_codes)

    def test_delivered_dispatch_requires_mechanism(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            failure_codes = [issue.code for issue in result.failures]
            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_RECORD_INCOMPLETE", failure_codes)
            self.assertIn("WORKER_OUTPUT_WITHOUT_DISPATCH", failure_codes)

    def test_unsupported_dispatch_mechanism_does_not_count_as_proof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "single_agent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            failure_codes = [issue.code for issue in result.failures]
            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_MECHANISM_UNSUPPORTED", failure_codes)
            self.assertIn("WORKER_OUTPUT_WITHOUT_DISPATCH", failure_codes)

    def test_delivered_dispatch_record_requires_existing_delivery_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(
                workspace,
                stages_completed=["stage_0", "stage_1", "stage_2"],
                current_stage="stage_3",
            )
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            state["loop_count"] = 1
            (workspace / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/missing.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(
                workspace,
                ContractProfile(mode="ticker", target="stage_transition", from_stage="stage_2", to_stage="stage_3"),
            )

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_DELIVERY_MISSING", [issue.code for issue in result.failures])

    def test_header_only_legacy_markdown_search_log_does_not_warn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            (workspace / "search_log.md").write_text(
                "\n".join(
                    [
                        "# Search Log",
                        "| Time | Query | Tool Tier | Result | Notes |",
                        "|------|-------|-----------|--------|-------|",
                    ]
                ),
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("SEARCH_LOG_MISSING", [issue.code for issue in result.failures])
            self.assertNotIn("LEGACY_SEARCH_LOG_USED", [issue.code for issue in result.warnings])

    def test_workflow_subagent_dispatch_claim_requires_machine_delivery_proof(self):
        cases = [
            ("missing", None),
            ("empty", ""),
            (
                "no_delivery",
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "planned",
                    }
                )
                + "\n",
            ),
        ]
        for label, dispatch_text in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    write_base_workspace(workspace)
                    write_workflow_with_subagent_dispatch_claim(workspace)
                    if dispatch_text is not None:
                        (workspace / "dispatch_log.jsonl").write_text(dispatch_text, encoding="utf-8")

                    result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="stage_transition"))

                    self.assertFalse(result.passed)
                    self.assertIn("DISPATCH_PROOF_MISSING", [issue.code for issue in result.failures])

    def test_subagent_dispatch_log_delivered_status_requires_machine_delivery_proof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace)
            (workspace / "research_workflow.md").write_text(
                "\n".join(
                    [
                        "# Research Workflow",
                        "",
                        "## Subagent Dispatch Log",
                        "| Time | Loop# | Role | File Path | Status | Quality |",
                        "|------|-------|------|-----------|--------|---------|",
                        "| 2026-06-26 | 1 | scout | scouts/loop_1_scout.md | delivered | good |",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="stage_transition"))

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_PROOF_MISSING", [issue.code for issue in result.failures])

    def test_workflow_tables_outside_subagent_dispatch_log_do_not_require_dispatch_proof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace)
            (workspace / "research_workflow.md").write_text(
                "\n".join(
                    [
                        "# Research Workflow",
                        "",
                        "## Stage Progress",
                        "| Stage | Status | Output Files | Notes |",
                        "|-------|--------|--------------|-------|",
                        "| Stage 2: Evidence Frontier Loops | complete | scouts/loop_1_scout.md | subagent delivered |",
                        "",
                        "## Evidence Loop Tracker",
                        "| Loop | Status | Notes |",
                        "|------|--------|-------|",
                        "| Loop 1 | complete | host_subagent delivered |",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="stage_transition"))

            self.assertTrue(result.passed, [issue.code for issue in result.failures])

    def test_malformed_dispatch_jsonl_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace)
            write_workflow_with_subagent_dispatch_claim(workspace)
            (workspace / "dispatch_log.jsonl").write_text("{not valid json\n", encoding="utf-8")

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="stage_transition"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_LOG_INVALID", [issue.code for issue in result.failures])

    def test_non_object_dispatch_jsonl_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace)
            write_workflow_with_subagent_dispatch_claim(workspace)
            (workspace / "dispatch_log.jsonl").write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")

            try:
                result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="stage_transition"))
            except Exception as exc:
                self.fail(f"evaluate_workspace raised {type(exc).__name__}: {exc}")

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_LOG_INVALID", [issue.code for issue in result.failures])


def write_valid_machine_ledgers(workspace: Path):
    write_valid_search_log(workspace)
    write_valid_dispatch_log(workspace)


class TestWorkerOutputContract(unittest.TestCase):
    def test_worker_output_missing_method_cards_loaded_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_machine_ledgers(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nSources consulted: company filing.\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("WORKER_METHOD_CARDS_MISSING", [issue.code for issue in result.failures])

    def test_worker_output_missing_source_trace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_machine_ledgers(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("WORKER_SOURCE_TRACE_MISSING", [issue.code for issue in result.failures])

    def test_scout_output_with_action_class_language_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_machine_ledgers(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\nSources consulted: company filing.\n\nAction Class: buy.\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("SCOUT_FORBIDDEN_CONCLUSION", [issue.code for issue in result.failures])

    def test_scout_action_language_matches_case_insensitive_independent_terms(self):
        cases = [
            "action class: buy.",
            "Conclusion: buy.",
            "Recommendation: sell.",
            "strong buy.",
        ]
        for text in cases:
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    write_completed_loop_workspace(workspace)
                    write_valid_machine_ledgers(workspace)
                    (workspace / "scouts" / "loop_1_scout.md").write_text(
                        "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\nSources consulted: company filing.\n\n"
                        + text
                        + "\n",
                        encoding="utf-8",
                    )

                    result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

                    self.assertFalse(result.passed)
                    self.assertIn("SCOUT_FORBIDDEN_CONCLUSION", [issue.code for issue in result.failures])

    def test_scout_action_language_does_not_match_word_fragments_or_hyphenated_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_machine_ledgers(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\n"
                "Method cards loaded: supply-chain-mapping.\n\n"
                "Sources consulted: company filing.\n\n"
                "BUYER qualification only. SELLING expenses noted. SELL-side context only.\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertTrue(result.passed, [issue.code for issue in result.failures])

    def test_source_trace_accepts_heading_or_label_case_insensitively(self):
        cases = [
            "sources consulted: company filing.",
            "### evidence sources\n- company filing.",
        ]
        for text in cases:
            with self.subTest(text=text):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = Path(temp_dir)
                    write_completed_loop_workspace(workspace)
                    write_valid_machine_ledgers(workspace)
                    (workspace / "scouts" / "loop_1_scout.md").write_text(
                        "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\n" + text + "\n",
                        encoding="utf-8",
                    )

                    result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

                    self.assertTrue(result.passed, [issue.code for issue in result.failures])

    def test_source_trace_does_not_match_chinese_body_sentence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_machine_ledgers(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\n观点来源尚未形成检索清单。\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(result.passed)
            self.assertIn("WORKER_SOURCE_TRACE_MISSING", [issue.code for issue in result.failures])

    def test_dispatch_role_must_match_delivery_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace, stages_completed=[], current_stage="stage_0")
            (workspace / "scouts").mkdir()
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\nSources consulted: company filing.\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "financial",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="workspace"))

            self.assertFalse(result.passed)
            self.assertIn("DISPATCH_ROLE_DELIVERY_MISMATCH", [issue.code for issue in result.failures])

    def test_sector_mapper_forbidden_action_language_uses_catalog_role_facts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace, stages_completed=[], current_stage="stage_0")
            (workspace / "maps").mkdir()
            (workspace / "maps" / "mapping_1.md").write_text(
                "# Sector Mapper\n\n"
                "Method cards loaded: supply-chain-mapping.\n\n"
                "Sources consulted: company filing.\n\n"
                "Action Class: buy.\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "sector_mapper",
                        "mechanism": "host_subagent",
                        "delivery_path": "maps/mapping_1.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="workspace"))

            self.assertFalse(result.passed)
            self.assertIn("WORKER_FORBIDDEN_CONCLUSION", [issue.code for issue in result.failures])


VALIDATE_DOSSIER_SCRIPT = ROOT / "scripts/validate_dossier.py"


def write_dossier_ready_workspace(workspace: Path) -> None:
    write_base_workspace(
        workspace,
        stages_completed=["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"],
        current_stage="stage_5",
    )
    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    state["loop_count"] = 3
    (workspace / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    (workspace / "evidence_ledger.md").write_text(
        "\n".join(
            [
                "# Evidence Ledger",
                "",
                "## Loop 1: Customer qualification",
                "Evidence body with enough detail to keep the legacy dossier check focused on hard prerequisites. "
                "The synthetic record cites filings, channel checks, and counter-evidence for the first loop.",
                "",
                "## Loop 2: Revenue bridge",
                "Evidence body with enough detail to keep the legacy dossier check focused on hard prerequisites. "
                "The synthetic record cites filings, channel checks, and counter-evidence for the second loop.",
                "",
                "## Loop 3: Competitive pressure",
                "Evidence body with enough detail to keep the legacy dossier check focused on hard prerequisites. "
                "The synthetic record cites filings, channel checks, and counter-evidence for the third loop.",
            ]
        ),
        encoding="utf-8",
    )

    worker_files = []
    for directory in ["scouts", "challenges", "financials", "redteam"]:
        (workspace / directory).mkdir(exist_ok=True)

    for loop in range(1, 4):
        scout = workspace / "scouts" / f"loop_{loop}_scout.md"
        scout.write_text(
            "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n\nSources consulted: company filing.\n",
            encoding="utf-8",
        )
        worker_files.append(scout)

        challenge = workspace / "challenges" / f"loop_{loop}_challenge.md"
        challenge.write_text(
            "# Challenge\n\nMethod cards loaded: red-team.\n\nSources consulted: company filing.\n",
            encoding="utf-8",
        )
        worker_files.append(challenge)

        redteam = workspace / "redteam" / f"round{loop}_redteam.md"
        redteam.write_text(
            "# Red Team\n\nMethod cards loaded: red-team.\n\nSources consulted: company filing.\n",
            encoding="utf-8",
        )
        worker_files.append(redteam)

        defense = workspace / "redteam" / f"round{loop}_defense.md"
        defense.write_text(
            "# Defense\n\nMethod cards loaded: main-thread-defense.\n\nSources consulted: company filing.\n",
            encoding="utf-8",
        )
        worker_files.append(defense)

    bridge = workspace / "financials" / "bridge.md"
    bridge.write_text(
        "# Financial Bridge\n\nMethod cards loaded: financial-bridge.\n\nSources consulted: company filing.\n",
        encoding="utf-8",
    )
    worker_files.append(bridge)

    revision = workspace / "redteam" / "thesis_revision.md"
    revision.write_text(
        "# Thesis Revision\n\nMethod cards loaded: thesis-revision.\n\nSources consulted: company filing.\n",
        encoding="utf-8",
    )
    worker_files.append(revision)

    write_valid_search_log(workspace)
    dispatch_records = []
    for index, path in enumerate(worker_files, start=1):
        dispatch_records.append(
            {
                "dispatch_id": f"dispatch_{index:04d}",
                "loop_id": "loop_1",
                "role": path.parent.name,
                "mechanism": "host_subagent",
                "delivery_path": path.relative_to(workspace).as_posix(),
                "status": "delivered",
            }
        )
    (workspace / "dispatch_log.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in dispatch_records),
        encoding="utf-8",
    )


class TestDossierValidatorContractIntegration(unittest.TestCase):
    def test_validate_dossier_fails_when_contract_finds_bad_worker_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_dossier_ready_workspace(workspace)
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nSources consulted: company filing.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(VALIDATE_DOSSIER_SCRIPT), str(workspace)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("WORKER_METHOD_CARDS_MISSING", result.stdout)

    def test_validate_dossier_does_not_require_final_report_before_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_dossier_ready_workspace(workspace)

            result = subprocess.run(
                [sys.executable, str(VALIDATE_DOSSIER_SCRIPT), str(workspace)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )

            self.assertEqual(0, result.returncode, result.stdout)
            self.assertNotIn("FINAL_REPORT_MISSING", result.stdout)


def write_sector_dossier_ready_workspace(workspace: Path) -> None:
    """A sector-mode workspace that satisfies the dossier contract once the
    final-report requirements are mode-aware. Worker outputs all carry
    method cards + a source trace; maps/dependency_ladder.md is present as the
    core main-thread artifact (it must NOT be treated as a worker output)."""
    write_base_workspace(
        workspace,
        stages_completed=["stage_0", "stage_1", "stage_2", "stage_3", "stage_4"],
        current_stage="stage_5",
    )
    state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
    state["mode"] = "sector"
    state["loop_count"] = 3
    (workspace / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

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
                "| Stage 2: Mapping Loops | complete | maps/dependency_ladder.md | |",
                "| Stage 3: Chokepoint Scoring + Financial Screen | complete | maps/ | |",
                "| Stage 4: Mapping Integrity Review | complete | redteam/ | |",
                "| Stage 5: Final Verdict | pending | reports/ | |",
                "| Stage 6: Watch Protocol | pending | | |",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (workspace / "evidence_ledger.md").write_text(
        "\n".join(
            [
                "# Evidence Ledger",
                "",
                "## Loop 1: mapping node A",
                "Evidence body for the first mapping loop citing channel checks and counter-evidence.",
                "",
                "## Loop 2: mapping node B",
                "Evidence body for the second mapping loop citing channel checks and counter-evidence.",
                "",
                "## Loop 3: mapping node C",
                "Evidence body for the third mapping loop citing channel checks and counter-evidence.",
            ]
        ),
        encoding="utf-8",
    )

    for dirname in ("maps", "coverage", "financials", "redteam"):
        (workspace / dirname).mkdir(exist_ok=True)

    # Core main-thread artifact: NOT a subagent worker output.
    (workspace / "maps" / "dependency_ladder.md").write_text(
        "# Dependency Ladder\n\n- node A\n- node B\n- node C\n",
        encoding="utf-8",
    )

    dispatch_records = []
    for loop in range(1, 4):
        (workspace / "maps" / f"mapping_{loop}.md").write_text(
            "# Mapping\n\nMethod cards loaded: supply-chain-mapping.\n\nSearch Exhaustion Report: 3 sources consulted.\n",
            encoding="utf-8",
        )
        dispatch_records.append(
            {
                "dispatch_id": f"dispatch_map_{loop:04d}",
                "loop_id": f"loop_{loop}",
                "role": "mapper",
                "mechanism": "host_subagent",
                "delivery_path": f"maps/mapping_{loop}.md",
                "status": "delivered",
            }
        )
        (workspace / "coverage" / f"coverage_{loop}.md").write_text(
            "# Coverage Challenge\n\nMethod cards loaded: coverage-challenge.\n\nSources consulted: channel checks.\n",
            encoding="utf-8",
        )
        dispatch_records.append(
            {
                "dispatch_id": f"dispatch_cov_{loop:04d}",
                "loop_id": f"loop_{loop}",
                "role": "coverage",
                "mechanism": "host_subagent",
                "delivery_path": f"coverage/coverage_{loop}.md",
                "status": "delivered",
            }
        )

    (workspace / "financials" / "screen.md").write_text(
        "# Financial Screen\n\nMethod cards loaded: financial-bridge.\n\nSources consulted: filings.\n",
        encoding="utf-8",
    )
    dispatch_records.append(
        {
            "dispatch_id": "dispatch_fin_0001",
            "loop_id": "loop_1",
            "role": "financial",
            "mechanism": "host_subagent",
            "delivery_path": "financials/screen.md",
            "status": "delivered",
        }
    )

    for loop in range(1, 4):
        (workspace / "redteam" / f"round{loop}_redteam.md").write_text(
            "# Red Team\n\nMethod cards loaded: red-team.\n\nSources consulted: filings.\n",
            encoding="utf-8",
        )
        dispatch_records.append(
            {
                "dispatch_id": f"dispatch_rt_{loop:04d}",
                "loop_id": f"loop_{loop}",
                "role": "redteam",
                "mechanism": "host_subagent",
                "delivery_path": f"redteam/round{loop}_redteam.md",
                "status": "delivered",
            }
        )
    (workspace / "redteam" / "thesis_revision.md").write_text(
        "# Thesis Revision\n\nMethod cards loaded: thesis-revision.\n\nSources consulted: filings.\n",
        encoding="utf-8",
    )
    dispatch_records.append(
        {
            "dispatch_id": "dispatch_tr_0001",
            "loop_id": "loop_1",
            "role": "thesis-revision",
            "mechanism": "host_subagent",
            "delivery_path": "redteam/thesis_revision.md",
            "status": "delivered",
        }
    )

    (workspace / "search_log.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "loop_id": f"loop_{loop}",
                    "actor": "main",
                    "tool_tier": "AnySearch",
                    "query": f"sector mapping loop {loop}",
                    "result_status": "completed",
                    "evidence_refs": [f"evidence_ledger.md#loop-{loop}"],
                }
            )
            + "\n"
            for loop in range(1, 4)
        ),
        encoding="utf-8",
    )

    (workspace / "dispatch_log.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in dispatch_records),
        encoding="utf-8",
    )

    reports = workspace / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "final.md").write_text(
        "\n".join(
            [
                "# Sector Hunt Report: Test Theme",
                "",
                "### Architecture Shift",
                "Stage 0 architecture shift brief summary.",
                "",
                "### Layered Dependency Map",
                "Stage 2 accumulated dependency ladder summary.",
                "",
                "### Chokepoint Scoring Matrix",
                "Stage 3 full 12-dimension scoring table.",
                "",
                "### Ranked Candidate Queue",
                "Tier 1 / Tier 2 / Tier 3 ranked candidates.",
                "",
                "### Red Team Summary",
                "Stage 4 key findings and revisions.",
                "",
                "### Recommended Next Steps",
                "- Priority Ticker Dive targets: list.",
                "- Basket candidates: list.",
                "",
                "### Dive Readiness Score",
                "- Evidence sufficiency: ready.",
            ]
        ),
        encoding="utf-8",
    )


class TestCodexCloudReviewRegressions(unittest.TestCase):
    """Regression guards for codex cloud review comments on PR #6.

    Each test maps to one review comment and was written red (before the fix).
    """

    # --- #1: maps/dependency_ladder.md is a core artifact, not a worker output ---
    def test_find_worker_outputs_excludes_dependency_ladder(self):
        from sofa_contract.workspace import find_worker_outputs

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            maps = workspace / "maps"
            maps.mkdir()
            (maps / "dependency_ladder.md").write_text("# Dependency Ladder\n", encoding="utf-8")
            (maps / "mapping_1.md").write_text("# Mapping 1\n", encoding="utf-8")
            (maps / "mapping_2.md").write_text("# Mapping 2\n", encoding="utf-8")

            names = [path.name for path in find_worker_outputs(workspace)]

            self.assertNotIn("dependency_ladder.md", names)
            self.assertIn("mapping_1.md", names)
            self.assertIn("mapping_2.md", names)

    def test_find_worker_outputs_returns_only_worker_map_outputs(self):
        from sofa_contract.workspace import find_worker_outputs

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            maps = workspace / "maps"
            maps.mkdir()
            (maps / "dependency_ladder.md").write_text("# Dependency Ladder\n", encoding="utf-8")
            (maps / "sector_mapper_loop1.md").write_text("# Sector Mapper\n", encoding="utf-8")

            outputs = [path.relative_to(workspace).as_posix() for path in find_worker_outputs(workspace)]

            self.assertEqual(["maps/sector_mapper_loop1.md"], outputs)

    # --- #2: a workspace advanced via complete_stage() must not be rejected ---
    def test_complete_stage_updates_workflow_progress_row(self):
        from gate_check import complete_stage

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace, stages_completed=[], current_stage="stage_0")
            # Mimic init_workspace.py: Stage Progress rows start as pending, not
            # pre-marked complete. complete_stage() must flip the row too.
            (workspace / "research_workflow.md").write_text(
                "\n".join(
                    [
                        "# Research Workflow",
                        "",
                        "## Stage Progress",
                        "| Stage | Status | Output Files | Notes |",
                        "|-------|--------|--------------|-------|",
                        "| Stage 0: Intake + Framing | pending | | |",
                        "| Stage 1: Provisional Frontier Plan | pending | | |",
                        "| Stage 2: Evidence Frontier Loops | pending | evidence_ledger.md | |",
                        "| Stage 3: Thesis + Financial Bridge | pending | financials/ | |",
                        "| Stage 4: Formal Red Team | pending | redteam/ | |",
                        "| Stage 5: Final Verdict | pending | reports/ | |",
                        "| Stage 6: Watch Protocol | pending | | |",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                complete_stage(str(workspace), "stage_0")

            self.assertIn("STAGE COMPLETED: stage_0", stdout.getvalue())

            result = evaluate_workspace(
                workspace,
                ContractProfile(
                    mode="ticker",
                    target="stage_transition",
                    from_stage="stage_0",
                    to_stage="stage_1",
                ),
            )

            self.assertNotIn(
                "STATE_WORKFLOW_STAGE_CONFLICT",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )
            self.assertTrue(result.passed, [issue.display() for issue in result.failures])

    # --- #3: sector final reports must be judged by sector requirements ---
    def test_sector_final_report_passes_with_sector_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_sector_dossier_ready_workspace(workspace)

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="dossier"))

            ticker_only_codes = [
                code
                for code in (
                    "FINAL_REPORT_MISSING_CONFIDENCE",
                    "FINAL_REPORT_MISSING_TIME_HORIZON",
                    "FINAL_REPORT_MISSING_FINANCIAL_BRIDGE",
                    "FINAL_REPORT_MISSING_CATALYST_CLOCK",
                    "FINAL_REPORT_MISSING_WATCH_PROTOCOL",
                )
                if code in [issue.code for issue in result.failures]
            ]
            self.assertEqual([], ticker_only_codes, ticker_only_codes)
            self.assertTrue(result.passed, [issue.display() for issue in result.failures])

    def test_sector_report_rejects_chinese_action_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_sector_dossier_ready_workspace(workspace)
            report = workspace / "reports" / "final.md"
            report.write_text(
                report.read_text(encoding="utf-8")
                + "\n\n### 结论\n建议买入该板块龙头，卖出弱势票。\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="dossier"))

            self.assertIn(
                "SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )

    def test_sector_report_rejects_action_language_in_any_complete_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_sector_dossier_ready_workspace(workspace)
            reports = workspace / "reports"
            clean_text = (reports / "final.md").read_text(encoding="utf-8")
            (reports / "a_clean.md").write_text(clean_text, encoding="utf-8")
            (reports / "z_bad.md").write_text(
                clean_text + "\n\n### Action Class\nBuy this sector basket.\n",
                encoding="utf-8",
            )
            (reports / "final.md").unlink()

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="dossier"))

            self.assertIn(
                "SECTOR_REPORT_FORBIDDEN_ACTION_LANGUAGE",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )

    # --- #4: absolute dispatch delivery paths must be normalized to workspace-relative ---
    def test_dispatch_absolute_delivery_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            absolute_delivery = str(workspace / "scouts" / "loop_1_scout.md")
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": absolute_delivery,
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertNotIn(
                "WORKER_OUTPUT_WITHOUT_DISPATCH",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )
            self.assertTrue(result.passed, [issue.display() for issue in result.failures])

    def test_dispatch_relative_delivery_path_is_normalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            write_valid_search_log(workspace)
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "./scouts/../scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertNotIn(
                "WORKER_OUTPUT_WITHOUT_DISPATCH",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )
            self.assertTrue(result.passed, [issue.display() for issue in result.failures])

    # --- #5: source trace is mandatory for scouts, optional for analysis roles ---
    def test_non_scout_worker_output_without_source_trace_does_not_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace, stages_completed=[], current_stage="stage_0")
            (workspace / "challenges").mkdir()
            (workspace / "challenges" / "loop_1_challenge.md").write_text(
                "# Challenge\n\nMethod cards loaded: red-team.\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "challenge",
                        "mechanism": "host_subagent",
                        "delivery_path": "challenges/loop_1_challenge.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="workspace"))

            self.assertNotIn(
                "WORKER_SOURCE_TRACE_MISSING",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )

    def test_scout_worker_output_without_source_trace_still_fails(self):
        # Scouts perform search; their source trace stays mandatory.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_base_workspace(workspace, stages_completed=[], current_stage="stage_0")
            (workspace / "scouts").mkdir()
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping.\n",
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_text(
                json.dumps(
                    {
                        "dispatch_id": "dispatch_0001",
                        "loop_id": "loop_1",
                        "role": "scout",
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="workspace"))

            self.assertIn(
                "WORKER_SOURCE_TRACE_MISSING",
                [issue.code for issue in result.failures],
            )

    def test_mapper_worker_output_without_source_trace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_sector_dossier_ready_workspace(workspace)
            (workspace / "maps" / "mapping_1.md").write_text(
                "# Mapping\n\nMethod cards loaded: supply-chain-mapping.\n",
                encoding="utf-8",
            )

            result = evaluate_workspace(workspace, ContractProfile(mode="sector", target="dossier"))

            self.assertIn(
                "WORKER_SOURCE_TRACE_MISSING",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )

    # --- #6: every completed loop needs its own search record ---
    def test_completed_loops_need_per_loop_search_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            write_completed_loop_workspace(workspace)
            # Intentionally provide only a loop_1 search record while
            # loop_count=3 — the workspace must be rejected for missing
            # per-loop coverage (SEARCH_LOG_LOOP_COVERAGE_MISSING).
            (workspace / "search_log.jsonl").write_text(
                json.dumps(
                    {
                        "loop_id": "loop_1",
                        "actor": "main",
                        "tool_tier": "AnySearch",
                        "query": "customer qualification",
                        "result_status": "completed",
                        "evidence_refs": ["evidence_ledger.md#loop_1"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            write_valid_dispatch_log(workspace)

            result = evaluate_workspace(workspace, ContractProfile(mode="ticker", target="dossier"))

            self.assertFalse(
                result.passed,
                "workspace with loop_count=3 but only a loop_1 search record must be rejected",
            )
            self.assertIn(
                "SEARCH_LOG_LOOP_COVERAGE_MISSING",
                [issue.code for issue in result.failures],
                [issue.display() for issue in result.failures],
            )
            missing_issue = next(
                issue
                for issue in result.failures
                if issue.code == "SEARCH_LOG_LOOP_COVERAGE_MISSING"
            )
            self.assertIn("loop_2", missing_issue.evidence)
            self.assertIn("loop_3", missing_issue.evidence)


if __name__ == "__main__":
    unittest.main()
