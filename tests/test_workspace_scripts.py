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
import revisit_contract
from frontier_lifecycle import (
    bind_frontier_layer,
    create_frontier,
    make_registry as make_frontier_registry,
    render_frontier_layer_coverage_md,
    set_layer_labels,
)
from workspace_contract import artifact_contract_for_mode

INIT_SCRIPT = ROOT / "scripts/init_workspace.py"
REVIEW_SCRIPT = ROOT / "scripts/frontier_review.py"
PACKET_SCRIPT = ROOT / "scripts/generate_ultra_packet.py"


class TestWorkspaceScripts(unittest.TestCase):
    def test_init_workspace_scaffolds_v3_registry_and_layer_block_in_stable_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "ticker-workspace"
            registry = make_frontier_registry("Coherent Corp", "ticker")
            events = []
            real_json_dump = json.dump

            def render_spy(document):
                self.assertIs(registry, document)
                events.append("render")
                return render_frontier_layer_coverage_md(document)

            def dump_spy(document, *args, **kwargs):
                if document is registry:
                    events.append("persist")
                return real_json_dump(document, *args, **kwargs)

            with (
                mock.patch.object(
                    init_workspace,
                    "make_registry",
                    return_value=registry,
                ) as registry_factory,
                mock.patch.object(
                    init_workspace,
                    "render_frontier_layer_coverage_md",
                    create=True,
                    side_effect=render_spy,
                ) as renderer,
                mock.patch.object(init_workspace.json, "dump", side_effect=dump_spy),
            ):
                init_workspace.create_workspace(
                    "Coherent Corp",
                    str(workspace),
                    "ticker",
                )

            registry_factory.assert_called_once_with("Coherent Corp", "ticker")
            renderer.assert_called_once_with(registry)
            self.assertEqual(["render", "persist"], events)
            self.assertEqual(
                registry,
                json.loads(
                    (workspace / "frontier_registry.json").read_text(encoding="utf-8")
                ),
            )

            workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
            headings = [
                "## Frontier Review Log",
                "## Frontier Discovery Log",
                "## Frontier Layer Coverage",
                "## Current Claim Ledger (summary)",
            ]
            self.assertEqual(
                sorted(workflow.index(heading) for heading in headings),
                [workflow.index(heading) for heading in headings],
            )
            start_marker = "<!-- SOFA:frontier-layer-coverage:start -->"
            end_marker = "<!-- SOFA:frontier-layer-coverage:end -->"
            self.assertEqual(1, workflow.count(start_marker))
            self.assertEqual(1, workflow.count(end_marker))
            interior = workflow.split(f"{start_marker}\n", 1)[1].split(
                f"\n{end_marker}", 1
            )[0]
            self.assertEqual(
                "\n".join(
                    [
                        "> Presence/status snapshot only. This does not establish research completeness, evidence adequacy, or action-class readiness.",
                        "",
                        "### Advisory Gaps",
                        "",
                        "- LAYER_LABELS_UNCONFIGURED: Frontier layer labels are unavailable; run set-layers.",
                    ]
                ),
                interior,
            )
            self.assertNotIn("| Layer | Label |", interior)

    def test_new_sector_ladder_uses_neutral_labels_without_generated_nodes_or_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"
            init_workspace.create_workspace(
                "AI Optical Interconnect",
                str(workspace),
                "sector",
            )

            ladder_path = workspace / "maps" / "dependency_ladder.md"
            ladder = ladder_path.read_text(encoding="utf-8")
            self.assertEqual(
                [
                    f"## Layer {index}: [Workspace label from Stage 0]"
                    for index in range(6)
                ],
                [line for line in ladder.splitlines() if line.startswith("## Layer ")],
            )
            self.assertIn("## Node Registry", ladder)
            self.assertIn("## Double Bottleneck Candidates", ladder)
            self.assertIn("## Chokepoint Scoring Matrix (Stage 3)", ladder)
            node_registry = ladder.split("## Node Registry\n", 1)[1].split(
                "\n## Double Bottleneck Candidates",
                1,
            )[0]
            self.assertEqual(
                "\n".join(
                    [
                        "| Company | Ticker | Layer | Role | Market Cap Bucket | Evidence Grade | Chokepoint Pre-Score |",
                        "|---------|--------|-------|------|-------------------|----------------|---------------------|",
                        "",
                    ]
                ),
                node_registry,
            )

            sentinel_bytes = b"existing ladder sentinel\r\n"
            ladder_path.write_bytes(sentinel_bytes)
            init_workspace.create_workspace(
                "AI Optical Interconnect",
                str(workspace),
                "sector",
            )
            self.assertEqual(sentinel_bytes, ladder_path.read_bytes())

    def test_init_workspace_rebuilds_missing_workflow_from_existing_registry_authority(self):
        def registry_bytes(document):
            return (
                json.dumps(document, ensure_ascii=False, indent=1).replace("\n", "\r\n")
                + "\r\n"
            ).encode("utf-8")

        def run_init(subject, workspace, mode):
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    init_workspace.create_workspace(subject, str(workspace), mode)
            except Exception as error:
                self.fail(f"valid recovery authority raised {type(error).__name__}: {error}")

        labels = [
            "Demand edge",
            "Platform fabric",
            "Optical modules",
            "Process inputs",
            "Production equipment",
            "Regulatory geography",
        ]
        configured_v3 = make_frontier_registry("Configured authority", "sector")
        configured_v3 = create_frontier(
            configured_v3,
            name="Bound optical frontier",
            proposed_at_loop=1,
            source="initial",
        )
        configured_v3 = set_layer_labels(
            configured_v3,
            list(enumerate(labels)),
        )
        configured_v3 = bind_frontier_layer(configured_v3, "F1", layer=2)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            configured_workspace = root / "configured-v3"
            configured_workspace.mkdir()
            configured_path = configured_workspace / "frontier_registry.json"
            configured_original = registry_bytes(configured_v3)
            configured_path.write_bytes(configured_original)

            run_init("Ignored scaffold subject", configured_workspace, "sector")

            self.assertEqual(configured_original, configured_path.read_bytes())
            configured_workflow = (
                configured_workspace / "research_workflow.md"
            ).read_text(encoding="utf-8")
            start_marker = "<!-- SOFA:frontier-layer-coverage:start -->"
            end_marker = "<!-- SOFA:frontier-layer-coverage:end -->"
            configured_interior = configured_workflow.split(
                f"{start_marker}\n",
                1,
            )[1].split(f"\n{end_marker}", 1)[0]
            self.assertEqual(
                render_frontier_layer_coverage_md(configured_v3).rstrip(),
                configured_interior,
            )
            for index, label in enumerate(labels):
                self.assertIn(f"| {index} | {label} |", configured_interior)
            self.assertIn("F1=New", configured_interior)

            legacy_workspace = root / "legacy-v2"
            legacy_workspace.mkdir()
            legacy_path = legacy_workspace / "frontier_registry.json"
            legacy_registry = {
                "version": 2,
                "subject": "Legacy authority",
                "mode": "ticker",
                "frontiers": [],
            }
            legacy_original = registry_bytes(legacy_registry)
            legacy_path.write_bytes(legacy_original)

            run_init("Ignored legacy subject", legacy_workspace, "ticker")

            self.assertEqual(legacy_original, legacy_path.read_bytes())
            legacy_workflow = (legacy_workspace / "research_workflow.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Frontier Review Log", legacy_workflow)
            self.assertIn("## Frontier Discovery Log", legacy_workflow)
            self.assertNotIn("## Frontier Layer Coverage", legacy_workflow)
            self.assertNotIn("SOFA:frontier-layer-coverage", legacy_workflow)
            self.assertFalse((legacy_workspace / "revisit_cycles").exists())
            self.assertFalse((legacy_workspace / "revisit_contract.json").exists())

            both_workspace = root / "both-existing"
            both_workspace.mkdir()
            both_workflow_path = both_workspace / "research_workflow.md"
            both_registry_path = both_workspace / "frontier_registry.json"
            both_workflow_original = b"existing complete workflow\r\n"
            both_registry_original = registry_bytes(configured_v3)
            both_workflow_path.write_bytes(both_workflow_original)
            both_registry_path.write_bytes(both_registry_original)

            run_init("Ignored complete subject", both_workspace, "sector")

            self.assertEqual(both_workflow_original, both_workflow_path.read_bytes())
            self.assertEqual(both_registry_original, both_registry_path.read_bytes())

    def _make_workflow_only_recovery_workspace(self, temp_dir):
        workspace = Path(temp_dir) / "workflow-only"
        init_workspace.create_workspace("Coherent Corp", str(workspace), "ticker")

        workflow_path = workspace / "research_workflow.md"
        workflow = workflow_path.read_text(encoding="utf-8")
        layer_heading = "## Frontier Layer Coverage\n"
        layer_end = "<!-- SOFA:frontier-layer-coverage:end -->"
        prefix, remainder = workflow.split(layer_heading, 1)
        _, suffix = remainder.split(layer_end, 1)
        workflow_path.write_text(
            prefix.rstrip() + "\n\n" + suffix.lstrip("\r\n"),
            encoding="utf-8",
        )
        (workspace / "frontier_registry.json").unlink()
        return workspace

    def test_init_workspace_repairs_existing_workflow_before_creating_missing_v3_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self._make_workflow_only_recovery_workspace(temp_dir)
            workflow_path = workspace / "research_workflow.md"
            layer_end = "<!-- SOFA:frontier-layer-coverage:end -->"

            with contextlib.redirect_stdout(io.StringIO()):
                init_workspace.create_workspace("Coherent Corp", str(workspace), "ticker")

            repaired = workflow_path.read_text(encoding="utf-8")
            start_marker = "<!-- SOFA:frontier-layer-coverage:start -->"
            self.assertEqual(1, repaired.count(start_marker))
            self.assertEqual(1, repaired.count(layer_end))
            self.assertLess(
                repaired.index("<!-- SOFA:frontier-discovery-log:end -->"),
                repaired.index("## Frontier Layer Coverage"),
            )
            self.assertLess(
                repaired.index("## Frontier Layer Coverage"),
                repaired.index("## Current Claim Ledger (summary)"),
            )

            registry = json.loads(
                (workspace / "frontier_registry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(3, registry["version"])

            add = subprocess.run(
                [
                    sys.executable,
                    str(REVIEW_SCRIPT),
                    str(workspace),
                    "add",
                    "--name",
                    "Supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, add.returncode, add.stderr)
            self.assertIn("Added F1", add.stdout)

    def test_init_workspace_preserves_existing_workflow_when_atomic_repair_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self._make_workflow_only_recovery_workspace(temp_dir)
            workflow_path = workspace / "research_workflow.md"
            original_workflow = workflow_path.read_bytes()

            with mock.patch.object(
                init_workspace,
                "write_atomic",
                side_effect=OSError("simulated workflow replace failure"),
                create=True,
            ) as write_atomic:
                with self.assertRaisesRegex(OSError, "workflow replace failure"):
                    init_workspace.create_workspace(
                        "Coherent Corp",
                        str(workspace),
                        "ticker",
                    )

            write_atomic.assert_called_once()
            self.assertEqual(workflow_path, Path(write_atomic.call_args.args[0]))
            self.assertEqual(original_workflow, workflow_path.read_bytes())
            self.assertFalse((workspace / "frontier_registry.json").exists())

    def test_init_workspace_registry_write_failure_leaves_retryable_repaired_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self._make_workflow_only_recovery_workspace(temp_dir)
            workflow_path = workspace / "research_workflow.md"
            registry_path = workspace / "frontier_registry.json"
            destinations = []

            def fail_registry_write(path, payload):
                target = Path(path)
                destinations.append(target)
                if len(destinations) == 2:
                    raise OSError("simulated registry replace failure")
                target.write_text(payload, encoding="utf-8")

            with mock.patch.object(
                init_workspace,
                "write_atomic",
                side_effect=fail_registry_write,
                create=True,
            ):
                with self.assertRaisesRegex(OSError, "registry replace failure"):
                    init_workspace.create_workspace(
                        "Coherent Corp",
                        str(workspace),
                        "ticker",
                    )

            self.assertEqual([workflow_path, registry_path], destinations)
            repaired = workflow_path.read_text(encoding="utf-8")
            self.assertEqual(
                1,
                repaired.count("<!-- SOFA:frontier-layer-coverage:start -->"),
            )
            self.assertFalse(registry_path.exists())

            with contextlib.redirect_stdout(io.StringIO()):
                init_workspace.create_workspace("Coherent Corp", str(workspace), "ticker")

            self.assertEqual(
                3,
                json.loads(registry_path.read_text(encoding="utf-8"))["version"],
            )
            self.assertEqual(
                1,
                workflow_path.read_text(encoding="utf-8").count(
                    "<!-- SOFA:frontier-layer-coverage:start -->"
                ),
            )

    def test_init_workspace_rejects_unanchored_workflow_before_creating_v3_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "malformed-workflow"
            workspace.mkdir()
            workflow_path = workspace / "research_workflow.md"
            original = b"existing workflow without managed anchors\r\n"
            workflow_path.write_bytes(original)

            with self.assertRaisesRegex(
                ValueError,
                "frontier-discovery-log.*exactly one start marker",
            ):
                init_workspace.create_workspace(
                    "Coherent Corp",
                    str(workspace),
                    "ticker",
                )

            self.assertEqual(original, workflow_path.read_bytes())
            self.assertFalse((workspace / "frontier_registry.json").exists())
            self.assertEqual({"research_workflow.md"}, {path.name for path in workspace.iterdir()})

    def test_init_workspace_rejects_malformed_existing_registry_before_workflow_write(self):
        malformed_documents = {
            "unreadable-json": b'{"version": 3, invalid json',
            "invalid-v3-schema": json.dumps(
                {
                    "version": 3,
                    "subject": "Malformed authority",
                    "mode": "ticker",
                    "layer_labels": ["only one label"],
                    "frontiers": [],
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for case, original_bytes in malformed_documents.items():
                with self.subTest(case=case):
                    workspace = root / case
                    workspace.mkdir()
                    registry_path = workspace / "frontier_registry.json"
                    registry_path.write_bytes(original_bytes)

                    with self.assertRaises((json.JSONDecodeError, ValueError)):
                        init_workspace.create_workspace(
                            "Ignored subject",
                            str(workspace),
                            "ticker",
                        )

                    self.assertEqual(original_bytes, registry_path.read_bytes())
                    self.assertEqual(
                        {"frontier_registry.json"},
                        {path.name for path in workspace.iterdir()},
                    )
                    self.assertFalse((workspace / "research_workflow.md").exists())

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

    def test_fresh_ticker_init_writes_exact_empty_revisit_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "ticker-workspace"

            init_workspace.create_workspace("MXL", str(workspace), "ticker")

            self.assertTrue((workspace / "revisit_cycles").is_dir())
            self.assertEqual(
                revisit_contract.canonical_document_bytes(
                    revisit_contract.empty_pointer()
                ),
                (workspace / "revisit_contract.json").read_bytes(),
            )

    def test_fresh_sector_init_does_not_create_revisit_scaffold(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "sector-workspace"

            init_workspace.create_workspace(
                "AI Optical Interconnect",
                str(workspace),
                "sector",
            )

            self.assertFalse((workspace / "revisit_cycles").exists())
            self.assertFalse((workspace / "revisit_contract.json").exists())

    def test_legacy_ticker_init_does_not_silently_create_revisit_authority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "legacy-ticker"
            workspace.mkdir()
            (workspace / "state.json").write_text(
                json.dumps(
                    {
                        "subject": "MXL",
                        "mode": "ticker",
                        "current_stage": "stage_3",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                init_workspace.create_workspace("MXL", str(workspace), "ticker")

            self.assertFalse((workspace / "revisit_cycles").exists())
            self.assertFalse((workspace / "revisit_contract.json").exists())
            self.assertNotIn("revisit_cycles/", stdout.getvalue())
            self.assertNotIn("revisit_contract.json", stdout.getvalue())

    def test_workflow_only_legacy_ticker_is_not_silently_adopted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self._make_workflow_only_recovery_workspace(temp_dir)
            (workspace / "state.json").unlink()
            (workspace / "revisit_contract.json").unlink()
            (workspace / "revisit_cycles").rmdir()
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                init_workspace.create_workspace("MXL", str(workspace), "ticker")

            self.assertFalse((workspace / "revisit_cycles").exists())
            self.assertFalse((workspace / "revisit_contract.json").exists())
            self.assertNotIn("revisit_cycles/", stdout.getvalue())
            self.assertNotIn("revisit_contract.json", stdout.getvalue())

    def test_adopted_ticker_init_repairs_directory_without_rewriting_pointer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "adopted-ticker"
            init_workspace.create_workspace("MXL", str(workspace), "ticker")
            pointer = revisit_contract.empty_pointer()
            pointer["current_revision"] = {
                "revision_id": "REV-0001",
                "cycle_id": None,
                "report_path": "reports/final.md",
                "report_sha256": "a" * 64,
                "action_class": "Watch with Trigger",
                "validated_at": "2026-07-15T00:00:00Z",
                "revision_of": None,
            }
            pointer_bytes = revisit_contract.canonical_document_bytes(pointer)
            pointer_path = workspace / "revisit_contract.json"
            pointer_path.write_bytes(pointer_bytes)
            (workspace / "revisit_cycles").rmdir()

            init_workspace.create_workspace("MXL", str(workspace), "ticker")

            self.assertEqual(pointer_bytes, pointer_path.read_bytes())
            self.assertTrue((workspace / "revisit_cycles").is_dir())

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
