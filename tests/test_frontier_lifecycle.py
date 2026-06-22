import copy
import json
import tempfile
import unittest
from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/frontier_lifecycle.py"
LOOP_ENFORCER_SCRIPT = ROOT / "scripts/loop_enforcer.py"


def load_module():
    spec = importlib.util.spec_from_file_location("frontier_lifecycle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_loop_enforcer():
    spec = importlib.util.spec_from_file_location("loop_enforcer", LOOP_ENFORCER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFrontierLifecycle(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def registry(self, mode="ticker"):
        return {
            "version": 2,
            "subject": "MXL",
            "mode": mode,
            "created": "2026-06-22",
            "frontiers": [
                {
                    "id": "F1",
                    "name": "InP substrate supply concentration",
                    "proposed_at_loop": 1,
                    "source": "initial",
                    "source_frontier": None,
                    "status": "Active",
                    "review_count": 0,
                    "max_reviews": 3,
                    "retire_category": None,
                    "lifecycle": [{"to": "New", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"}, {"to": "Active", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"}],
                    "review_decisions": [],
                    "evidence_pointers": [],
                },
                {
                    "id": "F2",
                    "name": "CW laser qualification race",
                    "proposed_at_loop": 1,
                    "source": "initial",
                    "source_frontier": None,
                    "status": "Active",
                    "review_count": 0,
                    "max_reviews": 3,
                    "retire_category": None,
                    "lifecycle": [{"to": "New", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"}, {"to": "Active", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"}],
                    "review_decisions": [],
                    "evidence_pointers": [],
                },
            ],
            "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
        }

    def test_make_registry_and_create_frontier_build_schema(self):
        registry = self.module.make_registry("MXL", "ticker")
        self.assertEqual(
            {
                "version": 2,
                "subject": "MXL",
                "mode": "ticker",
                "frontiers": [],
                "portfolio_limits": {"max_active": 3, "max_active_plus_new": 5},
                "review_trigger": {"every_loops": 3, "max_reviews": 3},
            },
            registry,
        )

        with self.assertRaises(self.module.LifecycleError):
            self.module.make_registry("MXL", "unsupported")

        with_f1 = self.module.create_frontier(
            registry,
            name="InP substrate supply concentration",
            proposed_at_loop=1,
            source="initial",
            initial_status="Active",
            ts="2026-06-22T00:00:00Z",
        )
        self.assertEqual([], registry["frontiers"])
        f1 = self.module.get_frontier(with_f1, "F1")
        self.assertEqual("Active", f1["status"])
        self.assertEqual("initial", f1["source"])
        self.assertIsNone(f1["source_frontier"])
        self.assertEqual(
            [
                {"to": "New", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
                {"to": "Active", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
            ],
            f1["lifecycle"],
        )

        with_f2 = self.module.create_frontier(
            with_f1,
            name="Export permits",
            proposed_at_loop=2,
            source="discovery",
            source_frontier="F1",
            initial_status="New",
            ts="2026-06-22T01:00:00Z",
        )
        f2 = self.module.get_frontier(with_f2, "F2")
        self.assertEqual("New", f2["status"])
        self.assertEqual("discovery", f2["source"])
        self.assertEqual("F1", f2["source_frontier"])
        self.assertEqual([{"to": "New", "at_loop": 2, "ts": "2026-06-22T01:00:00Z"}], f2["lifecycle"])

    def test_create_frontier_validates_source_status_and_portfolio_limits(self):
        registry = self.module.make_registry("MXL", "ticker")
        with self.assertRaises(self.module.InvalidTransition):
            self.module.create_frontier(registry, name="Bad", proposed_at_loop=1, source="discovery")
        with self.assertRaises(self.module.InvalidTransition):
            self.module.create_frontier(
                registry,
                name="Bad",
                proposed_at_loop=1,
                source="initial",
                source_frontier="F1",
            )
        with self.assertRaises(self.module.InvalidTransition):
            self.module.create_frontier(
                registry,
                name="Bad",
                proposed_at_loop=1,
                source="initial",
                initial_status="Continued",
            )

        limited = self.module.make_registry("MXL", "ticker")
        for index in range(3):
            limited = self.module.create_frontier(
                limited,
                name=f"Active {index + 1}",
                proposed_at_loop=1,
                source="initial",
                initial_status="Active",
            )
        with self.assertRaises(self.module.InvalidTransition):
            self.module.create_frontier(
                limited,
                name="Too many active",
                proposed_at_loop=2,
                source="initial",
                initial_status="Active",
            )

    def test_derive_loop_counts_uses_stable_frontier_id(self):
        ledger = "\n".join(
            [
                "## Loop 1: F1 - InP substrate supply concentration",
                "## Loop 2: F1 - renamed display text",
                "## Loop 3: F2 - CW laser qualification race",
            ]
        )
        counts = self.module.derive_loop_counts(ledger, self.registry())
        self.assertEqual({"F1": 2, "F2": 1}, counts)

    def test_derive_loop_counts_rejects_missing_or_unknown_id(self):
        with self.assertRaises(self.module.BindingError):
            self.module.derive_loop_counts("## Loop 1: InP substrate supply concentration", self.registry())
        with self.assertRaises(self.module.BindingError):
            self.module.derive_loop_counts("## Loop 1: F9 - Unknown frontier", self.registry())

    def test_derive_loop_counts_rejects_malformed_frontier_ids_even_if_registered(self):
        for malformed_id in ["F0", "F01"]:
            with self.subTest(malformed_id=malformed_id):
                registry = self.registry()
                registry["frontiers"][0]["id"] = malformed_id
                with self.assertRaises(self.module.BindingError):
                    self.module.derive_loop_counts(
                        f"## Loop 1: {malformed_id} - malformed persisted frontier",
                        registry,
                    )

    def test_loop_enforcer_wrapper_normalizes_known_frontier_ids(self):
        loop_enforcer = load_loop_enforcer()
        ledger = "\n".join(
            [
                "## Loop 1: F1 - InP substrate supply concentration",
                "## Loop 2: F1 - changed display text",
            ]
        )

        passed, counts, violations = loop_enforcer.check_ledger_binding(ledger, self.registry())

        self.assertTrue(passed, violations)
        self.assertEqual({"F1": 2, "F2": 0}, counts)
        self.assertEqual([], violations)

    def test_loop_enforcer_wrapper_returns_binding_violations(self):
        loop_enforcer = load_loop_enforcer()

        passed, counts, violations = loop_enforcer.check_ledger_binding(
            "## Loop 1: F9 - Unknown frontier",
            self.registry(),
        )

        self.assertFalse(passed)
        self.assertEqual({}, counts)
        self.assertEqual(1, len(violations))
        self.assertIn("F9", violations[0])

    def test_check_loop_depth_binds_ledger_to_frontier_registry(self):
        loop_enforcer = load_loop_enforcer()

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "frontier_registry.json").write_text(
                json.dumps(self.registry(), ensure_ascii=False),
                encoding="utf-8",
            )
            (workspace / "evidence_ledger.md").write_text(
                "## Loop 1: F1 - InP substrate supply concentration\n",
                encoding="utf-8",
            )

            passed, violations = loop_enforcer.check_loop_depth(str(workspace))
            self.assertTrue(passed, violations)
            self.assertEqual([], violations)

            (workspace / "evidence_ledger.md").write_text(
                "# Evidence Ledger\n",
                encoding="utf-8",
            )
            passed, violations = loop_enforcer.check_loop_depth(str(workspace))
            self.assertFalse(passed)
            self.assertTrue(violations)

            (workspace / "evidence_ledger.md").write_text(
                "## Loop 1: F9 - Unknown frontier\n",
                encoding="utf-8",
            )
            passed, violations = loop_enforcer.check_loop_depth(str(workspace))
            self.assertFalse(passed)
            self.assertTrue(any("F9" in violation for violation in violations))

    def test_get_frontier_rejects_malformed_requested_ids_even_if_registered(self):
        for malformed_id in ["F0", "F01"]:
            with self.subTest(malformed_id=malformed_id):
                registry = self.registry()
                registry["frontiers"][0]["id"] = malformed_id
                with self.assertRaises(self.module.BindingError):
                    self.module.get_frontier(registry, malformed_id)

    def test_transition_rejects_malformed_requested_ids_even_if_registered(self):
        for malformed_id in ["F0", "F01"]:
            with self.subTest(malformed_id=malformed_id):
                registry = self.registry()
                registry["frontiers"][0]["id"] = malformed_id
                original = copy.deepcopy(registry)

                with self.assertRaises(self.module.BindingError):
                    self.module.transition(
                        registry,
                        malformed_id,
                        "Retired",
                        {malformed_id: 3},
                        mode="ticker",
                        action="retire",
                        retire_category="answered_out",
                        at_loop=3,
                    )

                self.assertEqual(original, registry)

    def test_check_review_due_prevents_duplicate_boundary_review(self):
        registry = self.registry()
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 3, "F2": 2}))
        registry["frontiers"][0]["review_count"] = 1
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 3, "F2": 2}))
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 6, "F2": 2}))
        registry["frontiers"][0]["review_count"] = 3
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 9, "F2": 2}))

    def test_check_review_due_applies_only_to_active_frontiers(self):
        registry = self.registry()
        registry["frontiers"][0]["status"] = "New"
        registry["frontiers"][1]["status"] = "Continued"
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 3, "F2": 3}))

    def test_check_review_due_uses_configurable_review_trigger(self):
        registry = self.registry()
        registry["review_trigger"] = {"every_loops": 2}
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 2, "F2": 1}))
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 3, "F2": 1}))

        registry["frontiers"][0]["review_count"] = 1
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 2, "F2": 1}))
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 4, "F2": 1}))

    def test_check_review_due_rejects_invalid_review_trigger(self):
        for every_loops in [0, -1, "2", 1.5, True]:
            with self.subTest(every_loops=every_loops):
                registry = self.registry()
                registry["review_trigger"] = {"every_loops": every_loops}
                with self.assertRaises(self.module.LifecycleError):
                    self.module.check_review_due(registry, {"F1": 2})

    def test_record_continued_is_durable_and_reactivate_is_explicit(self):
        registry = self.registry()
        updated = self.module.transition(
            registry,
            "F1",
            "Continued",
            {"F1": 3, "F2": 0},
            mode="ticker",
            action="review",
            rationale="yield high",
            at_loop=3,
        )
        f1 = self.module.get_frontier(updated, "F1")
        self.assertEqual("Continued", f1["status"])
        self.assertEqual(1, f1["review_count"])

        due_after_record = self.module.check_review_due(updated, {"F1": 3, "F2": 0})
        self.assertEqual([], due_after_record)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                updated,
                "F1",
                "Active",
                {"F1": 3, "F2": 0},
                mode="ticker",
                action="review",
                at_loop=4,
            )

        reactivated = self.module.transition(
            updated,
            "F1",
            "Active",
            {"F1": 3, "F2": 0},
            mode="ticker",
            action="reactivate",
            at_loop=4,
        )
        self.assertEqual("Active", self.module.get_frontier(reactivated, "F1")["status"])

    def test_review_action_rejects_off_boundary_loops_without_mutating_input(self):
        for loop_count in [1, 4]:
            with self.subTest(loop_count=loop_count):
                registry = self.registry()
                original = copy.deepcopy(registry)

                with self.assertRaises(self.module.InvalidTransition):
                    self.module.transition(
                        registry,
                        "F1",
                        "Continued",
                        {"F1": loop_count, "F2": 0},
                        mode="ticker",
                        action="review",
                        rationale="not actually due",
                        at_loop=loop_count,
                    )

                self.assertEqual(original, registry)
                self.assertEqual(0, self.module.get_frontier(registry, "F1")["review_count"])

    def test_review_action_rejects_duplicate_boundary_without_mutating_input(self):
        registry = self.registry()
        registry["frontiers"][0]["review_count"] = 1
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F1",
                "Continued",
                {"F1": 3, "F2": 0},
                mode="ticker",
                action="review",
                rationale="duplicate boundary",
                at_loop=3,
            )

        self.assertEqual(original, registry)
        self.assertEqual(1, self.module.get_frontier(registry, "F1")["review_count"])

    def test_reactivate_at_max_reviews_is_rejected(self):
        registry = self.registry()
        registry["frontiers"][0]["status"] = "Continued"
        registry["frontiers"][0]["review_count"] = 3
        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F1",
                "Active",
                {"F1": 9, "F2": 0},
                mode="ticker",
                action="reactivate",
                at_loop=10,
            )

    def test_activate_rejects_max_active_overflow_without_mutating_input(self):
        registry = self.module.make_registry("MXL", "ticker")
        for index in range(3):
            registry = self.module.create_frontier(
                registry,
                name=f"Active {index + 1}",
                proposed_at_loop=1,
                source="initial",
                initial_status="Active",
            )
        registry = self.module.create_frontier(
            registry,
            name="Queued frontier",
            proposed_at_loop=2,
            source="initial",
            initial_status="New",
        )
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F4",
                "Active",
                {"F4": 1},
                mode="ticker",
                action="activate",
                at_loop=2,
            )

        self.assertEqual(original, registry)
        self.assertEqual("New", self.module.get_frontier(registry, "F4")["status"])

    def test_reactivate_rejects_max_active_overflow_without_mutating_input(self):
        registry = self.module.make_registry("MXL", "ticker")
        for index in range(3):
            registry = self.module.create_frontier(
                registry,
                name=f"Active {index + 1}",
                proposed_at_loop=1,
                source="initial",
                initial_status="Active",
            )
        registry = self.module.create_frontier(
            registry,
            name="Continued frontier",
            proposed_at_loop=2,
            source="initial",
            initial_status="New",
        )
        f4 = self.module.get_frontier(registry, "F4")
        f4["status"] = "Continued"
        f4["review_count"] = 1
        f4["lifecycle"].append({"to": "Continued", "at_loop": 3, "ts": None})
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F4",
                "Active",
                {"F4": 3},
                mode="ticker",
                action="reactivate",
                at_loop=4,
            )

        self.assertEqual(original, registry)
        self.assertEqual("Continued", self.module.get_frontier(registry, "F4")["status"])

    def test_mode_aware_early_retire(self):
        ticker_registry = self.registry(mode="ticker")
        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                ticker_registry,
                "F1",
                "Retired",
                {"F1": 1, "F2": 0},
                mode="ticker",
                action="retire",
                retire_category="barren",
                rationale="no nodes",
                at_loop=1,
            )

        sector_registry = self.registry(mode="sector")
        retired = self.module.transition(
            sector_registry,
            "F1",
            "Retired",
            {"F1": 1, "F2": 0},
            mode="sector",
            action="retire",
            retire_category="barren",
            rationale="dead mapping direction",
            at_loop=1,
        )
        self.assertEqual("Retired", self.module.get_frontier(retired, "F1")["status"])
        self.assertEqual("barren", self.module.get_frontier(retired, "F1")["retire_category"])

    def test_retire_rejects_unknown_category_without_mutating_input(self):
        for mode in ["ticker", "sector"]:
            with self.subTest(mode=mode):
                registry = self.registry(mode=mode)
                original = copy.deepcopy(registry)

                with self.assertRaises(self.module.InvalidTransition):
                    self.module.transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 3, "F2": 0},
                        mode=mode,
                        action="retire",
                        retire_category="nonsense",
                        rationale="invalid category",
                        at_loop=3,
                    )

                self.assertEqual(original, registry)
                self.assertEqual("Active", self.module.get_frontier(registry, "F1")["status"])

    def test_early_retire_category_matrix_is_mode_aware(self):
        cases = [
            ("ticker", {"blocked", "invalidated"}, {"answered_out", "bad_pick", "superseded", "barren"}),
            ("sector", {"blocked", "invalidated", "barren"}, {"answered_out", "bad_pick", "superseded"}),
        ]

        for mode, allowed, rejected in cases:
            for category in allowed:
                with self.subTest(mode=mode, category=category, allowed=True):
                    registry = self.registry(mode=mode)
                    retired = self.module.transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 1, "F2": 0},
                        mode=mode,
                        action="retire",
                        retire_category=category,
                        rationale="early stop",
                        at_loop=1,
                    )
                    self.assertEqual("Retired", self.module.get_frontier(retired, "F1")["status"])
                    self.assertEqual(category, self.module.get_frontier(retired, "F1")["retire_category"])

            for category in rejected:
                with self.subTest(mode=mode, category=category, allowed=False):
                    registry = self.registry(mode=mode)
                    original = copy.deepcopy(registry)

                    with self.assertRaises(self.module.InvalidTransition):
                        self.module.transition(
                            registry,
                            "F1",
                            "Retired",
                            {"F1": 1, "F2": 0},
                            mode=mode,
                            action="retire",
                            retire_category=category,
                            rationale="premature",
                            at_loop=1,
                        )

                    self.assertEqual(original, registry)

    def test_valid_retire_categories_are_allowed_at_three_or_more_loops(self):
        valid_categories = ["blocked", "invalidated", "barren", "superseded", "bad_pick", "answered_out"]

        for mode in ["ticker", "sector"]:
            for category in valid_categories:
                with self.subTest(mode=mode, category=category):
                    registry = self.registry(mode=mode)
                    retired = self.module.transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 3, "F2": 0},
                        mode=mode,
                        action="retire",
                        retire_category=category,
                        rationale="resolved after sufficient loops",
                        at_loop=3,
                    )
                    self.assertEqual("Retired", self.module.get_frontier(retired, "F1")["status"])
                    self.assertEqual(category, self.module.get_frontier(retired, "F1")["retire_category"])

    def test_review_retire_accepts_only_review_categories_without_mutating_input(self):
        allowed = ["answered_out", "bad_pick", "superseded"]
        rejected = ["blocked", "invalidated", "barren", "nonsense"]

        for category in allowed:
            with self.subTest(category=category, allowed=True):
                registry = self.registry(mode="ticker")
                retired = self.module.transition(
                    registry,
                    "F1",
                    "Retired",
                    {"F1": 3, "F2": 0},
                    mode="ticker",
                    action="review",
                    retire_category=category,
                    rationale="review decision",
                    at_loop=3,
                )
                f1 = self.module.get_frontier(retired, "F1")
                self.assertEqual("Retired", f1["status"])
                self.assertEqual(category, f1["retire_category"])
                self.assertEqual(1, f1["review_count"])
                self.assertEqual(category, f1["review_decisions"][0]["retire_category"])

        for category in rejected:
            with self.subTest(category=category, allowed=False):
                registry = self.registry(mode="ticker")
                original = copy.deepcopy(registry)

                with self.assertRaises(self.module.InvalidTransition):
                    self.module.transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 3, "F2": 0},
                        mode="ticker",
                        action="review",
                        retire_category=category,
                        rationale="invalid review category",
                        at_loop=3,
                    )

                self.assertEqual(original, registry)
                self.assertEqual("Active", self.module.get_frontier(registry, "F1")["status"])
                self.assertEqual(0, self.module.get_frontier(registry, "F1")["review_count"])

    def test_transition_rejects_mode_mismatch_before_sector_retire_rules(self):
        registry = self.registry(mode="ticker")
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F1",
                "Retired",
                {"F1": 1, "F2": 0},
                mode="sector",
                action="retire",
                retire_category="barren",
                rationale="would only be allowed in sector",
                at_loop=1,
            )

        self.assertEqual(original, registry)
        self.assertEqual("Active", self.module.get_frontier(registry, "F1")["status"])

    def test_validate_stage_transition_rejects_active_new_and_all_retired(self):
        registry = self.registry()
        passed, missing = self.module.validate_for_stage_transition(registry, {"F1": 3, "F2": 3}, "ticker", "stage_3")
        self.assertFalse(passed)
        self.assertIn("frontier F1 is Active; resolve it before stage_3", missing)

        continued = copy.deepcopy(registry)
        continued["frontiers"][0]["status"] = "Continued"
        continued["frontiers"][1]["status"] = "New"
        passed, missing = self.module.validate_for_stage_transition(continued, {"F1": 3, "F2": 0}, "ticker", "stage_3")
        self.assertFalse(passed)
        self.assertIn("frontier F2 is New; start and resolve it or retire it before stage_3", missing)

        all_retired = copy.deepcopy(registry)
        all_retired["frontiers"][0]["status"] = "Retired"
        all_retired["frontiers"][0]["retire_category"] = "answered_out"
        all_retired["frontiers"][1]["status"] = "Retired"
        all_retired["frontiers"][1]["retire_category"] = "answered_out"
        passed, missing = self.module.validate_for_stage_transition(all_retired, {"F1": 3, "F2": 3}, "ticker", "stage_3")
        self.assertFalse(passed)
        self.assertIn("at least one Continued frontier is required before stage_3", missing)

    def test_validate_stage_transition_rejects_continued_frontier_before_three_loops(self):
        registry = self.registry(mode="ticker")
        registry["frontiers"][0]["status"] = "Continued"
        registry["frontiers"][1]["status"] = "Retired"
        registry["frontiers"][1]["retire_category"] = "answered_out"

        passed, missing = self.module.validate_for_stage_transition(registry, {"F1": 2, "F2": 3}, "ticker", "stage_3")

        self.assertFalse(passed)
        self.assertIn("frontier F1 is Continued with only 2 loop(s); minimum 3 required before stage_3", missing)

    def test_validate_stage_transition_accepts_canonical_shapes(self):
        ticker = self.registry(mode="ticker")
        ticker["frontiers"][0]["status"] = "Continued"
        ticker["frontiers"][1]["status"] = "Retired"
        ticker["frontiers"][1]["retire_category"] = "answered_out"
        passed, missing = self.module.validate_for_stage_transition(ticker, {"F1": 3, "F2": 3}, "ticker", "stage_3")
        self.assertTrue(passed, missing)

        sector = self.registry(mode="sector")
        sector["frontiers"][0]["status"] = "Continued"
        sector["frontiers"][1]["status"] = "Retired"
        sector["frontiers"][1]["retire_category"] = "barren"
        passed, missing = self.module.validate_for_stage_transition(sector, {"F1": 3, "F2": 1}, "sector", "stage_3")
        self.assertTrue(passed, missing)

    def test_validate_stage_transition_rejects_mode_mismatch_before_sector_retire_rules(self):
        registry = self.registry(mode="ticker")
        registry["frontiers"][0]["status"] = "Continued"
        registry["frontiers"][1]["status"] = "Retired"
        registry["frontiers"][1]["retire_category"] = "barren"

        passed, missing = self.module.validate_for_stage_transition(registry, {"F1": 3, "F2": 1}, "sector", "stage_3")

        self.assertFalse(passed)
        self.assertIn("mode mismatch: registry mode ticker does not match requested mode sector", missing)

    def test_validate_stage_transition_rejects_unknown_target_stage(self):
        registry = self.registry()
        for known_stage in ["stage_0", "stage_6"]:
            with self.subTest(known_stage=known_stage):
                passed, missing = self.module.validate_for_stage_transition(registry, {}, "ticker", known_stage)
                self.assertTrue(passed)
                self.assertEqual([], missing)

        passed, missing = self.module.validate_for_stage_transition(registry, {}, "ticker", "stage3")

        self.assertFalse(passed)
        self.assertEqual(["unsupported target_stage: stage3"], missing)

    def test_portfolio_limits_count_active_and_new_only(self):
        registry = self.registry()
        extra_frontier = {
            "id": "F3",
            "name": "Export permits",
            "proposed_at_loop": 2,
            "source": "discovery",
            "source_frontier": "F1",
            "status": "Active",
            "review_count": 0,
            "max_reviews": 3,
            "retire_category": None,
            "lifecycle": [],
            "review_decisions": [],
            "evidence_pointers": [],
        }
        registry["frontiers"].append(extra_frontier)
        violations = self.module.enforce_portfolio_limits(registry)
        self.assertEqual([], violations)

        active_violation = copy.deepcopy(registry)
        active_violation["frontiers"].append(copy.deepcopy(extra_frontier))
        active_violation["frontiers"][-1]["id"] = "F4"
        active_violation["frontiers"][-1]["name"] = "Extra active frontier"
        violations = self.module.enforce_portfolio_limits(active_violation)
        self.assertIn("Active frontier count 4 exceeds max_active=3", violations)

        non_counted = copy.deepcopy(registry)
        non_counted["frontiers"].append(copy.deepcopy(extra_frontier))
        non_counted["frontiers"][-1]["id"] = "F4"
        non_counted["frontiers"][-1]["status"] = "Continued"
        non_counted["frontiers"].append(copy.deepcopy(extra_frontier))
        non_counted["frontiers"][-1]["id"] = "F5"
        non_counted["frontiers"][-1]["status"] = "Retired"
        non_counted["frontiers"][-1]["retire_category"] = "answered_out"
        self.assertEqual([], self.module.enforce_portfolio_limits(non_counted))

        new_limited = copy.deepcopy(non_counted)
        for frontier_id in ["F6", "F7"]:
            new_limited["frontiers"].append(copy.deepcopy(extra_frontier))
            new_limited["frontiers"][-1]["id"] = frontier_id
            new_limited["frontiers"][-1]["status"] = "New"
        self.assertEqual([], self.module.enforce_portfolio_limits(new_limited))

        new_limited["frontiers"].append(copy.deepcopy(extra_frontier))
        new_limited["frontiers"][-1]["id"] = "F8"
        new_limited["frontiers"][-1]["status"] = "New"
        violations = self.module.enforce_portfolio_limits(new_limited)
        self.assertIn("Active+New frontier count 6 exceeds max_active_plus_new=5", violations)

    def test_review_and_discovery_rendering_is_deterministic(self):
        registry = self.registry()
        registry["frontiers"][0]["review_decisions"].append(
            {
                "review_number": 1,
                "at_loop": 3,
                "decision": "Continued",
                "retire_category": None,
                "rationale_short": "yield high",
                "portfolio_actions": [
                    {"action": "add", "frontier": "F3", "source": "discovery", "source_frontier": "F1", "reason": "export permit gate"},
                    {"action": "reject", "candidate": "Silicon photonics tangent", "reason": "does not change Layer 0 demand"},
                ],
            }
        )
        review_md = self.module.render_review_log_md(registry)
        discovery_md = self.module.render_discovery_log_md(registry)
        self.assertIn("## Frontier Review: F1 @ loop 3 (review 1/3)", review_md)
        self.assertIn("**Decision**: Continued", review_md)
        self.assertIn("Added F3", review_md)
        self.assertIn("Silicon photonics tangent", discovery_md)
        self.assertEqual(review_md, self.module.render_review_log_md(registry))
        self.assertEqual(discovery_md, self.module.render_discovery_log_md(registry))

    def test_replace_managed_block_uses_v4_markers_and_rejects_malformed(self):
        original = "\n".join(
            [
                "# Report",
                "",
                "<!-- SOFA:frontier_review:start -->",
                "old content",
                "<!-- SOFA:frontier_review:end -->",
                "",
            ]
        )
        expected = "\n".join(
            [
                "# Report",
                "",
                "<!-- SOFA:frontier_review:start -->",
                "new content",
                "<!-- SOFA:frontier_review:end -->",
                "",
            ]
        )
        replaced = self.module.replace_managed_block(original, "frontier_review", "new content\n")
        self.assertEqual(expected, replaced)
        self.assertEqual(expected, self.module.replace_managed_block(replaced, "frontier_review", "new content"))

        with self.assertRaises(self.module.LifecycleError):
            self.module.replace_managed_block("# Report\n", "frontier_review", "new content")
        with self.assertRaises(self.module.LifecycleError):
            self.module.replace_managed_block(
                "<!-- SOFA:frontier_review:start -->\nold content\n",
                "frontier_review",
                "new content",
            )

    def test_replace_managed_block_rejects_duplicate_or_misordered_markers(self):
        malformed_cases = [
            "<!-- SOFA:frontier_review:end -->",
            "\n".join(
                [
                    "<!-- SOFA:frontier_review:start -->",
                    "first",
                    "<!-- SOFA:frontier_review:start -->",
                    "second",
                    "<!-- SOFA:frontier_review:end -->",
                ]
            ),
            "\n".join(
                [
                    "<!-- SOFA:frontier_review:start -->",
                    "first",
                    "<!-- SOFA:frontier_review:end -->",
                    "<!-- SOFA:frontier_review:end -->",
                ]
            ),
            "\n".join(
                [
                    "<!-- SOFA:frontier_review:end -->",
                    "<!-- SOFA:frontier_review:start -->",
                    "first",
                    "<!-- SOFA:frontier_review:end -->",
                ]
            ),
        ]

        for malformed in malformed_cases:
            with self.subTest(malformed=malformed):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.replace_managed_block(malformed, "frontier_review", "new content")


if __name__ == "__main__":
    unittest.main()
