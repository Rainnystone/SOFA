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
