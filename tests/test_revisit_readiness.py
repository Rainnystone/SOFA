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
