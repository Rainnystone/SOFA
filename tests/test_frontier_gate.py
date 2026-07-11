import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
GATE_SCRIPT = ROOT / "scripts/gate_check.py"
FRAMING_INTAKE_SCRIPT = ROOT / "scripts/framing_intake.py"

from init_workspace import create_workspace  # noqa: E402
import gate_check  # noqa: E402


class TestFrontierGateIntegration(unittest.TestCase):
    def make_stage_2_ticker_workspace(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        workspace = Path(temp_dir.name) / "ticker-workspace"
        workspace.mkdir()

        (workspace / "scouts").mkdir()
        (workspace / "challenges").mkdir()
        for loop in range(1, 4):
            (workspace / "scouts" / f"loop_{loop}_scout.md").write_text(
                f"# Scout {loop}\n\nEvidence for Frontier A.\n",
                encoding="utf-8",
            )
            (workspace / "challenges" / f"loop_{loop}_challenge.md").write_text(
                f"# Challenge {loop}\n\nChallenge for Frontier A.\n",
                encoding="utf-8",
            )

        (workspace / "state.json").write_text(
            json.dumps(
                {
                    "mode": "ticker",
                    "current_stage": "stage_3",
                    "loop_count": 3,
                    "stages_completed": ["stage_2"],
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
                    "Initial search notes include recent product launch and search records.",
                    "",
                    "## Evidence Loop Tracker",
                    "",
                    "| Loop# | Frontier | Scout File | Challenge File | Gate Score | Decision |",
                    "|---|---|---|---|---|---|",
                    "| 1 | F1 - Frontier A | scouts/loop_1_scout.md | challenges/loop_1_challenge.md | 4 | continue |",
                    "| 2 | F1 - Frontier A | scouts/loop_2_scout.md | challenges/loop_2_challenge.md | 4 | continue |",
                    "| 3 | F1 - Frontier A | scouts/loop_3_scout.md | challenges/loop_3_challenge.md | 5 | continue |",
                    "",
                    "## Serendipity Loop",
                    "",
                    "Serendipity finding recorded and reviewed.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.write_ledger(workspace, loop_count=3)
        self.write_registry(workspace, "Active")
        return workspace

    def write_ledger(self, workspace: Path, loop_count: int, frontier_id: str = "F1") -> None:
        lines = [
            "# Evidence Ledger",
            "",
            "Recent event and product launch context recorded for timeliness.",
            "",
        ]
        for loop in range(1, loop_count + 1):
            lines.extend(
                [
                    f"## Loop {loop}: {frontier_id} - Frontier A",
                    "",
                    "Evidence summary.",
                    "",
                ]
            )
        (workspace / "evidence_ledger.md").write_text("\n".join(lines), encoding="utf-8")

    def write_registry(self, workspace: Path, status: str) -> None:
        (workspace / "frontier_registry.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "subject": "TEST",
                    "mode": "ticker",
                    "frontiers": [
                        {
                            "id": "F1",
                            "name": "Frontier A",
                            "proposed_at_loop": 1,
                            "source": "initial",
                            "source_frontier": None,
                            "status": status,
                            "review_count": 1 if status == "Continued" else 0,
                            "max_reviews": 3,
                            "retire_category": None,
                            "lifecycle": [{"to": status, "at_loop": 3, "ts": None}],
                            "review_decisions": [],
                            "evidence_pointers": [],
                        }
                    ],
                    "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
                    "review_trigger": {"every_loops": 3, "max_reviews": 3},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def layered_v3_registry(self, *, first_status: str = "Continued") -> dict:
        frontiers = []
        for index in range(6):
            status = first_status if index == 0 else "Continued"
            frontiers.append(
                {
                    "id": f"F{index + 1}",
                    "name": f"Frontier {index + 1}",
                    "proposed_at_loop": 1,
                    "source": "initial",
                    "source_frontier": None,
                    "status": status,
                    "review_count": 0 if status == "Active" else 1,
                    "max_reviews": 3,
                    "retire_category": None,
                    "lifecycle": [{"to": status, "at_loop": 3, "ts": None}],
                    "review_decisions": [],
                    "evidence_pointers": [],
                    "layer": index,
                    "parent_frontier": None,
                }
            )
        return {
            "version": 3,
            "subject": "TEST",
            "mode": "ticker",
            "layer_labels": [f"Layer {index}" for index in range(6)],
            "frontiers": frontiers,
            "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
            "review_trigger": {"every_loops": 3, "max_reviews": 3},
        }

    def write_layered_v3_registry(self, workspace: Path, registry: dict) -> None:
        (workspace / "frontier_registry.json").write_text(
            json.dumps(registry, indent=2),
            encoding="utf-8",
        )

    def write_layered_v3_ledger(self, workspace: Path) -> None:
        lines = [
            "# Evidence Ledger",
            "",
            "Recent event and product launch context recorded for timeliness.",
            "",
        ]
        for loop in range(1, 4):
            for frontier in range(1, 7):
                lines.extend(
                    [
                        f"## Loop {loop}: F{frontier} - Frontier {frontier}",
                        "",
                        "Evidence summary.",
                        "",
                    ]
                )
        (workspace / "evidence_ledger.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    def check_gate_with_stdout(self, workspace: Path):
        stdout = StringIO()
        with redirect_stdout(stdout):
            result = gate_check.check_gate(str(workspace), "stage_2", "stage_3")
        return result, stdout.getvalue()

    def run_gate(self, workspace: Path):
        return subprocess.run(
            [sys.executable, str(GATE_SCRIPT), str(workspace), "stage_2", "stage_3"],
            text=True,
            capture_output=True,
        )

    def test_stage_2_gate_blocks_active_frontier_until_lifecycle_review_is_recorded(self):
        workspace = self.make_stage_2_ticker_workspace()

        blocked = self.run_gate(workspace)

        self.assertNotEqual(0, blocked.returncode, blocked.stdout)
        self.assertIn("frontier F1 is Active", blocked.stdout)

        self.write_registry(workspace, "Continued")
        passed = self.run_gate(workspace)

        self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)
        self.assertIn("GATE PASSED", passed.stdout)

    def test_stage_2_gate_blocks_continued_frontier_before_three_bound_loops(self):
        workspace = self.make_stage_2_ticker_workspace()
        self.write_registry(workspace, "Continued")
        self.write_ledger(workspace, loop_count=2)

        blocked = self.run_gate(workspace)

        self.assertNotEqual(0, blocked.returncode, blocked.stdout)
        self.assertIn("frontier F1 is Continued with only 2 loop(s); minimum 3 required before stage_3", blocked.stdout)

    def test_stage_2_gate_reports_missing_frontier_registry_once(self):
        workspace = self.make_stage_2_ticker_workspace()
        (workspace / "frontier_registry.json").unlink()

        blocked = self.run_gate(workspace)

        self.assertNotEqual(0, blocked.returncode, blocked.stdout)
        self.assertEqual(1, blocked.stdout.count("frontier_registry.json not found"))
        self.assertIn("frontier_registry.json not found - run init_workspace.py first", blocked.stdout)

    def test_stage_2_gate_reports_missing_evidence_ledger_once(self):
        workspace = self.make_stage_2_ticker_workspace()
        (workspace / "evidence_ledger.md").unlink()

        blocked = self.run_gate(workspace)

        self.assertNotEqual(0, blocked.returncode, blocked.stdout)
        self.assertEqual(1, blocked.stdout.count("evidence_ledger.md not found"))

    def test_stage_2_gate_reports_unknown_frontier_binding_once(self):
        workspace = self.make_stage_2_ticker_workspace()
        self.write_registry(workspace, "Continued")
        self.write_ledger(workspace, loop_count=3, frontier_id="F9")

        blocked = self.run_gate(workspace)

        self.assertNotEqual(0, blocked.returncode, blocked.stdout)
        self.assertEqual(1, blocked.stdout.count("unknown frontier id in loop header: F9"))

    def test_stage2_layer_warnings_do_not_change_pass_or_missing_when_gate_passes(self):
        workspace = self.make_stage_2_ticker_workspace()
        registry = self.layered_v3_registry()
        self.write_layered_v3_registry(workspace, registry)
        self.write_layered_v3_ledger(workspace)

        baseline_result, baseline_stdout = self.check_gate_with_stdout(workspace)

        registry["frontiers"][0]["layer"] = None
        registry["frontiers"][5]["layer"] = 4
        self.write_layered_v3_registry(workspace, registry)
        warned_result, warned_stdout = self.check_gate_with_stdout(workspace)

        expected_warnings = "\n".join(
            [
                "[WARN] LAYER_UNREPRESENTED: Layers 0 have no bound frontier.",
                "[WARN] LAYER_UNREPRESENTED: Layers 5 have no bound frontier.",
                "[WARN] FRONTIER_LAYER_UNBOUND: Frontiers F1 are not bound to a layer.",
                "",
            ]
        )
        self.assertEqual((True, []), baseline_result)
        self.assertEqual(baseline_result, warned_result)
        self.assertEqual("", baseline_stdout)
        self.assertEqual(expected_warnings, warned_stdout)
        self.assertFalse(any("[WARN]" in item for item in warned_result[1]))

    def test_stage2_layer_warnings_do_not_change_pass_or_missing_when_gate_fails(self):
        workspace = self.make_stage_2_ticker_workspace()
        registry = self.layered_v3_registry(first_status="Active")
        self.write_layered_v3_registry(workspace, registry)
        self.write_layered_v3_ledger(workspace)

        baseline_result, baseline_stdout = self.check_gate_with_stdout(workspace)

        registry["frontiers"][0]["layer"] = None
        registry["frontiers"][5]["layer"] = 4
        self.write_layered_v3_registry(workspace, registry)
        warned_result, warned_stdout = self.check_gate_with_stdout(workspace)

        expected_warnings = "\n".join(
            [
                "[WARN] LAYER_UNREPRESENTED: Layers 0 have no bound frontier.",
                "[WARN] LAYER_UNREPRESENTED: Layers 5 have no bound frontier.",
                "[WARN] FRONTIER_LAYER_UNBOUND: Frontiers F1 are not bound to a layer.",
                "",
            ]
        )
        self.assertEqual(
            (False, ["frontier F1 is Active; resolve it before stage_3"]),
            baseline_result,
        )
        self.assertEqual(baseline_result, warned_result)
        self.assertEqual("", baseline_stdout)
        self.assertEqual(expected_warnings, warned_stdout)
        self.assertFalse(any("[WARN]" in item for item in warned_result[1]))

    def test_stage2_malformed_v3_is_a_failure_not_an_advisory(self):
        workspace = self.make_stage_2_ticker_workspace()
        registry = self.layered_v3_registry()
        registry["frontiers"][0].pop("layer")
        self.write_layered_v3_registry(workspace, registry)
        self.write_layered_v3_ledger(workspace)
        expected = "frontier registry invalid: frontier F1.layer is required"

        result, stdout = self.check_gate_with_stdout(workspace)
        completed = self.run_gate(workspace)

        self.assertEqual((False, [expected]), result)
        self.assertEqual("", stdout)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("Missing 1 prerequisite(s):", completed.stdout)
        self.assertEqual(1, completed.stdout.count(expected))
        self.assertNotIn("[WARN]", completed.stdout)
        self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_stage2_malformed_ledger_is_failure_without_traceback(self):
        workspace = self.make_stage_2_ticker_workspace()
        registry = self.layered_v3_registry(first_status="Active")
        registry["frontiers"][0]["layer"] = None
        registry["frontiers"][5]["layer"] = 4
        self.write_layered_v3_registry(workspace, registry)
        (workspace / "evidence_ledger.md").write_bytes(b"\xff")
        expected = (
            "evidence ledger invalid: 'utf-8' codec can't decode byte 0xff "
            "in position 0: invalid start byte"
        )

        in_process_error = None
        result = None
        stdout = None
        try:
            result, stdout = self.check_gate_with_stdout(workspace)
        except UnicodeError as exc:
            in_process_error = exc
        completed = self.run_gate(workspace)

        leaked = []
        if in_process_error is not None:
            leaked.append(f"in-process leaked {type(in_process_error).__name__}")
        cli_output = completed.stdout + completed.stderr
        if "Traceback" in cli_output or "UnicodeDecodeError" in cli_output:
            leaked.append("CLI leaked UnicodeDecodeError traceback")
        self.assertEqual([], leaked)
        self.assertEqual((False, [expected]), result)
        self.assertEqual("", stdout)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("GATE FAILED: stage_2 -> stage_3", completed.stdout)
        self.assertIn("Missing 1 prerequisite(s):", completed.stdout)
        self.assertEqual(1, completed.stdout.count(expected))
        self.assertNotIn("[WARN]", completed.stdout)
        self.assertNotIn("Traceback", cli_output)
        self.assertNotIn("UnicodeDecodeError", cli_output)

    def test_stage2_unavailable_ledger_preserves_workflow_timeliness_diagnostics(self):
        workflow_violation = (
            "research_workflow.md does not appear to have Stage 0 search records"
        )
        cases = (
            ("missing", "evidence_ledger.md not found"),
            (
                "malformed",
                "evidence ledger invalid: 'utf-8' codec can't decode byte 0xff "
                "in position 0: invalid start byte",
            ),
        )

        for case, ledger_violation in cases:
            with self.subTest(case=case):
                workspace = self.make_stage_2_ticker_workspace()
                registry = self.layered_v3_registry(first_status="Active")
                registry["frontiers"][0]["layer"] = None
                registry["frontiers"][5]["layer"] = 4
                self.write_layered_v3_registry(workspace, registry)

                workflow_path = workspace / "research_workflow.md"
                workflow = workflow_path.read_text(encoding="utf-8")
                workflow = workflow.replace("# Research Workflow", "# Workflow")
                workflow = workflow.replace(
                    "Initial search notes include recent product launch and search records.",
                    "Stage 0 framing context is documented.",
                )
                workflow_path.write_text(workflow, encoding="utf-8")

                ledger_path = workspace / "evidence_ledger.md"
                if case == "missing":
                    ledger_path.unlink()
                else:
                    ledger_path.write_bytes(b"\xff")

                result, stdout = self.check_gate_with_stdout(workspace)
                completed = self.run_gate(workspace)
                cli_output = completed.stdout + completed.stderr

                self.assertEqual(
                    (False, [ledger_violation, workflow_violation]),
                    result,
                )
                self.assertEqual("", stdout)
                self.assertNotEqual(0, completed.returncode)
                self.assertEqual(1, completed.stdout.count(ledger_violation))
                self.assertEqual(1, completed.stdout.count(workflow_violation))
                self.assertNotIn("[WARN]", stdout + cli_output)
                self.assertNotIn("Traceback", stdout + cli_output)

    def test_timeliness_standalone_default_still_checks_ledger_and_workflow(self):
        from timeliness_checker import check_timeliness

        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        workspace = Path(temp_dir.name) / "ticker-workspace"
        workspace.mkdir()
        (workspace / "evidence_ledger.md").write_text(
            "# Evidence Ledger\n\nHistorical context only.\n",
            encoding="utf-8",
        )
        (workspace / "research_workflow.md").write_text(
            "# Workflow\n\nStage 0 framing context is documented.\n",
            encoding="utf-8",
        )

        result = check_timeliness(str(workspace))

        self.assertEqual(
            (
                False,
                [
                    "No timeliness/recent events recorded in evidence_ledger.md",
                    "research_workflow.md does not appear to have Stage 0 search records",
                ],
            ),
            result,
        )

    def test_stage2_gate_reuses_one_registry_and_ledger_snapshot(self):
        from loop_enforcer import check_loop_depth_from_documents as real_document_helper
        import timeliness_checker

        workspace = self.make_stage_2_ticker_workspace()
        registry = self.layered_v3_registry()
        self.write_layered_v3_registry(workspace, registry)
        self.write_layered_v3_ledger(workspace)

        real_open = open
        real_loader = gate_check.load_frontier_registry
        real_coverage = gate_check.derive_frontier_layer_coverage
        real_lifecycle = gate_check.validate_for_stage_transition
        real_timeliness = timeliness_checker.check_timeliness
        opened = []
        read_values = {"frontier_registry.json": [], "evidence_ledger.md": []}
        loaded_registries = []
        coverage_inputs = []
        helper_calls = []
        lifecycle_calls = []
        timeliness_calls = []
        ledger_not_supplied = object()

        class RecordingHandle:
            def __init__(self, handle, name):
                self.handle = handle
                self.name = name

            def __enter__(self):
                self.handle.__enter__()
                return self

            def __exit__(self, *args):
                return self.handle.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.handle, name)

            def read(self, *args, **kwargs):
                value = self.handle.read(*args, **kwargs)
                read_values[self.name].append(value)
                return value

        def recording_open(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            name = Path(path).name
            if name not in read_values:
                return handle
            opened.append(name)
            return RecordingHandle(handle, name)

        def recording_loader(workspace_path):
            loaded = real_loader(workspace_path)
            loaded_registries.append(loaded)
            return loaded

        def recording_coverage(loaded):
            coverage_inputs.append(loaded)
            return real_coverage(loaded)

        def recording_helper(ledger_text, loaded):
            result = real_document_helper(ledger_text, loaded)
            helper_calls.append((ledger_text, loaded, result))
            return result

        def recording_lifecycle(loaded, loop_counts, mode, target_stage):
            lifecycle_calls.append((loaded, loop_counts, mode, target_stage))
            return real_lifecycle(loaded, loop_counts, mode, target_stage)

        def recording_timeliness(
            workspace_path,
            *,
            ledger_text=ledger_not_supplied,
        ):
            timeliness_calls.append(ledger_text)
            if ledger_text is ledger_not_supplied:
                return real_timeliness(workspace_path)
            return real_timeliness(workspace_path, ledger_text=ledger_text)

        stdout = StringIO()
        with (
            mock.patch.object(gate_check, "open", side_effect=recording_open, create=True),
            mock.patch.object(
                timeliness_checker,
                "open",
                side_effect=recording_open,
                create=True,
            ),
            mock.patch.object(
                gate_check,
                "load_frontier_registry",
                side_effect=recording_loader,
            ),
            mock.patch.object(
                gate_check,
                "derive_frontier_layer_coverage",
                side_effect=recording_coverage,
            ),
            mock.patch.object(
                gate_check,
                "check_loop_depth_from_documents",
                side_effect=recording_helper,
                create=True,
            ),
            mock.patch.object(
                gate_check,
                "validate_for_stage_transition",
                side_effect=recording_lifecycle,
            ),
            mock.patch.object(
                gate_check,
                "check_timeliness",
                side_effect=recording_timeliness,
            ),
            redirect_stdout(stdout),
        ):
            result = gate_check.check_gate(str(workspace), "stage_2", "stage_3")

        self.assertEqual((True, []), result)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(
            ["frontier_registry.json", "evidence_ledger.md"],
            opened,
        )
        self.assertEqual(1, len(read_values["frontier_registry.json"]))
        self.assertEqual(1, len(read_values["evidence_ledger.md"]))
        self.assertEqual(1, len(loaded_registries))
        self.assertEqual(1, len(coverage_inputs))
        self.assertEqual(1, len(helper_calls))
        self.assertEqual(1, len(lifecycle_calls))
        self.assertEqual(1, len(timeliness_calls))

        loaded = loaded_registries[0]
        helper_ledger, helper_registry, helper_result = helper_calls[0]
        lifecycle_registry, lifecycle_counts, mode, target_stage = lifecycle_calls[0]
        self.assertIs(loaded, coverage_inputs[0])
        self.assertIs(loaded, helper_registry)
        self.assertIs(loaded, lifecycle_registry)
        self.assertIs(read_values["evidence_ledger.md"][0], helper_ledger)
        self.assertIs(read_values["evidence_ledger.md"][0], timeliness_calls[0])
        self.assertEqual(
            (True, {f"F{index}": 3 for index in range(1, 7)}, []),
            helper_result,
        )
        self.assertIs(helper_result[1], lifecycle_counts)
        self.assertEqual(("ticker", "stage_3"), (mode, target_stage))

    def test_stage_5_gate_uses_contract_for_missing_final_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "ticker-workspace"
            workspace.mkdir()
            (workspace / "scouts").mkdir()
            (workspace / "scouts" / "loop_1_scout.md").write_text(
                "# Scout\n\nMethod cards loaded: supply-chain-mapping\n\nSources consulted: company filing.\n",
                encoding="utf-8",
            )
            (workspace / "research_workflow.md").write_text(
                "\n".join(
                    [
                        "# Research Workflow",
                        "## Stage Progress",
                        "| Stage | Status | Output Files | Notes |",
                        "|-------|--------|--------------|-------|",
                        "| Stage 5: Final Verdict | complete | reports/ | |",
                    ]
                ),
                encoding="utf-8",
            )
            (workspace / "evidence_ledger.md").write_text("# Evidence Ledger\n", encoding="utf-8")
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
                        "mechanism": "host_subagent",
                        "delivery_path": "scouts/loop_1_scout.md",
                        "status": "delivered",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (workspace / "state.json").write_text(
                json.dumps(
                    {
                        "mode": "ticker",
                        "current_stage": "stage_6",
                        "loop_count": 3,
                        "stages_completed": ["stage_0", "stage_1", "stage_2", "stage_3", "stage_4", "stage_5"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), str(workspace), "stage_5", "stage_6"],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(0, result.returncode, result.stdout)
            self.assertIn("FINAL_REPORT_MISSING", result.stdout)


def complete_stage0_framing_contract(workspace: Path) -> None:
    commands = [
        ["set", "--field", "mode", "--value", "ticker"],
        ["set", "--field", "research_posture", "--value", "fresh"],
        ["set", "--field", "time_horizon", "--value", "6-12 months"],
        ["set", "--field", "market_scope", "--value", "US public market"],
        ["set", "--field", "risk_appetite", "--unknown-accepted"],
        ["set", "--field", "output_expectation", "--value", "decision memo"],
        ["set", "--field", "report_language", "--value", "zh"],
        ["set", "--field", "budget_appetite", "--unknown-accepted"],
        [
            "resolve-subject",
            "--name",
            "Coherent Corp",
            "--ticker",
            "COHR",
            "--exchange",
            "NYSE",
            "--method",
            "deterministic_quote",
        ],
    ]
    for args in commands:
        result = subprocess.run(
            [sys.executable, str(FRAMING_INTAKE_SCRIPT), str(workspace), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)


class TestStage0FramingGate(unittest.TestCase):
    def run_gate_transition(self, workspace: Path, from_stage: str, to_stage: str):
        return subprocess.run(
            [sys.executable, str(GATE_SCRIPT), str(workspace), from_stage, to_stage],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_stage_0_gate_fails_when_framing_contract_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_workspace("Coherent Corp", str(workspace), "ticker")
            # A freshly-initialized workspace has an empty framing contract,
            # so the stage_0 -> stage_1 gate must fail and surface framing
            # issue codes in its missing-items output.
            result = self.run_gate_transition(workspace, "stage_0", "stage_1")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            combined = result.stdout + result.stderr
            self.assertIn("FRAMING_FIELD_MISSING", combined)

    def test_stage_0_gate_accepts_complete_framing_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            create_workspace("Coherent Corp", str(workspace), "ticker")
            # Mark stage_0 complete in state.json AND in the workflow Stage
            # Progress row, so the existing "stage_0 not in stages_completed"
            # check and the STATE_WORKFLOW_STAGE_CONFLICT check do not mask
            # the framing-contract check (all run in the stage_0 branch).
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["stages_completed"] = ["stage_0"]
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            workflow_path = workspace / "research_workflow.md"
            workflow = workflow_path.read_text(encoding="utf-8")
            workflow = workflow.replace(
                "| Stage 0: Intake + Framing | in_progress | | |",
                "| Stage 0: Intake + Framing | complete | | |",
            )
            # Also satisfy the existing heading checks the stage_0 branch
            # keeps, so the only remaining gate is the framing contract.
            workflow_path.write_text(
                workflow
                + "\n## Methodology Alignment\n\nfilled\n"
                + "\n## Demand Decomposition\n\nfilled\n"
                + "\n## Blind Spot Report\n\nfilled\n",
                encoding="utf-8",
            )
            complete_stage0_framing_contract(workspace)
            result = self.run_gate_transition(workspace, "stage_0", "stage_1")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
