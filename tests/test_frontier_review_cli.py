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

    def write_registry_document(self, workspace, registry, *, newline="\n"):
        payload = json.dumps(registry, indent=2, ensure_ascii=False) + "\n"
        (workspace / "frontier_registry.json").write_bytes(
            payload.replace("\n", newline).encode("utf-8")
        )

    def make_v2_workspace(self, mode="ticker"):
        workspace = self.make_workspace(mode)
        registry = self.registry(workspace)
        registry["version"] = 2
        registry.pop("layer_labels", None)
        for frontier in registry.get("frontiers", []):
            frontier.pop("layer", None)
            frontier.pop("parent_frontier", None)
        self.write_registry_document(workspace, registry)

        workflow_path = workspace / "research_workflow.md"
        workflow = workflow_path.read_text(encoding="utf-8")
        start = "## Frontier Layer Coverage\n<!-- SOFA:frontier-layer-coverage:start -->"
        end = "<!-- SOFA:frontier-layer-coverage:end -->"
        if start in workflow and end in workflow:
            prefix, remainder = workflow.split(start, 1)
            _, suffix = remainder.split(end, 1)
            workflow_path.write_text(
                prefix.rstrip() + "\n\n" + suffix.lstrip(),
                encoding="utf-8",
            )
        return workspace

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

    def layer_label_args(self, *, indexes=range(6), labels=None):
        canonical = labels or [f"Layer {index} label" for index in range(6)]
        args = []
        for position, index in enumerate(indexes):
            args.extend(["--label", str(index), canonical[position]])
        return args

    def workspace_snapshot(self, workspace):
        return {
            "registry": (workspace / "frontier_registry.json").read_bytes(),
            "workflow": (workspace / "research_workflow.md").read_bytes(),
            "entries": tuple(sorted(path.name for path in workspace.iterdir())),
        }

    def assert_workspace_snapshot(self, workspace, expected):
        self.assertEqual(
            expected["registry"],
            (workspace / "frontier_registry.json").read_bytes(),
        )
        self.assertEqual(
            expected["workflow"],
            (workspace / "research_workflow.md").read_bytes(),
        )
        self.assertEqual(
            expected["entries"],
            tuple(sorted(path.name for path in workspace.iterdir())),
        )

    def configure_layers(self, workspace, labels=None):
        result = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(labels=labels),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def managed_block_interior(self, workspace, block):
        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        start_marker = f"<!-- SOFA:{block}:start -->"
        end_marker = f"<!-- SOFA:{block}:end -->"
        self.assertEqual(1, workflow.count(start_marker))
        self.assertEqual(1, workflow.count(end_marker))
        _, remainder = workflow.split(start_marker, 1)
        interior, _ = remainder.split(end_marker, 1)
        return interior.strip()

    def replace_managed_block_interior(self, workspace, block, replacement):
        workflow_path = workspace / "research_workflow.md"
        workflow = workflow_path.read_text(encoding="utf-8")
        start_marker = f"<!-- SOFA:{block}:start -->"
        end_marker = f"<!-- SOFA:{block}:end -->"
        self.assertEqual(1, workflow.count(start_marker))
        self.assertEqual(1, workflow.count(end_marker))
        prefix, remainder = workflow.split(start_marker, 1)
        _, suffix = remainder.split(end_marker, 1)
        workflow_path.write_text(
            f"{prefix}{start_marker}\n{replacement}\n{end_marker}{suffix}",
            encoding="utf-8",
        )

    def remove_layer_block(self, workspace):
        workflow_path = workspace / "research_workflow.md"
        workflow = workflow_path.read_text(encoding="utf-8")
        heading = "## Frontier Layer Coverage\n"
        end_marker = "<!-- SOFA:frontier-layer-coverage:end -->"
        start_index = workflow.index(heading)
        end_index = workflow.index(end_marker) + len(end_marker)
        workflow_path.write_text(
            workflow[:start_index].rstrip()
            + "\n\n"
            + workflow[end_index:].lstrip(),
            encoding="utf-8",
        )

    def assert_registered_block_order(self, workspace):
        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        blocks = [
            "frontier-review-log",
            "frontier-discovery-log",
            "frontier-layer-coverage",
        ]
        positions = []
        for block in blocks:
            start_marker = f"<!-- SOFA:{block}:start -->"
            end_marker = f"<!-- SOFA:{block}:end -->"
            self.assertEqual(1, workflow.count(start_marker))
            self.assertEqual(1, workflow.count(end_marker))
            self.assertLess(workflow.index(start_marker), workflow.index(end_marker))
            positions.append(workflow.index(start_marker))
        self.assertEqual(sorted(positions), positions)
        return workflow

    def test_add_matrix_covers_v2_v3_empty_and_v3_configured_layer_flags(self):
        v2_plain = self.make_v2_workspace()
        original_v2_workflow = (v2_plain / "research_workflow.md").read_bytes()
        added_v2 = self.run_cli(
            v2_plain,
            "add",
            "--name",
            "Legacy unbound branch",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(0, added_v2.returncode, added_v2.stderr)
        self.assertEqual("Added F1 (New): Legacy unbound branch\n", added_v2.stdout)
        legacy_registry = self.registry(v2_plain)
        self.assertEqual(2, legacy_registry["version"])
        self.assertNotIn("layer_labels", legacy_registry)
        self.assertNotIn("layer", legacy_registry["frontiers"][0])
        self.assertNotIn("parent_frontier", legacy_registry["frontiers"][0])
        self.assertEqual(
            original_v2_workflow,
            (v2_plain / "research_workflow.md").read_bytes(),
        )

        for case, flags in {
            "layer": ("--layer", "2"),
            "layer-and-parent": ("--layer", "2", "--parent", "F1"),
            "parent-without-layer": ("--parent", "F1"),
        }.items():
            with self.subTest(registry="v2", case=case):
                workspace = self.make_v2_workspace()
                before = self.workspace_snapshot(workspace)
                result = self.run_cli(
                    workspace,
                    "add",
                    "--name",
                    "Rejected legacy binding",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                    *flags,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                self.assertNotIn("Added ", result.stdout)
                self.assert_workspace_snapshot(workspace, before)

        v3_empty_plain = self.make_workspace()
        added_empty = self.run_cli(
            v3_empty_plain,
            "add",
            "--name",
            "Empty-label unbound branch",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(0, added_empty.returncode, added_empty.stderr)
        empty_frontier = self.registry(v3_empty_plain)["frontiers"][0]
        self.assertIsNone(empty_frontier["layer"])
        self.assertIsNone(empty_frontier["parent_frontier"])

        for case, flags in {
            "layer": ("--layer", "0"),
            "layer-and-parent": ("--layer", "2", "--parent", "F1"),
            "parent-without-layer": ("--parent", "F1"),
        }.items():
            with self.subTest(registry="v3-empty", case=case):
                workspace = self.make_workspace()
                before = self.workspace_snapshot(workspace)
                result = self.run_cli(
                    workspace,
                    "add",
                    "--name",
                    "Rejected empty-label binding",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                    *flags,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                self.assertNotIn("Added ", result.stdout)
                self.assert_workspace_snapshot(workspace, before)

        configured_plain = self.make_workspace()
        self.configure_layers(configured_plain)
        added_configured_unbound = self.run_cli(
            configured_plain,
            "add",
            "--name",
            "Configured unbound branch",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(
            0,
            added_configured_unbound.returncode,
            added_configured_unbound.stderr,
        )
        configured_frontier = self.registry(configured_plain)["frontiers"][0]
        self.assertIsNone(configured_frontier["layer"])
        self.assertIsNone(configured_frontier["parent_frontier"])

        configured_bound = self.make_workspace()
        self.configure_layers(configured_bound)
        root = self.run_cli(
            configured_bound,
            "add",
            "--name",
            "Layer root",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
        )
        self.assertEqual(0, root.returncode, root.stderr)
        child = self.run_cli(
            configured_bound,
            "add",
            "--name",
            "Layer child",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "3",
            "--parent",
            "F1",
        )
        self.assertEqual(0, child.returncode, child.stderr)
        by_id = {
            frontier["id"]: frontier
            for frontier in self.registry(configured_bound)["frontiers"]
        }
        self.assertEqual((0, None), (by_id["F1"]["layer"], by_id["F1"]["parent_frontier"]))
        self.assertEqual((3, "F1"), (by_id["F2"]["layer"], by_id["F2"]["parent_frontier"]))

        before_invalid_relation = self.workspace_snapshot(configured_bound)
        invalid_relation = self.run_cli(
            configured_bound,
            "add",
            "--name",
            "Invalid structural child",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
            "--parent",
            "F2",
        )
        self.assertEqual(2, invalid_relation.returncode, invalid_relation.stderr)
        self.assertEqual("", invalid_relation.stdout)
        self.assertNotIn("Added ", invalid_relation.stdout)
        self.assert_workspace_snapshot(configured_bound, before_invalid_relation)

    def test_add_parent_and_source_frontier_are_validated_independently(self):
        workspace = self.make_workspace()
        self.configure_layers(workspace)

        setup_cases = [
            (
                "Structural root",
                "initial",
                None,
                "0",
                None,
                "F1",
            ),
            (
                "Discovery provenance",
                "initial",
                None,
                "1",
                "F1",
                "F2",
            ),
            (
                "Different structural and discovery links",
                "discovery",
                "F2",
                "4",
                "F1",
                "F3",
            ),
            (
                "Equal structural and discovery links",
                "discovery",
                "F1",
                "2",
                "F1",
                "F4",
            ),
            (
                "Discovery link without structural parent",
                "discovery",
                "F1",
                "5",
                None,
                "F5",
            ),
        ]
        for name, source, source_frontier, layer, parent, expected_id in setup_cases:
            args = [
                "add",
                "--name",
                name,
                "--source",
                source,
                "--at-loop",
                "1",
                "--layer",
                layer,
            ]
            if source_frontier is not None:
                args.extend(["--source-frontier", source_frontier])
            if parent is not None:
                args.extend(["--parent", parent])
            result = self.run_cli(workspace, *args)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"Added {expected_id}", result.stdout)

        by_id = {
            frontier["id"]: frontier
            for frontier in self.registry(workspace)["frontiers"]
        }
        self.assertEqual("F2", by_id["F3"]["source_frontier"])
        self.assertEqual("F1", by_id["F3"]["parent_frontier"])
        self.assertEqual("F1", by_id["F4"]["source_frontier"])
        self.assertEqual("F1", by_id["F4"]["parent_frontier"])
        self.assertEqual("F1", by_id["F5"]["source_frontier"])
        self.assertIsNone(by_id["F5"]["parent_frontier"])

        invalid_cases = {
            "invalid-source-valid-parent": (
                "--source",
                "discovery",
                "--source-frontier",
                "F99",
                "--layer",
                "3",
                "--parent",
                "F1",
            ),
            "valid-source-invalid-parent": (
                "--source",
                "discovery",
                "--source-frontier",
                "F1",
                "--layer",
                "3",
                "--parent",
                "F99",
            ),
            "user-source-rejects-provenance": (
                "--source",
                "user",
                "--source-frontier",
                "F1",
                "--layer",
                "3",
                "--parent",
                "F1",
            ),
        }
        for case, flags in invalid_cases.items():
            with self.subTest(case=case):
                before = self.workspace_snapshot(workspace)
                result = self.run_cli(
                    workspace,
                    "add",
                    "--name",
                    "Rejected independent relation",
                    "--at-loop",
                    "1",
                    *flags,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)
                self.assert_workspace_snapshot(workspace, before)

        user_workspace = self.make_workspace()
        self.configure_layers(user_workspace)
        user_root = self.run_cli(
            user_workspace,
            "add",
            "--name",
            "User structural root",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
        )
        self.assertEqual(0, user_root.returncode, user_root.stderr)
        module = load_review_module()
        original_validate = module.validate_registry
        with mock.patch.object(
            module,
            "validate_registry",
            wraps=original_validate,
        ) as validate_registry:
            updated = module.create_frontier_for_cli(
                self.registry(user_workspace),
                name="Validated user child",
                proposed_at_loop=1,
                source="user",
                source_frontier=None,
                layer=3,
                parent_frontier="F1",
            )

        self.assertEqual(1, validate_registry.call_count)
        validated_registry = validate_registry.call_args.args[0]
        self.assertIs(updated, validated_registry)
        user_child = updated["frontiers"][-1]
        self.assertEqual("user", user_child["source"])
        self.assertIsNone(user_child["source_frontier"])
        self.assertEqual(3, user_child["layer"])
        self.assertEqual("F1", user_child["parent_frontier"])

    def test_record_add_keeps_four_part_grammar_and_v2_shape_and_stdout(self):
        workspace = self.make_v2_workspace()
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)

        recorded = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
            "--add",
            "Legacy discovery::discovery::F1::review branch",
        )

        self.assertEqual(0, recorded.returncode, recorded.stderr)
        self.assertEqual("Recorded F1 -> Continued\n", recorded.stdout)
        registry = self.registry(workspace)
        self.assertEqual(2, registry["version"])
        self.assertNotIn("layer_labels", registry)
        self.assertEqual(["F1", "F2"], [row["id"] for row in registry["frontiers"]])
        self.assertEqual("discovery", registry["frontiers"][1]["source"])
        self.assertEqual("F1", registry["frontiers"][1]["source_frontier"])
        for frontier in registry["frontiers"]:
            self.assertNotIn("layer", frontier)
            self.assertNotIn("parent_frontier", frontier)
        self.assertNotIn(
            "SOFA:frontier-layer-coverage",
            (workspace / "research_workflow.md").read_text(encoding="utf-8"),
        )

        invalid_adds = {
            "five-parts": "Candidate::discovery::F1::reason::layer-3",
            "six-parts": "Candidate::discovery::F1::reason::3::F1",
        }
        for case, raw_add in invalid_adds.items():
            with self.subTest(case=case):
                invalid_workspace = self.make_v2_workspace()
                self.add_and_start_frontier(invalid_workspace)
                self.write_loops(invalid_workspace)
                before = self.workspace_snapshot(invalid_workspace)

                rejected = self.run_cli(
                    invalid_workspace,
                    "record",
                    "F1",
                    "--decision",
                    "Continued",
                    "--rationale",
                    "Evidence remains material",
                    "--add",
                    raw_add,
                )

                self.assertEqual(2, rejected.returncode, rejected.stderr)
                self.assertEqual("", rejected.stdout)
                self.assertIn("--add requires NAME::source::source_frontier::reason", rejected.stderr)
                self.assert_workspace_snapshot(invalid_workspace, before)

    def test_record_add_v3_creates_null_layer_facts_and_renders_unbound_snapshot(self):
        workspace = self.make_workspace()
        self.configure_layers(workspace)
        root = self.run_cli(
            workspace,
            "add",
            "--name",
            "Reviewed root",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
        )
        self.assertEqual(0, root.returncode, root.stderr)
        started = self.run_cli(workspace, "start", "F1")
        self.assertEqual(0, started.returncode, started.stderr)
        self.write_loops(workspace, name="Reviewed root")

        recorded = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
            "--add",
            "Unbound review branch::discovery::F1::new evidence branch",
        )

        self.assertEqual(0, recorded.returncode, recorded.stderr)
        self.assertEqual("Recorded F1 -> Continued", recorded.stdout.splitlines()[0])
        registry = self.registry(workspace)
        self.assertEqual(3, registry["version"])
        added = registry["frontiers"][1]
        self.assertEqual("F2", added["id"])
        self.assertEqual("discovery", added["source"])
        self.assertEqual("F1", added["source_frontier"])
        self.assertIsNone(added["layer"])
        self.assertIsNone(added["parent_frontier"])

        layer_snapshot = self.managed_block_interior(
            workspace,
            "frontier-layer-coverage",
        )
        self.assertIn("| F1 | 0 | none | none | Continued | none |", layer_snapshot)
        self.assertIn("| F2 | none | none | F1 | New | none |", layer_snapshot)
        self.assertIn(
            "FRONTIER_LAYER_UNBOUND: Frontiers F2 are not bound to a layer.",
            layer_snapshot,
        )

    def test_record_add_v3_prints_new_unbound_ids_in_portfolio_action_order(self):
        workspace = self.make_workspace()
        self.configure_layers(workspace)
        root = self.run_cli(
            workspace,
            "add",
            "--name",
            "Reviewed root",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
        )
        self.assertEqual(0, root.returncode, root.stderr)
        started = self.run_cli(workspace, "start", "F1")
        self.assertEqual(0, started.returncode, started.stderr)
        self.write_loops(workspace, name="Reviewed root")

        recorded = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
            "--add",
            "First branch::discovery::F1::first in portfolio order",
            "--add",
            "Second branch::serendipity::F1::second in portfolio order",
        )

        self.assertEqual(0, recorded.returncode, recorded.stderr)
        self.assertEqual(
            [
                "Recorded F1 -> Continued",
                "Added F2 (unbound)",
                "Added F3 (unbound)",
            ],
            recorded.stdout.splitlines(),
        )
        registry = self.registry(workspace)
        actions = registry["frontiers"][0]["review_decisions"][0][
            "portfolio_actions"
        ]
        self.assertEqual(
            ["F2", "F3"],
            [action["frontier"] for action in actions if action["action"] == "add"],
        )
        for frontier in registry["frontiers"][1:]:
            self.assertIsNone(frontier["layer"])
            self.assertIsNone(frontier["parent_frontier"])

    def test_each_v3_set_bind_add_start_record_retire_and_reactivate_refreshes_layer_block(self):
        def configured_workspace(mode="ticker"):
            workspace = self.make_workspace(mode)
            self.configure_layers(workspace)
            return workspace

        def add_root(workspace, *, layer=None):
            args = [
                "add",
                "--name",
                "Layer refresh root",
                "--source",
                "initial",
                "--at-loop",
                "1",
            ]
            if layer is not None:
                args.extend(["--layer", str(layer)])
            result = self.run_cli(workspace, *args)
            self.assertEqual(0, result.returncode, result.stderr)

        def start_root(workspace):
            result = self.run_cli(workspace, "start", "F1")
            self.assertEqual(0, result.returncode, result.stderr)

        def make_continued(workspace):
            add_root(workspace, layer=1)
            start_root(workspace)
            self.write_loops(workspace, name="Layer refresh root")
            result = self.run_cli(
                workspace,
                "record",
                "F1",
                "--decision",
                "Continued",
                "--rationale",
                "Evidence remains material",
            )
            self.assertEqual(0, result.returncode, result.stderr)

        def exercise_refresh(
            family,
            workspace,
            command,
            expected_layer_fact,
            *,
            refresh_review_logs=False,
        ):
            sentinels = {}
            for block in (
                "frontier-review-log",
                "frontier-discovery-log",
                "frontier-layer-coverage",
            ):
                sentinel = f"STALE {family} {block}"
                sentinels[block] = sentinel
                self.replace_managed_block_interior(workspace, block, sentinel)
            original_entries = tuple(
                sorted(path.name for path in workspace.iterdir())
            )

            result = self.run_cli(workspace, *command)

            self.assertEqual(0, result.returncode, result.stderr)
            layer_interior = self.managed_block_interior(
                workspace,
                "frontier-layer-coverage",
            )
            self.assertNotIn(sentinels["frontier-layer-coverage"], layer_interior)
            self.assertIn(expected_layer_fact, layer_interior)
            for block in ("frontier-review-log", "frontier-discovery-log"):
                interior = self.managed_block_interior(workspace, block)
                if refresh_review_logs:
                    self.assertNotIn(sentinels[block], interior)
                else:
                    self.assertEqual(sentinels[block], interior)
            workflow = self.assert_registered_block_order(workspace)
            self.assertEqual(1, workflow.count(expected_layer_fact))
            self.assertEqual(
                original_entries,
                tuple(sorted(path.name for path in workspace.iterdir())),
            )

        set_workspace = self.make_workspace()
        exercise_refresh(
            "set-layers",
            set_workspace,
            ["set-layers", *self.layer_label_args()],
            "| 0 | Layer 0 label |",
        )

        bind_workspace = configured_workspace()
        add_root(bind_workspace)
        exercise_refresh(
            "bind-layer",
            bind_workspace,
            ["bind-layer", "F1", "--layer", "2"],
            "| F1 | 2 | none | none | New | none |",
        )

        add_workspace = configured_workspace()
        exercise_refresh(
            "add",
            add_workspace,
            [
                "add",
                "--name",
                "Layer refresh root",
                "--source",
                "initial",
                "--at-loop",
                "1",
                "--layer",
                "1",
            ],
            "| F1 | 1 | none | none | New | none |",
        )

        start_workspace = configured_workspace()
        add_root(start_workspace, layer=1)
        exercise_refresh(
            "start",
            start_workspace,
            ["start", "F1"],
            "| F1 | 1 | none | none | Active | none |",
        )

        record_workspace = configured_workspace()
        add_root(record_workspace, layer=1)
        start_root(record_workspace)
        self.write_loops(record_workspace, name="Layer refresh root")
        exercise_refresh(
            "record",
            record_workspace,
            [
                "record",
                "F1",
                "--decision",
                "Continued",
                "--rationale",
                "Evidence remains material",
            ],
            "| F1 | 1 | none | none | Continued | none |",
            refresh_review_logs=True,
        )
        self.assertIn(
            "## Frontier Review: F1 @ loop 3",
            self.managed_block_interior(record_workspace, "frontier-review-log"),
        )
        self.assertIn(
            "_No discovery actions recorded._",
            self.managed_block_interior(record_workspace, "frontier-discovery-log"),
        )

        retire_workspace = configured_workspace()
        make_continued(retire_workspace)
        reactivated = self.run_cli(retire_workspace, "reactivate", "F1")
        self.assertEqual(0, reactivated.returncode, reactivated.stderr)
        exercise_refresh(
            "retire",
            retire_workspace,
            [
                "retire",
                "F1",
                "--category",
                "invalidated",
                "--reason",
                "Later evidence invalidated the frontier",
            ],
            "| F1 | 1 | none | none | Retired | invalidated |",
        )

        reactivate_workspace = configured_workspace()
        make_continued(reactivate_workspace)
        exercise_refresh(
            "reactivate",
            reactivate_workspace,
            ["reactivate", "F1"],
            "| F1 | 1 | none | none | Active | none |",
        )

        def assert_missing_block_rejected(workspace, *command):
            self.remove_layer_block(workspace)
            before = self.workspace_snapshot(workspace)

            result = self.run_cli(workspace, *command)

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn("has no start marker", result.stderr)
            self.assert_workspace_snapshot(workspace, before)

        missing_add = configured_workspace()
        assert_missing_block_rejected(
            missing_add,
            "add",
            "--name",
            "Rejected missing-block add",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )

        missing_start = configured_workspace()
        add_root(missing_start, layer=1)
        assert_missing_block_rejected(missing_start, "start", "F1")

        missing_record = configured_workspace()
        add_root(missing_record, layer=1)
        start_root(missing_record)
        self.write_loops(missing_record, name="Layer refresh root")
        assert_missing_block_rejected(
            missing_record,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
        )

        missing_retire = configured_workspace(mode="sector")
        add_root(missing_retire, layer=1)
        start_root(missing_retire)
        self.write_loops(missing_retire, name="Layer refresh root", count=1)
        assert_missing_block_rejected(
            missing_retire,
            "retire",
            "F1",
            "--category",
            "barren",
            "--reason",
            "Mapping branch is exhausted",
        )

        missing_reactivate = configured_workspace()
        make_continued(missing_reactivate)
        assert_missing_block_rejected(
            missing_reactivate,
            "reactivate",
            "F1",
        )

    def test_layer_commands_never_modify_an_existing_sector_dependency_ladder(self):
        workspace = self.make_workspace(mode="sector")
        maps_dir = workspace / "maps"
        maps_dir.mkdir(parents=True, exist_ok=True)
        ladder_path = maps_dir / "dependency_ladder.md"
        ladder_bytes = (
            "# HUMAN-OWNED DEPENDENCY LADDER\r\n"
            "\r\n"
            "依赖梯级：原始人工判断，不得改写。\r\n"
            "<!-- distinctive-ladder-bytes: αβγ -->\r\n"
        ).encode("utf-8")
        ladder_path.write_bytes(ladder_bytes)
        original_map_entries = tuple(sorted(path.name for path in maps_dir.iterdir()))

        def run_without_ladder_change(*command):
            result = self.run_cli(workspace, *command)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(ladder_bytes, ladder_path.read_bytes())
            self.assertEqual(
                original_map_entries,
                tuple(sorted(path.name for path in maps_dir.iterdir())),
            )
            return result

        run_without_ladder_change(
            "set-layers",
            *self.layer_label_args(),
        )
        run_without_ladder_change(
            "add",
            "--name",
            "Sector root",
            "--source",
            "initial",
            "--at-loop",
            "1",
            "--layer",
            "0",
        )
        run_without_ladder_change(
            "add",
            "--name",
            "Sector child",
            "--source",
            "discovery",
            "--source-frontier",
            "F1",
            "--at-loop",
            "1",
            "--layer",
            "2",
            "--parent",
            "F1",
        )
        run_without_ladder_change(
            "bind-layer",
            "F2",
            "--layer",
            "3",
            "--parent",
            "F1",
        )
        run_without_ladder_change("start", "F2")

        self.write_loops(
            workspace,
            frontier_id="F2",
            name="Sector child",
        )
        self.assertEqual(ladder_bytes, ladder_path.read_bytes())
        run_without_ladder_change(
            "record",
            "F2",
            "--decision",
            "Continued",
            "--rationale",
            "Sector mapping remains material",
        )
        run_without_ladder_change("reactivate", "F2")
        run_without_ladder_change(
            "retire",
            "F2",
            "--category",
            "invalidated",
            "--reason",
            "Later mapping evidence invalidated the branch",
        )

    def test_set_layers_cli_requires_indexes_zero_through_five_exactly_once(self):
        workspace = self.make_workspace()
        result = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(indexes=[5, 3, 1, 4, 2, 0]),
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Layer labels configured\n", result.stdout)
        self.assertEqual(
            [
                "Layer 5 label",
                "Layer 2 label",
                "Layer 4 label",
                "Layer 1 label",
                "Layer 3 label",
                "Layer 0 label",
            ],
            self.registry(workspace)["layer_labels"],
        )

        invalid_cases = {
            "missing": self.layer_label_args(indexes=range(5)),
            "duplicate": self.layer_label_args(indexes=[0, 1, 2, 3, 4, 4]),
            "out-of-range": self.layer_label_args(indexes=[0, 1, 2, 3, 4, 6]),
            "non-integer": self.layer_label_args(indexes=[0, 1, 2, 3, 4, "five"]),
        }
        for case, args in invalid_cases.items():
            with self.subTest(case=case):
                invalid_workspace = self.make_workspace()
                registry_path = invalid_workspace / "frontier_registry.json"
                workflow_path = invalid_workspace / "research_workflow.md"
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in invalid_workspace.iterdir()}

                invalid = self.run_cli(invalid_workspace, "set-layers", *args)

                self.assertEqual(2, invalid.returncode)
                self.assertNotIn("Layer labels configured", invalid.stdout)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in invalid_workspace.iterdir()},
                )

    def test_set_layers_cli_rejects_blank_duplicate_multiline_and_control_labels(self):
        invalid_labels = {}

        blank = [f"Layer {index} label" for index in range(6)]
        blank[2] = "   "
        invalid_labels["blank"] = blank

        duplicate = [f"Layer {index} label" for index in range(6)]
        duplicate[4] = "  lAyEr 0 LaBeL  "
        invalid_labels["trimmed-casefold-duplicate"] = duplicate

        for name, separator in {
            "line-feed": "\n",
            "carriage-return": "\r",
            "line-separator": "\u2028",
            "paragraph-separator": "\u2029",
        }.items():
            multiline = [f"Layer {index} label" for index in range(6)]
            multiline[3] = f"Layer 3{separator}label"
            invalid_labels[name] = multiline

        control = [f"Layer {index} label" for index in range(6)]
        control[1] = "Layer\t1 label"
        invalid_labels["unicode-cc-control"] = control

        for case, labels in invalid_labels.items():
            with self.subTest(case=case):
                workspace = self.make_workspace()
                registry_path = workspace / "frontier_registry.json"
                workflow_path = workspace / "research_workflow.md"
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in workspace.iterdir()}

                result = self.run_cli(
                    workspace,
                    "set-layers",
                    *self.layer_label_args(labels=labels),
                )

                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("ERROR:"), result.stderr)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in workspace.iterdir()},
                )

    def test_set_layers_cli_is_idempotent_and_repairs_an_absent_layer_block(self):
        workspace = self.make_v2_workspace()
        self.add_and_start_frontier(workspace)
        labels = [f"Canonical layer {index}" for index in range(6)]
        args = self.layer_label_args(labels=labels)

        adopted = self.run_cli(workspace, "set-layers", *args)

        self.assertEqual(0, adopted.returncode, adopted.stderr)
        self.assertEqual("Layer labels configured\n", adopted.stdout)
        registry = self.registry(workspace)
        self.assertEqual(3, registry["version"])
        self.assertEqual(labels, registry["layer_labels"])
        self.assertIsNone(registry["frontiers"][0]["layer"])
        self.assertIsNone(registry["frontiers"][0]["parent_frontier"])

        workflow_path = workspace / "research_workflow.md"
        workflow = workflow_path.read_text(encoding="utf-8")
        layer_heading = "## Frontier Layer Coverage\n"
        layer_start = "<!-- SOFA:frontier-layer-coverage:start -->"
        layer_end = "<!-- SOFA:frontier-layer-coverage:end -->"
        self.assertEqual(1, workflow.count(layer_start))
        self.assertEqual(1, workflow.count(layer_end))
        self.assertLess(
            workflow.index("<!-- SOFA:frontier-discovery-log:end -->"),
            workflow.index(layer_start),
        )

        heading_index = workflow.index(layer_heading)
        end_index = workflow.index(layer_end) + len(layer_end)
        without_layer_block = (
            workflow[:heading_index].rstrip() + "\n\n" + workflow[end_index:].lstrip()
        )
        workflow_path.write_text(without_layer_block, encoding="utf-8")
        registry_before_repair = (workspace / "frontier_registry.json").read_bytes()

        repaired = self.run_cli(workspace, "set-layers", *args)

        self.assertEqual(0, repaired.returncode, repaired.stderr)
        self.assertEqual("Layer labels configured\n", repaired.stdout)
        self.assertEqual(
            registry_before_repair,
            (workspace / "frontier_registry.json").read_bytes(),
        )
        repaired_workflow = workflow_path.read_text(encoding="utf-8")
        self.assertEqual(1, repaired_workflow.count(layer_start))
        self.assertEqual(1, repaired_workflow.count(layer_end))
        self.assertIn("| F1 | none | none | none | Active | none |", repaired_workflow)
        self.assertLess(
            repaired_workflow.index("<!-- SOFA:frontier-discovery-log:end -->"),
            repaired_workflow.index(layer_start),
        )

        original_registry = (workspace / "frontier_registry.json").read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_entries = {path.name for path in workspace.iterdir()}
        different = [f"Replacement layer {index}" for index in range(6)]
        rejected = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(labels=different),
        )

        self.assertEqual(2, rejected.returncode)
        self.assertEqual("", rejected.stdout)
        self.assertIn("already configured", rejected.stderr)
        self.assertEqual(original_registry, (workspace / "frontier_registry.json").read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_entries, {path.name for path in workspace.iterdir()})

    def test_set_layers_replace_preserves_bindings_and_prints_review_notice(self):
        workspace = self.make_workspace()
        original_labels = [f"Original layer {index}" for index in range(6)]
        configured = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(labels=original_labels),
        )
        self.assertEqual(0, configured.returncode, configured.stderr)
        self.add_and_start_frontier(workspace, name="Bound branch", expected_id="F1")
        self.add_and_start_frontier(workspace, name="Unbound branch", expected_id="F2")

        registry = self.registry(workspace)
        registry["frontiers"][0]["layer"] = 1
        self.write_registry_document(workspace, registry)
        replacement = [f"Replacement layer {index}" for index in range(6)]

        replaced = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(labels=replacement),
            "--replace",
        )

        self.assertEqual(0, replaced.returncode, replaced.stderr)
        self.assertEqual(
            [
                "Layer labels configured",
                "NOTICE: Review layer binding semantics for: F1",
            ],
            replaced.stdout.splitlines(),
        )
        updated = self.registry(workspace)
        self.assertEqual(replacement, updated["layer_labels"])
        self.assertEqual(1, updated["frontiers"][0]["layer"])
        self.assertIsNone(updated["frontiers"][0]["parent_frontier"])
        self.assertIsNone(updated["frontiers"][1]["layer"])
        self.assertIsNone(updated["frontiers"][1]["parent_frontier"])
        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | Replacement layer 1 |", workflow)
        self.assertIn("| F1 | 1 | none | none | Active | none |", workflow)
        self.assertIn("| F2 | none | none | none | Active | none |", workflow)

        repeated = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(labels=replacement),
            "--replace",
        )

        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual("Layer labels configured\n", repeated.stdout)

    def test_set_layers_rejects_one_sided_duplicate_misordered_or_missing_anchor_markers_without_writes(self):
        layer_start = "<!-- SOFA:frontier-layer-coverage:start -->"
        layer_end = "<!-- SOFA:frontier-layer-coverage:end -->"
        discovery_start = "<!-- SOFA:frontier-discovery-log:start -->"
        discovery_end = "<!-- SOFA:frontier-discovery-log:end -->"

        def swap_markers(text, start, end):
            placeholder = "<!-- temporary marker swap -->"
            return text.replace(start, placeholder, 1).replace(end, start, 1).replace(
                placeholder,
                end,
                1,
            )

        def move_layer_before_anchor(text):
            layer_heading = "## Frontier Layer Coverage\n"
            discovery_heading = "## Frontier Discovery Log\n"
            block_start = text.index(layer_heading)
            block_end = text.index(layer_end) + len(layer_end)
            block = text[block_start:block_end]
            without_block = text[:block_start] + text[block_end:]
            insertion = without_block.index(discovery_heading)
            return without_block[:insertion] + block + "\n\n" + without_block[insertion:]

        mutations = {
            "target-missing-start": lambda text: text.replace(layer_start, "", 1),
            "target-missing-end": lambda text: text.replace(layer_end, "", 1),
            "target-duplicate-start": lambda text: text.replace(
                layer_start,
                f"{layer_start}\n{layer_start}",
                1,
            ),
            "target-duplicate-end": lambda text: text.replace(
                layer_end,
                f"{layer_end}\n{layer_end}",
                1,
            ),
            "target-misordered": lambda text: swap_markers(text, layer_start, layer_end),
            "target-before-anchor": move_layer_before_anchor,
            "anchor-missing-start": lambda text: text.replace(discovery_start, "", 1),
            "anchor-missing-end": lambda text: text.replace(discovery_end, "", 1),
            "anchor-missing-both": lambda text: text.replace(discovery_start, "", 1).replace(
                discovery_end,
                "",
                1,
            ),
            "anchor-duplicate-start": lambda text: text.replace(
                discovery_start,
                f"{discovery_start}\n{discovery_start}",
                1,
            ),
            "anchor-duplicate-end": lambda text: text.replace(
                discovery_end,
                f"{discovery_end}\n{discovery_end}",
                1,
            ),
            "anchor-misordered": lambda text: swap_markers(
                text,
                discovery_start,
                discovery_end,
            ),
        }

        for case, mutate in mutations.items():
            with self.subTest(case=case):
                workspace = self.make_workspace()
                registry_path = workspace / "frontier_registry.json"
                workflow_path = workspace / "research_workflow.md"
                malformed = mutate(workflow_path.read_text(encoding="utf-8"))
                workflow_path.write_text(malformed, encoding="utf-8")
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in workspace.iterdir()}

                result = self.run_cli(
                    workspace,
                    "set-layers",
                    *self.layer_label_args(),
                )

                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("ERROR:"), result.stderr)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in workspace.iterdir()},
                )

    def test_bind_layer_cli_sets_rebinds_and_clears_the_complete_binding(self):
        workspace = self.make_workspace()
        configured = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(),
        )
        self.assertEqual(0, configured.returncode, configured.stderr)
        self.add_and_start_frontier(workspace, name="Root branch", expected_id="F1")
        self.add_and_start_frontier(workspace, name="Child branch", expected_id="F2")

        bound_root = self.run_cli(workspace, "bind-layer", "F1", "--layer", "0")

        self.assertEqual(0, bound_root.returncode, bound_root.stderr)
        self.assertEqual(
            "Bound F1 layer=0 parent_frontier=none\n",
            bound_root.stdout,
        )
        registry = self.registry(workspace)
        self.assertEqual(0, registry["frontiers"][0]["layer"])
        self.assertIsNone(registry["frontiers"][0]["parent_frontier"])
        workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
        self.assertIn("| F1 | 0 | none | none | Active | none |", workflow)

        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        registry_after_root = registry_path.read_bytes()
        workflow_after_root = workflow_path.read_bytes()
        repeated_root = self.run_cli(workspace, "bind-layer", "F1", "--layer", "0")
        self.assertEqual(0, repeated_root.returncode, repeated_root.stderr)
        self.assertEqual(registry_after_root, registry_path.read_bytes())
        self.assertEqual(workflow_after_root, workflow_path.read_bytes())

        bound_child = self.run_cli(
            workspace,
            "bind-layer",
            "F2",
            "--layer",
            "2",
            "--parent",
            "F1",
        )
        self.assertEqual(0, bound_child.returncode, bound_child.stderr)
        self.assertEqual(
            "Bound F2 layer=2 parent_frontier=F1\n",
            bound_child.stdout,
        )
        child = self.registry(workspace)["frontiers"][1]
        self.assertEqual(2, child["layer"])
        self.assertEqual("F1", child["parent_frontier"])

        rebound = self.run_cli(
            workspace,
            "bind-layer",
            "F2",
            "--layer",
            "3",
            "--parent",
            "F1",
        )
        self.assertEqual(0, rebound.returncode, rebound.stderr)
        child = self.registry(workspace)["frontiers"][1]
        self.assertEqual(3, child["layer"])
        self.assertEqual("F1", child["parent_frontier"])

        whole_binding = self.run_cli(
            workspace,
            "bind-layer",
            "F2",
            "--layer",
            "2",
        )
        self.assertEqual(0, whole_binding.returncode, whole_binding.stderr)
        self.assertEqual(
            "Bound F2 layer=2 parent_frontier=none\n",
            whole_binding.stdout,
        )
        child = self.registry(workspace)["frontiers"][1]
        self.assertEqual(2, child["layer"])
        self.assertIsNone(child["parent_frontier"])

        rebound_with_parent = self.run_cli(
            workspace,
            "bind-layer",
            "F2",
            "--layer",
            "2",
            "--parent",
            "F1",
        )
        self.assertEqual(0, rebound_with_parent.returncode, rebound_with_parent.stderr)
        cleared = self.run_cli(workspace, "bind-layer", "F2", "--clear")
        self.assertEqual(0, cleared.returncode, cleared.stderr)
        self.assertEqual("Cleared layer binding for F2\n", cleared.stdout)
        child = self.registry(workspace)["frontiers"][1]
        self.assertIsNone(child["layer"])
        self.assertIsNone(child["parent_frontier"])
        self.assertIn(
            "| F2 | none | none | none | Active | none |",
            workflow_path.read_text(encoding="utf-8"),
        )

        registry_after_clear = registry_path.read_bytes()
        workflow_after_clear = workflow_path.read_bytes()
        repeated_clear = self.run_cli(workspace, "bind-layer", "F2", "--clear")
        self.assertEqual(0, repeated_clear.returncode, repeated_clear.stderr)
        self.assertEqual("Cleared layer binding for F2\n", repeated_clear.stdout)
        self.assertEqual(registry_after_clear, registry_path.read_bytes())
        self.assertEqual(workflow_after_clear, workflow_path.read_bytes())

        invalid_cases = {
            "missing-binding-action": ("F2",),
            "mutually-exclusive": ("F2", "--layer", "1", "--clear"),
            "parent-with-clear": ("F2", "--clear", "--parent", "F1"),
            "negative-layer": ("F2", "--layer", "-1"),
            "too-deep-layer": ("F2", "--layer", "6"),
            "non-integer-layer": ("F2", "--layer", "deep"),
        }
        for case, args in invalid_cases.items():
            with self.subTest(case=case):
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in workspace.iterdir()}

                invalid = self.run_cli(workspace, "bind-layer", *args)

                self.assertEqual(2, invalid.returncode)
                self.assertNotIn("Bound F2", invalid.stdout)
                self.assertNotIn("Cleared layer binding for F2", invalid.stdout)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in workspace.iterdir()},
                )

    def test_bind_layer_cli_rejects_v2_and_empty_label_v3_without_implicit_adoption(self):
        for version, workspace in {
            "v2": self.make_v2_workspace(),
            "v3-empty": self.make_workspace(),
        }.items():
            with self.subTest(version=version):
                self.add_and_start_frontier(workspace)
                registry_path = workspace / "frontier_registry.json"
                workflow_path = workspace / "research_workflow.md"
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in workspace.iterdir()}

                result = self.run_cli(
                    workspace,
                    "bind-layer",
                    "F1",
                    "--layer",
                    "0",
                )

                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertIn("run set-layers", result.stderr)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in workspace.iterdir()},
                )
                registry = self.registry(workspace)
                if version == "v2":
                    self.assertEqual(2, registry["version"])
                    self.assertNotIn("layer_labels", registry)
                    self.assertNotIn("layer", registry["frontiers"][0])
                    self.assertNotIn("parent_frontier", registry["frontiers"][0])
                else:
                    self.assertEqual(3, registry["version"])
                    self.assertEqual([], registry["layer_labels"])
                    self.assertIsNone(registry["frontiers"][0]["layer"])
                    self.assertIsNone(registry["frontiers"][0]["parent_frontier"])

    def test_bind_layer_cli_rejects_invalid_parent_or_descendant_breakage_without_writes(self):
        workspace = self.make_workspace()
        configured = self.run_cli(
            workspace,
            "set-layers",
            *self.layer_label_args(),
        )
        self.assertEqual(0, configured.returncode, configured.stderr)
        for expected_id, name in [
            ("F1", "Root branch"),
            ("F2", "Middle branch"),
            ("F3", "Leaf branch"),
            ("F4", "Independent branch"),
        ]:
            added = self.run_cli(
                workspace,
                "add",
                "--name",
                name,
                "--source",
                "initial",
                "--at-loop",
                "1",
            )
            self.assertEqual(0, added.returncode, added.stderr)
            self.assertIn(f"Added {expected_id}", added.stdout)

        setup_bindings = [
            ("F1", "0", None),
            ("F2", "2", "F1"),
            ("F3", "4", "F2"),
            ("F4", "3", None),
        ]
        for frontier_id, layer, parent in setup_bindings:
            args = ["bind-layer", frontier_id, "--layer", layer]
            if parent is not None:
                args.extend(["--parent", parent])
            bound = self.run_cli(workspace, *args)
            self.assertEqual(0, bound.returncode, bound.stderr)

        invalid_cases = {
            "malformed-parent": ("F2", "--layer", "2", "--parent", "middle"),
            "nonexistent-parent": ("F2", "--layer", "2", "--parent", "F99"),
            "self-parent": ("F2", "--layer", "2", "--parent", "F2"),
            "equal-layer-parent": ("F2", "--layer", "3", "--parent", "F4"),
            "deeper-layer-parent": ("F2", "--layer", "2", "--parent", "F4"),
            "ancestor-rebind-breaks-child": ("F1", "--layer", "3"),
            "ancestor-clear-breaks-child": ("F1", "--clear"),
            "middle-rebind-breaks-child": (
                "F2",
                "--layer",
                "4",
                "--parent",
                "F1",
            ),
            "middle-clear-breaks-child": ("F2", "--clear"),
        }
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        for case, args in invalid_cases.items():
            with self.subTest(case=case):
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_entries = {path.name for path in workspace.iterdir()}

                result = self.run_cli(workspace, "bind-layer", *args)

                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("ERROR:"), result.stderr)
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_entries,
                    {path.name for path in workspace.iterdir()},
                )

        missing_block_workspace = self.make_workspace()
        configured = self.run_cli(
            missing_block_workspace,
            "set-layers",
            *self.layer_label_args(),
        )
        self.assertEqual(0, configured.returncode, configured.stderr)
        added = self.run_cli(
            missing_block_workspace,
            "add",
            "--name",
            "Unbound branch",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(0, added.returncode, added.stderr)
        missing_registry_path = missing_block_workspace / "frontier_registry.json"
        missing_workflow_path = missing_block_workspace / "research_workflow.md"
        workflow = missing_workflow_path.read_text(encoding="utf-8")
        heading = "## Frontier Layer Coverage\n"
        end_marker = "<!-- SOFA:frontier-layer-coverage:end -->"
        block_start = workflow.index(heading)
        block_end = workflow.index(end_marker) + len(end_marker)
        missing_workflow_path.write_text(
            workflow[:block_start].rstrip() + "\n\n" + workflow[block_end:].lstrip(),
            encoding="utf-8",
        )
        original_registry = missing_registry_path.read_bytes()
        original_workflow = missing_workflow_path.read_bytes()
        original_entries = {path.name for path in missing_block_workspace.iterdir()}

        missing_block = self.run_cli(
            missing_block_workspace,
            "bind-layer",
            "F1",
            "--layer",
            "0",
        )

        self.assertEqual(2, missing_block.returncode)
        self.assertEqual("", missing_block.stdout)
        self.assertIn("has no start marker", missing_block.stderr)
        self.assertEqual(original_registry, missing_registry_path.read_bytes())
        self.assertEqual(original_workflow, missing_workflow_path.read_bytes())
        self.assertEqual(
            original_entries,
            {path.name for path in missing_block_workspace.iterdir()},
        )

    def test_render_failure_occurs_before_any_write(self):
        workspace = self.make_workspace()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        workflow_path.write_text(
            workflow_path.read_text(encoding="utf-8").replace(
                "<!-- SOFA:frontier-layer-coverage:start -->",
                "<!-- missing frontier layer coverage start -->",
            ),
            encoding="utf-8",
        )
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            mock.patch.object(module, "write_text", wraps=module.write_text) as write_text,
            mock.patch.object(module, "write_bytes", create=True) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main(
                [
                    str(workspace),
                    "add",
                    "--name",
                    "InP supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ]
            )

        self.assertEqual(2, result)
        self.assertTrue(stderr.getvalue().startswith("ERROR:"), stderr.getvalue())
        self.assertFalse(stdout.getvalue().startswith("Added "), stdout.getvalue())
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_filenames, {path.name for path in workspace.iterdir()})
        write_text.assert_not_called()
        write_bytes.assert_not_called()

    def test_first_file_write_failure_leaves_both_files_unchanged(self):
        workspace = self.make_workspace()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        write_atomic_impl = getattr(module, "write_atomic", lambda *args, **kwargs: None)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            mock.patch.object(
                module,
                "write_atomic",
                wraps=write_atomic_impl,
                create=True,
            ) as write_atomic,
            mock.patch.object(
                module,
                "replace_with_retry",
                side_effect=OSError("simulated first replace failure"),
            ) as replace,
            mock.patch.object(module, "write_bytes", create=True) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main(
                [
                    str(workspace),
                    "add",
                    "--name",
                    "InP supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ]
            )

        self.assertEqual(2, result)
        self.assertIn("simulated first replace failure", stderr.getvalue())
        self.assertFalse(stdout.getvalue().startswith("Added "), stdout.getvalue())
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_filenames, {path.name for path in workspace.iterdir()})
        write_atomic.assert_called_once()
        replace.assert_called_once()
        self.assertEqual(registry_path, Path(replace.call_args.args[1]))
        write_bytes.assert_not_called()

    def test_second_file_write_failure_restores_exact_original_registry_bytes(self):
        workspace = self.make_workspace()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        registry_path.write_bytes(
            (json.dumps(self.registry(workspace), separators=(", ", ": ")) + "\n\n").encode(
                "utf-8"
            )
        )
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        real_replace = module.replace_with_retry
        destinations = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fail_workflow_replace(src, dst, **kwargs):
            destinations.append(Path(dst).name)
            if Path(dst) == workflow_path:
                raise OSError("simulated workflow replace failure")
            return real_replace(src, dst, **kwargs)

        with (
            mock.patch.object(
                module,
                "replace_with_retry",
                side_effect=fail_workflow_replace,
            ),
            mock.patch.object(module, "write_bytes", wraps=module.write_bytes) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main(
                [
                    str(workspace),
                    "add",
                    "--name",
                    "InP supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ]
            )

        self.assertEqual(2, result)
        self.assertIn("simulated workflow replace failure", stderr.getvalue())
        self.assertFalse(stdout.getvalue().startswith("Added "), stdout.getvalue())
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_filenames, {path.name for path in workspace.iterdir()})
        self.assertEqual(
            ["frontier_registry.json", "research_workflow.md", "frontier_registry.json"],
            destinations,
        )
        write_bytes.assert_called_once_with(registry_path, original_registry)

    def test_rollback_failure_reports_primary_and_rollback_errors_and_actual_state(self):
        workspace = self.make_workspace()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        real_replace = module.replace_with_retry
        events = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fail_workflow_replace(src, dst, **kwargs):
            destination = Path(dst)
            events.append(("replace", destination))
            if destination == workflow_path:
                raise OSError("simulated workflow failure")
            return real_replace(src, dst, **kwargs)

        def fail_registry_rollback(path, data):
            events.append(("rollback", Path(path)))
            raise OSError("simulated rollback failure")

        with (
            mock.patch.object(
                module,
                "replace_with_retry",
                side_effect=fail_workflow_replace,
            ),
            mock.patch.object(
                module,
                "write_bytes",
                side_effect=fail_registry_rollback,
            ) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main(
                [
                    str(workspace),
                    "add",
                    "--name",
                    "InP supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ]
            )

        actual_registry_bytes = registry_path.read_bytes()
        actual_registry = json.loads(actual_registry_bytes.decode("utf-8"))
        self.assertEqual(2, result)
        self.assertIn(
            "workflow write failed: simulated workflow failure",
            stderr.getvalue(),
        )
        self.assertIn(
            "registry rollback failed: simulated rollback failure",
            stderr.getvalue(),
        )
        self.assertEqual("", stdout.getvalue())
        self.assertNotEqual(original_registry, actual_registry_bytes)
        self.assertEqual(
            ["F1"],
            [frontier["id"] for frontier in actual_registry["frontiers"]],
        )
        self.assertEqual("InP supply risk", actual_registry["frontiers"][0]["name"])
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(
            original_filenames,
            {path.name for path in workspace.iterdir()},
        )
        self.assertEqual(
            [
                ("replace", registry_path),
                ("replace", workflow_path),
                ("rollback", registry_path),
            ],
            events,
        )
        write_bytes.assert_called_once_with(registry_path, original_registry)

    def test_transaction_workflow_write_and_rollback_use_windows_replace_retry(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        workspace = Path(temp_dir.name)
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        registry_path.write_bytes(b'{"version": 3, "frontiers": []}\r\n')
        workflow_path.write_bytes(b"original workflow\r\n")
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        real_os_replace = module.os.replace
        primary_error = OSError("simulated workflow failure")
        destinations = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        def scripted_replace(src, dst):
            destination = Path(dst)
            destinations.append(destination)
            attempt = len(destinations)
            if attempt in (1, 4):
                raise PermissionError("simulated transient lock")
            if attempt == 3:
                raise primary_error
            return real_os_replace(src, dst)

        with (
            mock.patch.object(module.sys, "platform", "win32"),
            mock.patch.object(module.os, "replace", side_effect=scripted_replace),
            mock.patch("time.sleep") as sleep,
            mock.patch.object(
                module,
                "write_bytes",
                wraps=module.write_bytes,
            ) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(OSError) as raised:
                module.persist_registry_and_workflow(
                    registry_path=registry_path,
                    workflow_path=workflow_path,
                    original_registry_bytes=original_registry,
                    rendered_registry='{"version": 3, "frontiers": [{"id": "F1"}]}\n',
                    rendered_workflow="updated workflow\n",
                )

        self.assertIs(primary_error, raised.exception)
        self.assertEqual(
            [
                registry_path,
                registry_path,
                workflow_path,
                registry_path,
                registry_path,
            ],
            destinations,
        )
        self.assertEqual(
            [mock.call(0.05), mock.call(0.05)],
            sleep.call_args_list,
        )
        write_bytes.assert_called_once_with(registry_path, original_registry)
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(
            original_filenames,
            {path.name for path in workspace.iterdir()},
        )
        self.assertEqual("", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_successful_rollback_preserves_valid_utf8_crlf_registry_bytes(self):
        workspace = self.make_workspace()
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        registry = self.registry(workspace)
        cjk_sentinel = "华语研究主题"
        registry["subject"] = cjk_sentinel
        noncanonical_json = json.dumps(
            registry,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        registry_path.write_bytes(
            ("\r\n  " + noncanonical_json + "\r\n\r\n").encode("utf-8")
        )
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        original_decoded = original_registry.decode("utf-8")
        self.assertIn(cjk_sentinel, original_decoded)
        self.assertIn(b"\r\n", original_registry)
        self.assertNotIn(b"\n", original_registry.replace(b"\r\n", b""))
        module = load_review_module()
        self.assertNotEqual(
            module.registry_to_text(registry).encode("utf-8"),
            original_registry,
        )
        real_replace = module.replace_with_retry
        destinations = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fail_workflow_replace(src, dst, **kwargs):
            destination = Path(dst)
            destinations.append(destination)
            if destination == workflow_path:
                raise OSError("simulated workflow failure")
            return real_replace(src, dst, **kwargs)

        with (
            mock.patch.object(
                module,
                "replace_with_retry",
                side_effect=fail_workflow_replace,
            ),
            mock.patch.object(
                module,
                "write_bytes",
                wraps=module.write_bytes,
            ) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = module.main(
                [
                    str(workspace),
                    "add",
                    "--name",
                    "InP supply risk",
                    "--source",
                    "initial",
                    "--at-loop",
                    "1",
                ]
            )

        restored_registry = registry_path.read_bytes()
        restored_decoded = restored_registry.decode("utf-8")
        self.assertEqual(2, result)
        self.assertIn("simulated workflow failure", stderr.getvalue())
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(original_registry, restored_registry)
        self.assertIn(cjk_sentinel, restored_decoded)
        self.assertIn(b"\r\n", restored_registry)
        self.assertNotIn(b"\n", restored_registry.replace(b"\r\n", b""))
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(
            original_filenames,
            {path.name for path in workspace.iterdir()},
        )
        self.assertEqual(
            [registry_path, workflow_path, registry_path],
            destinations,
        )
        write_bytes.assert_called_once_with(registry_path, original_registry)

    def test_existing_mutation_handlers_use_shared_validated_persistence(self):
        module = load_review_module()

        def run(workspace, *args):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                result = module.main([str(workspace), *args])
            self.assertEqual(0, result, stderr.getvalue())
            return stdout.getvalue(), stderr.getvalue()

        def run_legal_sequence(workspace, *, assert_ordinary_workflow_unchanged=False):
            workflow_path = workspace / "research_workflow.md"
            initial_workflow = workflow_path.read_bytes()
            run(
                workspace,
                "add",
                "--name",
                "InP supply risk",
                "--source",
                "initial",
                "--at-loop",
                "1",
            )
            if assert_ordinary_workflow_unchanged:
                self.assertEqual(initial_workflow, workflow_path.read_bytes())
            else:
                self.assertIn(
                    "| F1 | none | none | none | New | none |",
                    workflow_path.read_text(encoding="utf-8"),
                )

            run(workspace, "start", "F1")
            if assert_ordinary_workflow_unchanged:
                self.assertEqual(initial_workflow, workflow_path.read_bytes())
            else:
                self.assertIn(
                    "| F1 | none | none | none | Active | none |",
                    workflow_path.read_text(encoding="utf-8"),
                )

            self.write_loops(workspace)
            run(
                workspace,
                "record",
                "F1",
                "--decision",
                "Continued",
                "--rationale",
                "Evidence remains material",
            )
            after_record = workflow_path.read_bytes()
            self.assertNotEqual(initial_workflow, after_record)
            if assert_ordinary_workflow_unchanged:
                self.assertNotIn(b"frontier-layer-coverage", after_record)
            else:
                self.assertIn(
                    "| F1 | none | none | none | Continued | none |",
                    after_record.decode("utf-8"),
                )

            run(workspace, "reactivate", "F1")
            if assert_ordinary_workflow_unchanged:
                self.assertEqual(after_record, workflow_path.read_bytes())
            else:
                self.assertIn(
                    "| F1 | none | none | none | Active | none |",
                    workflow_path.read_text(encoding="utf-8"),
                )

            run(
                workspace,
                "retire",
                "F1",
                "--category",
                "invalidated",
                "--reason",
                "Later evidence invalidated the frontier",
            )
            if assert_ordinary_workflow_unchanged:
                self.assertEqual(after_record, workflow_path.read_bytes())
            else:
                self.assertIn(
                    "| F1 | none | none | none | Retired | invalidated |",
                    workflow_path.read_text(encoding="utf-8"),
                )

        v3_workspace = self.make_workspace()
        v3_registry = self.registry(v3_workspace)
        v3_registry["layer_labels"] = [f"Layer {index}" for index in range(6)]
        self.write_registry_document(v3_workspace, v3_registry)
        with (
            mock.patch.object(
                module,
                "read_registry_snapshot",
                wraps=module.read_registry_snapshot,
            ) as read_snapshot,
            mock.patch.object(
                module,
                "read_registry",
                wraps=module.read_registry,
            ) as read_registry,
            mock.patch.object(
                module,
                "persist_mutation",
                wraps=module.persist_mutation,
            ) as persist_mutation,
        ):
            run_legal_sequence(v3_workspace)

        self.assertEqual(5, read_snapshot.call_count)
        read_registry.assert_not_called()
        self.assertEqual(5, persist_mutation.call_count)
        self.assertEqual(
            [False, False, True, False, False],
            [
                call.kwargs.get("refresh_review_logs", False)
                for call in persist_mutation.call_args_list
            ],
        )
        self.assertTrue(
            all(
                not call.kwargs.get("allow_layer_insert", False)
                for call in persist_mutation.call_args_list
            )
        )
        self.assertEqual(
            ["New", "Active", "Continued", "Active", "Retired"],
            [
                call.kwargs["updated_registry"]["frontiers"][0]["status"]
                for call in persist_mutation.call_args_list
            ],
        )

        v2_workspace = self.make_v2_workspace()
        with (
            mock.patch.object(
                module,
                "read_registry_snapshot",
                wraps=module.read_registry_snapshot,
            ) as read_snapshot,
            mock.patch.object(
                module,
                "read_registry",
                wraps=module.read_registry,
            ) as read_registry,
            mock.patch.object(
                module,
                "persist_mutation",
                wraps=module.persist_mutation,
            ) as persist_mutation,
        ):
            run_legal_sequence(v2_workspace, assert_ordinary_workflow_unchanged=True)

        self.assertEqual(5, read_snapshot.call_count)
        read_registry.assert_not_called()
        self.assertEqual(5, persist_mutation.call_count)
        self.assertEqual(
            [False, False, True, False, False],
            [
                call.kwargs.get("refresh_review_logs", False)
                for call in persist_mutation.call_args_list
            ],
        )
        self.assertTrue(
            all(
                not call.kwargs.get("allow_layer_insert", False)
                for call in persist_mutation.call_args_list
            )
        )
        self.assertEqual(
            [2, 2, 2, 2, 2],
            [
                call.kwargs["updated_registry"]["version"]
                for call in persist_mutation.call_args_list
            ],
        )

    def test_record_uses_canonical_registry_validation_before_mutation(self):
        workspace = self.make_workspace()
        self.add_and_start_frontier(workspace)
        self.write_loops(workspace)
        registry_path = workspace / "frontier_registry.json"
        workflow_path = workspace / "research_workflow.md"
        malformed_registry = self.registry(workspace)
        malformed_registry["layer_labels"] = ["Only one layer"]
        self.write_registry_document(workspace, malformed_registry)
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        module = load_review_module()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            mock.patch.object(
                module,
                "read_registry_snapshot",
                wraps=module.read_registry_snapshot,
            ) as read_snapshot,
            mock.patch.object(
                module,
                "validate_registry",
                wraps=module.validate_registry,
            ) as validate_registry,
            mock.patch.object(module, "transition", wraps=module.transition) as transition,
            mock.patch.object(
                module,
                "apply_portfolio_actions",
                wraps=module.apply_portfolio_actions,
            ) as apply_actions,
            mock.patch.object(
                module,
                "render_workflow",
                wraps=module.render_workflow,
            ) as render_workflow,
            mock.patch.object(
                module,
                "persist_mutation",
                wraps=module.persist_mutation,
            ) as persist_mutation,
            mock.patch.object(module, "write_text", wraps=module.write_text) as write_text,
            mock.patch.object(module, "write_bytes", wraps=module.write_bytes) as write_bytes,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
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

        self.assertEqual(2, result)
        self.assertIn(
            "layer_labels must contain exactly 6 labels",
            stderr.getvalue(),
        )
        self.assertFalse(stdout.getvalue().startswith("Recorded "), stdout.getvalue())
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_filenames, {path.name for path in workspace.iterdir()})
        read_snapshot.assert_called_once_with(workspace)
        validate_registry.assert_called_once()
        transition.assert_not_called()
        apply_actions.assert_not_called()
        render_workflow.assert_not_called()
        persist_mutation.assert_not_called()
        write_text.assert_not_called()
        write_bytes.assert_not_called()

    def test_all_registry_readers_reject_malformed_v3_shape(self):
        module = load_review_module()
        commands = [
            ("add", "--name", "Candidate", "--source", "initial", "--at-loop", "1"),
            ("start", "F1"),
            ("check-review",),
            (
                "record",
                "F1",
                "--decision",
                "Continued",
                "--rationale",
                "Evidence remains material",
            ),
            (
                "retire",
                "F1",
                "--category",
                "invalidated",
                "--reason",
                "Evidence invalidated the frontier",
            ),
            ("reactivate", "F1"),
            ("status",),
        ]

        for command in commands:
            with self.subTest(command=command[0]):
                workspace = self.make_workspace()
                registry_path = workspace / "frontier_registry.json"
                workflow_path = workspace / "research_workflow.md"
                malformed_registry = self.registry(workspace)
                malformed_registry["layer_labels"] = ["Only one layer"]
                self.write_registry_document(workspace, malformed_registry)
                original_registry = registry_path.read_bytes()
                original_workflow = workflow_path.read_bytes()
                original_filenames = {path.name for path in workspace.iterdir()}
                stdout = io.StringIO()
                stderr = io.StringIO()

                with (
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    result = module.main([str(workspace), *command])

                self.assertEqual(2, result)
                self.assertEqual("", stdout.getvalue())
                self.assertIn(
                    "layer_labels must contain exactly 6 labels",
                    stderr.getvalue(),
                )
                self.assertEqual(original_registry, registry_path.read_bytes())
                self.assertEqual(original_workflow, workflow_path.read_bytes())
                self.assertEqual(
                    original_filenames,
                    {path.name for path in workspace.iterdir()},
                )

    def test_v2_ordinary_mutations_preserve_version_shape_and_missing_layer_block(self):
        workspace = self.make_v2_workspace()

        def managed_block_interior(workflow, block):
            start_marker = f"<!-- SOFA:{block}:start -->"
            end_marker = f"<!-- SOFA:{block}:end -->"
            self.assertEqual(1, workflow.count(start_marker))
            self.assertEqual(1, workflow.count(end_marker))
            _, remainder = workflow.split(start_marker, 1)
            interior, _ = remainder.split(end_marker, 1)
            return interior.strip()

        def replace_managed_block_interior(workflow, block, replacement):
            start_marker = f"<!-- SOFA:{block}:start -->"
            end_marker = f"<!-- SOFA:{block}:end -->"
            self.assertEqual(1, workflow.count(start_marker))
            self.assertEqual(1, workflow.count(end_marker))
            prefix, remainder = workflow.split(start_marker, 1)
            _, suffix = remainder.split(end_marker, 1)
            return (
                f"{prefix}{start_marker}\n{replacement}\n"
                f"{end_marker}{suffix}"
            )

        def assert_v2_contract():
            registry = self.registry(workspace)
            self.assertEqual(2, registry["version"])
            self.assertNotIn("layer_labels", registry)
            for frontier in registry.get("frontiers", []):
                self.assertNotIn("layer", frontier)
                self.assertNotIn("parent_frontier", frontier)
            workflow = (workspace / "research_workflow.md").read_text(encoding="utf-8")
            self.assertNotIn("SOFA:frontier-layer-coverage", workflow)
            return workflow

        add = self.run_cli(
            workspace,
            "add",
            "--name",
            "InP supply risk",
            "--source",
            "initial",
            "--at-loop",
            "1",
        )
        self.assertEqual(0, add.returncode, add.stderr)
        assert_v2_contract()

        start = self.run_cli(workspace, "start", "F1")
        self.assertEqual(0, start.returncode, start.stderr)
        assert_v2_contract()

        workflow_path = workspace / "research_workflow.md"
        review_sentinel = "STALE REVIEW BLOCK CONTENT"
        discovery_sentinel = "STALE DISCOVERY BLOCK CONTENT"
        workflow = workflow_path.read_text(encoding="utf-8")
        workflow = replace_managed_block_interior(
            workflow,
            "frontier-review-log",
            review_sentinel,
        )
        workflow = replace_managed_block_interior(
            workflow,
            "frontier-discovery-log",
            discovery_sentinel,
        )
        workflow_path.write_text(workflow, encoding="utf-8")

        seeded_workflow = workflow_path.read_text(encoding="utf-8")
        self.assertEqual(
            review_sentinel,
            managed_block_interior(seeded_workflow, "frontier-review-log"),
        )
        self.assertEqual(
            discovery_sentinel,
            managed_block_interior(seeded_workflow, "frontier-discovery-log"),
        )

        self.write_loops(workspace)
        record = self.run_cli(
            workspace,
            "record",
            "F1",
            "--decision",
            "Continued",
            "--rationale",
            "Evidence remains material",
        )
        self.assertEqual(0, record.returncode, record.stderr)
        workflow = assert_v2_contract()
        review_interior = managed_block_interior(workflow, "frontier-review-log")
        discovery_interior = managed_block_interior(workflow, "frontier-discovery-log")
        expected_review = "## Frontier Review: F1 @ loop 3"
        expected_discovery = "_No discovery actions recorded._"

        self.assertNotIn(review_sentinel, workflow)
        self.assertNotIn(discovery_sentinel, workflow)
        self.assertEqual(1, workflow.count(expected_review))
        self.assertEqual(1, review_interior.count(expected_review))
        self.assertNotIn(expected_review, discovery_interior)
        self.assertEqual(1, workflow.count(expected_discovery))
        self.assertEqual(1, discovery_interior.count(expected_discovery))
        self.assertNotIn(expected_discovery, review_interior)

        reactivate = self.run_cli(workspace, "reactivate", "F1")
        self.assertEqual(0, reactivate.returncode, reactivate.stderr)
        assert_v2_contract()

        retire = self.run_cli(
            workspace,
            "retire",
            "F1",
            "--category",
            "invalidated",
            "--reason",
            "Later evidence invalidated the frontier",
        )
        self.assertEqual(0, retire.returncode, retire.stderr)
        assert_v2_contract()

    def test_check_review_no_due_prints_original_line_before_advisories_and_returns_zero(self):
        workspace = self.make_v2_workspace()

        result = self.run_cli(workspace, "check-review")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            [
                "No Frontier Review due",
                "[ADVISORY] LAYER_LABELS_UNCONFIGURED: Frontier layer labels are "
                "unavailable; run set-layers.",
            ],
            result.stdout.splitlines(),
        )

    def test_check_review_due_prints_original_lines_before_advisories_and_returns_one(self):
        workspace = self.make_workspace()
        self.configure_layers(workspace)
        additions = [
            ("Bound review frontier", ["--layer", "0"]),
            ("Unbound review frontier", []),
        ]
        for index, (name, layer_args) in enumerate(additions, start=1):
            added = self.run_cli(
                workspace,
                "add",
                "--name",
                name,
                "--source",
                "initial",
                "--at-loop",
                "1",
                *layer_args,
            )
            self.assertEqual(0, added.returncode, added.stderr)
            started = self.run_cli(workspace, "start", f"F{index}")
            self.assertEqual(0, started.returncode, started.stderr)
        ledger_lines = ["# Evidence Ledger", ""]
        for loop_index, frontier_id in enumerate(["F1"] * 3 + ["F2"] * 3, start=1):
            ledger_lines.extend(
                [
                    f"## Loop {loop_index}: {frontier_id} - review evidence",
                    "",
                    "Evidence summary.",
                    "",
                ]
            )
        (workspace / "evidence_ledger.md").write_text(
            "\n".join(ledger_lines),
            encoding="utf-8",
        )

        result = self.run_cli(workspace, "check-review")

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual(
            [
                "F1 reached loop 3",
                "F2 reached loop 3",
                "[ADVISORY] LAYER_UNREPRESENTED: Layers 1-5 have no bound frontier.",
                "[ADVISORY] FRONTIER_LAYER_UNBOUND: Frontiers F2 are not bound to a layer.",
            ],
            result.stdout.splitlines(),
        )

    def test_check_review_preserves_zero_one_two_exit_contract(self):
        no_due_workspace = self.make_workspace()
        no_due = self.run_cli(no_due_workspace, "check-review")
        self.assertEqual(0, no_due.returncode, no_due.stderr)
        self.assertEqual("No Frontier Review due", no_due.stdout.splitlines()[0])

        due_workspace = self.make_workspace()
        self.add_and_start_frontier(due_workspace)
        self.write_loops(due_workspace)
        due = self.run_cli(due_workspace, "check-review")
        self.assertEqual(1, due.returncode, due.stderr)
        self.assertEqual("F1 reached loop 3", due.stdout.splitlines()[0])

        malformed_workspace = self.make_workspace()
        (malformed_workspace / "frontier_registry.json").write_text(
            "{malformed",
            encoding="utf-8",
        )
        malformed = self.run_cli(malformed_workspace, "check-review")
        self.assertEqual(2, malformed.returncode)
        self.assertTrue(malformed.stderr.startswith("ERROR:"), malformed.stderr)

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
        original_registry = registry_path.read_bytes()
        original_workflow = workflow_path.read_bytes()
        original_filenames = {path.name for path in workspace.iterdir()}
        original_write_text = module.write_text
        calls = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        def fail_second_write(path, text):
            calls.append(Path(path).name)
            if len(calls) == 2:
                raise OSError("simulated second write failure")
            return original_write_text(path, text)

        with (
            mock.patch.object(module, "write_text", side_effect=fail_second_write),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
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

        self.assertEqual(2, result)
        self.assertIn("simulated second write failure", stderr.getvalue())
        self.assertFalse(stdout.getvalue().startswith("Recorded "), stdout.getvalue())
        self.assertEqual(
            ["frontier_registry.json", "research_workflow.md"],
            calls,
        )
        self.assertEqual(original_registry, registry_path.read_bytes())
        self.assertEqual(original_workflow, workflow_path.read_bytes())
        self.assertEqual(original_filenames, {path.name for path in workspace.iterdir()})

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
