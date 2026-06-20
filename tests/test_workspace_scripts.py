import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_SCRIPT = ROOT / "scripts/init_workspace.py"
PACKET_SCRIPT = ROOT / "scripts/generate_ultra_packet.py"


class TestWorkspaceScripts(unittest.TestCase):
    def test_init_workspace_creates_sofa_artifacts_for_sector_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"

            subprocess.run(
                [
                    sys.executable,
                    str(INIT_SCRIPT),
                    "AI Optical Interconnect",
                    str(workspace),
                    "--mode",
                    "sector",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            expected_paths = [
                "research_workflow.md",
                "evidence_ledger.md",
                "claim_ledger.md",
                "search_log.md",
                "state.json",
                "capability_report.md",
                "maps/dependency_ladder.md",
                "coverage",
                "reports",
                "dive_packets",
            ]
            missing = [
                path for path in expected_paths if not (workspace / path).exists()
            ]
            self.assertEqual([], missing)

    def test_init_workspace_ticker_mode_does_not_print_or_create_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "ticker-workspace"

            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT_SCRIPT),
                    "MXL",
                    str(workspace),
                    "--mode",
                    "ticker",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertNotIn("coverage/", result.stdout)
            self.assertFalse((workspace / "coverage").exists())

    def test_init_workspace_preserves_existing_state_json_and_reports_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"
            command = [
                sys.executable,
                str(INIT_SCRIPT),
                "AI Optical Interconnect",
                str(workspace),
                "--mode",
                "sector",
            ]
            subprocess.run(command, check=True, text=True, capture_output=True)
            sentinel_state = {
                "subject": "AI Optical Interconnect",
                "mode": "sector",
                "sentinel": "preserve-existing-state",
                "loop_count": 7,
                "stages_completed": ["stage_0"],
            }
            state_path = workspace / "state.json"
            state_path.write_text(
                json.dumps(sentinel_state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
            )

            preserved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("preserve-existing-state", preserved["sentinel"])
            self.assertEqual(7, preserved["loop_count"])
            self.assertRegex(result.stdout, r"(?i)(skipped|existing)")

    def test_generate_ultra_packet_writes_reader_ready_packet(self):
        candidates = [
            {
                "candidate_id": "candidate_001",
                "company": "Sivers Semiconductors",
                "ticker": "SIVE.ST",
                "why_surfaced": "CPO laser bottleneck candidate",
                "layer": "Component / Module",
                "evidence_grade": "B",
                "open_questions": ["Revenue conversion"],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"
            candidate_json = Path(temp_dir) / "candidates.json"
            workspace.mkdir()
            candidate_json.write_text(
                json.dumps(candidates, ensure_ascii=False),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(PACKET_SCRIPT),
                    "--workspace",
                    str(workspace),
                    "--candidate-json",
                    str(candidate_json),
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            packet = workspace / "dive_packets/candidate_001_SIVE_ST_ultra_packet.md"
            self.assertTrue(packet.exists())
            text = packet.read_text(encoding="utf-8")
            self.assertIn("# Ultra Dive Packet: Sivers Semiconductors", text)
            self.assertIn("Mode: Ticker Dive Ultra", text)
            self.assertIn("CPO laser bottleneck candidate", text)
            self.assertRegex(text, r"(Inherited Evidence Grade|Evidence Grade)")
            self.assertIn("B", text)
            self.assertIn("Revenue conversion", text)

    def test_generate_ultra_packet_refuses_to_overwrite_without_force(self):
        candidates = [
            {
                "candidate_id": "candidate_001",
                "company": "Sivers Semiconductors",
                "ticker": "SIVE.ST",
                "why_surfaced": "CPO laser bottleneck candidate",
                "layer": "Component / Module",
                "evidence_grade": "B",
                "open_questions": ["Revenue conversion"],
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"
            candidate_json = Path(temp_dir) / "candidates.json"
            workspace.mkdir()
            candidate_json.write_text(
                json.dumps(candidates, ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(PACKET_SCRIPT),
                "--workspace",
                str(workspace),
                "--candidate-json",
                str(candidate_json),
            ]
            subprocess.run(command, check=True, text=True, capture_output=True)
            packet = workspace / "dive_packets/candidate_001_SIVE_ST_ultra_packet.md"
            packet.write_text("sentinel packet content", encoding="utf-8")

            result = subprocess.run(command, text=True, capture_output=True)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("ERROR:", result.stderr)
            self.assertIn("exists", result.stderr)
            self.assertIn("--force", result.stderr)
            self.assertEqual("sentinel packet content", packet.read_text(encoding="utf-8"))

            force_result = subprocess.run(
                command + ["--force"],
                text=True,
                capture_output=True,
            )

            self.assertEqual(0, force_result.returncode)
            self.assertIn("CPO laser bottleneck candidate", packet.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
