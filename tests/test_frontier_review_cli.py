import contextlib
import io
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = ROOT / "scripts/init_workspace.py"
REVIEW_SCRIPT = ROOT / "scripts/frontier_review.py"


def load_review_module():
    script_dir = str(REVIEW_SCRIPT.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("frontier_review_under_test", REVIEW_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFrontierReviewCli(unittest.TestCase):
    def make_workspace(self, mode="ticker"):
        temp_dir = tempfile.TemporaryDirectory()
        workspace = Path(temp_dir.name) / f"{mode}-workspace"
        subprocess.run(
            [
                sys.executable,
                str(INIT_SCRIPT),
                "MXL" if mode == "ticker" else "AI Optical Interconnect",
                str(workspace),
                "--mode",
                mode,
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        self.addCleanup(temp_dir.cleanup)
        return workspace

    def run_cli(self, workspace, *args):
        return subprocess.run(
            [sys.executable, str(REVIEW_SCRIPT), str(workspace), *args],
            text=True,
            capture_output=True,
        )

    def registry(self, workspace):
        return json.loads((workspace / "frontier_registry.json").read_text(encoding="utf-8"))

    def write_loops(self, workspace, frontier_id="F1", name="InP supply risk", count=3):
        lines = ["# Evidence Ledger: MXL", ""]
        for index in range(1, count + 1):
            lines.append(f"## Loop {index}: {frontier_id} - {name}")
            lines.append("")
            lines.append("Evidence summary.")
            lines.append("")
        (workspace / "evidence_ledger.md").write_text("\n".join(lines), encoding="utf-8")

    def add_and_start_frontier(self, workspace, name="InP supply risk", expected_id="F1"):
        add_result = self.run_cli(
            workspace,
            "add",
            "--name",
            name,
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(0, add_result.returncode, add_result.stderr)
        self.assertIn(f"Added {expected_id}", add_result.stdout)

        start_result = self.run_cli(workspace, "start", expected_id)
        self.assertEqual(0, start_result.returncode, start_result.stderr)
        self.assertIn(f"{expected_id} -> Active", start_result.stdout)

    def test_full_review_flow_records_logs_without_duplicate_rendering(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)

        due = self.run_cli(workspace, "check-review")
        self.assertEqual(1, due.returncode)
        self.assertIn("F1 reached loop 3", due.stdout)

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
            "--reject",
            "Silicon photonics tangent::does not alter the demand layer",
        )
        self.assertEqual(0, record.returncode, record.stderr)
        self.assertIn("Recorded F1 -> Continued", record.stdout)

        registry = self.registry(workspace)
        f1 = registry["frontiers"][0]
        self.assertEqual("Continued", f1["status"])
        self.assertEqual(1, f1["review_count"])
        self.assertEqual(
            [
                {
                    "action": "reject",
                    "candidate": "Silicon photonics tangent",
                    "reason": "does not alter the demand layer",
                }
            ],
            f1["review_decisions"][0]["portfolio_actions"],
        )

        no_due = self.run_cli(workspace, "check-review")
        self.assertEqual(0, no_due.returncode)
        self.assertIn("No Frontier Review due", no_due.stdout)

        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        self.assertEqual(1, workflow.count("## Frontier Review: F1 @ loop 3"))
        self.assertIn("Rejected Silicon photonics tangent: does not alter the demand layer", workflow)

        status = self.run_cli(workspace, "status")
        self.assertEqual(0, status.returncode, status.stderr)
        self.assertIn("F1", status.stdout)
        self.assertIn("Continued", status.stdout)
        self.assertIn("derived_loops=3", status.stdout)
        self.assertIn("review_count=1", status.stdout)

        reactivate = self.run_cli(workspace, "reactivate", "F1")
        self.assertEqual(0, reactivate.returncode, reactivate.stderr)
        self.assertIn("F1 -> Active", reactivate.stdout)
        self.assertEqual("Active", self.registry(workspace)["frontiers"][0]["status"])

    def test_overdue_review_can_still_be_recorded(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace, count=4)

        due = self.run_cli(workspace, "check-review")
        self.assertEqual(1, due.returncode)
        self.assertIn("F1 reached loop 4", due.stdout)

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material after overrun",
        )

        self.assertEqual(0, record.returncode, record.stderr)
        f1 = self.registry(workspace)["frontiers"][0]
        self.assertEqual("Continued", f1["status"])
        self.assertEqual(1, f1["review_count"])
        self.assertEqual(4, f1["review_decisions"][0]["at_loop"])

    def test_record_actions_mutate_registry_and_store_structured_metadata(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.add_and_start_frontier(workspace, name="Legacy branch", expected_id="F2")

        ledger_lines = ["# Evidence Ledger: MXL", ""]
        for loop in range(1, 4):
            ledger_lines.extend(
                [
                    f"## Loop {loop}: F1 - InP supply risk",
                    "",
                    "Evidence summary.",
                    "",
                    f"## Loop {loop}: F2 - Legacy branch",
                    "",
                    "Retirement evidence.",
                    "",
                ]
            )
        (workspace / "evidence_ledger.md").write_text("\n".join(ledger_lines), encoding="utf-8")

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Primary evidence remains material",
            "--add",
            "Export license risk::discovery::F1::new branch from review",
            "--retire",
            "F2::answered_out::legacy branch answered",
            "--reprioritize",
            "F1::high::raise review priority",
            "--reject",
            "Packaging tangent::outside current frontier",
        )

        self.assertEqual(0, record.returncode, record.stderr)
        registry = self.registry(workspace)
        by_id = {frontier["id"]: frontier for frontier in registry["frontiers"]}
        self.assertEqual("Continued", by_id["F1"]["status"])
        self.assertEqual("Retired", by_id["F2"]["status"])
        self.assertEqual("answered_out", by_id["F2"]["retire_category"])
        self.assertEqual(1, by_id["F2"]["review_count"])
        self.assertEqual("Retired", by_id["F2"]["review_decisions"][0]["decision"])
        self.assertEqual("answered_out", by_id["F2"]["review_decisions"][0]["retire_category"])
        self.assertEqual("legacy branch answered", by_id["F2"]["review_decisions"][0]["rationale_short"])
        self.assertEqual(3, by_id["F2"]["review_decisions"][0]["at_loop"])
        self.assertEqual("New", by_id["F3"]["status"])
        self.assertEqual("Export license risk", by_id["F3"]["name"])
        self.assertEqual("discovery", by_id["F3"]["source"])
        self.assertEqual("F1", by_id["F3"]["source_frontier"])

        self.assertEqual(
            [
                {
                    "action": "add",
                    "frontier": "F3",
                    "source": "discovery",
                    "source_frontier": "F1",
                    "reason": "new branch from review",
                },
                {
                    "action": "retire",
                    "frontier": "F2",
                    "category": "answered_out",
                    "reason": "legacy branch answered",
                },
                {
                    "action": "reprioritize",
                    "frontier": "F1",
                    "priority": "high",
                    "reason": "raise review priority",
                },
                {
                    "action": "reject",
                    "candidate": "Packaging tangent",
                    "reason": "outside current frontier",
                },
            ],
            by_id["F1"]["review_decisions"][0]["portfolio_actions"],
        )

        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        self.assertEqual(1, workflow.count("## Frontier Review: F1 @ loop 3"))
        self.assertIn("Added F3", workflow)
        self.assertIn("legacy branch answered", workflow)
        self.assertIn("raise review priority", workflow)
        self.assertIn("Rejected Packaging tangent: outside current frontier", workflow)

    def test_record_persistence_rolls_back_registry_when_second_write_fails(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)
        module = load_review_module()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        original_registry = registry_path.read_text(encoding="utf-8")
        original_workflow = workflow_path.read_text(encoding="utf-8")
        original_write_text = module.write_text
        calls = []

        def fail_second_write(path, text):
            calls.append(Path(path).name)
            if len(calls) == 2:
                raise OSError("simulated second write failure")
            return original_write_text(path, text)

        with (
            mock.patch.object(module, "write_text", side_effect=fail_second_write),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = module.main(
                [
                    str(workspace),
                    "record",
                    "F1",
                    "--decision",
                    "Continued",
                    "--rationale",
                    "Evidence remains material",
                ]
            )

        self.assertNotEqual(0, result)
        self.assertEqual(original_registry, registry_path.read_text(encoding="utf-8"))
        self.assertEqual(original_workflow, workflow_path.read_text(encoding="utf-8"))

    def test_record_applies_portfolio_retires_before_adds_but_keeps_metadata_order(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.add_and_start_frontier(workspace, name="Legacy branch", expected_id="F2")

        ledger_lines = ["# Evidence Ledger: MXL", ""]
        for loop in range(1, 4):
            ledger_lines.extend(
                [
                    f"## Loop {loop}: F1 - InP supply risk",
                    "",
                    "Evidence summary.",
                    "",
                    f"## Loop {loop}: F2 - Legacy branch",
                    "",
                    "Retirement evidence.",
                    "",
                ]
            )
        (workspace / "evidence_ledger.md").write_text("\n".join(ledger_lines), encoding="utf-8")

        module = load_review_module()
        original_transition = module.transition
        original_create_frontier_for_cli = module.create_frontier_for_cli
        call_order = []

        def traced_transition(registry, frontier_id, to_status, loop_counts, **kwargs):
            if kwargs.get("action") == "review":
                call_order.append(f"review:{frontier_id}")
            elif kwargs.get("action") == "retire":
                call_order.append(f"retire:{frontier_id}")
            return original_transition(registry, frontier_id, to_status, loop_counts, **kwargs)

        def traced_create_frontier_for_cli(*args, **kwargs):
            call_order.append("add")
            return original_create_frontier_for_cli(*args, **kwargs)

        with (
            mock.patch.object(module, "transition", side_effect=traced_transition),
            mock.patch.object(module, "create_frontier_for_cli", side_effect=traced_create_frontier_for_cli),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = module.main(
                [
                    str(workspace),
                    "record",
                    "F1",
                    "--decision",
                    "Continued",
                    "--rationale",
                    "Primary evidence remains material",
                    "--add",
                    "Export license risk::discovery::F1::new branch from review",
                    "--retire",
                    "F2::answered_out::legacy branch answered",
                ]
            )

        self.assertEqual(0, result)
        self.assertEqual(["review:F1", "review:F2", "add"], call_order)
        actions = self.registry(workspace)["frontiers"][0]["review_decisions"][0]["portfolio_actions"]
        self.assertEqual(["add", "retire"], [action["action"] for action in actions])

    def test_record_retire_and_add_succeeds_when_full_cap_batch_is_net_compliant(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.add_and_start_frontier(workspace, name="Legacy branch", expected_id="F2")
        self.add_and_start_frontier(workspace, name="Third active branch", expected_id="F3")
        for expected_id, name in [("F4", "Queued branch 1"), ("F5", "Queued branch 2")]:
            result = self.run_cli(
                workspace,
                "add",
                "--name",
                name,
                "--source",
                "initial",
                "--at-loop",
                "1",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"Added {expected_id}", result.stdout)

        ledger_lines = ["# Evidence Ledger: MXL", ""]
        for loop in range(1, 4):
            ledger_lines.extend(
                [
                    f"## Loop {loop}: F1 - InP supply risk",
                    "",
                    "Evidence summary.",
                    "",
                    f"## Loop {loop}: F2 - Legacy branch",
                    "",
                    "Retirement evidence.",
                    "",
                ]
            )
        (workspace / "evidence_ledger.md").write_text("\n".join(ledger_lines), encoding="utf-8")

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Primary evidence remains material",
            "--add",
            "Export license risk::discovery::F1::new branch from review",
            "--retire",
            "F2::answered_out::legacy branch answered",
        )

        self.assertEqual(0, record.returncode, record.stderr)
        by_id = {frontier["id"]: frontier for frontier in self.registry(workspace)["frontiers"]}
        self.assertEqual("Continued", by_id["F1"]["status"])
        self.assertEqual("Retired", by_id["F2"]["status"])
        self.assertEqual("New", by_id["F6"]["status"])
        self.assertEqual("Export license risk", by_id["F6"]["name"])

    def test_record_invalid_portfolio_retire_is_atomic(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.add_and_start_frontier(workspace, name="Premature retire branch", expected_id="F2")

        ledger_lines = ["# Evidence Ledger: MXL", ""]
        for loop in range(1, 4):
            ledger_lines.extend(
                [
                    f"## Loop {loop}: F1 - InP supply risk",
                    "",
                    "Evidence summary.",
                    "",
                ]
            )
        ledger_lines.extend(
            [
                "## Loop 1: F2 - Premature retire branch",
                "",
                "Only one loop of evidence.",
                "",
            ]
        )
        (workspace / "evidence_ledger.md").write_text("\n".join(ledger_lines), encoding="utf-8")

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Primary evidence remains material",
            "--add",
            "Export license risk::discovery::F1::new branch from review",
            "--retire",
            "F2::answered_out::premature",
        )

        self.assertNotEqual(0, record.returncode)
        self.assertIn("ERROR:", record.stderr)
        registry = self.registry(workspace)
        by_id = {frontier["id"]: frontier for frontier in registry["frontiers"]}
        self.assertEqual({"F1", "F2"}, set(by_id))
        self.assertEqual("Active", by_id["F1"]["status"])
        self.assertEqual(0, by_id["F1"]["review_count"])
        self.assertEqual([], by_id["F1"]["review_decisions"])
        self.assertEqual("Active", by_id["F2"]["status"])
        self.assertIsNone(by_id["F2"]["retire_category"])

    def test_record_rejects_portfolio_retire_of_reviewed_frontier_atomically(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        original_registry = registry_path.read_text(encoding="utf-8")
        original_workflow = workflow_path.read_text(encoding="utf-8")

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
            "--retire",
            "F1::answered_out::same frontier contradiction",
        )

        self.assertNotEqual(0, record.returncode)
        self.assertIn("ERROR:", record.stderr)
        self.assertIn("--decision Retired", record.stderr)
        self.assertEqual(original_registry, registry_path.read_text(encoding="utf-8"))
        self.assertEqual(original_workflow, workflow_path.read_text(encoding="utf-8"))

    def test_record_retired_rejects_non_review_category_atomically(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Retired",
            "--category",
            "blocked",
            "--rationale",
            "blocked at review",
        )

        self.assertNotEqual(0, record.returncode)
        self.assertIn("ERROR:", record.stderr)
        f1 = self.registry(workspace)["frontiers"][0]
        self.assertEqual("Active", f1["status"])
        self.assertIsNone(f1["retire_category"])
        self.assertEqual(0, f1["review_count"])
        self.assertEqual([], f1["review_decisions"])

    def test_record_is_atomic_when_workflow_lacks_managed_blocks(self):
        workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)
        (workspace / "research_workflow.md").write_text("# Broken workflow\n", encoding="utf-8")

        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
        )

        self.assertNotEqual(0, record.returncode)
        self.assertIn("ERROR:", record.stderr)
        registry = self.registry(workspace)
        self.assertEqual("Active", registry["frontiers"][0]["status"])
        self.assertEqual(0, registry["frontiers"][0]["review_count"])

    def test_retire_applies_mode_aware_early_barren_rules(self):
        ticker = self.make_workspace("ticker")
        self.add_and_start_frontier(ticker)
        self.write_loops(ticker, count=1)

        for category in ["barren", "answered_out", "nonsense"]:
            with self.subTest(category=category):
                rejected = self.run_cli(
                    ticker,
                    "retire",
                    "F1",
                    "--category",
                    category,
                    "--reason",
                    "no investable evidence",
                )

                self.assertNotEqual(0, rejected.returncode)
                self.assertIn("ERROR:", rejected.stderr)
                self.assertEqual("Active", self.registry(ticker)["frontiers"][0]["status"])

        sector = self.make_workspace("sector")
        self.add_and_start_frontier(sector)
        self.write_loops(sector, count=1)

        accepted = self.run_cli(
            sector,
            "retire",
            "F1",
            "--category",
            "barren",
            "--reason",
            "mapping branch is exhausted",
        )

        self.assertEqual(0, accepted.returncode, accepted.stderr)
        f1 = self.registry(sector)["frontiers"][0]
        self.assertEqual("Retired", f1["status"])
        self.assertEqual("barren", f1["retire_category"])
        self.assertEqual("mapping branch is exhausted", f1["lifecycle"][-1]["rationale"])

        due_workspace = self.make_workspace("ticker")
        self.add_and_start_frontier(due_workspace)
        self.write_loops(due_workspace, count=3)
        blocked = self.run_cli(
            due_workspace,
            "retire",
            "F1",
            "--category",
            "answered_out",
            "--reason",
            "claims answered without review",
        )

        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("review due", blocked.stderr)
        f1_due = self.registry(due_workspace)["frontiers"][0]
        self.assertEqual("Active", f1_due["status"])
        self.assertEqual(0, f1_due["review_count"])


if __name__ == "__main__":
    unittest.main()
