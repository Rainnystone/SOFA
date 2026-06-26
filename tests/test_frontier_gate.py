import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = ROOT / "scripts/gate_check.py"


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


if __name__ == "__main__":
    unittest.main()
