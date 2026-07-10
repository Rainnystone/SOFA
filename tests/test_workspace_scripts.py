import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
from unittest import mock

sys.path.insert(0, str(ROOT / "scripts"))

import init_workspace
from workspace_contract import artifact_contract_for_mode

INIT_SCRIPT = ROOT / "scripts/init_workspace.py"
PACKET_SCRIPT = ROOT / "scripts/generate_ultra_packet.py"


class TestWorkspaceScripts(unittest.TestCase):
    def test_create_workspace_uses_artifact_contract_for_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"

            self.assertTrue(hasattr(init_workspace, "artifact_contract_for_mode"))
            with mock.patch.object(
                init_workspace,
                "artifact_contract_for_mode",
                wraps=artifact_contract_for_mode,
            ) as contract_factory:
                captured_stdout = io.StringIO()
                with contextlib.redirect_stdout(captured_stdout):
                    init_workspace.create_workspace(
                        "AI Optical Interconnect",
                        str(workspace),
                        "sector",
                    )

            contract_factory.assert_called_once_with("sector")
            self.assertIn("WORKSPACE INITIALIZED", captured_stdout.getvalue())
            self.assertTrue((workspace / "maps" / "dependency_ladder.md").exists())

    def test_create_workspace_canonicalizes_direct_call_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"

            captured_stdout = io.StringIO()
            with contextlib.redirect_stdout(captured_stdout):
                init_workspace.create_workspace(
                    "AI Optical Interconnect",
                    str(workspace),
                    " SECTOR ",
                )

            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            registry = json.loads(
                (workspace / "frontier_registry.json").read_text(encoding="utf-8")
            )
            self.assertEqual("sector", state["mode"])
            self.assertEqual("sector", registry["mode"])
            self.assertTrue((workspace / "maps" / "dependency_ladder.md").exists())
            self.assertIn("Mode: Sector Hunt", captured_stdout.getvalue())

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

            expected_paths = artifact_contract_for_mode("sector").all_scaffold_paths()
            missing = [
                path for path in expected_paths if not (workspace / path).exists()
            ]
            self.assertEqual([], missing)

            registry = json.loads(
                (workspace / "frontier_registry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(3, registry["version"])
            self.assertEqual("AI Optical Interconnect", registry["subject"])
            self.assertEqual("sector", registry["mode"])
            self.assertEqual([], registry["layer_labels"])
            self.assertEqual([], registry["frontiers"])
            self.assertEqual(
                {"max_active": 3, "max_active_plus_new": 5},
                registry["portfolio_limits"],
            )

            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            legacy_loop_list_key = "loops_" "completed"
            self.assertNotIn(legacy_loop_list_key, state)

            workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
            self.assertIn("## Frontier Review Log", workflow)
            self.assertIn("<!-- SOFA:frontier-review-log:start -->", workflow)
            self.assertIn("<!-- SOFA:frontier-review-log:end -->", workflow)
            self.assertIn("## Frontier Discovery Log", workflow)
            self.assertIn("<!-- SOFA:frontier-discovery-log:start -->", workflow)
            self.assertIn("<!-- SOFA:frontier-discovery-log:end -->", workflow)

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
            self.assertNotIn(
                "coverage", artifact_contract_for_mode("ticker").all_scaffold_paths()
            )

    def test_init_workspace_scaffolds_source_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            init_workspace.create_workspace("Coherent Corp", str(workspace), "ticker")
            self.assertTrue((workspace / "sources").is_dir())
            index = workspace / "sources_index.jsonl"
            self.assertTrue(index.exists())
            self.assertEqual("", index.read_text(encoding="utf-8"))
            ledger = (workspace / "evidence_ledger.md").read_text(encoding="utf-8")
            self.assertIn("src-NNN", ledger)
            self.assertIn("archive_source.py", ledger)

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
            registry_path = workspace / "frontier_registry.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "subject": "AI Optical Interconnect",
                        "mode": "sector",
                        "frontiers": [{"id": "sentinel-frontier"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
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
            preserved_registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            self.assertEqual([{"id": "sentinel-frontier"}], preserved_registry["frontiers"])
            self.assertRegex(result.stdout, r"(?i)(skipped|existing)")
            self.assertIn("frontier_registry.json", result.stdout)

    def test_init_workspace_preserves_machine_readable_ledgers_and_reports_skipped(self):
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

            search_log_path = workspace / "search_log.jsonl"
            dispatch_log_path = workspace / "dispatch_log.jsonl"
            self.assertTrue(search_log_path.exists())
            self.assertTrue(dispatch_log_path.exists())

            search_sentinel = '{"sentinel":"preserve-search"}\n'
            dispatch_sentinel = '{"sentinel":"preserve-dispatch"}\n'
            search_log_path.write_text(search_sentinel, encoding="utf-8")
            dispatch_log_path.write_text(dispatch_sentinel, encoding="utf-8")

            result = subprocess.run(
                command,
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertEqual(search_sentinel, search_log_path.read_text(encoding="utf-8"))
            self.assertEqual(dispatch_sentinel, dispatch_log_path.read_text(encoding="utf-8"))
            self.assertRegex(result.stdout, r"(?i)(skipped|existing)")
            self.assertIn("search_log.jsonl", result.stdout)
            self.assertIn("dispatch_log.jsonl", result.stdout)

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

    def test_init_workspace_creates_framing_contract_and_mirror_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            init_workspace.create_workspace("Coherent Corp", str(workspace), "ticker")
            contract_path = workspace / "framing_contract.json"
            self.assertTrue(contract_path.exists())
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual(contract["schema_version"], "1.0")
            self.assertEqual(contract["mode"], "")
            self.assertEqual(contract["subject_resolution"]["tickers"], [])
            workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
            self.assertIn("## Framing Intent Contract", workflow)
            self.assertIn("<!-- SOFA:framing-contract:start -->", workflow)
            self.assertIn("<!-- SOFA:framing-contract:end -->", workflow)
            self.assertLess(
                workflow.index("## Framing Intent Contract"),
                workflow.index("## Stage Progress"),
            )


if __name__ == "__main__":
    unittest.main()
