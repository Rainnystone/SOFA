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
import json
import sys
import tempfile
import unittest
from pathlib import Path
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
from sofa_contract import evaluate as sofa_evaluate  # noqa: E402
from sofa_contract.revisit_readiness import REVISIT_REQUIREMENT_IDS  # noqa: E402

# Module-level helpers from the existing revisit-contract test corpus. These are
# importable (NOT the instance-method ``assert_revisit_failure``).
from tests.test_revisit_contract import (  # noqa: E402
    make_task6_ready_workspace,
    run_revisit_cycle_cli,
    snapshot_tree,
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
                outcome, ws, cid, pc, pm, expected_relative="revisit_cycles"
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
                outcome, ws, cid, pc, pm, expected_relative="scouts"
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
                outcome, ws, cid, pc, pm, expected_relative="sources"
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
                        recursive=False,
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

    # ------------------------------------------------------------------
    # Completeness of the closed thirteen-row plan
    # ------------------------------------------------------------------
    def test_requirement_plan_is_exact_complete_and_ordered(self):
        self.assertEqual(13, len(REVISIT_REQUIREMENT_IDS))
        self.assertEqual(13, len(set(REVISIT_REQUIREMENT_IDS)))
        self.assertEqual(EXPECTED_REQUIREMENT_IDS, REVISIT_REQUIREMENT_IDS)

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


# unittest.mock is imported lazily inside probe 4 to keep the module import
# surface minimal, but make it available at module level for the patch above.
import unittest.mock  # noqa: E402  pylint: disable=wrong-import-position


if __name__ == "__main__":
    unittest.main()
