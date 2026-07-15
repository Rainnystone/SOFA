import copy
import dataclasses
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.revisit_contract as revisit_contract
import scripts.revisit_contract.model as revisit_model
import scripts.revisit_cycle as revisit_cycle_cli
from scripts.frontier_lifecycle import create_frontier, make_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
REVISIT_CYCLE_SCRIPT = REPO_ROOT / "scripts" / "revisit_cycle.py"


def complete_ticker_report_bytes() -> bytes:
    return (
        "\n".join(
            [
                "# Final Report",
                "Conclusion: research status is Watch with Trigger.",
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
                "UTF-8 proof: 中文证据保持原字节。",
            ]
        )
        + "\n"
    ).encode("utf-8")


def make_registration_workspace(root: Path, *, mode: str = "ticker") -> tuple[Path, Path]:
    workspace = root / "workspace"
    reports = workspace / "reports"
    reports.mkdir(parents=True)
    (workspace / "state.json").write_text(
        json.dumps(
            {
                "subject": "TEST",
                "mode": mode,
                "current_stage": "stage_5",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = reports / "final.md"
    report.write_bytes(complete_ticker_report_bytes())
    return workspace, report


def write_valid_revisit_request(root: Path, workspace: Path) -> Path:
    claim_ledger = workspace / "claim_ledger.md"
    claim_ledger.write_bytes(
        b"# Claim Ledger\n\n## Claim C1\nCustomer qualification timing.\n"
    )
    request = {
        "triggers": [
            {
                "kind": "downgrade",
                "statement": (
                    "The named qualification milestone moved beyond the prior "
                    "watch window."
                ),
                "observed_at": "2026-07-14T10:00:00Z",
                "evidence_refs": [
                    {
                        "kind": "source",
                        "source_id": "src-001",
                        "checked_at": "2026-07-14T10:00:00Z",
                    }
                ],
            }
        ],
        "selected_claims": [
            {
                "statement": (
                    "Customer qualification completes inside the prior watch window."
                ),
                "source_ref": {
                    "path": "claim_ledger.md",
                    "sha256": hashlib.sha256(claim_ledger.read_bytes()).hexdigest(),
                    "locator": "Claim C1",
                    "historical_claim_id": "C1",
                },
                "importance": "critical",
                "selection_reasons": [
                    "trigger_affected",
                    "decision_load_bearing",
                ],
                "trigger_indexes": [1],
                "inherited_grade": "B",
                "inherited_confidence": "medium",
                "inherited_evidence": [
                    {
                        "ref": {
                            "kind": "source",
                            "source_id": "src-001",
                            "checked_at": "2026-07-14T10:00:00Z",
                        },
                        "freshness": "unknown",
                        "checked_at": "2026-07-14T10:00:00Z",
                        "reason": "The old source predates the fired trigger.",
                    }
                ],
            }
        ],
    }
    request_path = root / "revisit-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return request_path


def make_revisit_start_workspace(root: Path) -> tuple[Path, Path]:
    workspace, report = make_registration_workspace(root)
    report_payload = report.read_bytes()
    pointer = revisit_contract.empty_pointer()
    pointer["current_revision"] = {
        "revision_id": "REV-0001",
        "cycle_id": None,
        "report_path": "reports/final.md",
        "report_sha256": hashlib.sha256(report_payload).hexdigest(),
        "action_class": "Watch with Trigger",
        "validated_at": "2026-07-14T09:00:00Z",
        "revision_of": None,
    }
    (workspace / revisit_contract.POINTER_FILENAME).write_bytes(
        revisit_contract.canonical_document_bytes(pointer)
    )
    (workspace / revisit_contract.CYCLES_DIRNAME).mkdir()

    framing = {
        "schema_version": "1.0",
        "subject_resolution": {
            "confirmed_name": "Test Issuer",
            "tickers": ["TEST"],
            "exchange": "NASDAQ",
            "resolution_method": "deterministic_quote",
            "candidates": [],
        },
        "mode": "ticker",
        "research_posture": "revisit",
        "time_horizon": "6-12 months",
        "market_scope": "US public market",
        "risk_appetite": "moderate",
        "output_expectation": "decision memo",
        "report_language": "en",
        "budget_appetite": "standard",
        "clarifications": [],
    }
    (workspace / "framing_contract.json").write_text(
        json.dumps(framing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    registry = create_frontier(
        make_registry("Test Issuer", "ticker"),
        name="Qualification timing",
        proposed_at_loop=1,
        source="initial",
        initial_status="Active",
        ts="2026-07-01T00:00:00Z",
    )
    (workspace / "frontier_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace / "evidence_ledger.md").write_text(
        "\n".join(
            [
                "# Evidence Ledger",
                "",
                "## Loop 2: F1 - Qualification timing",
                "",
                "Prior evidence.",
                "",
                "## Loop 7: F1 - Qualification timing",
                "",
                "Later evidence.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    source_excerpt = "Archived source excerpt for the qualification milestone.\n"
    source_path = workspace / "sources" / "src-001.md"
    source_path.parent.mkdir()
    source_path.write_text(source_excerpt, encoding="utf-8")
    source_record = {
        "source_id": "src-001",
        "url": "https://example.test/qualification",
        "title": "Qualification milestone source",
        "retrieved": "2026-07-14",
        "grade": "B",
        "excerpt_path": "sources/src-001.md",
        "sha256": hashlib.sha256(source_excerpt.encode("utf-8")).hexdigest(),
    }
    (workspace / "sources_index.jsonl").write_text(
        json.dumps(source_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return workspace, write_valid_revisit_request(root, workspace)


def run_revisit_cycle_cli(workspace: Path, *arguments: str, env=None):
    return subprocess.run(
        [
            sys.executable,
            str(REVISIT_CYCLE_SCRIPT),
            str(workspace),
            *arguments,
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=env,
    )


def snapshot_tree(root: Path) -> dict[str, tuple[str, bytes | None]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = ("directory", None)
        else:
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def make_initial_revision():
    return {
        "revision_id": "REV-0001",
        "cycle_id": None,
        "report_path": "reports/initial.md",
        "report_sha256": "a" * 64,
        "action_class": "Watch with Trigger",
        "validated_at": "2026-07-15T00:00:00Z",
        "revision_of": None,
    }


def make_revisit_revision():
    revision = make_initial_revision()
    revision.update(
        {
            "revision_id": "REV-0002",
            "cycle_id": "RC-0001",
            "revision_of": "REV-0001",
        }
    )
    return revision


def test_semantic_sha256(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def make_minimal_cycle():
    intake = {
        "base_revision": {
            "revision_id": "REV-0001",
            "report_path": "reports/initial.md",
            "report_sha256": "a" * 64,
            "action_class": "Watch with Trigger",
        },
        "framing": {
            "path": "framing_contract.json",
            "sha256": "b" * 64,
            "snapshot": {
                "subject_resolution": {},
                "research_posture": "decision_support",
                "time_horizon": "long_term",
                "market_scope": "global",
                "risk_appetite": "moderate",
                "output_expectation": "ticker_dive",
                "report_language": "en",
                "budget_appetite": "standard",
            },
        },
        "workspace_boundary": {
            "frontier_registry_sha256": "c" * 64,
            "max_existing_loop_number": 0,
        },
        "triggers": [],
        "selected_claims": [],
    }
    return {
        "schema_version": 1,
        "cycle_id": "RC-0001",
        "candidate_revision_id": "REV-0002",
        "status": "active",
        "created_at": "2026-07-15T00:00:00Z",
        "completed_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "intake_sha256": test_semantic_sha256(intake),
        "intake": intake,
        "frontier_bindings": [],
        "claim_resolutions": [],
        "derived_claims": [],
        "decision_assessment": None,
        "rerun_artifacts": [],
        "report_candidate": None,
        "audit": [],
    }


def make_populated_cycle():
    cycle = make_minimal_cycle()
    timestamp = "2026-07-15T00:30:00Z"
    source_ref = {
        "kind": "source",
        "source_id": "src-001",
        "checked_at": timestamp,
    }
    artifact_ref = {
        "kind": "artifact",
        "path": "evidence/filing.md",
        "sha256": "d" * 64,
        "locator": "p. 1",
        "checked_at": timestamp,
    }
    trigger_id = "RC-0001-TRG-01"
    claim_id = "RC-0001-CL-01"
    derived_id = "RC-0001-DC-01"
    cycle["intake"]["triggers"] = [
        {
            "trigger_id": trigger_id,
            "kind": "upgrade",
            "statement": "Primary filing changed the revenue baseline.",
            "observed_at": "2026-07-15",
            "evidence_refs": [copy.deepcopy(source_ref)],
        }
    ]
    cycle["intake"]["selected_claims"] = [
        {
            "claim_id": claim_id,
            "statement": "Revenue baseline remains decision-load-bearing.",
            "source_ref": {
                "path": "reports/initial.md",
                "sha256": "a" * 64,
                "locator": "Claim 1",
                "historical_claim_id": None,
            },
            "importance": "critical",
            "selection_reasons": ["trigger_affected"],
            "trigger_ids": [trigger_id],
            "inherited_grade": "A",
            "inherited_confidence": "high",
            "inherited_evidence": [
                {
                    "ref": copy.deepcopy(source_ref),
                    "freshness": "fresh",
                    "checked_at": timestamp,
                    "reason": "Primary source remains current.",
                }
            ],
        }
    ]
    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
    cycle["frontier_bindings"] = [
        {
            "frontier_id": "frontier-001",
            "action": "reuse",
            "claim_ids": [claim_id],
            "expected_evidence": ["Primary filing"],
            "baseline_loop_count": 1,
            "baseline_review_count": 1,
            "registry_sha256": "c" * 64,
            "bound_at": timestamp,
        }
    ]
    cycle["derived_claims"] = [
        {
            "claim_id": derived_id,
            "origin": "accepted_worker_output",
            "statement": "Updated revenue evidence is decision-relevant.",
            "derived_from": claim_id,
            "accepted_from": {
                "loop_id": "loop-001",
                "dispatch_id": "dispatch-001",
                "evidence_refs": [copy.deepcopy(artifact_ref)],
            },
            "acceptance_rationale": "The evidence is directly traceable.",
        }
    ]
    cycle["claim_resolutions"] = [
        {
            "claim_id": claim_id,
            "status": "confirmed",
            "revised_statement": None,
            "current_evidence_refs": [copy.deepcopy(artifact_ref)],
            "counter_evidence_refs": [],
            "current_grade": "A",
            "current_confidence": "high",
            "bound_frontier_ids": ["frontier-001"],
            "rationale": "The primary filing confirms the claim.",
            "missing_proof": None,
            "attempted_loop_ids": ["loop-001"],
            "attempted_search_refs": [
                {"loop_id": "loop-001", "query": "issuer filing revenue"}
            ],
            "verdict_impact": "No action-class change.",
            "split_child_ids": [],
        }
    ]
    cycle["decision_assessment"] = {
        "new_action_class": "Watch with Trigger",
        "financial_bridge_affected": False,
        "financial_bridge_rationale": None,
        "risk_class_changed": False,
        "risk_class_rationale": None,
        "supporting_claim_ids": [claim_id, derived_id],
        "verdict_rationale": "The new evidence confirms the prior posture.",
        "blocked_claim_ids": [],
        "change_class": "evidence_or_claim_only",
        "required_reruns": ["delta-frontier-review"],
    }
    cycle["rerun_artifacts"] = [
        {
            "kind": "delta-frontier-review",
            "scope": "affected",
            "round": 1,
            "path": "artifacts/delta-frontier-review.json",
            "sha256": "e" * 64,
            "recorded_at": timestamp,
        }
    ]
    cycle["report_candidate"] = {
        "revision_id": "REV-0002",
        "revision_of": "REV-0001",
        "report_path": "reports/revision-0002.md",
        "report_sha256": "f" * 64,
        "registered_at": timestamp,
    }
    return cycle


def nested_value(value, path):
    for part in path:
        value = value[part]
    return value


def set_nested_value(value, path, replacement):
    parent = nested_value(value, path[:-1]) if len(path) > 1 else value
    parent[path[-1]] = replacement


def attach_valid_audit(cycle):
    state = copy.deepcopy(cycle)
    state.pop("audit")
    cycle["audit"] = [
        {
            "sequence": 1,
            "timestamp": "2026-07-15T00:45:00Z",
            "command": "revisit-start",
            "affected_ids": [cycle["cycle_id"]],
            "pre_state_sha256": "0" * 64,
            "post_state_sha256": test_semantic_sha256(state),
        }
    ]
    return cycle


class TestRevisitPackageBootstrap(unittest.TestCase):
    def test_revisit_contract_package_entrypoint_exists(self):
        self.assertTrue(
            (REPO_ROOT / "scripts" / "revisit_contract" / "__init__.py").is_file()
        )


class TestRevisitCycleCliBootstrap(unittest.TestCase):
    def test_revisit_cycle_cli_entrypoint_exists(self):
        self.assertTrue(
            REVISIT_CYCLE_SCRIPT.is_file(),
            "scripts/revisit_cycle.py must exist before behavioral CLI tests run",
        )

    def test_revisit_cycle_cli_module_imports_from_repo_root(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import scripts.revisit_cycle"],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_register_current_adopts_one_explicit_complete_legacy_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            original_report = report.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            pointer_path = workspace / "revisit_contract.json"
            self.assertTrue(
                pointer_path.is_file(),
                f"registration did not create pointer: {result.stdout}{result.stderr}",
            )
            pointer = revisit_contract.load_pointer(workspace)
            revision = pointer["current_revision"]
            self.assertEqual("REV-0001", revision["revision_id"])
            self.assertIsNone(revision["cycle_id"])
            self.assertEqual("reports/final.md", revision["report_path"])
            self.assertEqual(
                hashlib.sha256(original_report).hexdigest(),
                revision["report_sha256"],
            )
            self.assertEqual("Watch with Trigger", revision["action_class"])
            self.assertRegex(
                revision["validated_at"],
                r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
            )
            self.assertIsNone(revision["revision_of"])
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((workspace / "revisit_cycles").is_dir())
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))
            self.assertEqual(original_report, report.read_bytes())


class TestRevisitCycleRegisterCurrentCli(unittest.TestCase):
    def test_register_current_rejects_pointer_changed_between_snapshot_and_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            report_bytes = report.read_bytes()
            revisit_contract.persist_pointer(
                workspace,
                revisit_contract.empty_pointer(),
                expected_sha256=None,
            )
            pointer_path = workspace / "revisit_contract.json"
            concurrent_pointer = revisit_contract.empty_pointer()
            concurrent_pointer["current_revision"] = {
                "revision_id": "REV-0001",
                "cycle_id": None,
                "report_path": "reports/concurrent.md",
                "report_sha256": "c" * 64,
                "action_class": "Reject",
                "validated_at": "2026-07-15T02:00:00Z",
                "revision_of": None,
            }
            concurrent_bytes = revisit_contract.canonical_document_bytes(
                concurrent_pointer
            )
            calls = []
            real_load_pointer = revisit_cycle_cli.load_pointer
            real_sha256_file = revisit_cycle_cli.sha256_file

            def inject_concurrent_pointer(operation):
                calls.append(operation)
                if len(calls) == 1:
                    pointer_path.write_bytes(concurrent_bytes)

            def interleaved_load_pointer(*args, **kwargs):
                loaded = real_load_pointer(*args, **kwargs)
                inject_concurrent_pointer("load")
                return loaded

            def interleaved_sha256_file(*args, **kwargs):
                digest = real_sha256_file(*args, **kwargs)
                inject_concurrent_pointer("digest")
                return digest

            with (
                mock.patch.object(
                    revisit_cycle_cli,
                    "load_pointer",
                    side_effect=interleaved_load_pointer,
                ),
                mock.patch.object(
                    revisit_cycle_cli,
                    "sha256_file",
                    side_effect=interleaved_sha256_file,
                ),
                mock.patch.object(revisit_cycle_cli.sys, "stdout", io.StringIO()),
                mock.patch.object(revisit_cycle_cli.sys, "stderr", io.StringIO()),
            ):
                result = revisit_cycle_cli.main(
                    [
                        str(workspace),
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        "Watch with Trigger",
                    ]
                )

            self.assertEqual(concurrent_bytes, pointer_path.read_bytes())
            self.assertEqual(["digest", "load"], calls)
            self.assertEqual(2, result)
            self.assertEqual(report_bytes, report.read_bytes())
            self.assertFalse((workspace / "revisit_cycles").exists())

    def test_register_current_accepts_exact_locked_action_vocabulary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index, action_class in enumerate(revisit_contract.ACTION_CLASSES):
                with self.subTest(action_class=action_class):
                    workspace, _ = make_registration_workspace(root / str(index))

                    result = run_revisit_cycle_cli(
                        workspace,
                        "register-current",
                        "--report",
                        "reports/final.md",
                        "--action-class",
                        action_class,
                    )

                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        action_class,
                        revisit_contract.load_pointer(workspace)["current_revision"][
                            "action_class"
                        ],
                    )

    def test_register_current_rejects_non_exact_action_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "watch with trigger",
            )

            self.assertEqual(2, result.returncode)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_register_current_rejects_unsafe_outside_and_non_markdown_paths_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = make_registration_workspace(root)
            outside = root / "outside.md"
            outside.write_bytes(complete_ticker_report_bytes())
            (workspace / "reports" / "final.txt").write_bytes(
                complete_ticker_report_bytes()
            )
            (workspace / "reports" / "nonutf8.md").write_bytes(b"\xff\xfe")
            paths = (
                "/".join(("..", "outside.md")),
                "/".join(("reports", "..", "outside.md")),
                str(outside.resolve()),
                "reports/final.txt",
                "reports/nonutf8.md",
                "reports/missing.md",
            )
            for report_path in paths:
                with self.subTest(report_path=report_path):
                    before = snapshot_tree(workspace)
                    outside_before = outside.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "register-current",
                        "--report",
                        report_path,
                        "--action-class",
                        "Watch with Trigger",
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))
                    self.assertEqual(outside_before, outside.read_bytes())

    def test_incomplete_report_is_readiness_failure_with_zero_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            report.write_bytes(
                report.read_bytes().replace(
                    b"Watch protocol: monitor customer updates.\n",
                    b"",
                )
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("FINAL_REPORT_MISSING_WATCH_PROTOCOL", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_register_current_accepts_strict_empty_pointer_and_preserves_raw_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            original_report = report.read_bytes().replace(b"\n", b"\r\n")
            report.write_bytes(original_report)
            revisit_contract.persist_pointer(
                workspace,
                revisit_contract.empty_pointer(),
                expected_sha256=None,
            )
            (workspace / "revisit_cycles").mkdir()

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            revision = revisit_contract.load_pointer(workspace)["current_revision"]
            self.assertEqual(
                hashlib.sha256(original_report).hexdigest(),
                revision["report_sha256"],
            )
            self.assertEqual(original_report, report.read_bytes())
            self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_second_registration_cannot_replace_non_null_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            first = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )
            self.assertEqual(0, first.returncode, first.stderr)
            second_report = workspace / "reports" / "second.md"
            second_report.write_bytes(complete_ticker_report_bytes())
            before = snapshot_tree(workspace)

            second = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/second.md",
                "--action-class",
                "Reject",
            )

            self.assertEqual(2, second.returncode, second.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_sector_workspace_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(
                Path(temp_dir),
                mode="sector",
            )
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_malformed_pointer_is_rejected_without_repair_or_cycle_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = make_registration_workspace(Path(temp_dir))
            pointer = workspace / "revisit_contract.json"
            pointer.write_bytes(b'{"schema_version": 1, invalid json')
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/final.md",
                "--action-class",
                "Watch with Trigger",
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_validation_error_prints_utf8_safely_under_ascii_stdio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, report = make_registration_workspace(Path(temp_dir))
            unicode_report = report.with_name("报告.md")
            unicode_report.write_bytes(
                report.read_bytes().replace(
                    b"Watch protocol: monitor customer updates.\n",
                    b"",
                )
            )
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "ascii"
            env["LC_ALL"] = "C"
            before = snapshot_tree(workspace)

            result = run_revisit_cycle_cli(
                workspace,
                "register-current",
                "--report",
                "reports/报告.md",
                "--action-class",
                "Watch with Trigger",
                env=env,
            )

            self.assertEqual(1, result.returncode, result.stderr)
            self.assertIn("reports/报告.md", result.stderr)
            self.assertNotIn("UnicodeEncodeError", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitCycleStartCli(unittest.TestCase):
    def run_invalid_request_case(self, mutate_request, expected_error):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            mutate_request(request)
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            workspace_before = snapshot_tree(workspace)
            request_before = request_path.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(2, result.returncode, result.stderr)
            self.assertRegex(result.stderr, expected_error)
            self.assertEqual(workspace_before, snapshot_tree(workspace))
            self.assertEqual(request_before, request_path.read_bytes())

    def test_start_creates_immutable_intake_with_stable_ids_and_initial_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            pointer_before = (workspace / revisit_contract.POINTER_FILENAME).read_bytes()
            request_before = request_path.read_bytes()

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "REVISIT CYCLE STARTED: RC-0001 (candidate REV-0002)\n",
                result.stdout,
            )
            cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
            mirror_path = workspace / "revisit_cycles" / "RC-0001.md"
            cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
            self.assertIs(cycle, revisit_contract.validate_cycle(cycle))
            self.assertEqual("RC-0001", cycle["cycle_id"])
            self.assertEqual("REV-0002", cycle["candidate_revision_id"])
            self.assertEqual("active", cycle["status"])
            self.assertEqual(
                ["RC-0001-TRG-01"],
                [trigger["trigger_id"] for trigger in cycle["intake"]["triggers"]],
            )
            self.assertEqual(
                ["RC-0001-CL-01"],
                [
                    claim["claim_id"]
                    for claim in cycle["intake"]["selected_claims"]
                ],
            )
            self.assertEqual(
                ["RC-0001-TRG-01"],
                cycle["intake"]["selected_claims"][0]["trigger_ids"],
            )
            self.assertNotIn(
                "trigger_indexes", cycle["intake"]["selected_claims"][0]
            )
            self.assertEqual(
                [
                    {
                        "claim_id": "RC-0001-CL-01",
                        "status": "inherited-pending-reverification",
                        "revised_statement": None,
                        "current_evidence_refs": [],
                        "counter_evidence_refs": [],
                        "current_grade": None,
                        "current_confidence": None,
                        "bound_frontier_ids": [],
                        "rationale": None,
                        "missing_proof": None,
                        "attempted_loop_ids": [],
                        "attempted_search_refs": [],
                        "verdict_impact": None,
                        "split_child_ids": [],
                    }
                ],
                cycle["claim_resolutions"],
            )
            self.assertEqual(
                hashlib.sha256(
                    (workspace / "framing_contract.json").read_bytes()
                ).hexdigest(),
                cycle["intake"]["framing"]["sha256"],
            )
            self.assertEqual(
                {
                    "subject_resolution",
                    "research_posture",
                    "time_horizon",
                    "market_scope",
                    "risk_appetite",
                    "output_expectation",
                    "report_language",
                    "budget_appetite",
                },
                set(cycle["intake"]["framing"]["snapshot"]),
            )
            self.assertEqual(
                {
                    "revision_id",
                    "report_path",
                    "report_sha256",
                    "action_class",
                },
                set(cycle["intake"]["base_revision"]),
            )
            self.assertEqual(
                hashlib.sha256(
                    (workspace / "frontier_registry.json").read_bytes()
                ).hexdigest(),
                cycle["intake"]["workspace_boundary"][
                    "frontier_registry_sha256"
                ],
            )
            self.assertEqual(
                7,
                cycle["intake"]["workspace_boundary"][
                    "max_existing_loop_number"
                ],
            )
            self.assertEqual(
                revisit_contract.intake_sha256(cycle["intake"]),
                cycle["intake_sha256"],
            )
            self.assertEqual(1, len(cycle["audit"]))
            self.assertEqual(1, cycle["audit"][0]["sequence"])
            self.assertEqual("start", cycle["audit"][0]["command"])
            self.assertEqual(
                revisit_contract.semantic_sha256(None),
                cycle["audit"][0]["pre_state_sha256"],
            )
            self.assertEqual(
                revisit_contract.cycle_state_sha256(cycle),
                cycle["audit"][0]["post_state_sha256"],
            )

            serialized = cycle_path.read_text(encoding="utf-8")
            mirror = mirror_path.read_text(encoding="utf-8")
            self.assertNotIn(str(request_path), serialized)
            self.assertNotIn("trigger_indexes", serialized)
            self.assertNotIn("Archived source excerpt", serialized)
            self.assertIn("RC-0001-TRG-01", mirror)
            self.assertIn("RC-0001-CL-01", mirror)
            self.assertIn(
                "Unselected historical claims are omitted and cannot support this cycle.",
                mirror,
            )
            self.assertEqual(1, mirror.count("Watch with Trigger"))
            for action_class in set(revisit_contract.ACTION_CLASSES) - {
                "Watch with Trigger"
            }:
                self.assertNotIn(action_class, mirror)
            self.assertEqual(
                pointer_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )
            self.assertEqual(request_before, request_path.read_bytes())

    def test_start_preserves_request_order_and_validates_artifact_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            second_trigger = copy.deepcopy(request["triggers"][0])
            second_trigger["statement"] = "A second fired trigger remains distinct."
            request["triggers"].append(second_trigger)
            second_claim = copy.deepcopy(request["selected_claims"][0])
            second_claim["statement"] = "The second selected claim keeps request order."
            second_claim["trigger_indexes"] = [2]
            request["selected_claims"].append(second_claim)
            request["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "claim_ledger.md",
                    "sha256": request["selected_claims"][0]["source_ref"]["sha256"],
                    "locator": "Claim C1",
                    "checked_at": "2026-07-14T10:00:00Z",
                }
            ]
            request_path.write_text(
                json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            cycle = revisit_contract.load_cycle(workspace, "RC-0001")
            self.assertEqual(
                ["RC-0001-TRG-01", "RC-0001-TRG-02"],
                [item["trigger_id"] for item in cycle["intake"]["triggers"]],
            )
            self.assertEqual(
                ["RC-0001-CL-01", "RC-0001-CL-02"],
                [item["claim_id"] for item in cycle["intake"]["selected_claims"]],
            )
            self.assertEqual(
                [["RC-0001-TRG-01"], ["RC-0001-TRG-02"]],
                [item["trigger_ids"] for item in cycle["intake"]["selected_claims"]],
            )
            self.assertEqual(
                "artifact",
                cycle["intake"]["triggers"][0]["evidence_refs"][0]["kind"],
            )
            self.assertEqual(
                "claim_ledger.md",
                cycle["intake"]["triggers"][0]["evidence_refs"][0]["path"],
            )
            self.assertEqual(
                ["RC-0001-CL-01", "RC-0001-CL-02"],
                [item["claim_id"] for item in cycle["claim_resolutions"]],
            )

    def test_start_rejects_unsafe_and_symlink_escape_artifact_paths_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outside = root / "outside.md"
            outside.write_text("Outside authority.\n", encoding="utf-8")
            outside_hash = hashlib.sha256(outside.read_bytes()).hexdigest()
            for label, unsafe_path in (
                ("parent", ".." + "/" + "outside.md"),
                ("absolute", str(outside.resolve())),
                ("windows", "C:" + "\\" + "outside.md"),
                ("symlink", "outside-link.md"),
            ):
                with self.subTest(label=label):
                    case_root = root / label
                    case_root.mkdir()
                    workspace, request_path = make_revisit_start_workspace(case_root)
                    if label == "symlink":
                        (workspace / unsafe_path).symlink_to(outside)
                    request = json.loads(request_path.read_text(encoding="utf-8"))
                    request["selected_claims"][0]["source_ref"].update(
                        {"path": unsafe_path, "sha256": outside_hash}
                    )
                    request_path.write_text(
                        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertRegex(
                        result.stderr,
                        r"absolute workspace path is forbidden|forbidden '\.\.'|path escapes workspace",
                    )
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_start_request_rejects_unknown_fields_at_every_owned_object_without_writes(self):
        cases = (
            (
                "top level",
                lambda request: request.update({"hidden": True}),
                r"request unknown field.*hidden",
            ),
            (
                "trigger",
                lambda request: request["triggers"][0].update({"hidden": True}),
                r"request\.triggers\[0\] unknown field.*hidden",
            ),
            (
                "trigger evidence",
                lambda request: request["triggers"][0]["evidence_refs"][0].update(
                    {"hidden": True}
                ),
                r"request\.triggers\[0\]\.evidence_refs\[0\] unknown field.*hidden",
            ),
            (
                "selected claim",
                lambda request: request["selected_claims"][0].update(
                    {"hidden": True}
                ),
                r"request\.selected_claims\[0\] unknown field.*hidden",
            ),
            (
                "claim source ref",
                lambda request: request["selected_claims"][0][
                    "source_ref"
                ].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.source_ref unknown field.*hidden",
            ),
            (
                "inherited evidence",
                lambda request: request["selected_claims"][0][
                    "inherited_evidence"
                ][0].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.inherited_evidence\[0\] unknown field.*hidden",
            ),
            (
                "inherited evidence ref",
                lambda request: request["selected_claims"][0][
                    "inherited_evidence"
                ][0]["ref"].update({"hidden": True}),
                r"request\.selected_claims\[0\]\.inherited_evidence\[0\]\.ref unknown field.*hidden",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_empty_required_arrays_without_writes(self):
        cases = (
            (
                "triggers",
                lambda request: request.__setitem__("triggers", []),
                r"request\.triggers must not be empty",
            ),
            (
                "selected claims",
                lambda request: request.__setitem__("selected_claims", []),
                r"request\.selected_claims must not be empty",
            ),
            (
                "trigger evidence",
                lambda request: request["triggers"][0].__setitem__(
                    "evidence_refs", []
                ),
                r"request\.triggers\[0\]\.evidence_refs must not be empty",
            ),
            (
                "selection reasons",
                lambda request: request["selected_claims"][0].__setitem__(
                    "selection_reasons", []
                ),
                r"selection_reasons must not be empty",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_malformed_times_raw_urls_and_missing_sources_without_writes(self):
        cases = (
            (
                "impossible observed date",
                lambda request: request["triggers"][0].__setitem__(
                    "observed_at", "2026-02-30"
                ),
                r"observed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "noncanonical checked at",
                lambda request: request["triggers"][0]["evidence_refs"][
                    0
                ].__setitem__("checked_at", "2026-07-14T10:00:00+00:00"),
                r"checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "raw URL evidence",
                lambda request: request["triggers"][0].__setitem__(
                    "evidence_refs", ["https://example.test/raw"]
                ),
                r"evidence_refs\[0\] must be an object",
            ),
            (
                "missing registered source",
                lambda request: request["triggers"][0]["evidence_refs"][
                    0
                ].__setitem__("source_id", "src-999"),
                r"source_id is not registered: src-999",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_request_rejects_bad_artifacts_or_trigger_mapping_without_writes(self):
        def artifact_ref(request, *, digest, locator="Claim C1"):
            request["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "claim_ledger.md",
                    "sha256": digest,
                    "locator": locator,
                    "checked_at": "2026-07-14T10:00:00Z",
                }
            ]

        cases = (
            (
                "artifact hash mismatch",
                lambda request: artifact_ref(request, digest="0" * 64),
                r"artifact hash mismatch: claim_ledger\.md",
            ),
            (
                "artifact locator empty",
                lambda request: artifact_ref(
                    request,
                    digest=request["selected_claims"][0]["source_ref"]["sha256"],
                    locator="",
                ),
                r"locator must be non-empty text",
            ),
            (
                "orphan trigger",
                lambda request: request["triggers"].append(
                    copy.deepcopy(request["triggers"][0])
                ),
                r"request trigger index 2 is not referenced by any selected claim",
            ),
            (
                "trigger index out of range",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", [2]
                ),
                r"trigger_indexes.*out of range: 2",
            ),
            (
                "boolean trigger index",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", [True]
                ),
                r"trigger_indexes.*integer >= 1",
            ),
            (
                "unsupported selection reason",
                lambda request: request["selected_claims"][0].__setitem__(
                    "selection_reasons", ["trigger_affected", "because_i_said_so"]
                ),
                r"selection_reasons selection reason is unsupported",
            ),
            (
                "trigger affected without mapping",
                lambda request: request["selected_claims"][0].__setitem__(
                    "trigger_indexes", []
                ),
                r"trigger_affected requires non-empty trigger_indexes",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                self.run_invalid_request_case(mutate, expected_error)

    def test_start_rejects_report_framing_and_registry_drift_without_writes(self):
        cases = (
            (
                "report hash drift",
                lambda workspace: (workspace / "reports" / "final.md").write_bytes(
                    complete_ticker_report_bytes() + b"drift\n"
                ),
                r"CURRENT_REPORT_HASH_DRIFT|registered report bytes do not match",
            ),
            (
                "framing mode drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "framing_contract.json", "mode", "sector"
                ),
                r"framing contract.*mode|FRAMING_MODE_DRIFT",
            ),
            (
                "framing posture drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "framing_contract.json",
                    "research_posture",
                    "fresh",
                ),
                r"framing contract research_posture must be revisit",
            ),
            (
                "registry mode drift",
                lambda workspace: self.rewrite_json_field(
                    workspace / "frontier_registry.json", "mode", "sector"
                ),
                r"frontier registry mode must be ticker",
            ),
            (
                "malformed loop header",
                lambda workspace: (workspace / "evidence_ledger.md").write_text(
                    "# Evidence Ledger\n\n## Loop X: F1 - Qualification timing\n",
                    encoding="utf-8",
                ),
                r"malformed loop header",
            ),
        )
        for label, mutate, expected_error in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    mutate(workspace)
                    workspace_before = snapshot_tree(workspace)
                    request_before = request_path.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertNotEqual(0, result.returncode, result.stderr)
                    self.assertRegex(result.stderr, expected_error)
                    self.assertEqual(workspace_before, snapshot_tree(workspace))
                    self.assertEqual(request_before, request_path.read_bytes())

    def test_start_rejects_concurrent_report_framing_and_registry_hash_drift_before_persistence(self):
        target_names = (
            "reports/final.md",
            "framing_contract.json",
            "frontier_registry.json",
        )
        real_create_cycle = revisit_cycle_cli.create_cycle
        for target_name in target_names:
            with self.subTest(target=target_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    target = workspace / target_name
                    before = snapshot_tree(workspace)
                    drifted_bytes = target.read_bytes() + b" "

                    def create_then_drift(**kwargs):
                        cycle = real_create_cycle(**kwargs)
                        target.write_bytes(drifted_bytes)
                        return cycle

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with mock.patch.object(
                        revisit_cycle_cli,
                        "create_cycle",
                        side_effect=create_then_drift,
                    ), mock.patch("sys.stdout", new=stdout), mock.patch(
                        "sys.stderr", new=stderr
                    ):
                        result = revisit_cycle_cli.main(
                            [
                                str(workspace),
                                "start",
                                "--intake-file",
                                str(request_path),
                            ]
                        )

                    self.assertEqual(2, result, stderr.getvalue())
                    self.assertIn(
                        f"authority changed before cycle persistence: {target.name}",
                        stderr.getvalue(),
                    )
                    after = snapshot_tree(workspace)
                    relative_target = target.relative_to(workspace).as_posix()
                    self.assertEqual(drifted_bytes, target.read_bytes())
                    self.assertEqual(set(before), set(after))
                    for relative, expected in before.items():
                        if relative == relative_target:
                            continue
                        self.assertEqual(expected, after[relative], relative)
                    self.assertEqual([], list((workspace / "revisit_cycles").iterdir()))

    def test_start_rejects_active_ready_and_completed_unpublished_cycle_conflicts_without_writes(self):
        for status in ("active", "ready_for_report", "completed"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    workspace, request_path = make_revisit_start_workspace(root)
                    first = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )
                    self.assertEqual(0, first.returncode, first.stderr)
                    if status != "active":
                        cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
                        previous = revisit_contract.load_cycle(workspace, "RC-0001")
                        updated = copy.deepcopy(previous)
                        updated["status"] = status
                        if status == "completed":
                            updated["completed_at"] = "2026-07-15T05:00:00Z"
                        transitioned = revisit_model.with_audit(
                            previous,
                            updated,
                            f"test-{status}",
                            ["RC-0001"],
                            "2026-07-15T05:00:00Z",
                        )
                        revisit_contract.persist_cycle(
                            workspace,
                            transitioned,
                            expected_sha256=hashlib.sha256(
                                cycle_path.read_bytes()
                            ).hexdigest(),
                        )
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "start",
                        "--intake-file",
                        str(request_path),
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    if status == "completed":
                        self.assertIn("completed-unpublished", result.stderr)
                    else:
                        self.assertIn(f"RC-0001 is {status}", result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))

    @staticmethod
    def rewrite_json_field(path, field, value):
        document = json.loads(path.read_text(encoding="utf-8"))
        document[field] = value
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class TestRevisitCycleAllocation(unittest.TestCase):
    def test_allocation_uses_maximum_reserved_ids_without_filling_gaps(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"].update(
            {
                "revision_id": "REV-0003",
                "cycle_id": "RC-0003",
                "revision_of": "REV-0002",
            }
        )

        aborted = make_minimal_cycle()
        aborted["status"] = "aborted"
        aborted["aborted_at"] = "2026-07-15T01:00:00Z"
        aborted["abort_reason"] = "Evidence access ended."
        aborted["candidate_revision_id"] = "REV-0002"

        completed = make_minimal_cycle()
        completed["cycle_id"] = "RC-0004"
        completed["candidate_revision_id"] = "REV-0007"
        completed["status"] = "completed"
        completed["completed_at"] = "2026-07-15T02:00:00Z"

        original_pointer = copy.deepcopy(pointer)
        original_cycles = copy.deepcopy([aborted, completed])
        allocate = getattr(
            revisit_contract, "allocate_cycle_and_revision_ids", None
        )
        self.assertTrue(callable(allocate), "allocation helper is missing")

        self.assertEqual(
            ("RC-0005", "REV-0008"),
            allocate(pointer, [aborted, completed]),
        )
        self.assertEqual(original_pointer, pointer)
        self.assertEqual(original_cycles, [aborted, completed])

    def test_allocation_rejects_cycle_or_revision_overflow(self):
        allocate = getattr(
            revisit_contract, "allocate_cycle_and_revision_ids", None
        )
        self.assertTrue(callable(allocate), "allocation helper is missing")
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()

        last_cycle = make_minimal_cycle()
        last_cycle["cycle_id"] = "RC-9999"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "cycle ID space is exhausted"
        ):
            allocate(pointer, [last_cycle])

        pointer["current_revision"].update(
            {
                "revision_id": "REV-9999",
                "cycle_id": "RC-9998",
                "revision_of": "REV-9998",
            }
        )
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "revision ID space is exhausted"
        ):
            allocate(pointer, [])


class TestRevisitCycleStatusCli(unittest.TestCase):
    def make_status_workspace(self, root, condition):
        workspace = root / "workspace"
        workspace.mkdir()
        pointer = revisit_contract.empty_pointer()
        cycle = None

        if condition != "empty":
            pointer["current_revision"] = make_initial_revision()
        if condition in {
            "active",
            "ready",
            "aborted",
            "published",
            "completed-unpublished",
        }:
            cycle = make_minimal_cycle()
        if condition == "ready":
            cycle["status"] = "ready_for_report"
        elif condition == "aborted":
            cycle["status"] = "aborted"
            cycle["aborted_at"] = "2026-07-15T03:00:00Z"
            cycle["abort_reason"] = "The selected proof became unavailable."
        elif condition in {"published", "completed-unpublished"}:
            cycle["status"] = "completed"
            cycle["completed_at"] = "2026-07-15T03:00:00Z"
        if condition == "published":
            pointer["current_revision"] = make_revisit_revision()

        (workspace / revisit_contract.POINTER_FILENAME).write_bytes(
            revisit_contract.canonical_document_bytes(pointer)
        )
        if cycle is not None:
            revisit_contract.persist_cycle(
                workspace, cycle, expected_sha256=None
            )
        return workspace

    def test_status_is_deterministic_read_only_and_reports_all_operational_conditions(self):
        cases = (
            (
                "empty",
                None,
                [],
                "register-current --report REPORT --action-class ACTION_CLASS",
            ),
            (
                "registered",
                "REV-0001",
                [],
                "start --intake-file REQUEST",
            ),
            (
                "active",
                "REV-0001",
                ["active"],
                "abort RC-0001 --reason TEXT",
            ),
            (
                "ready",
                "REV-0001",
                ["ready_for_report"],
                "abort RC-0001 --reason TEXT",
            ),
            (
                "aborted",
                "REV-0001",
                ["aborted"],
                "start --intake-file REQUEST",
            ),
            (
                "published",
                "REV-0002",
                ["completed"],
                "start --intake-file REQUEST",
            ),
            (
                "completed-unpublished",
                "REV-0001",
                ["completed-unpublished"],
                "publish RC-0001",
            ),
        )
        for condition, revision_id, statuses, next_command in cases:
            with self.subTest(condition=condition):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_status_workspace(
                        Path(temp_dir), condition
                    )
                    before = snapshot_tree(workspace)

                    first_json = run_revisit_cycle_cli(
                        workspace, "status", "--json"
                    )
                    second_json = run_revisit_cycle_cli(
                        workspace, "status", "--json"
                    )
                    text_result = run_revisit_cycle_cli(workspace, "status")

                    self.assertEqual(0, first_json.returncode, first_json.stderr)
                    self.assertEqual(0, second_json.returncode, second_json.stderr)
                    self.assertEqual(0, text_result.returncode, text_result.stderr)
                    self.assertEqual(first_json.stdout, second_json.stdout)
                    self.assertTrue(first_json.stdout.endswith("\n"))
                    summary = json.loads(first_json.stdout)
                    self.assertEqual(
                        {
                            "schema_version",
                            "mode",
                            "current_revision",
                            "cycles",
                            "issues",
                            "next_legal_command",
                        },
                        set(summary),
                    )
                    self.assertEqual(1, summary["schema_version"])
                    self.assertEqual("ticker", summary["mode"])
                    self.assertEqual([], summary["issues"])
                    self.assertEqual(next_command, summary["next_legal_command"])
                    self.assertEqual(
                        revision_id,
                        (
                            summary["current_revision"]["revision_id"]
                            if summary["current_revision"] is not None
                            else None
                        ),
                    )
                    self.assertEqual(
                        statuses,
                        [cycle["status"] for cycle in summary["cycles"]],
                    )
                    for cycle in summary["cycles"]:
                        self.assertEqual(
                            {
                                "cycle_id",
                                "candidate_revision_id",
                                "status",
                                "created_at",
                                "completed_at",
                                "aborted_at",
                                "abort_reason",
                            },
                            set(cycle),
                        )
                    self.assertIn(
                        f"NEXT LEGAL COMMAND: {next_command}",
                        text_result.stdout,
                    )
                    for status in statuses:
                        self.assertIn(f"STATUS: {status}", text_result.stdout)
                    self.assertEqual(before, snapshot_tree(workspace))

                    if condition == "completed-unpublished":
                        persisted = json.loads(
                            (
                                workspace
                                / "revisit_cycles"
                                / "RC-0001.json"
                            ).read_text(encoding="utf-8")
                        )
                        self.assertEqual("completed", persisted["status"])
                        self.assertNotIn(
                            "completed-unpublished",
                            (workspace / "revisit_cycles" / "RC-0001.json")
                            .read_text(encoding="utf-8"),
                        )

    def test_status_optional_cycle_filters_history_and_rejects_unknown_id_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "aborted")
            before = snapshot_tree(workspace)

            selected = run_revisit_cycle_cli(
                workspace, "status", "RC-0001", "--json"
            )
            missing = run_revisit_cycle_cli(
                workspace, "status", "RC-9999", "--json"
            )

            self.assertEqual(0, selected.returncode, selected.stderr)
            self.assertEqual(
                ["RC-0001"],
                [item["cycle_id"] for item in json.loads(selected.stdout)["cycles"]],
            )
            self.assertEqual(2, missing.returncode, missing.stderr)
            self.assertIn("cycle authority is missing: RC-9999", missing.stderr)
            self.assertEqual(before, snapshot_tree(workspace))

    def test_lower_completed_revision_is_published_history_and_does_not_block_later_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, request_path = make_revisit_start_workspace(root)
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["current_revision"].update(
                {
                    "revision_id": "REV-0003",
                    "cycle_id": "RC-0002",
                    "revision_of": "REV-0002",
                }
            )
            pointer_path.write_bytes(
                revisit_contract.canonical_document_bytes(pointer)
            )
            historical_bytes = {}
            for cycle_id, candidate_revision_id in (
                ("RC-0001", "REV-0002"),
                ("RC-0002", "REV-0003"),
            ):
                cycle = make_minimal_cycle()
                cycle["cycle_id"] = cycle_id
                cycle["candidate_revision_id"] = candidate_revision_id
                cycle["status"] = "completed"
                cycle["completed_at"] = "2026-07-15T03:00:00Z"
                revisit_contract.persist_cycle(
                    workspace, cycle, expected_sha256=None
                )
                historical_bytes[cycle_id] = (
                    (workspace / "revisit_cycles" / f"{cycle_id}.json").read_bytes(),
                    (workspace / "revisit_cycles" / f"{cycle_id}.md").read_bytes(),
                )
            pointer_before = pointer_path.read_bytes()

            status_result = run_revisit_cycle_cli(
                workspace, "status", "--json"
            )

            self.assertEqual(0, status_result.returncode, status_result.stderr)
            summary = json.loads(status_result.stdout)
            self.assertEqual(
                ["completed", "completed"],
                [item["status"] for item in summary["cycles"]],
            )
            self.assertEqual(
                "start --intake-file REQUEST", summary["next_legal_command"]
            )

            start_result = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, start_result.returncode, start_result.stderr)
            third = revisit_contract.load_cycle(workspace, "RC-0003")
            self.assertEqual("REV-0004", third["candidate_revision_id"])
            self.assertEqual(pointer_before, pointer_path.read_bytes())
            for cycle_id, (expected_json, expected_mirror) in historical_bytes.items():
                self.assertEqual(
                    expected_json,
                    (workspace / "revisit_cycles" / f"{cycle_id}.json").read_bytes(),
                )
                self.assertEqual(
                    expected_mirror,
                    (workspace / "revisit_cycles" / f"{cycle_id}.md").read_bytes(),
                )

    def test_status_prints_utf8_under_legacy_ascii_process_encoding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_status_workspace(Path(temp_dir), "registered")
            pointer_path = workspace / revisit_contract.POINTER_FILENAME
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["current_revision"]["report_path"] = "reports/报告.md"
            pointer_path.write_bytes(
                revisit_contract.canonical_document_bytes(pointer)
            )
            before = snapshot_tree(workspace)
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "ascii"
            env["LC_ALL"] = "C"

            result = run_revisit_cycle_cli(workspace, "status", env=env)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("reports/报告.md", result.stdout)
            self.assertNotIn("UnicodeEncodeError", result.stderr)
            self.assertEqual(before, snapshot_tree(workspace))


class TestRevisitCycleAbortCli(unittest.TestCase):
    def start_cycle(self, root):
        workspace, request_path = make_revisit_start_workspace(root)
        result = run_revisit_cycle_cli(
            workspace,
            "start",
            "--intake-file",
            str(request_path),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return workspace, request_path

    def transition_cycle_for_test(self, workspace, *, status):
        cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
        previous = revisit_contract.load_cycle(workspace, "RC-0001")
        updated = copy.deepcopy(previous)
        updated["status"] = status
        if status == "completed":
            updated["completed_at"] = "2026-07-15T04:00:00Z"
        transitioned = revisit_model.with_audit(
            previous,
            updated,
            f"test-{status}",
            ["RC-0001"],
            "2026-07-15T04:00:00Z",
        )
        revisit_contract.persist_cycle(
            workspace,
            transitioned,
            expected_sha256=hashlib.sha256(cycle_path.read_bytes()).hexdigest(),
        )

    def test_abort_accepts_active_and_ready_with_copy_on_write_audit(self):
        for starting_status in ("active", "ready_for_report"):
            with self.subTest(starting_status=starting_status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, request_path = self.start_cycle(Path(temp_dir))
                    if starting_status == "ready_for_report":
                        self.transition_cycle_for_test(
                            workspace, status="ready_for_report"
                        )
                    cycle_path = workspace / "revisit_cycles" / "RC-0001.json"
                    mirror_path = workspace / "revisit_cycles" / "RC-0001.md"
                    previous = revisit_contract.load_cycle(workspace, "RC-0001")
                    pointer_before = (
                        workspace / revisit_contract.POINTER_FILENAME
                    ).read_bytes()
                    request_before = request_path.read_bytes()

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        "The required primary proof became unavailable.",
                    )

                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(
                        "REVISIT CYCLE ABORTED: RC-0001\n", result.stdout
                    )
                    aborted = revisit_contract.load_cycle(workspace, "RC-0001")
                    self.assertEqual("aborted", aborted["status"])
                    self.assertRegex(
                        aborted["aborted_at"],
                        r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
                    )
                    self.assertEqual(
                        "The required primary proof became unavailable.",
                        aborted["abort_reason"],
                    )
                    self.assertEqual(
                        previous["audit"],
                        aborted["audit"][: len(previous["audit"])],
                    )
                    self.assertEqual("abort", aborted["audit"][-1]["command"])
                    self.assertEqual(
                        ["RC-0001"], aborted["audit"][-1]["affected_ids"]
                    )
                    self.assertEqual(
                        previous["audit"][-1]["post_state_sha256"],
                        aborted["audit"][-1]["pre_state_sha256"],
                    )
                    self.assertEqual(
                        revisit_contract.cycle_state_sha256(aborted),
                        aborted["audit"][-1]["post_state_sha256"],
                    )
                    mirror = mirror_path.read_text(encoding="utf-8")
                    self.assertIn("aborted", mirror)
                    self.assertIn(
                        "The required primary proof became unavailable.", mirror
                    )
                    self.assertTrue(cycle_path.is_file())
                    self.assertTrue(mirror_path.is_file())
                    self.assertEqual(
                        pointer_before,
                        (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
                    )
                    self.assertEqual(request_before, request_path.read_bytes())

    def test_abort_rejects_empty_reason_and_terminal_cycles_without_writes(self):
        reason_cases = ("", "   ", "bad\nreason")
        for reason in reason_cases:
            with self.subTest(reason=repr(reason)):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, _ = self.start_cycle(Path(temp_dir))
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        reason,
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn("abort reason must be non-empty", result.stderr)
                    self.assertEqual(before, snapshot_tree(workspace))

        for terminal_status in ("completed", "aborted"):
            with self.subTest(terminal_status=terminal_status):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, _ = self.start_cycle(Path(temp_dir))
                    if terminal_status == "completed":
                        self.transition_cycle_for_test(
                            workspace, status="completed"
                        )
                    else:
                        first_abort = run_revisit_cycle_cli(
                            workspace,
                            "abort",
                            "RC-0001",
                            "--reason",
                            "First explicit abort.",
                        )
                        self.assertEqual(0, first_abort.returncode, first_abort.stderr)
                    before = snapshot_tree(workspace)

                    result = run_revisit_cycle_cli(
                        workspace,
                        "abort",
                        "RC-0001",
                        "--reason",
                        "Attempted terminal rewrite.",
                    )

                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(
                        f"cannot abort cycle RC-0001 with status {terminal_status}",
                        result.stderr,
                    )
                    self.assertEqual(before, snapshot_tree(workspace))

    def test_aborted_cycle_reserves_cycle_and_revision_ids_without_cleanup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, request_path = self.start_cycle(Path(temp_dir))
            pointer_before = (
                workspace / revisit_contract.POINTER_FILENAME
            ).read_bytes()
            first_abort = run_revisit_cycle_cli(
                workspace,
                "abort",
                "RC-0001",
                "--reason",
                "First cycle stopped explicitly.",
            )
            self.assertEqual(0, first_abort.returncode, first_abort.stderr)
            first_json = (workspace / "revisit_cycles" / "RC-0001.json").read_bytes()
            first_mirror = (workspace / "revisit_cycles" / "RC-0001.md").read_bytes()

            second_start = run_revisit_cycle_cli(
                workspace,
                "start",
                "--intake-file",
                str(request_path),
            )

            self.assertEqual(0, second_start.returncode, second_start.stderr)
            second = revisit_contract.load_cycle(workspace, "RC-0002")
            self.assertEqual("RC-0002", second["cycle_id"])
            self.assertEqual("REV-0003", second["candidate_revision_id"])
            self.assertEqual(
                ["RC-0002-TRG-01"],
                [item["trigger_id"] for item in second["intake"]["triggers"]],
            )
            self.assertEqual(
                first_json,
                (workspace / "revisit_cycles" / "RC-0001.json").read_bytes(),
            )
            self.assertEqual(
                first_mirror,
                (workspace / "revisit_cycles" / "RC-0001.md").read_bytes(),
            )
            self.assertEqual(
                pointer_before,
                (workspace / revisit_contract.POINTER_FILENAME).read_bytes(),
            )
            self.assertEqual(
                {
                    "RC-0001.json",
                    "RC-0001.md",
                    "RC-0002.json",
                    "RC-0002.md",
                },
                {path.name for path in (workspace / "revisit_cycles").iterdir()},
            )


class TestPointerSchema(unittest.TestCase):
    def assert_contract_error(self, operation, pattern):
        try:
            operation()
        except Exception as error:
            self.assertIsInstance(error, revisit_contract.RevisitContractError)
            self.assertRegex(str(error), pattern)
            return
        self.fail("RevisitContractError not raised")

    def test_contract_error_is_an_explicit_value_error_export(self):
        error_type = getattr(revisit_contract, "RevisitContractError", None)
        self.assertTrue(
            isinstance(error_type, type) and issubclass(error_type, ValueError),
            "RevisitContractError export is missing",
        )

    def test_empty_pointer_is_strict_ticker_schema_v1(self):
        empty_pointer = getattr(revisit_contract, "empty_pointer", None)
        validate_pointer = getattr(revisit_contract, "validate_pointer", None)
        self.assertTrue(callable(empty_pointer), "empty_pointer export is missing")
        self.assertTrue(callable(validate_pointer), "validate_pointer export is missing")
        pointer = empty_pointer()
        self.assertEqual(
            {"schema_version": 1, "mode": "ticker", "current_revision": None},
            pointer,
        )
        self.assertIs(pointer, validate_pointer(pointer))

    def test_pointer_rejects_unknown_fields_without_mutating_input(self):
        pointer = revisit_contract.empty_pointer()
        pointer["hidden_authority"] = {"verdict": "Act"}
        original = copy.deepcopy(pointer)

        with self.assertRaisesRegex(ValueError, "pointer unknown field"):
            revisit_contract.validate_pointer(pointer)

        self.assertEqual(original, pointer)

    def test_pointer_rejects_non_object_input(self):
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer([]),
            "revisit_contract.json must contain an object",
        )

    def test_pointer_schema_version_rejects_bool(self):
        pointer = revisit_contract.empty_pointer()
        pointer["schema_version"] = True
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.schema_version must be an integer >= 1",
        )

    def test_pointer_rejects_unsupported_schema_version(self):
        pointer = revisit_contract.empty_pointer()
        pointer["schema_version"] = 2
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "unsupported pointer schema_version",
        )

    def test_pointer_mode_is_ticker_only(self):
        pointer = revisit_contract.empty_pointer()
        pointer["mode"] = "sector"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "pointer.mode must be ticker",
        )

    def test_current_revision_must_be_an_object_when_present(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = []
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision must be an object",
        )

    def test_current_revision_rejects_unknown_fields_without_mutation(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["hidden_authority"] = True
        original = copy.deepcopy(pointer)

        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision unknown field",
        )

        self.assertEqual(original, pointer)

    def test_current_revision_rejects_malformed_revision_id(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["revision_id"] = "rev-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.revision_id must match REV-NNNN",
        )

    def test_initial_registration_requires_revision_0001(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["revision_id"] = "REV-0002"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "initial registration revision_id must be REV-0001",
        )

    def test_revisit_revision_rejects_malformed_cycle_id(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["cycle_id"] = "RC-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.cycle_id must match RC-NNNN",
        )

    def test_revisit_revision_rejects_malformed_revision_of(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["revision_of"] = "REV-1"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.revision_of must match REV-NNNN",
        )

    def test_revisit_revision_requires_cycle_and_revision_of_together(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_revisit_revision()
        pointer["current_revision"]["cycle_id"] = None
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "cycle_id and revision_of must both be null or both be IDs",
        )

    def test_revision_report_path_must_be_non_empty_text(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_path"] = ""
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_path must be non-empty text",
        )

    def test_revision_report_path_rejects_control_characters(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_path"] = "reports/initial\n.md"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_path must not contain control characters",
        )

    def test_revision_report_hash_is_lowercase_sha256(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["report_sha256"] = "A" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.report_sha256 must be a lowercase SHA-256",
        )

    def test_revision_action_class_uses_locked_vocabulary(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["action_class"] = "Buy"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.action_class is unsupported",
        )

    def test_revision_validated_at_must_be_non_empty_text(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["validated_at"] = 0
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.validated_at must be non-empty text",
        )

    def test_revision_validated_at_requires_canonical_real_utc_timestamp(self):
        invalid_timestamps = (
            "2026-07-15 00:00:00Z",
            "2026-07-15T00:00:00+00:00",
            "2026-07-15T00:00:00.000Z",
            "2026-02-30T00:00:00Z",
            "２０２６-07-15T00:00:00Z",
        )
        for timestamp in invalid_timestamps:
            with self.subTest(timestamp=timestamp):
                pointer = revisit_contract.empty_pointer()
                pointer["current_revision"] = make_initial_revision()
                pointer["current_revision"]["validated_at"] = timestamp
                self.assert_contract_error(
                    lambda: revisit_contract.validate_pointer(pointer),
                    r"pointer\.current_revision\.validated_at must be YYYY-MM-DDTHH:MM:SSZ",
                )

    def test_pointer_missing_field_is_rejected(self):
        pointer = revisit_contract.empty_pointer()
        del pointer["mode"]
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            "pointer missing field.*mode",
        )

    def test_revision_timestamp_rejects_control_characters(self):
        pointer = revisit_contract.empty_pointer()
        pointer["current_revision"] = make_initial_revision()
        pointer["current_revision"]["validated_at"] += "\x00"
        self.assert_contract_error(
            lambda: revisit_contract.validate_pointer(pointer),
            r"pointer\.current_revision\.validated_at must not contain control characters",
        )

    def test_valid_initial_and_revisit_revisions_return_the_same_pointer(self):
        for revision in (make_initial_revision(), make_revisit_revision()):
            with self.subTest(revision_id=revision["revision_id"]):
                pointer = revisit_contract.empty_pointer()
                pointer["current_revision"] = revision
                original = copy.deepcopy(pointer)

                self.assertIs(pointer, revisit_contract.validate_pointer(pointer))
                self.assertEqual(original, pointer)

    def test_action_classes_are_the_exact_locked_vocabulary(self):
        self.assertEqual(
            (
                "Act",
                "Watch with Trigger",
                "Trade-only",
                "Basket-only",
                "Reject",
                "Needs Primary Evidence",
            ),
            getattr(revisit_contract, "ACTION_CLASSES", None),
        )


class TestRevisitStorePaths(unittest.TestCase):
    def assert_internal_symlink_target_rejected(
        self, target_parent, target_name, pattern
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            reports = workspace / "reports"
            target_directory = workspace / target_parent
            reports.mkdir(parents=True)
            target_directory.mkdir(parents=True, exist_ok=True)
            target = target_directory / target_name
            target.write_bytes(b"authority bytes")
            (reports / "final.md").symlink_to(target)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, pattern
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                )

    def test_resolve_workspace_path_rejects_internal_symlink_parent_and_suffix_change(
        self,
    ):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.json", "resolved path must be under reports/"
        )

    def test_resolve_workspace_path_rejects_internal_symlink_parent_change(self):
        self.assert_internal_symlink_target_rejected(
            "other", "authority.md", "resolved path must be under reports/"
        )

    def test_resolve_workspace_path_rejects_internal_symlink_suffix_change(self):
        self.assert_internal_symlink_target_rejected(
            "reports", "authority.json", "resolved path must end with .md"
        )

    def test_resolve_workspace_path_accepts_real_matching_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            report = workspace / "reports" / "final.md"
            report.parent.mkdir(parents=True)
            report.write_bytes(b"ordinary report")

            self.assertEqual(
                report.resolve(),
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                ),
            )

    def test_resolve_workspace_path_rejects_c1_control_character(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "control-free"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/next\u0085line.md",
                    parent="reports",
                    suffix=".md",
                )

    def test_normalize_workspace_relative_path_preserves_unicode_and_separators(self):
        normalize = getattr(
            revisit_contract, "normalize_workspace_relative_path", None
        )
        self.assertTrue(
            callable(normalize),
            "normalize_workspace_relative_path export is missing",
        )
        self.assertEqual(
            "reports/研究/最终.md",
            normalize("./reports\\研究//最终.md"),
        )

    def test_normalize_workspace_relative_path_rejects_absolute_forms(self):
        cases = (
            "/" + "reports/final.md",
            "C:" + "\\" + "reports\\final.md",
            "C:" + "reports\\final.md",
            "\\" + "reports\\final.md",
            "\\" + "\\" + "server\\share\\reports\\final.md",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for value in cases:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        "absolute workspace path is forbidden",
                    ):
                        revisit_contract.resolve_workspace_path(
                            workspace,
                            value,
                            parent="reports",
                            suffix=".md",
                        )

    def test_normalize_workspace_relative_path_rejects_raw_parent_components(self):
        cases = (
            ".." + "/" + "final.md",
            "reports/" + ".." + "/" + "final.md",
            "reports\\" + ".." + "\\" + "final.md",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            for value in cases:
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        revisit_contract.RevisitContractError,
                        "contains forbidden '..'",
                    ):
                        revisit_contract.resolve_workspace_path(
                            workspace,
                            value,
                            parent="reports",
                            suffix=".md",
                        )

    def test_resolve_workspace_path_requires_parent_and_suffix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "path must be under reports/"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "other/final.md",
                    parent="reports",
                    suffix=".md",
                )
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "path must end with .md"
            ):
                revisit_contract.resolve_workspace_path(
                    workspace,
                    "reports/final.json",
                    parent="reports",
                    suffix=".md",
                )

    def test_resolve_workspace_path_returns_normalized_path_under_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertEqual(
                workspace.resolve() / "reports" / "最终.md",
                revisit_contract.resolve_workspace_path(
                    workspace,
                    ".\\reports\\最终.md",
                    parent="reports",
                    suffix=".md",
                ),
            )

    def test_resolve_workspace_path_rejects_symlink_escape(self):
        resolve_workspace_path = getattr(
            revisit_contract, "resolve_workspace_path", None
        )
        self.assertTrue(
            callable(resolve_workspace_path),
            "resolve_workspace_path export is missing",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            (workspace / "reports").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "escapes workspace"
            ):
                resolve_workspace_path(
                    workspace,
                    "reports/final.md",
                    parent="reports",
                    suffix=".md",
                )


class TestRevisitStoreBytes(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def test_canonical_value_bytes_are_compact_sorted_and_unicode(self):
        canonical_value_bytes = self.required_callable("canonical_value_bytes")
        first = {"z": "雪", "a": {"later": 2, "earlier": 1}}
        second = {"a": {"earlier": 1, "later": 2}, "z": "雪"}
        expected = '{"a":{"earlier":1,"later":2},"z":"雪"}'.encode("utf-8")

        self.assertEqual(expected, canonical_value_bytes(first))
        self.assertEqual(expected, canonical_value_bytes(second))
        self.assertNotIn(b"\\u", canonical_value_bytes(first))

    def test_canonical_document_bytes_are_indented_unicode_with_one_newline(self):
        canonical_document_bytes = self.required_callable("canonical_document_bytes")
        document = {"schema_version": 1, "label": "研究"}
        expected = (
            '{\n  "schema_version": 1,\n  "label": "研究"\n}\n'.encode("utf-8")
        )

        payload = canonical_document_bytes(document)

        self.assertEqual(expected, payload)
        self.assertTrue(payload.endswith(b"}\n"))
        self.assertFalse(payload.endswith(b"\n\n"))

    def test_sha256_helpers_hash_exact_raw_bytes(self):
        sha256_bytes = self.required_callable("sha256_bytes")
        sha256_file = self.required_callable("sha256_file")
        payload = "line one\r\n雪\r\n".encode("utf-8")
        expected = hashlib.sha256(payload).hexdigest()

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "report.md"
            path.write_bytes(payload)
            self.assertEqual(expected, sha256_file(path))

        self.assertEqual(expected, sha256_bytes(payload))


class TestRevisitStoreReads(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def write_cycle(self, workspace, cycle, filename=None):
        directory = workspace / revisit_contract.CYCLES_DIRNAME
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (filename or f"{cycle['cycle_id']}.json")
        path.write_bytes(revisit_contract.canonical_document_bytes(cycle))
        return path

    def test_store_paths_are_canonical_and_cycle_ids_are_strict(self):
        pointer_path = self.required_callable("pointer_path")
        cycle_directory = self.required_callable("cycle_directory")
        cycle_json_path = self.required_callable("cycle_json_path")
        cycle_markdown_path = self.required_callable("cycle_markdown_path")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertEqual(
                workspace.resolve() / revisit_contract.POINTER_FILENAME,
                pointer_path(workspace),
            )
            self.assertEqual(
                workspace.resolve() / revisit_contract.CYCLES_DIRNAME,
                cycle_directory(workspace),
            )
            self.assertEqual(
                workspace.resolve()
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.json",
                cycle_json_path(workspace, "RC-0001"),
            )
            self.assertEqual(
                workspace.resolve()
                / revisit_contract.CYCLES_DIRNAME
                / "RC-0001.md",
                cycle_markdown_path(workspace, "RC-0001"),
            )
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "cycle_id must match RC-NNNN"
            ):
                cycle_json_path(workspace, ".." + "/" + "RC-0001")

    def test_pointer_reads_are_strict_and_allow_missing_is_explicit(self):
        load_pointer = self.required_callable("load_pointer")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.assertIsNone(load_pointer(workspace, allow_missing=True))
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "pointer authority is missing"
            ):
                load_pointer(workspace)

            path = workspace / revisit_contract.POINTER_FILENAME
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed JSON.*revisit_contract"
            ):
                load_pointer(workspace)

    def test_cycle_reads_never_use_markdown_when_json_is_absent_or_malformed(self):
        load_cycle = self.required_callable("load_cycle")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            markdown = directory / "RC-0001.md"
            markdown.write_bytes(revisit_contract.canonical_document_bytes(make_minimal_cycle()))

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "cycle authority is missing"
            ):
                load_cycle(workspace, "RC-0001")

            (directory / "RC-0001.json").write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed JSON.*RC-0001.json"
            ):
                load_cycle(workspace, "RC-0001")

            self.assertTrue(markdown.exists())

    def test_list_cycle_ids_validates_history_and_returns_numeric_order(self):
        list_cycle_ids = self.required_callable("list_cycle_ids")
        load_cycle = self.required_callable("load_cycle")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            second = make_minimal_cycle()
            second["cycle_id"] = "RC-0002"
            second["candidate_revision_id"] = "REV-0003"
            self.write_cycle(workspace, second)
            self.write_cycle(workspace, make_minimal_cycle())
            (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").write_text(
                "derived mirror\n", encoding="utf-8"
            )

            self.assertEqual(("RC-0001", "RC-0002"), list_cycle_ids(workspace))
            self.assertEqual("RC-0002", load_cycle(workspace, "RC-0002")["cycle_id"])

    def test_list_cycle_ids_rejects_malformed_filenames_and_internal_ids(self):
        list_cycle_ids = self.required_callable("list_cycle_ids")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.write_cycle(workspace, make_minimal_cycle(), "RC-1.json")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "malformed cycle filename"
            ):
                list_cycle_ids(workspace)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            self.write_cycle(workspace, make_minimal_cycle(), "RC-0002.json")
            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError,
                "filename RC-0002 does not match internal cycle_id RC-0001",
            ):
                list_cycle_ids(workspace)


class TestRevisitRender(unittest.TestCase):
    def test_render_cycle_markdown_is_deterministic_escaped_and_factual(self):
        render_cycle_markdown = getattr(
            revisit_contract, "render_cycle_markdown", None
        )
        self.assertTrue(
            callable(render_cycle_markdown),
            "render_cycle_markdown export is missing",
        )
        cycle = make_populated_cycle()
        cycle["intake"]["triggers"][0]["statement"] = "Revenue | baseline changed."
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])

        first = render_cycle_markdown(cycle)
        second = render_cycle_markdown(copy.deepcopy(cycle))

        self.assertEqual(first, second)
        for heading in (
            "## Identity And Status",
            "## Immutable Base And Framing Boundary",
            "## Fired Triggers",
            "## Selected And Derived Claims",
            "## Freshness",
            "## Frontier Bindings And Floors",
            "## Decision And Rerun Duties",
            "## Report Candidate",
            "## Audit",
        ):
            self.assertIn(heading, first)
        self.assertIn("Revenue \\| baseline changed.", first)
        self.assertIn("### Claim Resolutions", first)
        self.assertIn("confirmed", first)
        self.assertIn("The primary filing confirms the claim.", first)
        self.assertNotIn("Inferred verdict", first)
        self.assertTrue(first.endswith("\n"))
        self.assertFalse(first.endswith("\n\n"))

        minimal = render_cycle_markdown(make_minimal_cycle())
        self.assertIn("No decision assessment recorded.", minimal)


class TestRevisitPersistence(unittest.TestCase):
    def required_callable(self, name):
        operation = getattr(revisit_contract, name, None)
        self.assertTrue(callable(operation), f"{name} export is missing")
        return operation

    def test_persist_cycle_replaces_mirror_before_json_with_exact_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_populated_cycle()
        real_replace = os.replace
        destinations = []

        def recording_replace(source, destination):
            destinations.append(Path(destination).name)
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                json_path, markdown_path = persist_cycle(
                    workspace, cycle, expected_sha256=None
                )

            self.assertEqual(["RC-0001.md", "RC-0001.json"], destinations)
            self.assertEqual(
                revisit_contract.canonical_document_bytes(cycle),
                json_path.read_bytes(),
            )
            self.assertEqual(
                revisit_contract.render_cycle_markdown(cycle).encode("utf-8"),
                markdown_path.read_bytes(),
            )
            self.assertEqual(cycle, revisit_contract.load_cycle(workspace, "RC-0001"))

    def test_persist_cycle_rejects_path_alias_before_render_and_preserves_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "aborted"
        updated["aborted_at"] = "2026-07-15T02:00:00Z"
        updated["abort_reason"] = "\ud800"
        original_json = revisit_contract.canonical_document_bytes(original)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)

            try:
                with mock.patch(
                    "scripts.revisit_contract.store.cycle_markdown_path",
                    return_value=json_path.resolve(),
                ):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )
            except Exception as error:
                self.assertIsInstance(error, revisit_contract.RevisitContractError)
                self.assertRegex(str(error), "authority targets must be distinct")
            else:
                self.fail("aliased cycle authority targets were not rejected")

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertFalse(markdown_path.exists())

    def test_json_replace_failure_restores_exact_existing_mirror_bytes(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\nwith exact CRLF bytes\r\n"
        real_replace = os.replace
        destinations = []

        def fail_json_replace(source, destination):
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("cycle JSON replace failed")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_replace,
            ):
                with self.assertRaisesRegex(OSError, "cycle JSON replace failed"):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )

            self.assertEqual(original_markdown, markdown_path.read_bytes())
            self.assertEqual(original_json, json_path.read_bytes())
            self.assertEqual(
                ["RC-0001.md", "RC-0001.json", "RC-0001.md"], destinations
            )

    def test_first_write_json_failure_removes_new_orphan_mirror(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        real_replace = os.replace
        destinations = []

        def fail_json_replace(source, destination):
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("first cycle JSON replace failed")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=fail_json_replace,
            ):
                with self.assertRaisesRegex(OSError, "first cycle JSON replace failed"):
                    persist_cycle(workspace, cycle, expected_sha256=None)

            directory = workspace / revisit_contract.CYCLES_DIRNAME
            self.assertFalse((directory / "RC-0001.md").exists())
            self.assertFalse((directory / "RC-0001.json").exists())
            self.assertEqual(["RC-0001.md", "RC-0001.json"], destinations)
            self.assertEqual([], list(directory.iterdir()))

    def test_rollback_error_is_an_explicit_contract_error(self):
        error_type = getattr(
            revisit_contract, "RevisitPersistenceRollbackError", None
        )
        self.assertTrue(
            isinstance(error_type, type)
            and issubclass(error_type, revisit_contract.RevisitContractError),
            "RevisitPersistenceRollbackError export is missing",
        )

    def test_rollback_failure_surfaces_original_and_rollback_errors_together(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\n"
        real_replace = os.replace
        destinations = []
        markdown_replaces = 0

        def fail_json_and_rollback(source, destination):
            nonlocal markdown_replaces
            destination = Path(destination)
            destinations.append(destination.name)
            if destination.name == "RC-0001.json":
                raise OSError("original JSON failure")
            if destination.name == "RC-0001.md":
                markdown_replaces += 1
                if markdown_replaces == 2:
                    raise OSError("mirror rollback failure")
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            try:
                with mock.patch(
                    "scripts.revisit_contract.store.os.replace",
                    side_effect=fail_json_and_rollback,
                ):
                    persist_cycle(
                        workspace,
                        updated,
                        expected_sha256=hashlib.sha256(original_json).hexdigest(),
                    )
            except Exception as error:
                self.assertIsInstance(
                    error, revisit_contract.RevisitPersistenceRollbackError
                )
                self.assertIn("original JSON failure", str(error))
                self.assertIn("mirror rollback failure", str(error))
                self.assertEqual("original JSON failure", str(error.original_error))
                self.assertEqual("mirror rollback failure", str(error.rollback_error))
            else:
                self.fail("combined rollback error not raised")

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertNotEqual(original_markdown, markdown_path.read_bytes())
            self.assertEqual(
                ["RC-0001.md", "RC-0001.json", "RC-0001.md"], destinations
            )

    def test_render_payload_failure_writes_neither_cycle_file(self):
        persist_cycle = self.required_callable("persist_cycle")
        cycle = make_minimal_cycle()
        cycle["status"] = "aborted"
        cycle["aborted_at"] = "2026-07-15T02:00:00Z"
        cycle["abort_reason"] = "\ud800"
        self.assertIs(cycle, revisit_contract.validate_cycle(cycle))

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with self.assertRaises(UnicodeEncodeError):
                persist_cycle(workspace, cycle, expected_sha256=None)
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.md").exists()
            )
            self.assertFalse(
                (workspace / revisit_contract.CYCLES_DIRNAME / "RC-0001.json").exists()
            )

    def test_optimistic_cycle_digest_mismatch_changes_neither_file(self):
        persist_cycle = self.required_callable("persist_cycle")
        original = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        original_json = revisit_contract.canonical_document_bytes(original)
        original_markdown = b"prior mirror\r\nexact bytes\r\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            directory = workspace / revisit_contract.CYCLES_DIRNAME
            directory.mkdir()
            json_path = directory / "RC-0001.json"
            markdown_path = directory / "RC-0001.md"
            json_path.write_bytes(original_json)
            markdown_path.write_bytes(original_markdown)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "authority changed before write"
            ):
                persist_cycle(workspace, updated, expected_sha256="0" * 64)

            self.assertEqual(original_json, json_path.read_bytes())
            self.assertEqual(original_markdown, markdown_path.read_bytes())

    def test_persist_pointer_is_one_atomic_replace_with_optimistic_guard(self):
        persist_pointer = self.required_callable("persist_pointer")
        pointer = revisit_contract.empty_pointer()
        real_replace = os.replace
        destinations = []

        def recording_replace(source, destination):
            destinations.append(Path(destination).name)
            return real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                path = persist_pointer(workspace, pointer, expected_sha256=None)
            self.assertEqual([revisit_contract.POINTER_FILENAME], destinations)
            self.assertEqual(
                revisit_contract.canonical_document_bytes(pointer), path.read_bytes()
            )

            prior_bytes = path.read_bytes()
            updated = revisit_contract.empty_pointer()
            updated["current_revision"] = make_initial_revision()
            destinations.clear()
            with mock.patch(
                "scripts.revisit_contract.store.os.replace",
                side_effect=recording_replace,
            ):
                persist_pointer(
                    workspace,
                    updated,
                    expected_sha256=hashlib.sha256(prior_bytes).hexdigest(),
                )
            self.assertEqual([revisit_contract.POINTER_FILENAME], destinations)
            updated_bytes = path.read_bytes()
            self.assertEqual(revisit_contract.canonical_document_bytes(updated), updated_bytes)

            with self.assertRaisesRegex(
                revisit_contract.RevisitContractError, "authority changed before write"
            ):
                persist_pointer(workspace, pointer, expected_sha256="0" * 64)
            self.assertEqual(updated_bytes, path.read_bytes())


class TestRevisitAuditMutation(unittest.TestCase):
    def test_with_audit_is_copy_on_write_and_uses_locked_null_pre_hash(self):
        with_audit = getattr(revisit_model, "with_audit", None)
        self.assertTrue(callable(with_audit), "with_audit helper is missing")
        previous = make_minimal_cycle()
        updated = make_minimal_cycle()
        updated["status"] = "ready_for_report"
        previous_before = copy.deepcopy(previous)
        updated_before = copy.deepcopy(updated)

        result = with_audit(
            previous,
            updated,
            command="mark-ready",
            affected_ids=["RC-0001"],
            timestamp="2026-07-15T03:00:00Z",
        )

        self.assertEqual(previous_before, previous)
        self.assertEqual(updated_before, updated)
        self.assertIsNot(result, updated)
        self.assertEqual(1, result["audit"][0]["sequence"])
        self.assertEqual(
            test_semantic_sha256(None), result["audit"][0]["pre_state_sha256"]
        )
        self.assertEqual(
            revisit_contract.cycle_state_sha256(updated),
            result["audit"][0]["post_state_sha256"],
        )
        self.assertIs(result, revisit_contract.validate_cycle(result))

    def test_with_audit_preserves_prefix_and_audit_text_cannot_change_state_hashes(self):
        with_audit = getattr(revisit_model, "with_audit", None)
        self.assertTrue(callable(with_audit), "with_audit helper is missing")
        base = make_minimal_cycle()
        first = with_audit(
            base,
            base,
            command="start",
            affected_ids=["RC-0001"],
            timestamp="2026-07-15T03:00:00Z",
        )
        updated = copy.deepcopy(first)
        updated["status"] = "ready_for_report"
        tampered_audit_text = copy.deepcopy(updated)
        tampered_audit_text["audit"][0]["command"] = "ignored audit-only text"

        second = with_audit(
            first,
            updated,
            command="mark-ready",
            affected_ids=["RC-0001"],
            timestamp="2026-07-15T03:05:00Z",
        )
        alternate = with_audit(
            first,
            tampered_audit_text,
            command="different audit text",
            affected_ids=["RC-0001", "REV-0002"],
            timestamp="2026-07-15T03:06:00Z",
        )

        self.assertEqual(first["audit"], second["audit"][:-1])
        self.assertEqual(first["audit"], alternate["audit"][:-1])
        self.assertEqual(2, second["audit"][-1]["sequence"])
        self.assertEqual(
            first["audit"][-1]["post_state_sha256"],
            second["audit"][-1]["pre_state_sha256"],
        )
        self.assertEqual(
            second["audit"][-1]["post_state_sha256"],
            alternate["audit"][-1]["post_state_sha256"],
        )
        self.assertEqual(
            revisit_contract.cycle_state_sha256(second),
            revisit_contract.cycle_state_sha256(alternate),
        )
        self.assertIs(second, revisit_contract.validate_cycle(second))
        self.assertIs(alternate, revisit_contract.validate_cycle(alternate))


class TestCycleSchema(unittest.TestCase):
    def assert_contract_error(self, operation, pattern):
        try:
            operation()
        except Exception as error:
            self.assertIsInstance(error, revisit_contract.RevisitContractError)
            self.assertRegex(str(error), pattern)
            return
        self.fail("RevisitContractError not raised")

    def test_validate_cycle_is_an_explicit_callable_export(self):
        self.assertTrue(
            callable(getattr(revisit_contract, "validate_cycle", None)),
            "validate_cycle export is missing",
        )

    def test_cycle_rejects_persisted_completed_unpublished_status(self):
        cycle = make_minimal_cycle()
        cycle["status"] = "completed-unpublished"
        with self.assertRaisesRegex(
            revisit_contract.RevisitContractError, "unsupported cycle status"
        ):
            revisit_contract.validate_cycle(cycle)

    def test_semantic_hash_helpers_are_canonical_pure_and_audit_free(self):
        value = {"z": "中", "a": [2, 1]}
        expected_bytes = '{"a":[2,1],"z":"中"}'.encode()
        cycle = make_minimal_cycle()
        cycle["audit"] = [{"arbitrary": "excluded"}]
        original = copy.deepcopy(cycle)
        expected_state = copy.deepcopy(cycle)
        expected_state.pop("audit")

        checks = (
            (
                "canonical_semantic_bytes",
                expected_bytes,
                getattr(revisit_contract, "canonical_semantic_bytes", lambda _: b"")(
                    value
                ),
            ),
            (
                "semantic_sha256",
                test_semantic_sha256(value),
                getattr(revisit_contract, "semantic_sha256", lambda _: "")(value),
            ),
            (
                "intake_sha256",
                test_semantic_sha256(cycle["intake"]),
                getattr(revisit_contract, "intake_sha256", lambda _: "")(
                    cycle["intake"]
                ),
            ),
            (
                "state_without_audit",
                expected_state,
                getattr(revisit_contract, "state_without_audit", lambda _: {})(cycle),
            ),
            (
                "cycle_state_sha256",
                test_semantic_sha256(expected_state),
                getattr(revisit_contract, "cycle_state_sha256", lambda _: "")(cycle),
            ),
        )
        for name, expected, actual in checks:
            with self.subTest(helper=name):
                self.assertEqual(expected, actual)
        self.assertEqual(original, cycle)

    def test_cycle_rejects_non_object_input(self):
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle([]),
            "cycle JSON must contain an object",
        )

    def test_cycle_top_level_keys_are_exact_and_validation_is_non_mutating(self):
        cycle = make_minimal_cycle()
        cycle["hidden_authority"] = "Act"
        original = copy.deepcopy(cycle)
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle unknown field.*hidden_authority",
        )
        self.assertEqual(original, cycle)

    def test_cycle_schema_version_rejects_bool(self):
        cycle = make_minimal_cycle()
        cycle["schema_version"] = True
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle\.schema_version must be an integer >= 1",
        )

    def test_cycle_rejects_unsupported_schema_version(self):
        cycle = make_minimal_cycle()
        cycle["schema_version"] = 2
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "unsupported cycle schema_version",
        )

    def test_cycle_and_candidate_revision_ids_use_locked_formats(self):
        cases = (
            ("cycle_id", "RC-1", r"cycle\.cycle_id must match RC-NNNN"),
            (
                "candidate_revision_id",
                "REV-1",
                r"cycle\.candidate_revision_id must match REV-NNNN",
            ),
        )
        for field, value, pattern in cases:
            with self.subTest(field=field):
                cycle = make_minimal_cycle()
                cycle[field] = value
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_cycle_timestamps_and_abort_reason_follow_terminal_status(self):
        timestamp = "2026-07-15T01:00:00Z"
        cases = (
            (
                "created_at_format",
                {"created_at": "2026-02-30T00:00:00Z"},
                r"cycle\.created_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "completed_at_on_active",
                {"completed_at": timestamp},
                "cycle.completed_at is only valid when status is completed",
            ),
            (
                "aborted_at_on_active",
                {"aborted_at": timestamp},
                "cycle.aborted_at is only valid when status is aborted",
            ),
            (
                "abort_reason_on_active",
                {"abort_reason": "Stopped"},
                "cycle.abort_reason is only valid when status is aborted",
            ),
            (
                "completed_without_timestamp",
                {"status": "completed"},
                "completed cycle requires completed_at",
            ),
            (
                "aborted_without_timestamp",
                {"status": "aborted", "abort_reason": "Stopped"},
                "aborted cycle requires aborted_at",
            ),
            (
                "aborted_without_reason",
                {"status": "aborted", "aborted_at": timestamp},
                "aborted cycle requires abort_reason",
            ),
        )
        for name, overrides, pattern in cases:
            with self.subTest(case=name):
                cycle = make_minimal_cycle()
                cycle.update(overrides)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_cycle_rejects_intake_hash_mismatch(self):
        cycle = make_minimal_cycle()
        cycle["intake_sha256"] = "0" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle.intake_sha256 does not match immutable intake",
        )

    def test_every_nested_object_rejects_unknown_fields(self):
        cases = (
            (("intake",), "cycle.intake"),
            (("intake", "base_revision"), "cycle.intake.base_revision"),
            (("intake", "framing"), "cycle.intake.framing"),
            (("intake", "framing", "snapshot"), "cycle.intake.framing.snapshot"),
            (
                ("intake", "workspace_boundary"),
                "cycle.intake.workspace_boundary",
            ),
            (("intake", "triggers", 0), "cycle.intake.triggers[0]"),
            (
                ("intake", "triggers", 0, "evidence_refs", 0),
                "cycle.intake.triggers[0].evidence_refs[0]",
            ),
            (("intake", "selected_claims", 0), "cycle.intake.selected_claims[0]"),
            (
                ("intake", "selected_claims", 0, "source_ref"),
                "cycle.intake.selected_claims[0].source_ref",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence", 0),
                "cycle.intake.selected_claims[0].inherited_evidence[0]",
            ),
            (("frontier_bindings", 0), "cycle.frontier_bindings[0]"),
            (("derived_claims", 0), "cycle.derived_claims[0]"),
            (
                ("derived_claims", 0, "accepted_from"),
                "cycle.derived_claims[0].accepted_from",
            ),
            (("claim_resolutions", 0), "cycle.claim_resolutions[0]"),
            (
                ("claim_resolutions", 0, "current_evidence_refs", 0),
                "cycle.claim_resolutions[0].current_evidence_refs[0]",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs", 0),
                "cycle.claim_resolutions[0].attempted_search_refs[0]",
            ),
            (("decision_assessment",), "cycle.decision_assessment"),
            (("rerun_artifacts", 0), "cycle.rerun_artifacts[0]"),
            (("report_candidate",), "cycle.report_candidate"),
        )
        for path, error_path in cases:
            with self.subTest(path=error_path):
                cycle = make_populated_cycle()
                nested_value(cycle, path)["extra"] = "hidden"
                if path[0] == "intake":
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"{re.escape(error_path)} unknown field.*extra",
                )

    def test_nested_objects_and_lists_reject_wrong_container_types(self):
        cases = (
            (("intake",), [], "cycle.intake must be an object"),
            (
                ("intake", "base_revision"),
                [],
                "cycle.intake.base_revision must be an object",
            ),
            (("intake", "framing"), [], "cycle.intake.framing must be an object"),
            (
                ("intake", "framing", "snapshot"),
                [],
                "cycle.intake.framing.snapshot must be an object",
            ),
            (
                ("intake", "workspace_boundary"),
                [],
                "cycle.intake.workspace_boundary must be an object",
            ),
            (("intake", "triggers"), {}, "cycle.intake.triggers must be a list"),
            (
                ("intake", "selected_claims"),
                {},
                "cycle.intake.selected_claims must be a list",
            ),
            (
                ("intake", "framing", "snapshot", "subject_resolution"),
                [],
                "subject_resolution must be an object",
            ),
            (
                ("intake", "triggers", 0),
                [],
                r"cycle\.intake\.triggers\[0\] must be an object",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs"),
                {},
                "evidence_refs must be a list",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0),
                [],
                r"evidence_refs\[0\] must be an object",
            ),
            (
                ("intake", "selected_claims", 0),
                [],
                r"cycle\.intake\.selected_claims\[0\] must be an object",
            ),
            (
                ("intake", "selected_claims", 0, "source_ref"),
                [],
                "source_ref must be an object",
            ),
            (
                ("intake", "selected_claims", 0, "selection_reasons"),
                {},
                "selection_reasons must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "trigger_ids"),
                {},
                "trigger_ids must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence"),
                {},
                "inherited_evidence must be a list",
            ),
            (
                ("intake", "selected_claims", 0, "inherited_evidence", 0),
                [],
                r"inherited_evidence\[0\] must be an object",
            ),
            (("frontier_bindings",), {}, "cycle.frontier_bindings must be a list"),
            (
                ("frontier_bindings", 0),
                [],
                r"cycle.frontier_bindings\[0\] must be an object",
            ),
            (
                ("frontier_bindings", 0, "claim_ids"),
                {},
                "claim_ids must be a list",
            ),
            (
                ("frontier_bindings", 0, "expected_evidence"),
                {},
                "expected_evidence must be a list",
            ),
            (
                ("claim_resolutions",),
                {},
                "cycle.claim_resolutions must be a list",
            ),
            (("derived_claims",), {}, "cycle.derived_claims must be a list"),
            (
                ("derived_claims", 0),
                [],
                r"cycle.derived_claims\[0\] must be an object",
            ),
            (
                ("derived_claims", 0, "accepted_from"),
                [],
                "accepted_from must be an object or null",
            ),
            (
                ("derived_claims", 0, "accepted_from", "evidence_refs"),
                {},
                "accepted_from.evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0),
                [],
                r"cycle.claim_resolutions\[0\] must be an object",
            ),
            (
                ("claim_resolutions", 0, "current_evidence_refs"),
                {},
                "current_evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "counter_evidence_refs"),
                {},
                "counter_evidence_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "bound_frontier_ids"),
                {},
                "bound_frontier_ids must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_loop_ids"),
                {},
                "attempted_loop_ids must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs"),
                {},
                "attempted_search_refs must be a list",
            ),
            (
                ("claim_resolutions", 0, "attempted_search_refs", 0),
                [],
                r"attempted_search_refs\[0\] must be an object",
            ),
            (
                ("claim_resolutions", 0, "split_child_ids"),
                {},
                "split_child_ids must be a list",
            ),
            (
                ("decision_assessment",),
                [],
                "cycle.decision_assessment must be an object or null",
            ),
            (
                ("decision_assessment", "supporting_claim_ids"),
                {},
                "supporting_claim_ids must be a list",
            ),
            (
                ("decision_assessment", "blocked_claim_ids"),
                {},
                "blocked_claim_ids must be a list",
            ),
            (
                ("decision_assessment", "required_reruns"),
                {},
                "required_reruns must be a list",
            ),
            (("rerun_artifacts",), {}, "cycle.rerun_artifacts must be a list"),
            (
                ("rerun_artifacts", 0),
                [],
                r"cycle.rerun_artifacts\[0\] must be an object",
            ),
            (
                ("report_candidate",),
                [],
                "cycle.report_candidate must be an object or null",
            ),
            (("audit",), {}, "cycle.audit must be a list"),
        )
        for path, replacement, pattern in cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, replacement)
                if path[0] == "intake":
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_intake_foundation_scalars_are_strict(self):
        cases = [
            (
                ("intake", "base_revision", "revision_id"),
                "REV-1",
                "base_revision.revision_id must match REV-NNNN",
            ),
            (
                ("intake", "base_revision", "report_path"),
                "reports/bad\n.md",
                "base_revision.report_path must not contain control characters",
            ),
            (
                ("intake", "base_revision", "report_sha256"),
                "A" * 64,
                "base_revision.report_sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "base_revision", "action_class"),
                "Buy",
                "base_revision.action_class is unsupported",
            ),
            (
                ("intake", "framing", "path"),
                "other.json",
                "cycle.intake.framing.path must be framing_contract.json",
            ),
            (
                ("intake", "framing", "sha256"),
                "bad",
                "cycle.intake.framing.sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "workspace_boundary", "frontier_registry_sha256"),
                "bad",
                "frontier_registry_sha256 must be a lowercase SHA-256",
            ),
            (
                ("intake", "workspace_boundary", "max_existing_loop_number"),
                True,
                "max_existing_loop_number must be an integer >= 0",
            ),
        ]
        snapshot_fields = (
            "research_posture",
            "time_horizon",
            "market_scope",
            "risk_appetite",
            "output_expectation",
            "report_language",
            "budget_appetite",
        )
        cases.extend(
            (
                ("intake", "framing", "snapshot", field),
                "",
                rf"{field} must be non-empty text",
            )
            for field in snapshot_fields
        )
        for path, replacement, pattern in cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        cycle = make_populated_cycle()
        cycle["intake_sha256"] = "A" * 64
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle.intake_sha256 must be a lowercase SHA-256",
        )

    def test_triggers_and_evidence_refs_enforce_ids_vocab_and_timestamps(self):
        intake_cases = (
            (
                ("intake", "triggers", 0, "trigger_id"),
                "RC-0001-TRG-1",
                "trigger_id must match RC-NNNN-TRG-NN",
            ),
            (
                ("intake", "triggers", 0, "trigger_id"),
                "RC-0002-TRG-01",
                "trigger_id must belong to cycle RC-0001",
            ),
            (
                ("intake", "triggers", 0, "kind"),
                "neutral",
                "trigger kind is unsupported",
            ),
            (
                ("intake", "triggers", 0, "statement"),
                "",
                "trigger.*statement must be non-empty text",
            ),
            (
                ("intake", "triggers", 0, "observed_at"),
                "2026-02-30",
                "observed_at must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "kind"),
                "url",
                r"evidence_refs\[0\]\.kind must be source or artifact",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "source_id"),
                "src-001\n",
                "source_id must match src-NNN",
            ),
            (
                ("intake", "triggers", 0, "evidence_refs", 0, "checked_at"),
                "2026-07-15",
                "checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for path, replacement, pattern in intake_cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_selected_claim_scalars_use_locked_ids_and_vocabularies(self):
        cases = (
            (
                ("claim_id",),
                "RC-0001-CL-1",
                "claim_id must match RC-NNNN-CL-NN",
            ),
            (
                ("claim_id",),
                "RC-0002-CL-01",
                "claim_id must belong to cycle RC-0001",
            ),
            (("statement",), "", "selected_claims.*statement must be non-empty text"),
            (("source_ref", "path"), "", "source_ref.path must be non-empty text"),
            (
                ("source_ref", "sha256"),
                "bad",
                "source_ref.sha256 must be a lowercase SHA-256",
            ),
            (
                ("source_ref", "locator"),
                "",
                "source_ref.locator must be non-empty text",
            ),
            (
                ("source_ref", "historical_claim_id"),
                "",
                "historical_claim_id must be non-empty text or null",
            ),
            (("importance",), "urgent", "claim importance is unsupported"),
            (
                ("selection_reasons", 0),
                "manual",
                "selection reason is unsupported",
            ),
            (
                ("trigger_ids", 0),
                "RC-0002-TRG-01",
                "trigger_ids.*must belong to cycle RC-0001",
            ),
            (("inherited_grade",), "E", "inherited_grade is unsupported"),
            (
                ("inherited_confidence",),
                "certain",
                "inherited_confidence is unsupported",
            ),
            (
                ("inherited_evidence", 0, "freshness"),
                "expired",
                "freshness is unsupported",
            ),
            (
                ("inherited_evidence", 0, "checked_at"),
                "2026-07-15",
                "inherited_evidence.*checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                ("inherited_evidence", 0, "reason"),
                "",
                "inherited_evidence.*reason must be non-empty text",
            ),
        )
        for relative_path, replacement, pattern in cases:
            with self.subTest(path=relative_path):
                cycle = make_populated_cycle()
                path = ("intake", "selected_claims", 0, *relative_path)
                set_nested_value(cycle, path, replacement)
                cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_frontier_binding_scalars_are_strict_and_same_cycle(self):
        cases = (
            ("frontier_id", "", "frontier_id must be non-empty text"),
            ("action", "", "frontier_bindings.*action must be non-empty text"),
            (
                "claim_ids",
                ["RC-0002-CL-01"],
                "claim_ids must belong to cycle RC-0001",
            ),
            (
                "expected_evidence",
                [""],
                "expected_evidence.*must be non-empty text",
            ),
            (
                "baseline_loop_count",
                True,
                "baseline_loop_count must be an integer >= 0",
            ),
            (
                "baseline_review_count",
                True,
                "baseline_review_count must be an integer >= 0",
            ),
            (
                "registry_sha256",
                "bad",
                "registry_sha256 must be a lowercase SHA-256",
            ),
            (
                "bound_at",
                "2026-07-15",
                "bound_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["frontier_bindings"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_derived_claim_scalars_and_parent_reference_are_strict(self):
        cases = (
            ("claim_id", "RC-0001-DC-1", "claim_id must match RC-NNNN-DC-NN"),
            (
                "claim_id",
                "RC-0002-DC-01",
                "claim_id must belong to cycle RC-0001",
            ),
            ("origin", "", "derived_claims.*origin must be non-empty text"),
            ("statement", "", "derived_claims.*statement must be non-empty text"),
            (
                "derived_from",
                "RC-0001-CL-99",
                "derived_from must reference a known same-cycle claim ID",
            ),
            (
                "acceptance_rationale",
                "",
                "acceptance_rationale must be non-empty text",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        for field in ("loop_id", "dispatch_id"):
            with self.subTest(accepted_from=field):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0]["accepted_from"][field] = ""
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"accepted_from\.{field} must be non-empty text",
                )

    def test_missing_derived_claim_id_uses_the_public_contract_error(self):
        cycle = make_populated_cycle()
        del cycle["derived_claims"][0]["claim_id"]

        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle\.derived_claims\[0\] missing field\(s\): claim_id",
        )

    def test_malformed_derived_claim_id_containers_use_the_public_error(self):
        for malformed_id in ([], {}):
            with self.subTest(malformed_id=malformed_id):
                cycle = make_populated_cycle()
                cycle["derived_claims"][0]["claim_id"] = malformed_id

                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    r"cycle\.derived_claims\[0\]\.claim_id must match RC-NNNN-DC-NN",
                )

    def test_free_text_rejects_unicode_c1_controls(self):
        cases = (
            (
                ("derived_claims", 0, "statement"),
                r"cycle\.derived_claims\[0\]\.statement must not contain control characters",
            ),
            (
                ("claim_resolutions", 0, "rationale"),
                r"cycle\.claim_resolutions\[0\]\.rationale must not contain control characters",
            ),
        )
        for path, pattern in cases:
            with self.subTest(path=path):
                cycle = make_populated_cycle()
                set_nested_value(cycle, path, "plain\u0085text")

                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        ordinary_unicode = make_populated_cycle()
        ordinary_unicode["derived_claims"][0]["statement"] = "普通文本 café — Δ"
        ordinary_unicode["claim_resolutions"][0]["rationale"] = "证据审阅完成"
        self.assertIs(
            ordinary_unicode,
            revisit_contract.validate_cycle(ordinary_unicode),
        )

    def test_claim_resolution_scalars_and_references_are_strict(self):
        cases = (
            ("claim_id", "bad", "claim_id must match RC-NNNN-CL-NN or RC-NNNN-DC-NN"),
            (
                "claim_id",
                "RC-0002-CL-01",
                "claim_id must belong to cycle RC-0001",
            ),
            (
                "claim_id",
                "RC-0001-CL-99",
                "claim_id must reference a known same-cycle claim",
            ),
            ("status", "open", "claim resolution status is unsupported"),
            (
                "revised_statement",
                [],
                "revised_statement must be non-empty text or null",
            ),
            ("rationale", [], "rationale must be non-empty text or null"),
            ("missing_proof", [], "missing_proof must be non-empty text or null"),
            (
                "verdict_impact",
                [],
                "verdict_impact must be non-empty text or null",
            ),
            ("current_grade", "E", "current_grade is unsupported"),
            (
                "current_confidence",
                "certain",
                "current_confidence is unsupported",
            ),
            (
                "bound_frontier_ids",
                [""],
                "bound_frontier_ids must contain non-empty text",
            ),
            (
                "attempted_loop_ids",
                [""],
                "attempted_loop_ids must contain non-empty text",
            ),
            (
                "split_child_ids",
                ["RC-0002-DC-01"],
                "split_child_ids must belong to cycle RC-0001",
            ),
        )
        for field, replacement, pattern in cases:
            with self.subTest(field=field):
                cycle = make_populated_cycle()
                cycle["claim_resolutions"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        for field in ("loop_id", "query"):
            with self.subTest(attempted_search=field):
                cycle = make_populated_cycle()
                cycle["claim_resolutions"][0]["attempted_search_refs"][0][field] = ""
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle),
                    rf"attempted_search_refs.*{field} must be non-empty text",
                )

    def test_decision_rerun_and_report_candidate_scalars_are_strict(self):
        decision_cases = (
            ("new_action_class", "Buy", "new_action_class is unsupported"),
            (
                "financial_bridge_affected",
                1,
                "financial_bridge_affected must be a boolean",
            ),
            (
                "financial_bridge_rationale",
                [],
                "financial_bridge_rationale must be non-empty text or null",
            ),
            ("risk_class_changed", 0, "risk_class_changed must be a boolean"),
            (
                "risk_class_rationale",
                [],
                "risk_class_rationale must be non-empty text or null",
            ),
            (
                "supporting_claim_ids",
                ["RC-0002-CL-01"],
                "supporting_claim_ids must belong to cycle RC-0001",
            ),
            ("verdict_rationale", "", "verdict_rationale must be non-empty text"),
            (
                "blocked_claim_ids",
                ["bad"],
                "blocked_claim_ids must match RC-NNNN-CL-NN or RC-NNNN-DC-NN",
            ),
            ("change_class", "none", "change_class is unsupported"),
            (
                "required_reruns",
                ["all"],
                "required_reruns entry is unsupported",
            ),
        )
        for field, replacement, pattern in decision_cases:
            with self.subTest(decision_field=field):
                cycle = make_populated_cycle()
                cycle["decision_assessment"][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_ids_and_required_reruns_are_unique_within_arrays(self):
        cases = (
            (
                "triggers",
                lambda cycle: cycle["intake"]["triggers"].append(
                    copy.deepcopy(cycle["intake"]["triggers"][0])
                ),
                "cycle.intake.triggers contains duplicate trigger_id",
                True,
            ),
            (
                "selected_claims",
                lambda cycle: cycle["intake"]["selected_claims"].append(
                    copy.deepcopy(cycle["intake"]["selected_claims"][0])
                ),
                "cycle.intake.selected_claims contains duplicate claim_id",
                True,
            ),
            (
                "selected_trigger_ids",
                lambda cycle: cycle["intake"]["selected_claims"][0][
                    "trigger_ids"
                ].append("RC-0001-TRG-01"),
                "trigger_ids must not contain duplicate IDs",
                True,
            ),
            (
                "bindings",
                lambda cycle: cycle["frontier_bindings"].append(
                    copy.deepcopy(cycle["frontier_bindings"][0])
                ),
                "cycle.frontier_bindings contains duplicate frontier_id",
                False,
            ),
            (
                "binding_claim_ids",
                lambda cycle: cycle["frontier_bindings"][0]["claim_ids"].append(
                    "RC-0001-CL-01"
                ),
                "frontier_bindings.*claim_ids must not contain duplicate IDs",
                False,
            ),
            (
                "derived_claims",
                lambda cycle: cycle["derived_claims"].append(
                    copy.deepcopy(cycle["derived_claims"][0])
                ),
                "cycle.derived_claims contains duplicate claim_id",
                False,
            ),
            (
                "claim_resolutions",
                lambda cycle: cycle["claim_resolutions"].append(
                    copy.deepcopy(cycle["claim_resolutions"][0])
                ),
                "cycle.claim_resolutions contains duplicate claim_id",
                False,
            ),
            (
                "bound_frontier_ids",
                lambda cycle: cycle["claim_resolutions"][0][
                    "bound_frontier_ids"
                ].append("frontier-001"),
                "bound_frontier_ids must not contain duplicate IDs",
                False,
            ),
            (
                "attempted_loop_ids",
                lambda cycle: cycle["claim_resolutions"][0][
                    "attempted_loop_ids"
                ].append("loop-001"),
                "attempted_loop_ids must not contain duplicate IDs",
                False,
            ),
            (
                "split_child_ids",
                lambda cycle: cycle["claim_resolutions"][0].update(
                    {
                        "split_child_ids": [
                            "RC-0001-DC-01",
                            "RC-0001-DC-01",
                        ]
                    }
                ),
                "split_child_ids must not contain duplicate IDs",
                False,
            ),
            (
                "supporting_claim_ids",
                lambda cycle: cycle["decision_assessment"][
                    "supporting_claim_ids"
                ].append("RC-0001-CL-01"),
                "supporting_claim_ids must not contain duplicate IDs",
                False,
            ),
            (
                "required_reruns",
                lambda cycle: cycle["decision_assessment"]["required_reruns"].append(
                    "delta-frontier-review"
                ),
                "required_reruns must not contain duplicates",
                False,
            ),
        )
        for name, mutate, pattern, intake_changed in cases:
            with self.subTest(case=name):
                cycle = make_populated_cycle()
                mutate(cycle)
                if intake_changed:
                    cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

    def test_audit_rows_enforce_sequence_hash_chain_and_current_state(self):
        cases = (
            (
                "sequence_bool",
                lambda cycle: cycle["audit"][0].update({"sequence": True}),
                r"audit\[0\].sequence must be an integer >= 1",
            ),
            (
                "sequence_gap",
                lambda cycle: cycle["audit"][0].update({"sequence": 2}),
                "audit sequence must be continuous starting at 1",
            ),
            (
                "timestamp",
                lambda cycle: cycle["audit"][0].update({"timestamp": "2026-07-15"}),
                r"audit\[0\].timestamp must be YYYY-MM-DDTHH:MM:SSZ",
            ),
            (
                "command",
                lambda cycle: cycle["audit"][0].update({"command": ""}),
                r"audit\[0\].command must be non-empty text",
            ),
            (
                "affected_id_text",
                lambda cycle: cycle["audit"][0].update({"affected_ids": [""]}),
                "affected_ids must contain non-empty text",
            ),
            (
                "affected_id_unique",
                lambda cycle: cycle["audit"][0].update(
                    {"affected_ids": ["RC-0001", "RC-0001"]}
                ),
                "affected_ids must not contain duplicate IDs",
            ),
            (
                "pre_hash",
                lambda cycle: cycle["audit"][0].update({"pre_state_sha256": "bad"}),
                "pre_state_sha256 must be a lowercase SHA-256",
            ),
            (
                "post_hash",
                lambda cycle: cycle["audit"][0].update({"post_state_sha256": "bad"}),
                "post_state_sha256 must be a lowercase SHA-256",
            ),
            (
                "current_state",
                lambda cycle: cycle["audit"][0].update(
                    {"post_state_sha256": "1" * 64}
                ),
                "last audit post_state_sha256 does not match current state",
            ),
        )
        for name, mutate, pattern in cases:
            with self.subTest(case=name):
                cycle = attach_valid_audit(make_populated_cycle())
                mutate(cycle)
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        cycle = make_populated_cycle()
        state_hash = test_semantic_sha256(
            {key: value for key, value in cycle.items() if key != "audit"}
        )
        cycle["audit"] = [
            {
                "sequence": 1,
                "timestamp": "2026-07-15T00:45:00Z",
                "command": "revisit-start",
                "affected_ids": ["RC-0001"],
                "pre_state_sha256": "0" * 64,
                "post_state_sha256": "1" * 64,
            },
            {
                "sequence": 2,
                "timestamp": "2026-07-15T00:46:00Z",
                "command": "revisit-update",
                "affected_ids": ["RC-0001-CL-01"],
                "pre_state_sha256": "2" * 64,
                "post_state_sha256": state_hash,
            },
        ]
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "audit pre/post hash continuity is broken",
        )

    def test_audit_rows_have_exact_keys(self):
        cycle = attach_valid_audit(make_populated_cycle())
        cycle["audit"][0]["extra"] = "hidden"
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            r"cycle.audit\[0\] unknown field.*extra",
        )

    def test_locked_public_surface_and_constants_are_exact(self):
        expected_names = {
            "SCHEMA_VERSION",
            "POINTER_FILENAME",
            "CYCLES_DIRNAME",
            "ACTION_CLASSES",
            "CYCLE_STATUSES",
            "TERMINAL_CYCLE_STATUSES",
            "TRIGGER_KINDS",
            "SELECTION_REASONS",
            "CLAIM_IMPORTANCE",
            "CLAIM_TERMINAL_STATES",
            "CURRENT_GRADES",
            "CURRENT_CONFIDENCE",
            "FRESHNESS",
            "CYCLE_ID_RE",
            "REVISION_ID_RE",
            "TRIGGER_ID_RE",
            "CLAIM_ID_RE",
            "DERIVED_CLAIM_ID_RE",
            "SHA256_RE",
            "CYCLE_KEYS",
            "RevisitIssue",
            "RevisitContractError",
            "SOURCE_EVIDENCE_KEYS",
            "ARTIFACT_EVIDENCE_KEYS",
            "validate_evidence_ref",
            "validate_intake_request",
            "allocate_cycle_and_revision_ids",
            "create_cycle",
            "empty_pointer",
            "validate_pointer",
            "canonical_semantic_bytes",
            "canonical_value_bytes",
            "canonical_document_bytes",
            "sha256_bytes",
            "sha256_file",
            "pointer_path",
            "cycle_directory",
            "cycle_json_path",
            "cycle_markdown_path",
            "load_pointer",
            "load_cycle",
            "list_cycle_ids",
            "persist_pointer",
            "persist_cycle",
            "RevisitPersistenceRollbackError",
            "render_cycle_markdown",
            "semantic_sha256",
            "state_without_audit",
            "cycle_state_sha256",
            "intake_sha256",
            "validate_cycle",
            "normalize_workspace_relative_path",
            "resolve_workspace_path",
        }
        self.assertEqual(expected_names, set(revisit_contract.__all__))
        expected_values = {
            "SCHEMA_VERSION": 1,
            "POINTER_FILENAME": "revisit_contract.json",
            "CYCLES_DIRNAME": "revisit_cycles",
            "CYCLE_STATUSES": ("active", "ready_for_report", "completed", "aborted"),
            "TERMINAL_CYCLE_STATUSES": frozenset({"completed", "aborted"}),
            "TRIGGER_KINDS": ("upgrade", "downgrade", "invalidation"),
            "SELECTION_REASONS": (
                "trigger_affected",
                "decision_load_bearing",
                "stale_but_reused",
            ),
            "CLAIM_IMPORTANCE": ("critical", "high", "medium", "low"),
            "CLAIM_TERMINAL_STATES": (
                "confirmed",
                "weakened",
                "refuted",
                "split",
                "blocked",
            ),
            "CURRENT_GRADES": ("A", "B", "C", "D"),
            "CURRENT_CONFIDENCE": ("high", "medium", "low", "speculative"),
            "FRESHNESS": ("fresh", "stale", "unknown"),
        }
        for name, expected in expected_values.items():
            with self.subTest(constant=name):
                self.assertEqual(expected, getattr(revisit_contract, name, None))

        expected_patterns = {
            "CYCLE_ID_RE": r"^RC-(?P<number>[0-9]{4})$",
            "REVISION_ID_RE": r"^REV-(?P<number>[0-9]{4})$",
            "TRIGGER_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-TRG-(?P<number>[0-9]{2})$",
            "CLAIM_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-CL-(?P<number>[0-9]{2})$",
            "DERIVED_CLAIM_ID_RE": r"^(?P<cycle>RC-[0-9]{4})-DC-(?P<number>[0-9]{2})$",
            "SHA256_RE": r"^[0-9a-f]{64}$",
        }
        for name, expected in expected_patterns.items():
            with self.subTest(regex=name):
                pattern = getattr(revisit_contract, name, None)
                self.assertEqual(expected, getattr(pattern, "pattern", None))

    def test_revisit_issue_is_a_frozen_value_object(self):
        issue_type = getattr(revisit_contract, "RevisitIssue", None)
        self.assertTrue(dataclasses.is_dataclass(issue_type), "RevisitIssue is missing")
        issue = issue_type("bad_state", "cycle.status", "Unsupported", "open")
        self.assertEqual(
            ("bad_state", "cycle.status", "Unsupported", "open"),
            (issue.code, issue.path, issue.message, issue.evidence),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            issue.code = "changed"

    def test_cycle_state_hash_changes_for_every_non_audit_top_level_field(self):
        cycle = make_populated_cycle()
        baseline = revisit_contract.cycle_state_sha256(cycle)

        audit_changed = copy.deepcopy(cycle)
        audit_changed["audit"] = [{"anything": "is excluded"}]
        self.assertEqual(baseline, revisit_contract.cycle_state_sha256(audit_changed))

        for field in revisit_contract.CYCLE_KEYS - {"audit"}:
            with self.subTest(field=field):
                changed = copy.deepcopy(cycle)
                changed[field] = {"changed_field": field}
                self.assertNotEqual(
                    baseline,
                    revisit_contract.cycle_state_sha256(changed),
                )

    def test_valid_skeleton_populated_terminal_and_audited_cycles_are_non_mutating(self):
        cycles = [make_minimal_cycle(), make_populated_cycle()]

        ready = make_minimal_cycle()
        ready["status"] = "ready_for_report"
        cycles.append(ready)

        completed = make_populated_cycle()
        completed["status"] = "completed"
        completed["completed_at"] = "2026-07-15T02:00:00Z"
        cycles.append(completed)

        aborted = make_minimal_cycle()
        aborted["status"] = "aborted"
        aborted["aborted_at"] = "2026-07-15T02:00:00Z"
        aborted["abort_reason"] = "Primary evidence became unavailable."
        cycles.append(aborted)

        cycles.append(attach_valid_audit(make_populated_cycle()))

        for cycle in cycles:
            with self.subTest(status=cycle["status"], audited=bool(cycle["audit"])):
                original = copy.deepcopy(cycle)
                self.assertIs(cycle, revisit_contract.validate_cycle(cycle))
                self.assertEqual(original, cycle)

    def test_locked_nullable_values_and_trigger_timestamp_variant_are_valid(self):
        cycle = make_populated_cycle()
        resolution = cycle["claim_resolutions"][0]
        for field in (
            "revised_statement",
            "rationale",
            "missing_proof",
            "verdict_impact",
            "current_grade",
            "current_confidence",
        ):
            resolution[field] = None
        cycle["derived_claims"][0]["derived_from"] = None
        cycle["derived_claims"][0]["accepted_from"] = None
        cycle["decision_assessment"] = None
        cycle["rerun_artifacts"][0]["scope"] = None
        cycle["rerun_artifacts"][0]["round"] = None
        cycle["report_candidate"] = None
        cycle["intake"]["triggers"][0]["observed_at"] = "2026-07-15T00:30:00Z"
        cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])

        self.assertIs(cycle, revisit_contract.validate_cycle(cycle))

    def test_cycle_missing_required_field_is_rejected(self):
        cycle = make_minimal_cycle()
        del cycle["audit"]
        self.assert_contract_error(
            lambda: revisit_contract.validate_cycle(cycle),
            "cycle missing field.*audit",
        )

        rerun_cases = (
            ("kind", "", "rerun_artifacts.*kind must be non-empty text"),
            ("scope", "partial", "rerun_artifacts.*scope is unsupported"),
            ("round", True, "rerun_artifacts.*round must be an integer >= 1"),
            ("path", "", "rerun_artifacts.*path must be non-empty text"),
            ("sha256", "bad", "rerun_artifacts.*sha256 must be a lowercase"),
            (
                "recorded_at",
                "2026-07-15",
                "rerun_artifacts.*recorded_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in rerun_cases:
            with self.subTest(rerun_field=field):
                cycle = make_populated_cycle()
                cycle["rerun_artifacts"][0][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        candidate_cases = (
            ("revision_id", "REV-1", "report_candidate.revision_id must match REV-NNNN"),
            ("revision_of", "REV-1", "report_candidate.revision_of must match REV-NNNN"),
            ("report_path", "", "report_candidate.report_path must be non-empty text"),
            (
                "report_sha256",
                "bad",
                "report_candidate.report_sha256 must be a lowercase SHA-256",
            ),
            (
                "registered_at",
                "2026-07-15",
                "report_candidate.registered_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in candidate_cases:
            with self.subTest(candidate_field=field):
                cycle = make_populated_cycle()
                cycle["report_candidate"][field] = replacement
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )

        artifact_cases = (
            ("path", "", "current_evidence_refs.*path must be non-empty text"),
            ("sha256", "bad", "current_evidence_refs.*sha256 must be a lowercase"),
            ("locator", "", "current_evidence_refs.*locator must be non-empty text"),
            (
                "checked_at",
                "2026-07-15",
                "current_evidence_refs.*checked_at must be YYYY-MM-DDTHH:MM:SSZ",
            ),
        )
        for field, replacement, pattern in artifact_cases:
            with self.subTest(artifact_field=field):
                cycle = make_populated_cycle()
                cycle["claim_resolutions"][0]["current_evidence_refs"][0][field] = (
                    replacement
                )
                self.assert_contract_error(
                    lambda: revisit_contract.validate_cycle(cycle), pattern
                )
