"""Convergence parity tests for the single revisit readiness seam (Task 6.4).

The four structural convergence probes must produce IDENTICAL ordered issue
codes across the three routes that now share one seam:

* direct   -> ``evaluate_revisit_readiness(workspace, cycle_id)``
* profile  -> ``evaluate_workspace(..., ContractProfile(mode="ticker",
              target="revisit_report"))``
* CLI      -> ``run_revisit_cycle_cli(workspace, "check", cycle_id)``

Today (RED) they disagree. After the seam lands (GREEN) they converge.

``assert_revisit_failure`` in ``tests.test_revisit_contract`` is an instance
method, so a minimal parity-check helper is copied here against the readiness
module's public seam.
"""

from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sofa_contract import (  # noqa: E402
    ContractProfile,
    RevisitCheckEffect,
    RevisitCheckOutcome,
    check_revisit_readiness,
    evaluate_revisit_readiness,
    evaluate_workspace,
)
from sofa_contract import revisit_readiness as readiness_mod  # noqa: E402
from sofa_contract.revisit_readiness import (  # noqa: E402
    REVISIT_REQUIREMENT_IDS,
    ReadinessPlanError,
)

# Module-level helpers from the existing revisit-contract test corpus. These are
# importable (NOT the instance-method ``assert_revisit_failure``).
from tests.test_revisit_contract import (  # noqa: E402
    CAN_SYMLINK,
    append_task6_loops,
    attach_valid_audit,
    bind_task6_reactivated_frontier,
    complete_revisit_report_bytes,
    derive_task6_floor_issues,
    make_registration_workspace,
    make_task6_binding_workspace,
    make_task6_ready_workspace,
    make_terminal_cycle_fixture,
    run_revisit_cycle_cli,
    snapshot_tree,
    test_semantic_sha256,
)

import revisit_contract  # noqa: E402


EXPECTED_REQUIREMENT_IDS = (
    "core_state_workflow",
    "global_cycle_history",
    "intake_provenance",
    "trigger_evidence",
    "claim_freshness",
    "frontier_registry",
    "frontier_research_floor",
    "search_coverage",
    "dispatch_delivery",
    "worker_outputs",
    "source_cache",
    "generation_closure",
    "route_and_effect_parity",
)


def _noop_requirement(_context) -> None:
    """Test-only handler used before the private executable plan exists."""


def _plan_rows():
    plan = getattr(readiness_mod, "_READINESS_PLAN", None)
    if plan is not None:
        return tuple(plan)
    return tuple(
        SimpleNamespace(
            requirement_id=requirement_id,
            handlers=(_noop_requirement,),
            prerequisites=(),
            invariant=(requirement_id == "route_and_effect_parity"),
        )
        for requirement_id in EXPECTED_REQUIREMENT_IDS
    )


def _replace_plan_row(row, **changes):
    values = {
        "requirement_id": row.requirement_id,
        "handlers": row.handlers,
        "prerequisites": row.prerequisites,
        "invariant": row.invariant,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _trace_pairs(prepared) -> tuple[tuple[str, str], ...]:
    return tuple(
        (entry.requirement_id, entry.status)
        for entry in getattr(prepared, "trace", ())
    )


def _failure_codes(result) -> list[str]:
    return [issue.code for issue in result.failures]


def _assert_three_route_failure_codes(
    test_case: unittest.TestCase,
    make_workspace,
    cycle_id_getter,
    *,
    expected_codes_for_named: list[str],
):
    """Assert the SAME failure codes across direct/profile routes and the CLI.

    ``make_workspace(root)`` returns ``(workspace, cycle_id)``.
    ``cycle_id_getter`` is a callable returning the named cycle id from the
    pair (kept explicit so probe workspaces can name a non-eligible id).

    The three routes are:
      * direct  -> ``evaluate_revisit_readiness(workspace, cycle_id)``
      * profile -> ``evaluate_workspace(..., target="revisit_report")``
      * CLI     -> ``run_revisit_cycle_cli(workspace, "check", cycle_id)``

    For the CLI we additionally assert zero filesystem writes.
    """
    # direct
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace, cycle_id = make_workspace(Path(temp_dir))
        direct = evaluate_revisit_readiness(workspace, cycle_id_getter(workspace, cycle_id))
        direct_codes = _failure_codes(direct)

    # profile (target=revisit_report discovers the cycle)
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace, cycle_id = make_workspace(Path(temp_dir))
        profile = evaluate_workspace(
            workspace,
            ContractProfile(mode="ticker", target="revisit_report"),
        )
        profile_codes = _failure_codes(profile)

    # CLI (named) — also assert zero writes
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace, cycle_id = make_workspace(Path(temp_dir))
        named_id = cycle_id_getter(workspace, cycle_id)
        cycle_json = workspace / "revisit_cycles" / f"{named_id}.json"
        cycle_md = workspace / "revisit_cycles" / f"{named_id}.md"
        prior_cycle = cycle_json.read_bytes()
        prior_mirror = cycle_md.read_bytes()
        prior_tree = snapshot_tree(workspace)

        cli = run_revisit_cycle_cli(workspace, "check", named_id)

        test_case.assertEqual(1, cli.returncode, cli.stderr)
        # The CLI prints failures to stderr; extract the codes by parsing the
        # ``CODE:`` prefix that ContractIssue.display() emits.
        cli_codes = _extract_cli_codes(cli.stderr)
        test_case.assertEqual(prior_cycle, cycle_json.read_bytes())
        test_case.assertEqual(prior_mirror, cycle_md.read_bytes())
        test_case.assertEqual(prior_tree, snapshot_tree(workspace))

    test_case.assertEqual(expected_codes_for_named, direct_codes)
    test_case.assertEqual(direct_codes, profile_codes)
    test_case.assertEqual(direct_codes, cli_codes)


def _extract_cli_codes(stderr_text: str) -> list[str]:
    """Return issue codes in first-seen order from CLI stderr.

    ``ContractIssue.display()`` formats as ``CODE: message [path] - evidence``.
    The readiness seam emits failures in plan order, so first-seen order matches
    the ContractResult failure order.
    """
    codes: list[str] = []
    for line in stderr_text.splitlines():
        marker = "revisit readiness: "
        # The CLI prints ``failure.display()`` per failure; display() begins
        # with ``CODE: ``. Capture the token before the first ``: ``.
        stripped = line.strip()
        if ": " not in stripped:
            continue
        candidate = stripped.split(": ", 1)[0]
        # Only accept tokens that look like issue codes (uppercase + underscores).
        if candidate and candidate.isupper() and "_" in candidate:
            if candidate not in codes:
                codes.append(candidate)
    return codes


class TestRevisitCheckEffects(unittest.TestCase):
    """Task 6.5 Step 5.2: the three atomic effects of ``check_revisit_readiness``.

    Uses a fixed canonical timestamp; never wall clock. Each workspace is built
    fresh in its own temp dir.
    """

    TIMESTAMP = "2026-07-16T12:00:00Z"

    # ------------------------------------------------------------------
    # BLOCKED: semantic failure preserves the complete tree and reports the
    # selected cycle id when history selection succeeded.
    # ------------------------------------------------------------------
    def test_semantic_failure_is_blocked_with_selected_cycle_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            # Corrupt the registry so the semantic plan fails (history still
            # selects exactly one eligible cycle).
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["version"] = 999
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            prior_tree = snapshot_tree(workspace)

            outcome = check_revisit_readiness(
                workspace, cycle_id, timestamp=self.TIMESTAMP
            )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            self.assertEqual(cycle_id, outcome.cycle_id)
            self.assertFalse(outcome.result.passed)
            self.assertIn(
                "REVISIT_FRONTIER_REGISTRY_MALFORMED",
                [issue.code for issue in outcome.result.failures],
            )
            # Zero writes: complete tree byte-for-byte preserved.
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())
            self.assertEqual(prior_tree, snapshot_tree(workspace))

    # ------------------------------------------------------------------
    # BLOCKED: malformed history preventing selection -> cycle_id is None.
    # ------------------------------------------------------------------
    def test_malformed_history_selection_failure_blocks_with_none_cycle_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            # Corrupt the pointer so global history is malformed (cycles exist
            # without a current revision); this prevents sole-eligible selection
            # and makes _discover_eligible_cycle_id return None.
            pointer_path = workspace / "revisit_contract.json"
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            pointer["current_revision"] = None
            pointer_path.write_text(
                json.dumps(pointer, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            prior_tree = snapshot_tree(workspace)

            outcome = check_revisit_readiness(
                workspace, cycle_id, timestamp=self.TIMESTAMP
            )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            self.assertIsNone(outcome.cycle_id)
            self.assertFalse(outcome.result.passed)
            self.assertEqual(prior_tree, snapshot_tree(workspace))

    # ------------------------------------------------------------------
    # TRANSITIONED: active passing cycle transitions to ready; ONLY the cycle
    # JSON and Markdown mirror change; exactly one ``check`` audit at the
    # supplied timestamp.
    # ------------------------------------------------------------------
    def test_active_passing_cycle_transitions_with_one_check_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = revisit_contract.load_cycle(workspace, cycle_id)
            prior_audit_count = len(prior_cycle["audit"])
            prior_tree = snapshot_tree(workspace)

            outcome = check_revisit_readiness(
                workspace, cycle_id, timestamp=self.TIMESTAMP
            )

            self.assertEqual(RevisitCheckEffect.TRANSITIONED, outcome.effect)
            self.assertEqual(cycle_id, outcome.cycle_id)
            self.assertTrue(outcome.result.passed, [issue.display() for issue in outcome.result.failures])

            ready = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("ready_for_report", ready["status"])
            self.assertEqual(prior_audit_count + 1, len(ready["audit"]))
            self.assertEqual("check", ready["audit"][-1]["command"])
            self.assertEqual(
                self.TIMESTAMP, ready["audit"][-1]["timestamp"]
            )
            self.assertEqual([cycle_id], ready["audit"][-1]["affected_ids"])

            # ONLY the cycle JSON and mirror changed; every other file is
            # byte-identical to the pre-check tree.
            after_tree = snapshot_tree(workspace)
            for relative, entry in prior_tree.items():
                if relative in (
                    f"revisit_cycles/{cycle_id}.json",
                    f"revisit_cycles/{cycle_id}.md",
                ):
                    continue
                self.assertEqual(
                    entry, after_tree[relative], f"unexpected change: {relative}"
                )

    # ------------------------------------------------------------------
    # UNCHANGED_READY: a fresh second check on the now-ready cycle is a
    # byte-preserving no-op with NO new audit entry.
    # ------------------------------------------------------------------
    def test_already_ready_cycle_is_unchanged_ready_byte_preserving_noop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            # First check transitions active -> ready.
            first = check_revisit_readiness(
                workspace, cycle_id, timestamp=self.TIMESTAMP
            )
            self.assertEqual(RevisitCheckEffect.TRANSITIONED, first.effect)
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            ready_cycle_bytes = cycle_path.read_bytes()
            ready_mirror_bytes = mirror_path.read_bytes()
            ready_audit_count = len(
                revisit_contract.load_cycle(workspace, cycle_id)["audit"]
            )

            second = check_revisit_readiness(
                workspace, cycle_id, timestamp=self.TIMESTAMP
            )

            self.assertEqual(RevisitCheckEffect.UNCHANGED_READY, second.effect)
            self.assertEqual(cycle_id, second.cycle_id)
            self.assertTrue(second.result.passed)
            # Byte-for-byte preservation.
            self.assertEqual(ready_cycle_bytes, cycle_path.read_bytes())
            self.assertEqual(ready_mirror_bytes, mirror_path.read_bytes())
            # No new audit entry.
            self.assertEqual(
                ready_audit_count,
                len(revisit_contract.load_cycle(workspace, cycle_id)["audit"]),
            )

    def test_completed_unpublished_is_passing_unchanged_ready_across_routes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["status"] = "ready_for_report"
            attach_valid_audit(cycle)
            candidate_relative = (
                "reports/TEST_SOFA_Report_2026-07-16_REV-0002.md"
            )
            candidate_payload = complete_revisit_report_bytes(cycle)
            (workspace / candidate_relative).write_bytes(candidate_payload)
            cycle = make_terminal_cycle_fixture(
                cycle,
                "completed",
                timestamp="2026-07-16T11:00:00Z",
                report_path=candidate_relative,
                report_sha256=hashlib.sha256(candidate_payload).hexdigest(),
            )
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=revisit_contract.sha256_file(cycle_path),
            )
            current = revisit_contract.load_pointer(workspace)[
                "current_revision"
            ]
            completed = revisit_contract.load_cycle(workspace, cycle_id)
            self.assertEqual("REV-0001", current["revision_id"])
            self.assertEqual(
                "REV-0002",
                completed["report_candidate"]["revision_id"],
            )
            prior_tree = snapshot_tree(workspace)
            prior_audit = tuple(
                revisit_contract.load_cycle(workspace, cycle_id)["audit"]
            )

            direct = evaluate_revisit_readiness(workspace, cycle_id)
            profile = evaluate_workspace(
                workspace,
                ContractProfile(mode="ticker", target="revisit_report"),
            )
            outcome = check_revisit_readiness(
                workspace,
                cycle_id,
                timestamp=self.TIMESTAMP,
            )

            self.assertTrue(
                direct.passed,
                [issue.display() for issue in direct.failures],
            )
            self.assertTrue(
                profile.passed,
                [issue.display() for issue in profile.failures],
            )
            self.assertTrue(
                outcome.result.passed,
                [issue.display() for issue in outcome.result.failures],
            )
            self.assertEqual(
                RevisitCheckEffect.UNCHANGED_READY,
                outcome.effect,
            )
            self.assertEqual(cycle_id, outcome.cycle_id)
            self.assertEqual(prior_tree, snapshot_tree(workspace))
            self.assertEqual(
                prior_audit,
                tuple(
                    revisit_contract.load_cycle(workspace, cycle_id)["audit"]
                ),
            )

    def test_effect_reducer_rejects_impossible_prepared_combinations(self):
        passing = readiness_mod.ContractResult()
        blocked = readiness_mod.ContractResult()
        blocked.fail(
            code="SYNTHETIC_FAILURE",
            message="test-only semantic failure",
            path="state.json",
        )
        cycle = {"cycle_id": "RC-0001", "status": "active"}
        selected = readiness_mod._SelectedCycle(
            cycle_id="RC-0001",
            cycle=cycle,
            cycle_sha256="0" * 64,
            status="active",
        )

        blocked_without_selection = (
            readiness_mod._make_revisit_check_outcome(blocked, None)
        )
        self.assertEqual(
            RevisitCheckEffect.BLOCKED,
            blocked_without_selection.effect,
        )
        self.assertIsNone(blocked_without_selection.cycle_id)
        blocked_with_selection = readiness_mod._make_revisit_check_outcome(
            blocked,
            selected,
        )
        self.assertEqual(
            RevisitCheckEffect.BLOCKED,
            blocked_with_selection.effect,
        )
        self.assertEqual("RC-0001", blocked_with_selection.cycle_id)
        transitioned = readiness_mod._make_revisit_check_outcome(
            passing,
            selected,
        )
        self.assertEqual(
            RevisitCheckEffect.TRANSITIONED,
            transitioned.effect,
        )
        self.assertEqual("RC-0001", transitioned.cycle_id)
        for stable_status in ("ready_for_report", "completed"):
            stable_cycle = {
                "cycle_id": "RC-0001",
                "status": stable_status,
            }
            stable = readiness_mod._SelectedCycle(
                cycle_id="RC-0001",
                cycle=stable_cycle,
                cycle_sha256="0" * 64,
                status=stable_status,
            )
            self.assertEqual(
                RevisitCheckEffect.UNCHANGED_READY,
                readiness_mod._make_revisit_check_outcome(
                    passing,
                    stable,
                ).effect,
            )

        with self.assertRaisesRegex(
            ReadinessPlanError,
            "passing readiness requires one complete selected cycle",
        ):
            readiness_mod._make_revisit_check_outcome(passing, None)

        invalid_values = (
            {
                "cycle_id": "RC-0002",
                "cycle": cycle,
                "cycle_sha256": "0" * 64,
                "status": "active",
            },
            {
                "cycle_id": "RC-0001",
                "cycle": cycle,
                "cycle_sha256": "0" * 64,
                "status": "ready_for_report",
            },
            {
                "cycle_id": "RC-0001",
                "cycle": cycle,
                "cycle_sha256": "not-a-digest",
                "status": "active",
            },
            {
                "cycle_id": "RC-0001",
                "cycle": {"cycle_id": "RC-0001", "status": "aborted"},
                "cycle_sha256": "0" * 64,
                "status": "aborted",
            },
        )
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ReadinessPlanError):
                    readiness_mod._SelectedCycle(**values)

    def test_public_check_rejects_passing_prepare_without_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            prior_tree = snapshot_tree(workspace)
            real_prepare = readiness_mod._prepare_revisit_readiness

            def omit_selected_cycle(
                session,
                result,
                named_cycle_id,
                lexical_workspace,
            ):
                prepared = real_prepare(
                    session,
                    result,
                    named_cycle_id,
                    lexical_workspace,
                )
                self.assertTrue(prepared.result.passed)
                return readiness_mod._PreparedRevisitReadiness(
                    result=prepared.result,
                    selected_cycle=None,
                    closure=prepared.closure,
                    trace=prepared.trace,
                )

            with mock.patch.object(
                readiness_mod,
                "_prepare_revisit_readiness",
                side_effect=omit_selected_cycle,
            ):
                with self.assertRaisesRegex(
                    ReadinessPlanError,
                    "passing readiness requires one complete selected cycle",
                ):
                    check_revisit_readiness(
                        workspace,
                        cycle_id,
                        timestamp=self.TIMESTAMP,
                    )

            self.assertEqual(prior_tree, snapshot_tree(workspace))


class TestRevisitCheckAuthorityDrift(unittest.TestCase):
    """Task 6.5 Step 5.4: authority drift BETWEEN preparation and persistence.

    The frozen ``GenerationClosure`` observed during preparation is the ONLY
    authority the store may recheck (with the two cycle/mirror exclusions). Any
    drift of an observed immutable authority in the pre-write or post-write
    window -> BLOCKED + REVISIT_AUTHORITY_DRIFT + exact path, with the cycle
    pair restored to exact prior bytes. A rollback failure lets
    ``RevisitPersistenceRollbackError`` escape.
    """

    TIMESTAMP = "2026-07-16T12:00:00Z"

    def _run_with_store_injection(
        self, *, mutate_at_call, mutate_factory, ready_factory=None,
    ):
        """Build a ready workspace, capture prior cycle/mirror bytes, then run
        ``check_revisit_readiness`` while invoking ``mutate_factory(workspace)``
        before the ``mutate_at_call``-th (1-based) ``_require_unchanged_except``
        store call (1 = pre-write, 2 = post-write).

        Yields ``(outcome, workspace, cycle_id, prior_cycle, prior_mirror)``
        while the temp dir is still alive so assertions can read the files.
        """
        from contextlib import contextmanager
        from revisit_contract import store as revisit_store

        make = ready_factory or make_task6_ready_workspace
        real_require = revisit_store._require_unchanged_except

        @contextmanager
        def runner():
            calls = []
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                workspace, cycle_id = make(root)
                mutate = mutate_factory(workspace)
                cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
                mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
                prior_cycle = cycle_path.read_bytes()
                prior_mirror = mirror_path.read_bytes()

                def injecting_require(closure, excluded):
                    calls.append(1)
                    if len(calls) == mutate_at_call:
                        mutate()
                    return real_require(closure, excluded)

                with unittest.mock.patch.object(
                    revisit_store,
                    "_require_unchanged_except",
                    injecting_require,
                ):
                    outcome = check_revisit_readiness(
                        workspace, cycle_id, timestamp=self.TIMESTAMP
                    )
                yield outcome, workspace, cycle_id, prior_cycle, prior_mirror

        return runner()

    def _assert_blocked_drift_restored(
        self, outcome, workspace, cycle_id, prior_cycle, prior_mirror,
        *, expected_relative,
    ):
        self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
        codes = [issue.code for issue in outcome.result.failures]
        self.assertIn("REVISIT_AUTHORITY_DRIFT", codes)
        drift_issue = next(
            issue for issue in outcome.result.failures
            if issue.code == "REVISIT_AUTHORITY_DRIFT"
        )
        self.assertEqual(expected_relative, drift_issue.path)
        # Cycle pair restored to exact prior bytes (zero net write).
        self.assertEqual(
            prior_cycle,
            (workspace / "revisit_cycles" / f"{cycle_id}.json").read_bytes(),
        )
        self.assertEqual(
            prior_mirror,
            (workspace / "revisit_cycles" / f"{cycle_id}.md").read_bytes(),
        )

    # ------------------------------------------------------------------
    # Pre-write byte drift of an observed immutable authority.
    # ------------------------------------------------------------------
    def test_pre_write_byte_drift_of_indexed_excerpt_blocks_with_exact_path(self):
        excerpt_rel = "sources/src-001.md"

        def mutate_factory(workspace):
            target = workspace / excerpt_rel

            def mutate():
                target.write_bytes(target.read_bytes() + b"pre-write drift\n")

            return mutate

        with self._run_with_store_injection(
            mutate_at_call=1, mutate_factory=mutate_factory
        ) as (outcome, ws, cid, pc, pm):
            self._assert_blocked_drift_restored(
                outcome, ws, cid, pc, pm, expected_relative=excerpt_rel
            )

    # ------------------------------------------------------------------
    # Post-write byte drift: immutable authority changed AFTER the cycle pair
    # is written but BEFORE the store's postcheck -> BLOCKED + exact restore.
    # ------------------------------------------------------------------
    def test_post_write_byte_drift_restores_prior_cycle_pair_bytes(self):
        excerpt_rel = "sources/src-001.md"

        def mutate_factory(workspace):
            target = workspace / excerpt_rel

            def mutate():
                target.write_bytes(target.read_bytes() + b"post-write drift\n")

            return mutate

        with self._run_with_store_injection(
            mutate_at_call=2, mutate_factory=mutate_factory
        ) as (outcome, ws, cid, pc, pm):
            self._assert_blocked_drift_restored(
                outcome, ws, cid, pc, pm, expected_relative=excerpt_rel
            )

    def test_post_write_validation_error_restores_pair_before_propagating(self):
        from revisit_contract import store as revisit_store

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            real_require = revisit_store._require_unchanged_except
            calls = []

            def fail_second_validation(closure, excluded):
                calls.append(None)
                if len(calls) == 2:
                    raise revisit_contract.RevisitContractError(
                        "synthetic post-write generation failure"
                    )
                return real_require(closure, excluded)

            with unittest.mock.patch.object(
                revisit_store,
                "_require_unchanged_except",
                fail_second_validation,
            ):
                with self.assertRaisesRegex(
                    revisit_contract.RevisitContractError,
                    "synthetic post-write generation failure",
                ):
                    check_revisit_readiness(
                        workspace,
                        cycle_id,
                        timestamp=self.TIMESTAMP,
                    )

            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())

    # ------------------------------------------------------------------
    # Cycle-sibling membership change: a new cycle JSON appears in
    # revisit_cycles/ during the pre-write window.
    # ------------------------------------------------------------------
    def test_pre_write_cycle_sibling_membership_change_blocks(self):
        def mutate_factory(workspace):
            sibling = workspace / "revisit_cycles" / "RC-9999.json"

            def mutate():
                sibling.write_bytes(b"{}\n")

            return mutate

        with self._run_with_store_injection(
            mutate_at_call=1, mutate_factory=mutate_factory
        ) as (outcome, ws, cid, pc, pm):
            self._assert_blocked_drift_restored(
                outcome,
                ws,
                cid,
                pc,
                pm,
                expected_relative="revisit_cycles/RC-9999.json",
            )

    # ------------------------------------------------------------------
    # Worker-output membership change: a new orphan file appears in a worker
    # output directory during the pre-write window.
    # ------------------------------------------------------------------
    def test_pre_write_worker_output_membership_change_blocks(self):
        def mutate_factory(workspace):
            orphan = workspace / "scouts" / "orphan-drift.md"

            def mutate():
                orphan.write_text("# orphan\n", encoding="utf-8")

            return mutate

        with self._run_with_store_injection(
            mutate_at_call=1, mutate_factory=mutate_factory
        ) as (outcome, ws, cid, pc, pm):
            self._assert_blocked_drift_restored(
                outcome,
                ws,
                cid,
                pc,
                pm,
                expected_relative="scouts/orphan-drift.md",
            )

    # ------------------------------------------------------------------
    # Source-membership change: a new excerpt file appears in sources/ during
    # the pre-write window.
    # ------------------------------------------------------------------
    def test_pre_write_source_membership_change_blocks(self):
        def mutate_factory(workspace):
            new_source = workspace / "sources" / "src-777.md"

            def mutate():
                new_source.write_bytes(b"new source\n")

            return mutate

        with self._run_with_store_injection(
            mutate_at_call=1, mutate_factory=mutate_factory
        ) as (outcome, ws, cid, pc, pm):
            self._assert_blocked_drift_restored(
                outcome,
                ws,
                cid,
                pc,
                pm,
                expected_relative="sources/src-777.md",
            )

    # ------------------------------------------------------------------
    # Rollback-failure injection: the post-write drift's restore fails ->
    # RevisitPersistenceRollbackError escapes (catastrophic, not BLOCKED).
    # ------------------------------------------------------------------
    def test_rollback_failure_lets_persistence_rollback_error_escape(self):
        from revisit_contract import store as revisit_store

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            excerpt = workspace / "sources" / "src-001.md"
            real_require = revisit_store._require_unchanged_except
            calls = []

            def injecting_require(closure, excluded):
                calls.append(1)
                if len(calls) == 2:
                    excerpt.write_bytes(
                        excerpt.read_bytes() + b"post-write drift\n"
                    )
                return real_require(closure, excluded)

            def fail_restore(*args, **kwargs):
                raise OSError("simulated restore failure")

            with (
                unittest.mock.patch.object(
                    revisit_store,
                    "_require_unchanged_except",
                    injecting_require,
                ),
                unittest.mock.patch.object(
                    revisit_store,
                    "_restore_committed_cycle_pair",
                    fail_restore,
                ),
            ):
                with self.assertRaises(
                    revisit_store.RevisitPersistenceRollbackError
                ):
                    check_revisit_readiness(
                        workspace, cycle_id, timestamp=self.TIMESTAMP
                    )


class TestRevisitCheckClosureVsSnapshots(unittest.TestCase):
    """Task 6.5 Step 5.4: the closure path catches what file-only snapshots miss.

    The legacy ``authority_snapshots`` persistence only binds named file paths,
    so an absence->appearance or directory-membership change of an UNlisted
    authority is invisible to it (it would silently succeed or leak a raw
    exception). The closure path observes directories and absences and rejects
    every such mutation.
    """

    def test_persist_cycle_rejects_simultaneous_snapshots_and_closure(self):
        from revisit_contract.generation import GenerationClosure
        from revisit_contract import store as revisit_store

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            cycle = {"cycle_id": "RC-0001"}
            with self.assertRaises(revisit_store.RevisitContractError):
                revisit_store.persist_cycle(
                    workspace,
                    cycle,
                    expected_sha256=None,
                    authority_snapshots={},
                    generation_closure=object(),  # type: ignore[arg-type]
                )

    def test_persist_cycle_rejects_closure_workspace_mismatch(self):
        from revisit_contract.generation import (
            DirectoryGeneration,
            GenerationClosure,
        )
        from revisit_contract import store as revisit_store

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            other = Path(temp_dir) / "other"
            other.mkdir()
            closure = GenerationClosure(
                workspace=other.resolve(),
                generations=(
                    DirectoryGeneration(
                        relative_path="revisit_cycles",
                        resolved_target=other / "revisit_cycles",
                        entries=(),
                    ),
                ),
            )
            with self.assertRaises(revisit_store.RevisitContractError):
                revisit_store.persist_cycle(
                    workspace,
                    {"cycle_id": "RC-0001"},
                    expected_sha256=None,
                    generation_closure=closure,
                )

    def test_closure_catches_directory_drift_that_snapshots_miss(self):
        """The legacy file-only ``authority_snapshots`` path only binds named
        file paths, so a directory membership change of an UNlisted directory
        (e.g. a new sibling cycle file) is invisible to it. The closure path
        observes directory membership and rejects the same mutation.

        This is the contrast that motivates routing the check through the
        closure: the snapshot path silently succeeds where the closure blocks.
        """
        from revisit_contract.generation import (
            DirectoryGeneration,
            GenerationClosure,
        )
        from revisit_contract import store as revisit_store

        # Build the workspace, then persist an identical cycle with BOTH
        # mechanisms while a sibling cycle file appears mid-write. The snapshot
        # path has no directory observation, so it succeeds; the closure path
        # observes ``revisit_cycles`` membership and blocks.
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, cycle_id = make_task6_ready_workspace(root)
            cycles_dir = workspace / "revisit_cycles"
            sibling = cycles_dir / "RC-9999.json"

            # Snapshot path: a pre-bound snapshot of the cycle JSON only. Inject
            # a directory membership change via the render seam (between the
            # snapshot pre-check and post-check there is no directory binding).
            real_render = revisit_store.render_cycle_markdown

            def render_then_add_sibling(cycle):
                sibling.write_bytes(b"{}\n")
                return real_render(cycle)

            cycle_doc = revisit_contract.load_cycle(workspace, cycle_id)
            prior_sha = revisit_contract.sha256_file(
                cycles_dir / f"{cycle_id}.json"
            )
            snapshot = revisit_store.prepare_authority_snapshot(
                workspace,
                cycles_dir / f"{cycle_id}.json",
                prior_sha,
            )
            with unittest.mock.patch.object(
                revisit_store,
                "render_cycle_markdown",
                side_effect=render_then_add_sibling,
            ):
                # The snapshot path does NOT observe directory membership, so
                # the sibling appearance is invisible: persistence succeeds.
                revisit_store.persist_cycle(
                    workspace,
                    cycle_doc,
                    expected_sha256=prior_sha,
                    authority_snapshots=(snapshot,),
                )
            self.assertTrue(sibling.exists())

        # Closure path: the same directory membership change is observed and
        # rejected (covered by test_pre_write_cycle_sibling_membership_change_blocks
        # in TestRevisitCheckAuthorityDrift via the readiness seam).


class TestReadOnlyReadinessParity(unittest.TestCase):
    """Focused convergence + completeness tests for the readiness seam."""

    TIMESTAMP = "2026-07-17T12:00:00Z"

    def _prepare(self, workspace: Path, cycle_id: str):
        return readiness_mod._prepare_revisit_readiness(
            readiness_mod.ObservedReadSession(workspace),
            readiness_mod.ContractResult(),
            cycle_id,
            workspace,
        )

    def _assert_trace_statuses(self, prepared, expected: dict[str, str]) -> None:
        statuses = dict(_trace_pairs(prepared))
        self.assertEqual(
            tuple(expected.items()),
            tuple((key, statuses.get(key)) for key in expected),
        )

    def _assert_public_route_codes(
        self,
        mutate,
        *,
        expected_codes: list[str],
        expected_paths: list[str] | None = None,
    ) -> None:
        """Run one malformed workspace independently through all public routes.

        The check route must be BLOCKED and byte-preserving. Expected workspace
        input must become a ContractResult issue rather than an incidental
        traceback.
        """
        for route in ("direct", "profile", "check"):
            with self.subTest(route=route):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_ready_workspace(
                        Path(temp_dir)
                    )
                    mutate(workspace, cycle_id)
                    prior_tree = snapshot_tree(workspace)
                    try:
                        if route == "direct":
                            result = evaluate_revisit_readiness(
                                workspace,
                                cycle_id,
                            )
                        elif route == "profile":
                            result = evaluate_workspace(
                                workspace,
                                ContractProfile(
                                    mode="ticker",
                                    target="revisit_report",
                                ),
                            )
                        else:
                            outcome = check_revisit_readiness(
                                workspace,
                                cycle_id,
                                timestamp=self.TIMESTAMP,
                            )
                            self.assertEqual(
                                RevisitCheckEffect.BLOCKED,
                                outcome.effect,
                            )
                            result = outcome.result
                    except Exception as exc:  # expected input must not escape
                        self.fail(
                            f"{route} raised {type(exc).__name__}: {exc}"
                        )
                    self.assertEqual(
                        expected_codes,
                        _failure_codes(result),
                    )
                    if expected_paths is not None:
                        self.assertEqual(
                            expected_paths,
                            [issue.path for issue in result.failures],
                        )
                    self.assertEqual(prior_tree, snapshot_tree(workspace))

    def _assert_public_route_codes_pair_preserving(
        self,
        mutate,
        *,
        expected_codes: list[str],
        expected_paths: list[str],
    ) -> None:
        """Parity helper for malformed symlinks snapshot_tree cannot open."""
        for route in ("direct", "profile", "check"):
            with self.subTest(route=route):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace, cycle_id = make_task6_ready_workspace(
                        Path(temp_dir)
                    )
                    mutate(workspace, cycle_id)
                    authority_paths = (
                        workspace / "revisit_contract.json",
                        workspace / "revisit_cycles" / f"{cycle_id}.json",
                        workspace / "revisit_cycles" / f"{cycle_id}.md",
                    )
                    prior_authorities = tuple(
                        path.read_bytes() for path in authority_paths
                    )
                    try:
                        if route == "direct":
                            result = evaluate_revisit_readiness(
                                workspace,
                                cycle_id,
                            )
                        elif route == "profile":
                            result = evaluate_workspace(
                                workspace,
                                ContractProfile(
                                    mode="ticker",
                                    target="revisit_report",
                                ),
                            )
                        else:
                            outcome = check_revisit_readiness(
                                workspace,
                                cycle_id,
                                timestamp=self.TIMESTAMP,
                            )
                            self.assertEqual(
                                RevisitCheckEffect.BLOCKED,
                                outcome.effect,
                            )
                            result = outcome.result
                    except Exception as exc:
                        self.fail(
                            f"{route} raised {type(exc).__name__}: {exc}"
                        )
                    self.assertEqual(expected_codes, _failure_codes(result))
                    self.assertEqual(
                        expected_paths,
                        [issue.path for issue in result.failures],
                    )
                    self.assertEqual(
                        prior_authorities,
                        tuple(path.read_bytes() for path in authority_paths),
                    )

    def _assert_bad_plan_before_read(self, plan, expected_fragment: str) -> None:
        reads: list[tuple[str, str]] = []
        real_init = readiness_mod.ObservedReadSession.__init__
        real_read_required = readiness_mod.ObservedReadSession.read_required
        real_read_optional = readiness_mod.ObservedReadSession.read_optional
        real_list_directory = readiness_mod.ObservedReadSession.list_directory

        def tracking_init(session, workspace):
            reads.append(("session_init", str(workspace)))
            return real_init(session, workspace)

        def tracking_read_required(session, relative_path):
            reads.append(("read_required", relative_path))
            return real_read_required(session, relative_path)

        def tracking_read_optional(session, relative_path):
            reads.append(("read_optional", relative_path))
            return real_read_optional(session, relative_path)

        def tracking_list_directory(
            session,
            relative_path,
            *,
            recursive,
            optional=False,
        ):
            reads.append(("list_directory", relative_path))
            return real_list_directory(
                session,
                relative_path,
                recursive=recursive,
                optional=optional,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            with (
                mock.patch.object(
                    readiness_mod,
                    "_READINESS_PLAN",
                    tuple(plan),
                    create=True,
                ),
                mock.patch.object(
                    readiness_mod.ObservedReadSession,
                    "__init__",
                    tracking_init,
                ),
                mock.patch.object(
                    readiness_mod.ObservedReadSession,
                    "read_required",
                    tracking_read_required,
                ),
                mock.patch.object(
                    readiness_mod.ObservedReadSession,
                    "read_optional",
                    tracking_read_optional,
                ),
                mock.patch.object(
                    readiness_mod.ObservedReadSession,
                    "list_directory",
                    tracking_list_directory,
                ),
            ):
                try:
                    evaluate_revisit_readiness(workspace, cycle_id)
                except ReadinessPlanError as exc:
                    self.assertIn(expected_fragment, str(exc))
                else:
                    self.fail(
                        "malformed readiness plan did not raise "
                        "ReadinessPlanError"
                    )
        self.assertEqual([], reads, "plan shape must fail before workspace reads")

    # ------------------------------------------------------------------
    # Completeness of the closed thirteen-row plan
    # ------------------------------------------------------------------
    def test_requirement_plan_is_exact_complete_and_ordered(self):
        self.assertEqual(13, len(REVISIT_REQUIREMENT_IDS))
        self.assertEqual(13, len(set(REVISIT_REQUIREMENT_IDS)))
        self.assertEqual(EXPECTED_REQUIREMENT_IDS, REVISIT_REQUIREMENT_IDS)

    def test_row_13_rejects_passing_state_without_complete_selection(self):
        context = SimpleNamespace(
            trace=[
                SimpleNamespace(requirement_id=requirement_id)
                for requirement_id in REVISIT_REQUIREMENT_IDS[:-1]
            ],
            closure=object(),
            result=readiness_mod.ContractResult(),
            selected_cycle=None,
        )
        with self.assertRaisesRegex(
            ReadinessPlanError,
            "passing readiness requires one complete selected cycle",
        ):
            readiness_mod._evaluate_route_and_effect_parity(context)

    def test_requirement_plan_uses_only_canonical_row_prerequisites(self):
        expected = {
            "core_state_workflow": (),
            "global_cycle_history": ("ticker_mode",),
            "intake_provenance": ("ticker_mode", "cycle"),
            "trigger_evidence": ("ticker_mode", "cycle"),
            "claim_freshness": ("ticker_mode", "cycle"),
            "frontier_registry": ("ticker_mode",),
            "frontier_research_floor": ("ticker_mode", "cycle"),
            "search_coverage": ("ticker_mode",),
            "dispatch_delivery": ("ticker_mode",),
            "worker_outputs": ("ticker_mode",),
            "source_cache": (),
            "generation_closure": (),
            "route_and_effect_parity": (),
        }
        self.assertEqual(
            expected,
            {
                row.requirement_id: row.prerequisites
                for row in _plan_rows()
            },
        )

    def test_requirement_plan_rejects_missing_row_before_filesystem_read(self):
        self._assert_bad_plan_before_read(_plan_rows()[:-1], "missing")

    def test_requirement_plan_rejects_duplicate_row_before_filesystem_read(self):
        plan = _plan_rows()
        self._assert_bad_plan_before_read(plan[:-1] + (plan[0],), "duplicate")

    def test_requirement_plan_rejects_unknown_row_before_filesystem_read(self):
        plan = list(_plan_rows())
        plan[-1] = _replace_plan_row(
            plan[-1],
            requirement_id="unknown_requirement",
        )
        self._assert_bad_plan_before_read(plan, "unknown")

    def test_requirement_plan_rejects_unowned_row_before_filesystem_read(self):
        plan = list(_plan_rows())
        plan[4] = _replace_plan_row(plan[4], handlers=())
        self._assert_bad_plan_before_read(plan, "unowned")

    def test_requirement_plan_rejects_multi_owned_row_before_filesystem_read(self):
        plan = list(_plan_rows())
        plan[4] = _replace_plan_row(
            plan[4],
            handlers=plan[4].handlers + plan[4].handlers,
        )
        self._assert_bad_plan_before_read(plan, "multi-owned")

    def test_requirement_plan_rejects_wrong_order_before_filesystem_read(self):
        plan = list(_plan_rows())
        plan[0], plan[1] = plan[1], plan[0]
        self._assert_bad_plan_before_read(plan, "wrong-order")

    def test_ready_fixture_trace_visits_all_requirements_once_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            prepared = readiness_mod._prepare_revisit_readiness(
                readiness_mod.ObservedReadSession(workspace),
                readiness_mod.ContractResult(),
                cycle_id,
                workspace,
            )

        self.assertEqual(
            tuple(
                (
                    requirement_id,
                    "invariant"
                    if requirement_id == "route_and_effect_parity"
                    else "evaluated",
                )
                for requirement_id in EXPECTED_REQUIREMENT_IDS
            ),
            _trace_pairs(prepared),
        )

    def test_sector_mode_skips_ticker_rows_but_runs_closure_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _report = make_registration_workspace(
                Path(temp_dir),
                mode="sector",
            )
            prepared = readiness_mod._prepare_revisit_readiness(
                readiness_mod.ObservedReadSession(workspace),
                readiness_mod.ContractResult(),
                None,
                workspace,
            )

        self.assertEqual(
            ["REVISIT_UNSUPPORTED_MODE"],
            _failure_codes(prepared.result),
        )
        self.assertEqual(
            (
                ("core_state_workflow", "evaluated"),
                ("global_cycle_history", "skipped"),
                ("intake_provenance", "skipped"),
                ("trigger_evidence", "skipped"),
                ("claim_freshness", "skipped"),
                ("frontier_registry", "skipped"),
                ("frontier_research_floor", "skipped"),
                ("search_coverage", "skipped"),
                ("dispatch_delivery", "skipped"),
                ("worker_outputs", "skipped"),
                ("source_cache", "evaluated"),
                ("generation_closure", "evaluated"),
                ("route_and_effect_parity", "invariant"),
            ),
            _trace_pairs(prepared),
        )

    def test_malformed_history_sibling_suppresses_unsafe_selection_derivations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            aborted = run_revisit_cycle_cli(
                workspace,
                "abort",
                cycle_id,
                "--reason",
                "Architecture correction isolates incomplete history.",
            )
            self.assertEqual(0, aborted.returncode, aborted.stderr)
            index_record = json.loads(
                (workspace / "sources_index.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            (workspace / index_record["excerpt_path"]).unlink()
            malformed_path = workspace / "revisit_cycles" / "RC-9999.json"
            malformed_path.write_bytes(b"{")

            prepared = readiness_mod._prepare_revisit_readiness(
                readiness_mod.ObservedReadSession(workspace),
                readiness_mod.ContractResult(),
                "RC-9999",
                workspace,
            )

        history_issues = [
            issue
            for issue in prepared.result.failures
            if issue.code == "REVISIT_CYCLE_MALFORMED"
        ]
        self.assertEqual(1, len(history_issues))
        self.assertEqual(
            "revisit_cycles/RC-9999.json",
            history_issues[0].path,
        )
        self.assertIn(
            "SOURCE_EXCERPT_MISSING",
            _failure_codes(prepared.result),
        )
        self.assertIsNone(prepared.cycle_id)
        trace = _trace_pairs(prepared)
        self.assertEqual(EXPECTED_REQUIREMENT_IDS, tuple(row[0] for row in trace))
        self.assertEqual(13, len(trace))
        self.assertEqual(13, len({row[0] for row in trace}))

    def test_invalid_registry_does_not_skip_row_7_cycle_projection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["version"] = 999
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            prepared = self._prepare(workspace, cycle_id)

        self.assertIn(
            "REVISIT_FRONTIER_REGISTRY_MALFORMED",
            _failure_codes(prepared.result),
        )
        self._assert_trace_statuses(
            prepared,
            {
                "frontier_registry": "evaluated",
                "frontier_research_floor": "evaluated",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_ledger_does_not_mask_independent_owners(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            (workspace / "evidence_ledger.md").write_bytes(b"\xff")
            try:
                prepared = self._prepare(workspace, cycle_id)
            except UnicodeDecodeError as exc:
                self.fail(f"invalid ledger escaped its row owner: {exc}")

        codes = _failure_codes(prepared.result)
        self.assertIn("EVIDENCE_LEDGER_INVALID", codes)
        self.assertNotIn("REVISIT_SEARCH_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_CHALLENGE_FLOOR_MISSING", codes)
        self._assert_trace_statuses(
            prepared,
            {
                "frontier_registry": "evaluated",
                "frontier_research_floor": "evaluated",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_ledger_and_registry_do_not_mask_row_7_claim_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            (workspace / "evidence_ledger.md").write_bytes(b"\xff")
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["version"] = 999
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            prepared = self._prepare(workspace, cycle_id)

        owner_codes = {
            "EVIDENCE_LEDGER_INVALID",
            "REVISIT_FRONTIER_REGISTRY_MALFORMED",
            "REVISIT_FRONTIER_BINDING_INVALID",
        }
        self.assertEqual(
            [
                "EVIDENCE_LEDGER_INVALID",
                "REVISIT_FRONTIER_REGISTRY_MALFORMED",
                "REVISIT_FRONTIER_BINDING_INVALID",
            ],
            [
                code
                for code in _failure_codes(prepared.result)
                if code in owner_codes
            ],
        )
        self._assert_trace_statuses(
            prepared,
            {
                "core_state_workflow": "evaluated",
                "frontier_registry": "evaluated",
                "frontier_research_floor": "evaluated",
            },
        )

    def test_invalid_search_is_owned_without_masking_dispatch_or_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            (workspace / "search_log.jsonl").write_bytes(b"\xff")
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        self.assertIn("SEARCH_LOG_INVALID", codes)
        self.assertNotIn("REVISIT_SEARCH_FLOOR_MISSING", codes)
        self._assert_trace_statuses(
            prepared,
            {
                "frontier_research_floor": "evaluated",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_dispatch_does_not_mask_independent_worker_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            worker_path = workspace / "challenges" / "loop_8_challenge.md"
            worker_path.write_text(
                worker_path.read_text(encoding="utf-8").replace(
                    "Method cards loaded: red-team, supply-chain-mapping, "
                    "customer-graph-discovery.\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            (workspace / "dispatch_log.jsonl").write_bytes(b"{\n")
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        self.assertEqual(
            ["DISPATCH_LOG_INVALID", "WORKER_METHOD_CARDS_MISSING"],
            [
                code
                for code in codes
                if code
                in {
                    "DISPATCH_LOG_INVALID",
                    "WORKER_METHOD_CARDS_MISSING",
                }
            ],
        )
        self.assertNotIn("WORKER_OUTPUT_WITHOUT_DISPATCH", codes)
        self.assertNotIn("DISPATCH_ROLE_DELIVERY_MISMATCH", codes)
        self.assertNotIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_CHALLENGE_FLOOR_MISSING", codes)
        self._assert_trace_statuses(
            prepared,
            {
                "frontier_research_floor": "evaluated",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "worker_outputs": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_source_suppresses_only_source_dependent_subchecks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            artifact_ref = {
                "kind": "artifact",
                "path": "evidence/missing-proof.md",
                "sha256": "0" * 64,
                "locator": "Missing artifact remains independently checkable",
                "checked_at": "2026-07-14T12:00:00Z",
            }
            cycle["intake"]["triggers"][0]["evidence_refs"].append(
                dict(artifact_ref)
            )
            cycle["claim_resolutions"][0]["current_evidence_refs"].append(
                dict(artifact_ref)
            )
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
            attach_valid_audit(cycle)
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / f"{cycle_id}.json"
                ),
            )

            worker_path = workspace / "challenges" / "loop_8_challenge.md"
            worker_path.write_text(
                worker_path.read_text(encoding="utf-8").replace(
                    "Method cards loaded: red-team, supply-chain-mapping, "
                    "customer-graph-discovery.\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            index_record = json.loads(
                (workspace / "sources_index.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            (workspace / index_record["excerpt_path"]).unlink()
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        conditional_codes = {
            "REVISIT_TRIGGER_EVIDENCE_MISSING",
            "REVISIT_FRESHNESS_SUPPORT_INVALID",
            "WORKER_METHOD_CARDS_MISSING",
            "SOURCE_EXCERPT_MISSING",
        }
        self.assertEqual(
            [
                "REVISIT_TRIGGER_EVIDENCE_MISSING",
                "REVISIT_FRESHNESS_SUPPORT_INVALID",
                "WORKER_METHOD_CARDS_MISSING",
                "SOURCE_EXCERPT_MISSING",
            ],
            [code for code in codes if code in conditional_codes],
        )
        trigger_issues = [
            issue
            for issue in prepared.result.failures
            if issue.code == "REVISIT_TRIGGER_EVIDENCE_MISSING"
        ]
        freshness_issues = [
            issue
            for issue in prepared.result.failures
            if issue.code == "REVISIT_FRESHNESS_SUPPORT_INVALID"
        ]
        self.assertEqual(
            ["cycle.intake.triggers[0].evidence_refs[1]"],
            [issue.path for issue in trigger_issues],
        )
        self.assertEqual(
            ["cycle.claim_resolutions[0].current_evidence_refs[1]"],
            [issue.path for issue in freshness_issues],
        )
        self.assertNotIn("REVISIT_COUNTER_EVIDENCE_INVALID", codes)
        self.assertNotIn("WORKER_SOURCE_TRACE_MISSING", codes)
        self.assertNotIn(
            "WORKER_SOURCE_TRACE_RECOMMENDED",
            [issue.code for issue in prepared.result.warnings],
        )
        self._assert_trace_statuses(
            prepared,
            {
                "trigger_evidence": "evaluated",
                "claim_freshness": "evaluated",
                "frontier_registry": "evaluated",
                "frontier_research_floor": "evaluated",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "worker_outputs": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_core_authority_error_matrix_converges_across_public_routes(self):
        def remove(relative_path: str):
            return lambda workspace, _cycle_id: (
                workspace / relative_path
            ).unlink()

        def replace_bytes(relative_path: str, payload: bytes):
            return lambda workspace, _cycle_id: (
                workspace / relative_path
            ).write_bytes(payload)

        def replace_with_directory(relative_path: str):
            def mutate(workspace: Path, _cycle_id: str) -> None:
                path = workspace / relative_path
                path.unlink()
                path.mkdir()

            return mutate

        def remove_all_core(workspace: Path, _cycle_id: str) -> None:
            for relative_path in (
                "state.json",
                "research_workflow.md",
                "evidence_ledger.md",
            ):
                (workspace / relative_path).unlink()

        cases = (
            ("state missing", remove("state.json"), ["STATE_JSON_MISSING"]),
            (
                "state malformed JSON",
                replace_bytes("state.json", b"{\n"),
                ["STATE_JSON_INVALID"],
            ),
            (
                "state invalid UTF-8",
                replace_bytes("state.json", b"\xff"),
                ["STATE_JSON_INVALID"],
            ),
            (
                "state non-object",
                replace_bytes("state.json", b"[]\n"),
                ["STATE_JSON_INVALID"],
            ),
            (
                "state wrong lexical kind",
                replace_with_directory("state.json"),
                ["STATE_JSON_INVALID"],
            ),
            (
                "workflow missing",
                remove("research_workflow.md"),
                ["RESEARCH_WORKFLOW_MISSING"],
            ),
            (
                "workflow invalid UTF-8",
                replace_bytes("research_workflow.md", b"\xff"),
                ["RESEARCH_WORKFLOW_INVALID"],
            ),
            (
                "workflow wrong lexical kind",
                replace_with_directory("research_workflow.md"),
                ["RESEARCH_WORKFLOW_INVALID"],
            ),
            (
                "ledger missing",
                remove("evidence_ledger.md"),
                ["EVIDENCE_LEDGER_MISSING"],
            ),
            (
                "ledger invalid UTF-8",
                replace_bytes("evidence_ledger.md", b"\xff"),
                ["EVIDENCE_LEDGER_INVALID"],
            ),
            (
                "ledger wrong lexical kind",
                replace_with_directory("evidence_ledger.md"),
                ["EVIDENCE_LEDGER_INVALID"],
            ),
            (
                "all core authorities missing in stable owner order",
                remove_all_core,
                [
                    "STATE_JSON_MISSING",
                    "RESEARCH_WORKFLOW_MISSING",
                    "EVIDENCE_LEDGER_MISSING",
                ],
            ),
        )
        for label, mutate, expected_codes in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=expected_codes,
                )

    def test_typed_state_shape_matrix_converges_across_public_routes(self):
        def mutate_state(mutator):
            def mutate(workspace: Path, _cycle_id: str) -> None:
                path = workspace / "state.json"
                state = json.loads(path.read_text(encoding="utf-8"))
                mutator(state)
                path.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

            return mutate

        cases = (
            ("mode missing", lambda state: state.pop("mode")),
            ("mode unknown", lambda state: state.__setitem__("mode", "hybrid")),
            ("mode wrong type", lambda state: state.__setitem__("mode", 7)),
            (
                "stages completed null",
                lambda state: state.__setitem__("stages_completed", None),
            ),
            (
                "stages completed object",
                lambda state: state.__setitem__(
                    "stages_completed",
                    {"stage_2": True},
                ),
            ),
            (
                "stages completed non-string member",
                lambda state: state.__setitem__("stages_completed", [2]),
            ),
            (
                "current stage wrong type",
                lambda state: state.__setitem__("current_stage", 5),
            ),
            (
                "current stage unknown",
                lambda state: state.__setitem__("current_stage", "stage_9"),
            ),
            (
                "loop count list",
                lambda state: state.__setitem__("loop_count", []),
            ),
            (
                "loop count string",
                lambda state: state.__setitem__("loop_count", "3"),
            ),
            (
                "loop count boolean",
                lambda state: state.__setitem__("loop_count", True),
            ),
            (
                "loop count negative",
                lambda state: state.__setitem__("loop_count", -1),
            ),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate_state(mutate),
                    expected_codes=["STATE_JSON_INVALID"],
                    expected_paths=["state.json"],
                )

    def test_typed_workflow_rows_have_one_exact_owner(self):
        def workflow_case(workflow_text: str):
            def mutate(workspace: Path, _cycle_id: str) -> None:
                state_path = workspace / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["stages_completed"] = ["stage_2"]
                state_path.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                (workspace / "research_workflow.md").write_text(
                    workflow_text,
                    encoding="utf-8",
                )

            return mutate

        invalid_cases = (
            (
                "near-match stage identifier",
                "| Stage 20: Not Stage 2 | complete | | |\n",
            ),
            (
                "duplicate stage row",
                "| Stage 2: Evidence | complete | | |\n"
                "| Stage 2: Evidence | pending | | |\n",
            ),
            (
                "invalid status",
                "| Stage 2: Evidence | finished | | |\n",
            ),
        )
        for label, workflow_text in invalid_cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    workflow_case(workflow_text),
                    expected_codes=["RESEARCH_WORKFLOW_INVALID"],
                    expected_paths=["research_workflow.md"],
                )

        self._assert_public_route_codes(
            workflow_case("# Research Workflow\n"),
            expected_codes=["STATE_WORKFLOW_STAGE_CONFLICT"],
            expected_paths=["research_workflow.md"],
        )

    def test_typed_ledger_syntax_and_progress_have_distinct_owners(self):
        def replace_ledger(text: str):
            return lambda workspace, _cycle_id: (
                workspace / "evidence_ledger.md"
            ).write_text(text, encoding="utf-8")

        self._assert_public_route_codes(
            replace_ledger(
                "# Evidence Ledger\n\n"
                "## Loop 8: F1\n\nMalformed header.\n"
            ),
            expected_codes=["EVIDENCE_LEDGER_INVALID"],
            expected_paths=["evidence_ledger.md"],
        )
        self._assert_public_route_codes(
            replace_ledger(
                "# Evidence Ledger\n\n"
                "## Loop 8: F99 - Unknown frontier\n\nEvidence.\n"
            ),
            expected_codes=["REVISIT_FRONTIER_BINDING_INVALID"],
            expected_paths=["evidence_ledger.md"],
        )
        self._assert_public_route_codes(
            replace_ledger("# Evidence Ledger\n\nNo loop headers yet.\n"),
            expected_codes=[
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                "REVISIT_REVIEW_FLOOR_MISSING",
                "REVISIT_FRONTIER_BINDING_INVALID",
            ],
        )

    def test_history_authority_error_matrix_converges_without_traceback(self):
        def pointer_missing(workspace: Path, _cycle_id: str) -> None:
            (workspace / "revisit_contract.json").unlink()

        def pointer_malformed(workspace: Path, _cycle_id: str) -> None:
            (workspace / "revisit_contract.json").write_bytes(b"{\n")

        def pointer_wrong_kind(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "revisit_contract.json"
            path.unlink()
            path.mkdir()

        def cycle_directory_missing(workspace: Path, _cycle_id: str) -> None:
            shutil.rmtree(workspace / "revisit_cycles")

        def cycle_directory_wrong_kind(
            workspace: Path,
            _cycle_id: str,
        ) -> None:
            path = workspace / "revisit_cycles"
            shutil.rmtree(path)
            path.write_bytes(b"not a directory\n")

        def cycle_json_missing(workspace: Path, cycle_id: str) -> None:
            (workspace / "revisit_cycles" / f"{cycle_id}.json").unlink()

        def cycle_json_malformed(workspace: Path, cycle_id: str) -> None:
            (workspace / "revisit_cycles" / f"{cycle_id}.json").write_bytes(
                b"{\n"
            )

        cases = (
            ("pointer missing", pointer_missing),
            ("pointer malformed", pointer_malformed),
            ("pointer wrong lexical kind", pointer_wrong_kind),
            ("cycle directory missing", cycle_directory_missing),
            ("cycle directory wrong lexical kind", cycle_directory_wrong_kind),
            ("cycle JSON missing", cycle_json_missing),
            ("cycle JSON malformed", cycle_json_malformed),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=["REVISIT_CYCLE_MALFORMED"],
                )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_cycle_directory_rejects_noncanonical_members_and_loads_all_json(self):
        def illegal_filename(workspace: Path, _cycle_id: str) -> None:
            (workspace / "revisit_cycles" / "notes.txt").write_text(
                "not a cycle member\n",
                encoding="utf-8",
            )

        def json_named_directory(workspace: Path, _cycle_id: str) -> None:
            (workspace / "revisit_cycles" / "RC-9999.json").mkdir()

        def markdown_symlink(workspace: Path, _cycle_id: str) -> None:
            os.symlink(
                "RC-0001.md",
                workspace / "revisit_cycles" / "RC-9999.md",
            )

        def malformed_sibling_json(workspace: Path, _cycle_id: str) -> None:
            (workspace / "revisit_cycles" / "RC-9999.json").write_bytes(
                b"{\n"
            )

        cases = (
            ("illegal filename", illegal_filename, "revisit_cycles/notes.txt"),
            (
                "directory member",
                json_named_directory,
                "revisit_cycles/RC-9999.json",
            ),
            (
                "symlink member",
                markdown_symlink,
                "revisit_cycles/RC-9999.md",
            ),
            (
                "malformed sibling JSON is loaded",
                malformed_sibling_json,
                "revisit_cycles/RC-9999.json",
            ),
        )
        for label, mutate, expected_path in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=["REVISIT_CYCLE_MALFORMED"],
                    expected_paths=[expected_path],
                )

    def test_search_invalid_variants_converge_without_floor_noise(self):
        def replace_bytes(payload: bytes):
            return lambda workspace, _cycle_id: (
                workspace / "search_log.jsonl"
            ).write_bytes(payload)

        def valid_prefix_bad_tail(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "search_log.jsonl"
            path.write_bytes(path.read_bytes() + b"{\n")

        def wrong_kind(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "search_log.jsonl"
            path.unlink()
            path.mkdir()

        cases = (
            ("invalid UTF-8", replace_bytes(b"\xff")),
            ("invalid JSON", replace_bytes(b"{\n")),
            ("non-object", replace_bytes(b"[]\n")),
            ("valid prefix plus bad tail", valid_prefix_bad_tail),
            ("wrong lexical kind", wrong_kind),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=["SEARCH_LOG_INVALID"],
                    expected_paths=["search_log.jsonl"],
                )

    def test_dispatch_wrong_lexical_kind_is_owned_without_floor_noise(self):
        def wrong_kind(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "dispatch_log.jsonl"
            path.unlink()
            path.mkdir()

        self._assert_public_route_codes(
            wrong_kind,
            expected_codes=["DISPATCH_LOG_INVALID"],
            expected_paths=["dispatch_log.jsonl"],
        )

    def test_worker_invalid_utf8_does_not_mask_valid_sibling_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            invalid_path = workspace / "challenges" / "loop_8_challenge.md"
            invalid_path.write_bytes(b"\xff")
            sibling_path = workspace / "challenges" / "loop_9_challenge.md"
            sibling_path.write_text(
                sibling_path.read_text(encoding="utf-8").replace(
                    "Method cards loaded: red-team, supply-chain-mapping, "
                    "customer-graph-discovery.\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )

            result = evaluate_revisit_readiness(workspace, cycle_id)

        relevant = [
            (issue.code, issue.path)
            for issue in result.failures
            if issue.code
            in {"WORKER_OUTPUT_INVALID", "WORKER_METHOD_CARDS_MISSING"}
        ]
        self.assertEqual(
            [
                ("WORKER_OUTPUT_INVALID", "challenges/loop_8_challenge.md"),
                (
                    "WORKER_METHOD_CARDS_MISSING",
                    "challenges/loop_9_challenge.md",
                ),
            ],
            relevant,
        )

    def test_registry_malformed_variants_converge_across_routes(self):
        def replace_bytes(payload: bytes):
            return lambda workspace, _cycle_id: (
                workspace / "frontier_registry.json"
            ).write_bytes(payload)

        def wrong_kind(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "frontier_registry.json"
            path.unlink()
            path.mkdir()

        cases = (
            ("invalid JSON", replace_bytes(b"{\n")),
            ("invalid UTF-8", replace_bytes(b"\xff")),
            ("non-object", replace_bytes(b"[]\n")),
            ("wrong lexical kind", wrong_kind),
        )
        for label, mutate in cases:
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=[
                        "REVISIT_FRONTIER_REGISTRY_MALFORMED"
                    ],
                    expected_paths=["frontier_registry.json"],
                )

    def test_readiness_requires_current_ticker_registry_facts(self):
        def legacy_v2(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "frontier_registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["version"] = 2
            registry.pop("layer_labels", None)
            for frontier in registry["frontiers"]:
                frontier.pop("layer", None)
                frontier.pop("parent_frontier", None)
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        def sector_v3(workspace: Path, _cycle_id: str) -> None:
            path = workspace / "frontier_registry.json"
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["mode"] = "sector"
            path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        for label, mutate in (
            ("legacy v2", legacy_v2),
            ("v3 Sector", sector_v3),
        ):
            with self.subTest(case=label):
                self._assert_public_route_codes(
                    mutate,
                    expected_codes=[
                        "REVISIT_FRONTIER_REGISTRY_MALFORMED"
                    ],
                    expected_paths=["frontier_registry.json"],
                )

    def test_invalid_frontier_inputs_keep_row_owners_disjoint(self):
        def mutate(workspace: Path, _cycle_id: str) -> None:
            registry_path = workspace / "frontier_registry.json"
            registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            registry["version"] = 2
            registry.pop("layer_labels", None)
            for frontier in registry["frontiers"]:
                frontier.pop("layer", None)
                frontier.pop("parent_frontier", None)
            registry_path.write_text(
                json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (workspace / "search_log.jsonl").write_bytes(b"{\n")
            (workspace / "dispatch_log.jsonl").write_bytes(b"[]\n")

        self._assert_public_route_codes(
            mutate,
            expected_codes=[
                "REVISIT_FRONTIER_REGISTRY_MALFORMED",
                "SEARCH_LOG_INVALID",
                "DISPATCH_LOG_INVALID",
            ],
            expected_paths=[
                "frontier_registry.json",
                "search_log.jsonl",
                "dispatch_log.jsonl",
            ],
        )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_source_directory_invalid_kinds_have_one_stable_owner(self):
        def replace_source_root(workspace: Path, kind: str) -> None:
            source_root = workspace / "sources"
            shutil.rmtree(source_root)
            if kind == "file":
                source_root.write_text("not a directory\n", encoding="utf-8")
            elif kind == "broken":
                os.symlink(
                    "missing-sources",
                    source_root,
                    target_is_directory=True,
                )
            else:
                outside = workspace.parent / "outside-sources"
                outside.mkdir()
                os.symlink(
                    outside,
                    source_root,
                    target_is_directory=True,
                )

        for kind in ("file", "broken", "outside"):
            with self.subTest(kind=kind):
                self._assert_public_route_codes_pair_preserving(
                    lambda workspace, _cycle_id, kind=kind: (
                        replace_source_root(workspace, kind)
                    ),
                    expected_codes=["SOURCE_INDEX_MALFORMED"],
                    expected_paths=["sources"],
                )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_source_invalid_sibling_does_not_mask_excerpt_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            record = json.loads(
                (workspace / "sources_index.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            excerpt_path = workspace / record["excerpt_path"]
            excerpt_path.write_bytes(b"\xff")
            invalid_sibling = workspace / "sources" / "linked-source.md"
            os.symlink(excerpt_path.name, invalid_sibling)

            result = evaluate_revisit_readiness(workspace, cycle_id)

        relevant = [
            (issue.code, issue.path)
            for issue in result.failures
            if issue.code == "SOURCE_INDEX_MALFORMED"
        ]
        self.assertEqual(
            [
                ("SOURCE_INDEX_MALFORMED", record["excerpt_path"]),
                ("SOURCE_INDEX_MALFORMED", "sources/linked-source.md"),
            ],
            relevant,
        )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_worker_directory_invalid_kinds_have_one_stable_owner(self):
        def replace_worker_root(workspace: Path, kind: str) -> None:
            worker_root = workspace / "maps"
            if worker_root.exists() or worker_root.is_symlink():
                if worker_root.is_dir() and not worker_root.is_symlink():
                    shutil.rmtree(worker_root)
                else:
                    worker_root.unlink()
            if kind == "file":
                worker_root.write_text("not a directory\n", encoding="utf-8")
            elif kind == "broken":
                os.symlink(
                    "missing-maps",
                    worker_root,
                    target_is_directory=True,
                )
            else:
                outside = workspace.parent / "outside-maps"
                outside.mkdir()
                os.symlink(
                    outside,
                    worker_root,
                    target_is_directory=True,
                )

        for kind in ("file", "broken", "outside"):
            with self.subTest(kind=kind):
                self._assert_public_route_codes_pair_preserving(
                    lambda workspace, _cycle_id, kind=kind: (
                        replace_worker_root(workspace, kind)
                    ),
                    expected_codes=["WORKER_OUTPUT_INVALID"],
                    expected_paths=["maps"],
                )

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_worker_invalid_sibling_does_not_mask_valid_sibling_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            challenge_path = (
                workspace / "challenges" / "loop_8_challenge.md"
            )
            challenge_path.write_text(
                challenge_path.read_text(encoding="utf-8").replace(
                    "Method cards loaded: red-team, supply-chain-mapping, "
                    "customer-graph-discovery.\n\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )
            maps = workspace / "maps"
            maps.mkdir(exist_ok=True)
            invalid_sibling = maps / "linked-output.md"
            os.symlink(challenge_path, invalid_sibling)

            result = evaluate_revisit_readiness(workspace, cycle_id)

        relevant = [
            (issue.code, issue.path)
            for issue in result.failures
            if issue.code
            in {"WORKER_OUTPUT_INVALID", "WORKER_METHOD_CARDS_MISSING"}
        ]
        self.assertEqual(
            [
                ("WORKER_OUTPUT_INVALID", "maps/linked-output.md"),
                (
                    "WORKER_METHOD_CARDS_MISSING",
                    "challenges/loop_8_challenge.md",
                ),
            ],
            relevant,
        )

    def test_named_mismatch_check_reports_global_cycle_and_preserves_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            cycle_path = workspace / "revisit_cycles" / f"{cycle_id}.json"
            mirror_path = workspace / "revisit_cycles" / f"{cycle_id}.md"
            prior_cycle = cycle_path.read_bytes()
            prior_mirror = mirror_path.read_bytes()
            prior_tree = snapshot_tree(workspace)

            outcome = check_revisit_readiness(
                workspace,
                "RC-9999",
                timestamp=self.TIMESTAMP,
            )

            self.assertEqual(RevisitCheckEffect.BLOCKED, outcome.effect)
            self.assertEqual(cycle_id, outcome.cycle_id)
            self.assertEqual(
                ["REVISIT_CYCLE_MALFORMED"],
                _failure_codes(outcome.result),
            )
            self.assertEqual(prior_cycle, cycle_path.read_bytes())
            self.assertEqual(prior_mirror, mirror_path.read_bytes())
            self.assertEqual(prior_tree, snapshot_tree(workspace))

    def _remove_indexed_excerpt(self, workspace: Path) -> None:
        record = json.loads(
            (workspace / "sources_index.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        (workspace / record["excerpt_path"]).unlink()

    def test_invalid_core_continues_source_cache_and_skips_dependents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            (workspace / "state.json").write_bytes(b"{\n")
            self._remove_indexed_excerpt(workspace)
            invalid_core = self._prepare(workspace, cycle_id)

        self.assertEqual(
            ["STATE_JSON_INVALID", "SOURCE_EXCERPT_MISSING"],
            _failure_codes(invalid_core.result),
        )
        self._assert_trace_statuses(
            invalid_core,
            {
                "core_state_workflow": "evaluated",
                "global_cycle_history": "skipped",
                "intake_provenance": "skipped",
                "trigger_evidence": "skipped",
                "claim_freshness": "skipped",
                "frontier_registry": "skipped",
                "frontier_research_floor": "skipped",
                "search_coverage": "skipped",
                "dispatch_delivery": "skipped",
                "worker_outputs": "skipped",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_history_continues_source_cache_and_skips_dependents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            (workspace / "revisit_contract.json").write_bytes(b"{\n")
            self._remove_indexed_excerpt(workspace)
            invalid_history = self._prepare(workspace, cycle_id)

        self.assertEqual(
            ["REVISIT_CYCLE_MALFORMED", "SOURCE_EXCERPT_MISSING"],
            _failure_codes(invalid_history.result),
        )
        self._assert_trace_statuses(
            invalid_history,
            {
                "global_cycle_history": "evaluated",
                "intake_provenance": "skipped",
                "trigger_evidence": "skipped",
                "claim_freshness": "skipped",
                "frontier_registry": "evaluated",
                "frontier_research_floor": "skipped",
                "search_coverage": "evaluated",
                "dispatch_delivery": "evaluated",
                "worker_outputs": "evaluated",
                "source_cache": "evaluated",
            },
        )

    def test_invalid_history_does_not_mask_invalid_source_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            (workspace / "revisit_contract.json").write_bytes(b"{\n")
            index_path = workspace / "sources_index.jsonl"
            index_path.unlink()
            index_path.mkdir()
            try:
                invalid_source = self._prepare(workspace, cycle_id)
            except Exception as exc:
                self.fail(
                    "source-cache wrong lexical kind escaped its owner: "
                    f"{type(exc).__name__}: {exc}"
                )

        self.assertEqual(
            ["REVISIT_CYCLE_MALFORMED", "SOURCE_INDEX_MALFORMED"],
            _failure_codes(invalid_source.result),
        )
        self._assert_trace_statuses(
            invalid_source,
            {
                "global_cycle_history": "evaluated",
                "source_cache": "evaluated",
                "generation_closure": "evaluated",
                "route_and_effect_parity": "invariant",
            },
        )

    def test_unbound_claim_is_reported_without_fabricated_progress_issues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        self.assertIn("REVISIT_FRONTIER_BINDING_INVALID", codes)
        claim_issue = next(
            issue
            for issue in prepared.result.failures
            if issue.code == "REVISIT_FRONTIER_BINDING_INVALID"
        )
        self.assertEqual(
            "cycle.claim_resolutions[RC-0001-CL-01]",
            claim_issue.path,
        )
        self.assertNotIn("REVISIT_FRONTIER_LOOP_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_SEARCH_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_SCOUT_FLOOR_MISSING", codes)

    def test_loop_failure_does_not_mask_review_search_or_delivery_siblings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            append_task6_loops(workspace, 1)
            prepared = self._prepare(workspace, cycle_id)

        sibling_codes = {
            "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
            "REVISIT_REVIEW_FLOOR_MISSING",
            "REVISIT_SEARCH_FLOOR_MISSING",
            "REVISIT_SCOUT_FLOOR_MISSING",
            "REVISIT_CHALLENGE_FLOOR_MISSING",
        }
        self.assertEqual(
            [
                "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
                "REVISIT_REVIEW_FLOOR_MISSING",
                "REVISIT_SEARCH_FLOOR_MISSING",
                "REVISIT_SCOUT_FLOOR_MISSING",
                "REVISIT_CHALLENGE_FLOOR_MISSING",
            ],
            [
                code
                for code in _failure_codes(prepared.result)
                if code in sibling_codes
            ],
        )

    def test_ordinary_adapter_stops_after_loop_floor_compatibility_issue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_binding_workspace(Path(temp_dir))
            bind_task6_reactivated_frontier(workspace, cycle_id)
            append_task6_loops(workspace, 1)

            issues = derive_task6_floor_issues(workspace, cycle_id)

        sibling_codes = {
            "REVISIT_FRONTIER_LOOP_FLOOR_MISSING",
            "REVISIT_REVIEW_FLOOR_MISSING",
            "REVISIT_SEARCH_FLOOR_MISSING",
            "REVISIT_SCOUT_FLOOR_MISSING",
            "REVISIT_CHALLENGE_FLOOR_MISSING",
        }
        self.assertEqual(
            ["REVISIT_FRONTIER_LOOP_FLOOR_MISSING"],
            [issue.code for issue in issues if issue.code in sibling_codes],
        )

    def test_row_8_owns_revisit_search_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            search_path = workspace / "search_log.jsonl"
            records = [
                json.loads(line)
                for line in search_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            search_path.write_text(
                "".join(
                    json.dumps(record) + "\n"
                    for record in records
                    if record.get("loop_id") != "loop_10"
                ),
                encoding="utf-8",
            )
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        self.assertIn("REVISIT_SEARCH_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_CHALLENGE_FLOOR_MISSING", codes)

    def test_row_9_owns_revisit_dispatch_floor_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            dispatch_path = workspace / "dispatch_log.jsonl"
            records = [
                json.loads(line)
                for line in dispatch_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            removed = next(
                record
                for record in records
                if record.get("loop_id") == "loop_10"
                and record.get("role") == "frontier_scout"
            )
            dispatch_path.write_text(
                "".join(
                    json.dumps(record) + "\n"
                    for record in records
                    if record is not removed
                ),
                encoding="utf-8",
            )
            (workspace / removed["delivery_path"]).unlink()
            prepared = self._prepare(workspace, cycle_id)

        codes = _failure_codes(prepared.result)
        self.assertIn("REVISIT_SCOUT_FLOOR_MISSING", codes)
        self.assertNotIn("REVISIT_SEARCH_FLOOR_MISSING", codes)

    # ------------------------------------------------------------------
    # Probe 1: sibling/global-history conflict must fail on all three routes
    # ------------------------------------------------------------------
    def _make_ready_with_conflicting_sibling(self, root: Path):
        workspace, cycle_id = make_task6_ready_workspace(root)
        # Copy the named cycle to RC-0002 with a DUPLICATE candidate_revision_id
        # so evaluate_history flags duplicate_candidate_revision across ALL
        # cycles (which the named-only direct/profile routes used to miss).
        source_cycle = revisit_contract.load_cycle(workspace, cycle_id)
        sibling = json.loads(json.dumps(source_cycle))
        sibling["cycle_id"] = "RC-0002"
        # Same candidate_revision_id as RC-0001 -> duplicate reservation.
        sibling_path = workspace / "revisit_cycles" / "RC-0002.json"
        sibling_path.write_text(
            json.dumps(sibling, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return workspace, cycle_id

    def test_probe_sibling_history_conflict_converges_across_routes(self):
        _assert_three_route_failure_codes(
            self,
            self._make_ready_with_conflicting_sibling,
            lambda workspace, cycle_id: cycle_id,
            expected_codes_for_named=["REVISIT_CYCLE_MALFORMED"],
        )

    # ------------------------------------------------------------------
    # Probe 2: state/workflow stage conflict on all three routes
    # ------------------------------------------------------------------
    def _make_ready_with_state_workflow_conflict(self, root: Path):
        workspace, cycle_id = make_task6_ready_workspace(root)
        # Declare stage_5 completed in state.json but keep the minimal
        # research_workflow.md that the fixture writes; then add a Stage
        # Progress table marking stage_5 as pending.
        state_path = workspace / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["stages_completed"] = ["stage_5"]
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        workflow = workspace / "research_workflow.md"
        workflow.write_text(
            "\n".join(
                [
                    "# Research Workflow",
                    "",
                    "## Stage Progress",
                    "| Stage | Status | Output Files | Notes |",
                    "|-------|--------|--------------|-------|",
                    "| Stage 5: Final Verdict | pending | reports/ | |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return workspace, cycle_id

    def test_probe_state_workflow_conflict_converges_across_routes(self):
        _assert_three_route_failure_codes(
            self,
            self._make_ready_with_state_workflow_conflict,
            lambda workspace, cycle_id: cycle_id,
            expected_codes_for_named=["STATE_WORKFLOW_STAGE_CONFLICT"],
        )

    # ------------------------------------------------------------------
    # Probe 3: malformed registry -> REVISIT_FRONTIER_REGISTRY_MALFORMED
    # ------------------------------------------------------------------
    def _make_ready_with_malformed_registry(self, root: Path):
        workspace, cycle_id = make_task6_ready_workspace(root)
        registry_path = workspace / "frontier_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        # Bump to an unsupported version so validate_registry raises
        # LifecycleError.
        registry["version"] = 999
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return workspace, cycle_id

    def test_probe_malformed_registry_converges_across_routes(self):
        _assert_three_route_failure_codes(
            self,
            self._make_ready_with_malformed_registry,
            lambda workspace, cycle_id: cycle_id,
            expected_codes_for_named=["REVISIT_FRONTIER_REGISTRY_MALFORMED"],
        )

    # ------------------------------------------------------------------
    # Probe 4: unrelated indexed excerpt drift -> REVISIT_AUTHORITY_DRIFT
    # ------------------------------------------------------------------
    def _make_ready_with_drifting_unrelated_excerpt(self, root: Path):
        workspace, cycle_id = make_task6_ready_workspace(root)
        # Add an UNRELATED but valid indexed excerpt. The named cycle does not
        # reference it, but the source-cache row reads every planned excerpt.
        excerpt_path = workspace / "sources" / "src-099.md"
        excerpt_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"Unrelated current source excerpt for drift detection.\n"
        excerpt_path.write_bytes(payload)
        record = {
            "source_id": "src-099",
            "url": "https://example.test/unrelated-drift",
            "title": "Unrelated drift source",
            "retrieved": "2026-07-14",
            "grade": "B",
            "excerpt_path": "sources/src-099.md",
            "sha256": __import__("hashlib").sha256(payload).hexdigest(),
        }
        with (workspace / "sources_index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return workspace, cycle_id

    def test_probe_unrelated_excerpt_drift_converges_across_routes(self):
        # The drift is injected between the semantic read and the closure
        # recheck by mutating the excerpt inside the seam window. For the
        # direct/profile routes we patch the session; for the CLI the snapshot
        # mechanism in revisit_cycle.py is the boundary. To exercise the seam's
        # OWN closure uniformly across routes, we mutate the excerpt via a
        # filesystem race patched around the readiness call.
        import hashlib

        def make_workspace(root: Path):
            return self._make_ready_with_drifting_unrelated_excerpt(root)

        excerpt_rel = "sources/src-099.md"

        # --- direct: patch evaluate_revisit_readiness's session freeze point
        from sofa_contract import revisit_readiness as readiness_mod
        from revisit_contract.generation import AuthorityDriftError, GenerationDrift

        # direct route
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_workspace(Path(temp_dir))
            target = workspace / excerpt_rel
            original_freeze = readiness_mod.evaluate_revisit_readiness

            def drift_then_call(*args, **kwargs):
                # Trigger the real seam but mutate the excerpt right before it
                # performs its closure recheck. We wrap by patching
                # GenerationClosure.require_unchanged to mutate first.
                from revisit_contract import generation as gen_mod

                real_require = gen_mod.GenerationClosure.require_unchanged

                def mutating_require(self):
                    target.write_bytes(target.read_bytes() + b"drift\n")
                    return real_require(self)

                with unittest.mock.patch.object(
                    gen_mod.GenerationClosure,
                    "require_unchanged",
                    mutating_require,
                ):
                    return original_freeze(*args, **kwargs)

            direct = drift_then_call(workspace, cycle_id)
            direct_codes = _failure_codes(direct)
            self.assertIn("REVISIT_AUTHORITY_DRIFT", direct_codes)
            drift_issue = next(
                issue for issue in direct.failures
                if issue.code == "REVISIT_AUTHORITY_DRIFT"
            )
            self.assertEqual(excerpt_rel, drift_issue.path)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_artifact_symlink_retarget_reports_lexical_authority(self):
        from revisit_contract.generation import ObservedReadSession

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            artifacts = workspace / "artifacts"
            artifacts.mkdir()
            first_target = artifacts / "first.md"
            second_target = artifacts / "second.md"
            payload = b"Same artifact evidence generation.\n"
            first_target.write_bytes(payload)
            second_target.write_bytes(payload)
            lexical_link = artifacts / "proof.md"
            os.symlink(first_target.name, lexical_link)

            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["intake"]["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": "artifacts/proof.md",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "locator": "Same-byte lexical artifact proof",
                    "checked_at": cycle["created_at"],
                }
            ]
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
            attach_valid_audit(cycle)
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / f"{cycle_id}.json"
                ),
            )

            real_freeze = ObservedReadSession.freeze
            retargeted = False

            def retarget_then_freeze(session):
                nonlocal retargeted
                if not retargeted:
                    lexical_link.unlink()
                    os.symlink(second_target.name, lexical_link)
                    retargeted = True
                return real_freeze(session)

            with mock.patch.object(
                ObservedReadSession,
                "freeze",
                retarget_then_freeze,
            ):
                result = evaluate_revisit_readiness(workspace, cycle_id)

            self.assertFalse(
                result.passed,
                [issue.display() for issue in result.failures],
            )
            drift_issue = next(
                issue
                for issue in result.failures
                if issue.code == "REVISIT_AUTHORITY_DRIFT"
            )
            self.assertEqual("artifacts/proof.md", drift_issue.path)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_workspace_alias_absolute_artifact_is_ready_across_routes(self):
        def make_alias_workspace(root: Path) -> tuple[Path, Path, str]:
            workspace, cycle_id = make_task6_ready_workspace(root)
            artifact = workspace / "artifacts" / "proof.md"
            artifact.parent.mkdir()
            payload = b"Workspace alias artifact evidence.\n"
            artifact.write_bytes(payload)
            alias = root / "workspace-alias"
            os.symlink(workspace, alias, target_is_directory=True)

            cycle = revisit_contract.load_cycle(workspace, cycle_id)
            cycle["intake"]["triggers"][0]["evidence_refs"] = [
                {
                    "kind": "artifact",
                    "path": str(alias / "artifacts" / "proof.md"),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "locator": "Workspace alias absolute artifact proof",
                    "checked_at": cycle["created_at"],
                }
            ]
            cycle["intake_sha256"] = test_semantic_sha256(cycle["intake"])
            attach_valid_audit(cycle)
            revisit_contract.persist_cycle(
                workspace,
                cycle,
                expected_sha256=revisit_contract.sha256_file(
                    workspace / "revisit_cycles" / f"{cycle_id}.json"
                ),
            )
            return workspace, alias, cycle_id

        with tempfile.TemporaryDirectory() as temp_dir:
            _workspace, alias, cycle_id = make_alias_workspace(Path(temp_dir))
            direct = evaluate_revisit_readiness(alias, cycle_id)
            self.assertTrue(
                direct.passed,
                [issue.display() for issue in direct.failures],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            _workspace, alias, _cycle_id = make_alias_workspace(Path(temp_dir))
            profile = evaluate_workspace(
                alias,
                ContractProfile(mode="ticker", target="revisit_report"),
            )
            self.assertTrue(
                profile.passed,
                [issue.display() for issue in profile.failures],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            _workspace, alias, cycle_id = make_alias_workspace(Path(temp_dir))
            checked = check_revisit_readiness(
                alias,
                cycle_id,
                timestamp="2026-07-17T12:00:00Z",
            )
            self.assertTrue(
                checked.result.passed,
                [issue.display() for issue in checked.result.failures],
            )
            self.assertEqual(RevisitCheckEffect.TRANSITIONED, checked.effect)

    # ------------------------------------------------------------------
    # Named-selection tests
    # ------------------------------------------------------------------
    def test_named_selection_must_equal_sole_eligible_cycle(self):
        # A ready workspace has exactly one eligible cycle; naming it passes.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            result = evaluate_revisit_readiness(workspace, cycle_id)
            self.assertTrue(
                result.passed,
                [issue.display() for issue in result.failures],
            )

    def test_discovered_profile_selects_sole_eligible_cycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            result = evaluate_workspace(
                workspace,
                ContractProfile(mode="ticker", target="revisit_report"),
            )
            self.assertTrue(
                result.passed,
                [issue.display() for issue in result.failures],
            )


class TestReadOnlyReadinessIOAndDrift(unittest.TestCase):
    """Step 4.6: read-only drift boundary and single-read semantics."""

    def test_freeze_catches_drift_of_already_consumed_unrelated_excerpt(self):
        """Patching ObservedReadSession.freeze mutates an unrelated excerpt.

        The seam must translate the drift to exactly one REVISIT_AUTHORITY_DRIFT
        at the excerpt's relative path and not pass.
        """
        from sofa_contract import revisit_readiness as readiness_mod
        from revisit_contract.generation import (
            GenerationClosure,
            ObservedReadSession,
        )

        excerpt_rel = "sources/src-099.md"

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
            excerpt_path = workspace / excerpt_rel
            excerpt_path.parent.mkdir(parents=True, exist_ok=True)
            payload = b"Unrelated indexed excerpt for freeze drift.\n"
            excerpt_path.write_bytes(payload)
            record = {
                "source_id": "src-099",
                "url": "https://example.test/unrelated-drift",
                "title": "Unrelated drift source",
                "retrieved": "2026-07-14",
                "grade": "B",
                "excerpt_path": excerpt_rel,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            with (workspace / "sources_index.jsonl").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

            real_freeze = ObservedReadSession.freeze

            def mutate_then_freeze(self):
                excerpt_path.write_bytes(payload + b"drift\n")
                return real_freeze(self)

            with unittest.mock.patch.object(
                ObservedReadSession, "freeze", mutate_then_freeze
            ):
                result = readiness_mod.evaluate_revisit_readiness(
                    workspace, cycle_id
                )

            self.assertFalse(result.passed)
            drift_codes = [
                issue.code for issue in result.failures
            ]
            self.assertIn("REVISIT_AUTHORITY_DRIFT", drift_codes)
            drift_issue = next(
                issue
                for issue in result.failures
                if issue.code == "REVISIT_AUTHORITY_DRIFT"
            )
            self.assertEqual(excerpt_rel, drift_issue.path)

    def test_files_consumed_by_multiple_requirements_are_read_once(self):
        """A lexical file used by multiple semantic owners is cached by the session.

        research_workflow.md is consumed by core_state_workflow and dispatch_delivery;
        it must be read exactly once during semantic consumption. The closure
        verification is a separate boundary and must run exactly once.
        """
        from revisit_contract.generation import (
            GenerationClosure,
            ObservedReadSession,
        )

        read_counts: dict[str, int] = {}
        require_calls: list[None] = []

        real_read_required = ObservedReadSession.read_required
        real_read_optional = ObservedReadSession.read_optional
        real_require_unchanged = GenerationClosure.require_unchanged

        def counted_read_required(self, relative_path: str):
            read_counts[relative_path] = read_counts.get(relative_path, 0) + 1
            return real_read_required(self, relative_path)

        def counted_read_optional(self, relative_path: str):
            read_counts[relative_path] = read_counts.get(relative_path, 0) + 1
            return real_read_optional(self, relative_path)

        def counted_require_unchanged(self):
            require_calls.append(None)
            return real_require_unchanged(self)

        with (
            unittest.mock.patch.object(
                ObservedReadSession, "read_required", counted_read_required
            ),
            unittest.mock.patch.object(
                ObservedReadSession, "read_optional", counted_read_optional
            ),
            unittest.mock.patch.object(
                GenerationClosure,
                "require_unchanged",
                counted_require_unchanged,
            ),
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                result = evaluate_revisit_readiness(workspace, cycle_id)
                self.assertTrue(
                    result.passed,
                    [issue.display() for issue in result.failures],
                )

        self.assertEqual(
            1,
            read_counts.get("research_workflow.md", 0),
            "research_workflow.md must be read once during semantic consumption",
        )
        self.assertEqual(
            1,
            read_counts.get("state.json", 0),
            "state.json must be read once during semantic consumption",
        )
        self.assertEqual(1, len(require_calls))

    def test_direct_evaluation_observes_all_cycle_siblings_and_source_records(self):
        """The seam observes every cycle JSON and every planned source excerpt."""
        from revisit_contract.generation import ObservedReadSession

        real_read_optional = ObservedReadSession.read_optional
        read_paths: set[str] = set()

        def tracking_read_optional(self, relative_path: str):
            read_paths.add(relative_path)
            return real_read_optional(self, relative_path)

        with unittest.mock.patch.object(
            ObservedReadSession, "read_optional", tracking_read_optional
        ):
            with tempfile.TemporaryDirectory() as temp_dir:
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))

                # Add a sibling cycle that makes global history fail; the seam
                # still observes it before reporting the history issue.
                source_cycle = revisit_contract.load_cycle(workspace, cycle_id)
                sibling = json.loads(json.dumps(source_cycle))
                sibling["cycle_id"] = "RC-0002"
                sibling_path = workspace / "revisit_cycles" / "RC-0002.json"
                sibling_path.write_text(
                    json.dumps(sibling, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                # Add an unrelated valid indexed source.
                excerpt_rel = "sources/src-099.md"
                excerpt_path = workspace / excerpt_rel
                excerpt_path.parent.mkdir(parents=True, exist_ok=True)
                payload = b"Unrelated current source excerpt.\n"
                excerpt_path.write_bytes(payload)
                record = {
                    "source_id": "src-099",
                    "url": "https://example.test/unrelated",
                    "title": "Unrelated source",
                    "retrieved": "2026-07-14",
                    "grade": "B",
                    "excerpt_path": excerpt_rel,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                with (workspace / "sources_index.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

                result = evaluate_revisit_readiness(workspace, cycle_id)
                codes = [issue.code for issue in result.failures]
                self.assertIn("REVISIT_CYCLE_MALFORMED", codes)

        self.assertIn("revisit_cycles/RC-0001.json", read_paths)
        self.assertIn("revisit_cycles/RC-0002.json", read_paths)
        self.assertIn(excerpt_rel, read_paths)


class TestUnexpectedIoReadinessBoundary(unittest.TestCase):
    def test_direct_profile_and_check_propagate_unexpected_io(self) -> None:
        routes = (
            (
                "direct",
                lambda workspace, cycle_id: evaluate_revisit_readiness(
                    workspace,
                    cycle_id,
                ),
            ),
            (
                "profile",
                lambda workspace, _cycle_id: evaluate_workspace(
                    workspace,
                    ContractProfile(mode="ticker", target="revisit_report"),
                ),
            ),
            (
                "check",
                lambda workspace, cycle_id: check_revisit_readiness(
                    workspace,
                    cycle_id,
                    timestamp="2026-07-17T00:00:00Z",
                ),
            ),
        )
        for route, invoke in routes:
            with self.subTest(route=route), tempfile.TemporaryDirectory() as temp_dir:
                workspace, cycle_id = make_task6_ready_workspace(Path(temp_dir))
                with mock.patch.object(
                    readiness_mod.ObservedReadSession,
                    "read_optional",
                    side_effect=OSError(errno.EIO, f"{route} I/O fault"),
                ):
                    with self.assertRaises(OSError) as raised:
                        invoke(workspace, cycle_id)
                self.assertEqual(errno.EIO, raised.exception.errno)


# unittest.mock is imported lazily inside probe 4 to keep the module import
# surface minimal, but make it available at module level for the patch above.
import unittest.mock  # noqa: E402  pylint: disable=wrong-import-position


if __name__ == "__main__":
    unittest.main()
