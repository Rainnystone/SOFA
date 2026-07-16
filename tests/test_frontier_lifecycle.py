import copy
import html
import inspect
from contextlib import redirect_stdout
from io import StringIO
import json
import re
import subprocess
import sys
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

    def v3_registry(self, mode="ticker"):
        registry = self.module.make_registry("MXL", mode)
        return self.module.create_frontier(
            registry,
            name="InP substrate supply concentration",
            proposed_at_loop=1,
            source="initial",
            initial_status="Active",
        )

    def layer_labels(self):
        return [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]

    def configured_v3_registry(self, frontier_count=3):
        registry = self.module.make_registry("MXL", "ticker")
        for index in range(frontier_count):
            registry = self.module.create_frontier(
                registry,
                name=f"Frontier {index + 1}",
                proposed_at_loop=index + 1,
                source="initial",
            )
        return self.module.set_layer_labels(
            registry,
            list(enumerate(self.layer_labels())),
        )

    def layer_coverage_registry(self):
        registry = self.module.make_registry("MXL", "ticker")
        registry["portfolio_limits"] = {
            "max_active": 20,
            "max_active_plus_new": 20,
        }
        for index in range(10):
            registry = self.module.create_frontier(
                registry,
                name=f"Frontier {index + 1}",
                proposed_at_loop=index + 1,
                source="initial",
            )
        registry = self.module.set_layer_labels(
            registry,
            list(enumerate(self.layer_labels())),
        )

        facts = {
            "F1": (5, "F4", "New", None),
            "F2": (0, None, "Active", None),
            "F3": (1, "F2", "Retired", "blocked"),
            "F4": (2, "F3", "Retired", "blocked"),
            "F5": (None, None, "Continued", None),
            "F6": (5, "F4", "Continued", None),
            "F7": (1, "F2", "Retired", "blocked"),
            "F8": (2, "F3", "Retired", "barren"),
            "F9": (None, None, "Retired", "superseded"),
            "F10": (0, None, "Retired", "blocked"),
        }
        frontier_by_id = {frontier["id"]: frontier for frontier in registry["frontiers"]}
        for frontier_id, (layer, parent, status, retire_category) in facts.items():
            frontier = frontier_by_id[frontier_id]
            frontier["layer"] = layer
            frontier["parent_frontier"] = parent
            frontier["status"] = status
            frontier["retire_category"] = retire_category
            self._sync_lifecycle_to_status(frontier)
        frontier_by_id["F6"]["source"] = "discovery"
        frontier_by_id["F6"]["source_frontier"] = "F10"
        registry["frontiers"] = [
            frontier_by_id[frontier_id]
            for frontier_id in ("F10", "F2", "F7", "F3", "F8", "F4", "F6", "F1", "F9", "F5")
        ]
        self.module.validate_registry(registry)
        return registry

    @staticmethod
    def _sync_lifecycle_to_status(frontier):
        """Canonicalize a frontier fixture's lifecycle so its final ``to``
        matches ``frontier["status"]``. Used only to keep existing positive
        fixtures coherent after they mutate status for unrelated tests."""
        status = frontier["status"]
        retire_category = frontier.get("retire_category")
        proposed_at_loop = frontier.get("proposed_at_loop", 1)
        lifecycle = [{"to": "New", "at_loop": proposed_at_loop, "ts": None}]
        if status == "Active":
            lifecycle.append({"to": "Active", "at_loop": proposed_at_loop, "ts": None})
        elif status == "Continued":
            lifecycle.append({"to": "Active", "at_loop": proposed_at_loop, "ts": None})
            lifecycle.append({"to": "Continued", "at_loop": proposed_at_loop, "ts": None})
        elif status == "Retired":
            row = {"to": "Retired", "at_loop": proposed_at_loop, "ts": None}
            if retire_category:
                row["retire_category"] = retire_category
            lifecycle.append(row)
        frontier["lifecycle"] = lifecycle

    def test_validate_registry_rejects_unknown_mixed_and_malformed_v3(self):
        valid = self.v3_registry()
        valid["extension"] = {"preserve": ["as-is"]}
        valid["frontiers"][0]["extension"] = {"owner": "research"}
        original = copy.deepcopy(valid)

        self.assertIs(valid, self.module.validate_registry(valid))
        self.assertEqual(original, valid)

        invalid_roots_and_versions = [
            None,
            [],
            {},
            {"version": "3"},
            {"version": True},
            {"version": 1},
            {"version": 4},
        ]
        for invalid in invalid_roots_and_versions:
            with self.subTest(invalid=invalid):
                original = copy.deepcopy(invalid)
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(invalid)
                self.assertEqual(original, invalid)

        mixed_registries = [
            {"version": 2, "layer_labels": []},
            {"version": 2, "frontiers": [{"layer": None}]},
            {"version": 2, "frontiers": [{"parent_frontier": None}]},
        ]
        for mixed in mixed_registries:
            with self.subTest(mixed=mixed):
                original = copy.deepcopy(mixed)
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(mixed)
                self.assertEqual(original, mixed)

        for required_frontier_key in ("layer", "parent_frontier"):
            malformed = self.v3_registry()
            malformed["frontiers"][0].pop(required_frontier_key)
            original = copy.deepcopy(malformed)
            with self.subTest(required_frontier_key=required_frontier_key):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

    def test_v3_required_optional_field_matrix_and_existing_defaults(self):
        minimal = {
            "version": 3,
            "subject": "",
            "mode": "sector",
            "layer_labels": [],
            "frontiers": [
                {
                    "id": "F1",
                    "name": "",
                    "proposed_at_loop": 1,
                    "source": "initial",
                    "status": "New",
                    "layer": None,
                    "parent_frontier": None,
                }
            ],
            "extension": {"keep": True},
        }
        original = copy.deepcopy(minimal)

        self.assertIs(minimal, self.module.validate_registry(minimal))
        self.assertEqual(original, minimal)
        for optional in ("portfolio_limits", "review_trigger"):
            self.assertNotIn(optional, minimal)
        for optional in (
            "source_frontier",
            "review_count",
            "max_reviews",
            "retire_category",
            "lifecycle",
            "review_decisions",
            "evidence_pointers",
        ):
            self.assertNotIn(optional, minimal["frontiers"][0])

        self.assertEqual([], self.module.check_review_due(minimal, {"F1": 3}))
        with_new_frontier = self.module.create_frontier(
            minimal,
            name="Optional-default probe",
            proposed_at_loop=2,
            source="initial",
        )
        self.assertEqual(3, self.module.get_frontier(with_new_frontier, "F2")["max_reviews"])
        self.assertEqual(original, minimal)

        partial_optional_objects = [
            ("portfolio_limits", {"max_active": 0}),
            ("portfolio_limits", {"max_active_plus_new": 0}),
            ("review_trigger", {"every_loops": 1}),
            ("review_trigger", {"max_reviews": 0}),
        ]
        for field, value in partial_optional_objects:
            registry = self.v3_registry()
            registry[field] = value
            original = copy.deepcopy(registry)
            with self.subTest(partial_optional_object=(field, value)):
                self.assertIs(registry, self.module.validate_registry(registry))
                self.assertEqual(original, registry)

        configured = self.v3_registry()
        configured["layer_labels"] = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        configured["frontiers"][0]["layer"] = 0
        configured["frontiers"][0]["parent_frontier"] = None
        configured["frontiers"][0]["extension"] = ["untouched"]
        original = copy.deepcopy(configured)
        self.assertIs(configured, self.module.validate_registry(configured))
        self.assertEqual(original, configured)

        for field in ("subject", "mode", "layer_labels", "frontiers"):
            malformed = self.v3_registry()
            malformed.pop(field)
            original = copy.deepcopy(malformed)
            with self.subTest(required_top_level=field):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

        for field in (
            "id",
            "name",
            "proposed_at_loop",
            "source",
            "status",
            "layer",
            "parent_frontier",
        ):
            malformed = self.v3_registry()
            malformed["frontiers"][0].pop(field)
            original = copy.deepcopy(malformed)
            with self.subTest(required_frontier=field):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

        malformed_shapes = {
            "subject": ("subject", None),
            "mode": ("mode", None),
            "layer_labels": ("layer_labels", {}),
            "frontiers": ("frontiers", {}),
            "portfolio_limits": ("portfolio_limits", []),
            "review_trigger": ("review_trigger", []),
        }
        for case, (field, value) in malformed_shapes.items():
            malformed = self.v3_registry()
            malformed[field] = value
            original = copy.deepcopy(malformed)
            with self.subTest(malformed_top_level=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

        malformed = self.v3_registry()
        malformed["frontiers"] = [None]
        original = copy.deepcopy(malformed)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(malformed)
        self.assertEqual(original, malformed)

        for field in ("id", "name", "source", "status"):
            malformed = self.v3_registry()
            malformed["frontiers"][0][field] = None
            original = copy.deepcopy(malformed)
            with self.subTest(non_string_frontier_field=field):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

        for field in ("lifecycle", "review_decisions", "evidence_pointers"):
            malformed = self.v3_registry()
            malformed["frontiers"][0][field] = {}
            original = copy.deepcopy(malformed)
            with self.subTest(non_list_optional_frontier_field=field):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(malformed)
                self.assertEqual(original, malformed)

    def test_v3_rejects_noncanonical_persisted_values_without_normalizing(self):
        canonical_labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]

        def reject(case, registry):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(registry)
                self.assertEqual(original, registry)

        for field in ("max_active", "max_active_plus_new"):
            for invalid in (True, -1, "3", 1.0):
                registry = self.v3_registry()
                registry["portfolio_limits"][field] = invalid
                reject(f"portfolio_limits.{field}={invalid!r}", registry)

        for invalid in (True, 0, -1, "3", 1.0):
            registry = self.v3_registry()
            registry["review_trigger"]["every_loops"] = invalid
            reject(f"review_trigger.every_loops={invalid!r}", registry)

        for invalid in (True, -1, "3", 1.0):
            registry = self.v3_registry()
            registry["review_trigger"]["max_reviews"] = invalid
            reject(f"review_trigger.max_reviews={invalid!r}", registry)

        invalid_label_sets = {
            "partial": canonical_labels[:5],
            "too_many": [*canonical_labels, "Extra"],
            "non_string": [True, *canonical_labels[1:]],
            "blank": ["", *canonical_labels[1:]],
            "whitespace_only": ["   ", *canonical_labels[1:]],
            "leading_whitespace": [" End demand", *canonical_labels[1:]],
            "trailing_whitespace": ["End demand ", *canonical_labels[1:]],
            "newline": ["End\ndemand", *canonical_labels[1:]],
            "carriage_return": ["End\rdemand", *canonical_labels[1:]],
            "unicode_line_separator": ["End\u2028demand", *canonical_labels[1:]],
            "control_character": ["End\x00demand", *canonical_labels[1:]],
            "casefold_duplicate": ["Layer", "layer", *canonical_labels[2:]],
            "unicode_casefold_duplicate": ["Straße", "STRASSE", *canonical_labels[2:]],
        }
        for case, labels in invalid_label_sets.items():
            registry = self.v3_registry()
            registry["layer_labels"] = labels
            reject(f"layer_labels.{case}", registry)

        punctuation = self.v3_registry()
        punctuation["layer_labels"] = ["End | demand", *canonical_labels[1:]]
        original = copy.deepcopy(punctuation)
        self.assertIs(punctuation, self.module.validate_registry(punctuation))
        self.assertEqual(original, punctuation)

        for field, value in (("layer", 0), ("parent_frontier", "F9")):
            registry = self.v3_registry()
            registry["frontiers"][0][field] = value
            reject(f"empty_layer_labels_with_{field}", registry)

        for invalid_id in ("F0", "F01", "F-1", 1):
            registry = self.v3_registry()
            registry["frontiers"][0]["id"] = invalid_id
            reject(f"frontier.id={invalid_id!r}", registry)

        duplicate = self.v3_registry()
        duplicate["frontiers"].append(copy.deepcopy(duplicate["frontiers"][0]))
        reject("duplicate_frontier_id", duplicate)

        for invalid in (True, 0, -1, "1", 1.0):
            registry = self.v3_registry()
            registry["frontiers"][0]["proposed_at_loop"] = invalid
            reject(f"frontier.proposed_at_loop={invalid!r}", registry)

        for invalid in ("manual", [], {}):
            registry = self.v3_registry()
            registry["frontiers"][0]["source"] = invalid
            reject(f"frontier.source={invalid!r}", registry)

        for field in ("source_frontier", "parent_frontier"):
            for invalid in ("F0", "F01", 1):
                registry = self.v3_registry()
                registry["layer_labels"] = canonical_labels
                registry["frontiers"][0][field] = invalid
                reject(f"frontier.{field}={invalid!r}", registry)

        registry = self.v3_registry()
        registry["frontiers"][0]["status"] = "active"
        reject("frontier.status=active", registry)

        for field in ("review_count", "max_reviews"):
            for invalid in (True, -1, "0", 0.0):
                registry = self.v3_registry()
                registry["frontiers"][0][field] = invalid
                reject(f"frontier.{field}={invalid!r}", registry)

        for missing_or_invalid in (None, "unknown"):
            registry = self.v3_registry()
            registry["frontiers"][0]["status"] = "Retired"
            registry["frontiers"][0]["retire_category"] = missing_or_invalid
            reject(f"retired_category={missing_or_invalid!r}", registry)

        registry = self.v3_registry()
        registry["frontiers"][0]["status"] = "Retired"
        registry["frontiers"][0].pop("retire_category")
        reject("retired_category_missing", registry)

        for status in ("New", "Active", "Continued"):
            registry = self.v3_registry()
            registry["frontiers"][0]["status"] = status
            registry["frontiers"][0]["retire_category"] = "blocked"
            reject(f"non_retired_category_status={status}", registry)

        for invalid in (True, -1, 6, "0", 0.0):
            registry = self.v3_registry()
            registry["layer_labels"] = canonical_labels
            registry["frontiers"][0]["layer"] = invalid
            reject(f"frontier.layer={invalid!r}", registry)

        valid_scalars = self.v3_registry()
        valid_scalars["layer_labels"] = canonical_labels
        valid_scalars["portfolio_limits"] = {"max_active": 0, "max_active_plus_new": 0}
        valid_scalars["review_trigger"] = {"every_loops": 1, "max_reviews": 0}
        frontier = valid_scalars["frontiers"][0]
        frontier["proposed_at_loop"] = 1
        frontier["review_count"] = 0
        frontier["max_reviews"] = 0
        frontier["layer"] = 5
        original = copy.deepcopy(valid_scalars)
        self.assertIs(valid_scalars, self.module.validate_registry(valid_scalars))
        self.assertEqual(original, valid_scalars)

        for category in self.module.VALID_RETIRE_CATEGORIES:
            retired = self.v3_registry()
            retired["frontiers"][0]["status"] = "Retired"
            retired["frontiers"][0]["retire_category"] = category
            self._sync_lifecycle_to_status(retired["frontiers"][0])
            original = copy.deepcopy(retired)
            with self.subTest(valid_retire_category=category):
                self.assertIs(retired, self.module.validate_registry(retired))
                self.assertEqual(original, retired)

    def test_validate_v3_enforces_source_frontier_provenance_independently(self):
        canonical_labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]

        def registry_with_frontiers(count):
            registry = self.module.make_registry("MXL", "ticker")
            for index in range(count):
                registry = self.module.create_frontier(
                    registry,
                    name=f"Frontier {index + 1}",
                    proposed_at_loop=index + 1,
                    source="initial",
                )
            return registry

        def validate_success(case, registry):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                self.assertIs(registry, self.module.validate_registry(registry))
                self.assertEqual(original, registry)

        def reject(case, registry):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(registry)
                self.assertEqual(original, registry)

        for source in ("initial", "user"):
            for source_frontier_state in ("missing", "null"):
                registry = registry_with_frontiers(1)
                frontier = registry["frontiers"][0]
                frontier["source"] = source
                if source_frontier_state == "missing":
                    frontier.pop("source_frontier")
                else:
                    frontier["source_frontier"] = None
                validate_success(f"{source}.{source_frontier_state}", registry)

            registry = registry_with_frontiers(2)
            registry["frontiers"][0]["source"] = source
            registry["frontiers"][0]["source_frontier"] = "F2"
            reject(f"{source}.non_null", registry)

        for source in ("discovery", "serendipity"):
            for source_frontier_state, source_frontier in (
                ("missing", None),
                ("null", None),
                ("self", "F2"),
                ("unknown", "F999"),
            ):
                registry = registry_with_frontiers(2)
                frontier = registry["frontiers"][1]
                frontier["source"] = source
                if source_frontier_state == "missing":
                    frontier.pop("source_frontier")
                else:
                    frontier["source_frontier"] = source_frontier
                reject(f"{source}.{source_frontier_state}", registry)

        forward_source = registry_with_frontiers(2)
        forward_source["layer_labels"] = canonical_labels
        child, later_source = forward_source["frontiers"]
        child["source"] = "discovery"
        child["source_frontier"] = "F2"
        child["layer"] = 1
        later_source["status"] = "Retired"
        later_source["retire_category"] = "blocked"
        later_source["layer"] = 5
        self._sync_lifecycle_to_status(later_source)
        validate_success("forward_retired_unrelated_source", forward_source)

        unbound = registry_with_frontiers(2)
        unbound["frontiers"][1]["source"] = "serendipity"
        unbound["frontiers"][1]["source_frontier"] = "F1"
        validate_success("valid_provenance_with_empty_layer_labels", unbound)

        independent_relations = registry_with_frontiers(3)
        independent_relations["layer_labels"] = canonical_labels
        source, parent, child = independent_relations["frontiers"]
        source["layer"] = 5
        parent["layer"] = 0
        child["source"] = "discovery"
        child["source_frontier"] = "F1"
        child["layer"] = 3
        child["parent_frontier"] = "F2"
        validate_success("different_valid_source_and_parent", independent_relations)

    def test_validate_v3_enforces_parent_relationships_whole_registry(self):
        canonical_labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]

        def registry_with_frontiers(count):
            registry = self.module.make_registry("MXL", "ticker")
            for index in range(count):
                registry = self.module.create_frontier(
                    registry,
                    name=f"Frontier {index + 1}",
                    proposed_at_loop=index + 1,
                    source="initial",
                )
            registry["layer_labels"] = canonical_labels
            return registry

        def validate_success(case, registry):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                self.assertIs(registry, self.module.validate_registry(registry))
                self.assertEqual(original, registry)

        def reject(case, registry):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(registry)
                self.assertEqual(original, registry)

        forward_retired_parent = registry_with_frontiers(2)
        child, later_parent = forward_retired_parent["frontiers"]
        child["layer"] = 5
        child["parent_frontier"] = "F2"
        later_parent["layer"] = 1
        later_parent["status"] = "Retired"
        later_parent["retire_category"] = "blocked"
        self._sync_lifecycle_to_status(later_parent)
        validate_success(
            "forward_retired_parent_with_layer_skip",
            forward_retired_parent,
        )

        null_parents = registry_with_frontiers(2)
        unbound, bound = null_parents["frontiers"]
        unbound["layer"] = None
        bound["source"] = "user"
        bound["layer"] = 4
        validate_success("null_parent_bound_and_unbound", null_parents)

        invalid_relationships = {
            "unknown_parent": (0, 2, "F999"),
            "self_parent": (None, 2, "F2"),
            "unbound_parent": (None, 2, "F1"),
            "unbound_child": (0, None, "F1"),
            "same_layer": (2, 2, "F1"),
            "deeper_parent": (4, 2, "F1"),
        }
        for case, (parent_layer, child_layer, parent_frontier) in invalid_relationships.items():
            registry = registry_with_frontiers(2)
            parent, child = registry["frontiers"]
            parent["layer"] = parent_layer
            child["layer"] = child_layer
            child["parent_frontier"] = parent_frontier
            reject(case, registry)

        invalid_pre_existing_child = registry_with_frontiers(3)
        first_child, parent, valid_later_child = invalid_pre_existing_child["frontiers"]
        first_child["layer"] = 2
        first_child["parent_frontier"] = "F2"
        parent["layer"] = 2
        valid_later_child["layer"] = 5
        valid_later_child["parent_frontier"] = "F2"
        reject("invalid_pre_existing_child_relationship", invalid_pre_existing_child)

        independent_relations = registry_with_frontiers(3)
        source, parent, child = independent_relations["frontiers"]
        source["layer"] = 5
        parent["layer"] = 0
        child["source"] = "serendipity"
        child["source_frontier"] = "F1"
        child["layer"] = 3
        child["parent_frontier"] = "F2"
        validate_success("different_valid_source_and_parent", independent_relations)

    def test_validate_v3_accepts_persisted_user_source(self):
        registry = self.v3_registry()
        registry["frontiers"][0]["source"] = "user"
        original = copy.deepcopy(registry)

        try:
            validated = self.module.validate_registry(registry)
        except self.module.LifecycleError as exc:
            self.fail(f"persisted source='user' must remain valid: {exc}")

        self.assertIs(registry, validated)
        self.assertEqual(original, registry)

    # ------------------------------------------------------------------
    # Task 6.2: strict nested-member validation (lifecycle / review /
    # evidence / portfolio actions). Every malformed nested member must be
    # rejected on ANY frontier (bound or unbound); a valid sibling must not
    # mask it; the input registry must never be mutated; only clean
    # LifecycleError may be raised.
    # ------------------------------------------------------------------

    def _two_frontier_v3_registry(self):
        """Return a configured v3 registry with two unbound New frontiers."""
        registry = self.configured_v3_registry(frontier_count=2)
        # configured_v3_registry leaves every frontier unbound (layer=None);
        # mirror the spec's canonical RED by making index 0 bound and
        # index 1 unbound so both code paths are exercised.
        registry["frontiers"][0]["layer"] = 0
        registry["frontiers"][0]["parent_frontier"] = None
        registry["frontiers"][1]["layer"] = None
        registry["frontiers"][1]["parent_frontier"] = None
        return registry

    def _canonical_lifecycle_row(self, **overrides):
        row = {"to": "Active", "at_loop": 1, "ts": "2026-01-01T00:00:00Z"}
        row.update(overrides)
        return row

    def _canonical_review_row(self, **overrides):
        row = {
            "review_number": 1,
            "at_loop": 3,
            "decision": "Continued",
            "retire_category": None,
            "rationale_short": "looks good",
            "portfolio_actions": [],
        }
        row.update(overrides)
        return row

    def _canonical_evidence_row(self, **overrides):
        row = {"claim": "InP concentration", "evidence_id": "E-17"}
        row.update(overrides)
        return row

    def test_v3_nested_member_validation_cannot_be_masked_by_a_valid_sibling(self):
        for field in ("lifecycle", "review_decisions", "evidence_pointers"):
            for malformed_index in (0, 1):
                with self.subTest(field=field, malformed_index=malformed_index):
                    registry = self.configured_v3_registry(frontier_count=2)
                    registry["frontiers"][0]["layer"] = 0
                    registry["frontiers"][0]["parent_frontier"] = None
                    registry["frontiers"][1]["layer"] = None
                    registry["frontiers"][1]["parent_frontier"] = None
                    registry["frontiers"][0][field] = []
                    registry["frontiers"][1][field] = []
                    registry["frontiers"][malformed_index][field] = [{"bogus": True}]
                    original = copy.deepcopy(registry)
                    with self.assertRaises(self.module.LifecycleError):
                        self.module.validate_registry(registry)
                    self.assertEqual(original, registry)

    def test_v3_lifecycle_member_strict_shape_rejections(self):
        cases = {
            "scalar_member": "not-a-dict",
            "missing_to_field": {"at_loop": 1, "ts": None},
            "missing_at_loop_field": {"to": "Active", "ts": None},
            "missing_ts_field": {"to": "Active", "at_loop": 1},
            "unknown_extra_key": {
                "to": "Active",
                "at_loop": 1,
                "ts": None,
                "extra": True,
            },
            "unsupported_status": {"to": "Archived", "at_loop": 1, "ts": None},
            "at_loop_not_int": {"to": "Active", "at_loop": "1", "ts": None},
            "at_loop_bool": {"to": "Active", "at_loop": True, "ts": None},
            "at_loop_negative": {"to": "Active", "at_loop": -1, "ts": None},
            "at_loop_float": {"to": "Active", "at_loop": 1.0, "ts": None},
            "ts_not_str_or_none": {"to": "Active", "at_loop": 1, "ts": 5},
            "ts_empty_string": {"to": "Active", "at_loop": 1, "ts": ""},
            "rationale_empty_string": {
                "to": "Active",
                "at_loop": 1,
                "ts": None,
                "rationale": "",
            },
            "rationale_wrong_type": {
                "to": "Active",
                "at_loop": 1,
                "ts": None,
                "rationale": 7,
            },
            "retire_category_on_non_retired": {
                "to": "Active",
                "at_loop": 1,
                "ts": None,
                "retire_category": "blocked",
            },
            "retire_category_unknown_vocab": {
                "to": "Retired",
                "at_loop": 1,
                "ts": None,
                "retire_category": "mystery",
            },
        }
        for name, malformed_row in cases.items():
            for malformed_index in (0, 1):
                with self.subTest(case=name, malformed_index=malformed_index):
                    registry = self._two_frontier_v3_registry()
                    registry["frontiers"][0]["lifecycle"] = []
                    registry["frontiers"][1]["lifecycle"] = []
                    registry["frontiers"][malformed_index]["lifecycle"].append(
                        malformed_row
                    )
                    original = copy.deepcopy(registry)
                    with self.assertRaises(self.module.LifecycleError):
                        self.module.validate_registry(registry)
                    self.assertEqual(original, registry)

    def test_v3_lifecycle_timestamp_monotonicity(self):
        # Rule: when there is more than one lifecycle row, every ts must be a
        # non-null string and the ts values must be non-decreasing (compared as
        # strings). A None ts is only permitted for a single-row lifecycle.
        registry = self._two_frontier_v3_registry()
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts="2026-06-22T00:00:00Z"),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-20T00:00:00Z"
            ),
        ]
        registry["frontiers"][0]["status"] = "Active"
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_lifecycle_none_ts_is_unorderable_and_accepted_among_nulls(self):
        # Documented rule: a None ts is unorderable; monotonicity is enforced
        # only over the subsequence of non-null ts values. So multiple None-ts
        # rows are accepted (writer seeding shape), but a later non-null ts
        # that decreases relative to an earlier non-null ts is rejected.
        registry = self._two_frontier_v3_registry()
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts=None),
            self._canonical_lifecycle_row(to="Active", at_loop=1, ts=None),
        ]
        registry["frontiers"][0]["status"] = "Active"
        original_accepted = copy.deepcopy(registry)
        result = self.module.validate_registry(registry)
        self.assertIs(registry, result)
        self.assertEqual(original_accepted, registry)

        # A decreasing non-null ts pair must still be rejected.
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(
                to="New", at_loop=1, ts="2026-06-22T00:00:00Z"
            ),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-20T00:00:00Z"
            ),
        ]
        registry["frontiers"][0]["status"] = "Active"
        original_rejected = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original_rejected, registry)

    def test_v3_final_lifecycle_to_must_equal_persisted_status(self):
        registry = self._two_frontier_v3_registry()
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts="2026-06-22T00:00:00Z"),
            self._canonical_lifecycle_row(
                to="Continued", at_loop=3, ts="2026-06-24T00:00:00Z"
            ),
        ]
        # persisted status disagrees with final lifecycle to ("Continued")
        registry["frontiers"][0]["status"] = "Active"
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_review_member_strict_shape_rejections(self):
        base = self._canonical_review_row()
        cases = {
            "scalar_member": "not-a-dict",
            "missing_review_number": {k: v for k, v in base.items() if k != "review_number"},
            "missing_decision": {k: v for k, v in base.items() if k != "decision"},
            "missing_portfolio_actions": {
                k: v for k, v in base.items() if k != "portfolio_actions"
            },
            "unknown_extra_key": {**base, "extra": True},
            "review_number_not_int": {**base, "review_number": "1"},
            "review_number_bool": {**base, "review_number": True},
            "review_number_below_one": {**base, "review_number": 0},
            "at_loop_not_int": {**base, "at_loop": "3"},
            "at_loop_below_one": {**base, "at_loop": 0},
            "unsupported_decision": {**base, "decision": "Paused"},
            "retire_category_set_when_not_retired": {
                **base,
                "decision": "Continued",
                "retire_category": "answered_out",
            },
            "retire_category_unknown_vocab_when_retired": {
                **base,
                "decision": "Retired",
                "retire_category": "mystery",
            },
            "rationale_short_empty_string": {**base, "rationale_short": ""},
            "rationale_short_wrong_type": {**base, "rationale_short": 9},
            "portfolio_actions_not_list": {**base, "portfolio_actions": "x"},
        }
        for name, malformed_row in cases.items():
            for malformed_index in (0, 1):
                with self.subTest(case=name, malformed_index=malformed_index):
                    registry = self._two_frontier_v3_registry()
                    for frontier in registry["frontiers"]:
                        frontier["review_decisions"] = []
                        frontier["review_count"] = 0
                    registry["frontiers"][malformed_index]["review_decisions"].append(
                        malformed_row
                    )
                    original = copy.deepcopy(registry)
                    with self.assertRaises(self.module.LifecycleError):
                        self.module.validate_registry(registry)
                    self.assertEqual(original, registry)

    def test_v3_review_number_must_be_strictly_increasing_from_one(self):
        registry = self._two_frontier_v3_registry()
        for frontier in registry["frontiers"]:
            frontier["review_decisions"] = []
            frontier["review_count"] = 2
        registry["frontiers"][0]["review_decisions"] = [
            self._canonical_review_row(review_number=1, at_loop=3),
            self._canonical_review_row(review_number=2, at_loop=3),
        ]
        # sibling with a nonsequential review_number (skips 1)
        registry["frontiers"][1]["review_decisions"] = [
            self._canonical_review_row(review_number=2, at_loop=3),
        ]
        registry["frontiers"][1]["review_count"] = 1
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_review_at_loop_must_be_nondecreasing(self):
        registry = self._two_frontier_v3_registry()
        for frontier in registry["frontiers"]:
            frontier["review_decisions"] = []
            frontier["review_count"] = 2
        registry["frontiers"][0]["review_decisions"] = [
            self._canonical_review_row(review_number=1, at_loop=6),
            self._canonical_review_row(review_number=2, at_loop=3),  # decreases
        ]
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_review_count_must_equal_len_review_decisions(self):
        registry = self._two_frontier_v3_registry()
        for frontier in registry["frontiers"]:
            frontier["review_decisions"] = []
            frontier["review_count"] = 0
        registry["frontiers"][0]["review_decisions"] = [
            self._canonical_review_row(review_number=1, at_loop=3),
        ]
        # review_count disagrees with the actual number of rows
        registry["frontiers"][0]["review_count"] = 2
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_review_decision_must_match_a_lifecycle_transition(self):
        registry = self._two_frontier_v3_registry()
        for frontier in registry["frontiers"]:
            frontier["review_decisions"] = []
            frontier["review_count"] = 1
        # frontier 0 has a lifecycle that ends in Continued at loop 3 ...
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts="2026-06-22T00:00:00Z"),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-22T00:00:00Z"
            ),
            self._canonical_lifecycle_row(
                to="Continued", at_loop=3, ts="2026-06-24T00:00:00Z"
            ),
        ]
        registry["frontiers"][0]["status"] = "Continued"
        # ... but the review row claims a Continued decision at a loop that
        # has no matching lifecycle transition.
        registry["frontiers"][0]["review_decisions"] = [
            self._canonical_review_row(review_number=1, at_loop=9, decision="Continued"),
        ]
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_max_reviews_bound_enforced_on_review_rows(self):
        registry = self._two_frontier_v3_registry()
        for frontier in registry["frontiers"]:
            frontier["review_decisions"] = []
            frontier["review_count"] = 1
            frontier["max_reviews"] = 1
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts="2026-06-22T00:00:00Z"),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-22T00:00:00Z"
            ),
            self._canonical_lifecycle_row(
                to="Continued", at_loop=3, ts="2026-06-24T00:00:00Z"
            ),
        ]
        registry["frontiers"][0]["status"] = "Continued"
        registry["frontiers"][0]["review_decisions"] = [
            # review_number 2 exceeds max_reviews=1
            self._canonical_review_row(review_number=2, at_loop=3, decision="Continued"),
        ]
        registry["frontiers"][0]["review_count"] = 2
        original = copy.deepcopy(registry)
        with self.assertRaises(self.module.LifecycleError):
            self.module.validate_registry(registry)
        self.assertEqual(original, registry)

    def test_v3_portfolio_action_strict_shape_rejections(self):
        add_action = {
            "action": "add",
            "frontier": "F9",
            "source": "discovery",
            "source_frontier": "F1",
            "reason": "new evidence",
        }
        retire_action = {
            "action": "retire",
            "frontier": "F2",
            "category": "blocked",
            "reason": "done",
        }
        reprioritize_action = {
            "action": "reprioritize",
            "frontier": "F3",
            "priority": "high",
            "reason": "reorder",
        }
        reject_action = {
            "action": "reject",
            "candidate": "F4",
            "reason": "no fit",
        }
        cases = {
            "unknown_action": {"action": "promote", "frontier": "F1", "reason": "x"},
            "missing_action_key": {"frontier": "F1", "reason": "x"},
            "add_missing_reason": {
                "action": "add",
                "frontier": "F9",
                "source": "discovery",
                "source_frontier": "F1",
            },
            "add_extra_key": {**add_action, "extra": True},
            "add_bad_source_vocab": {**add_action, "source": "rumour"},
            "add_bad_frontier_shape": {**add_action, "frontier": "f9"},
            "add_empty_reason": {**add_action, "reason": ""},
            "retire_missing_category": {
                "action": "retire",
                "frontier": "F2",
                "reason": "done",
            },
            "retire_bad_category_vocab": {**retire_action, "category": "mystery"},
            "reprioritize_missing_priority": {
                "action": "reprioritize",
                "frontier": "F3",
                "reason": "reorder",
            },
            "reprioritize_empty_priority": {**reprioritize_action, "priority": ""},
            "reject_missing_candidate": {
                "action": "reject",
                "reason": "no fit",
            },
            "reject_empty_reason": {**reject_action, "reason": ""},
        }
        for name, malformed_action in cases.items():
            for malformed_index in (0, 1):
                with self.subTest(case=name, malformed_index=malformed_index):
                    registry = self._two_frontier_v3_registry()
                    for frontier in registry["frontiers"]:
                        frontier["review_decisions"] = []
                        frontier["review_count"] = 0
                    registry["frontiers"][malformed_index]["review_decisions"] = [
                        self._canonical_review_row(
                            review_number=1, at_loop=3, decision="Continued"
                        )
                    ]
                    registry["frontiers"][malformed_index]["review_count"] = 1
                    registry["frontiers"][malformed_index]["review_decisions"][0][
                        "portfolio_actions"
                    ] = [malformed_action]
                    original = copy.deepcopy(registry)
                    with self.assertRaises(self.module.LifecycleError):
                        self.module.validate_registry(registry)
                    self.assertEqual(original, registry)

    def test_v3_evidence_member_strict_shape_rejections(self):
        cases = {
            "scalar_member": "not-a-dict",
            "missing_claim": {"evidence_id": "E-17"},
            "missing_evidence_id": {"claim": "InP concentration"},
            "unknown_extra_key": {
                "claim": "InP concentration",
                "evidence_id": "E-17",
                "extra": True,
            },
            "claim_empty_string": {"claim": "", "evidence_id": "E-17"},
            "claim_wrong_type": {"claim": 5, "evidence_id": "E-17"},
            "evidence_id_empty_string": {"claim": "InP concentration", "evidence_id": ""},
            "claim_multiline": {
                "claim": "line one\nline two",
                "evidence_id": "E-17",
            },
            "evidence_id_multiline": {
                "claim": "InP concentration",
                "evidence_id": "E-17\nE-18",
            },
        }
        for name, malformed_row in cases.items():
            for malformed_index in (0, 1):
                with self.subTest(case=name, malformed_index=malformed_index):
                    registry = self._two_frontier_v3_registry()
                    registry["frontiers"][0]["evidence_pointers"] = []
                    registry["frontiers"][1]["evidence_pointers"] = []
                    registry["frontiers"][malformed_index]["evidence_pointers"].append(
                        malformed_row
                    )
                    original = copy.deepcopy(registry)
                    with self.assertRaises(self.module.LifecycleError):
                        self.module.validate_registry(registry)
                    self.assertEqual(original, registry)

    def test_v3_canonical_writer_shapes_still_validate(self):
        # The exact shapes the existing writers produce MUST still validate.
        registry = self._two_frontier_v3_registry()
        registry["frontiers"][0]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts=None),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-22T00:00:00Z"
            ),
        ]
        registry["frontiers"][0]["status"] = "Active"
        registry["frontiers"][0]["retire_category"] = None
        registry["frontiers"][1]["lifecycle"] = [
            self._canonical_lifecycle_row(to="New", at_loop=1, ts=None),
            self._canonical_lifecycle_row(
                to="Active", at_loop=1, ts="2026-06-22T00:00:00Z"
            ),
            self._canonical_lifecycle_row(
                to="Continued", at_loop=3, ts="2026-06-24T00:00:00Z"
            ),
            self._canonical_lifecycle_row(
                to="Retired",
                at_loop=6,
                ts="2026-06-27T00:00:00Z",
                retire_category="blocked",
            ),
        ]
        registry["frontiers"][1]["status"] = "Retired"
        registry["frontiers"][1]["retire_category"] = "blocked"
        registry["frontiers"][1]["review_count"] = 1
        registry["frontiers"][1]["review_decisions"] = [
            self._canonical_review_row(
                review_number=1,
                at_loop=3,
                decision="Continued",
                retire_category=None,
                rationale_short=None,
                portfolio_actions=[
                    {
                        "action": "add",
                        "frontier": "F9",
                        "source": "discovery",
                        "source_frontier": "F2",
                        "reason": "spinoff",
                    },
                    {
                        "action": "retire",
                        "frontier": "F2",
                        "category": "blocked",
                        "reason": "exhausted",
                    },
                    {
                        "action": "reprioritize",
                        "frontier": "F2",
                        "priority": "watch",
                        "reason": "demote",
                    },
                    {
                        "action": "reject",
                        "candidate": "F10",
                        "reason": "out of scope",
                    },
                ],
            )
        ]
        registry["frontiers"][1]["evidence_pointers"] = [
            self._canonical_evidence_row(),
        ]
        original = copy.deepcopy(registry)
        result = self.module.validate_registry(registry)
        self.assertIs(registry, result)
        self.assertEqual(original, registry)

    def test_v3_optional_nested_collections_remain_optional(self):
        # A frontier with no nested key, or an empty list, is still valid.
        registry = self._two_frontier_v3_registry()
        del registry["frontiers"][0]["lifecycle"]
        del registry["frontiers"][0]["review_decisions"]
        del registry["frontiers"][0]["evidence_pointers"]
        registry["frontiers"][1]["lifecycle"] = []
        registry["frontiers"][1]["review_decisions"] = []
        registry["frontiers"][1]["evidence_pointers"] = []
        original = copy.deepcopy(registry)
        result = self.module.validate_registry(registry)
        self.assertIs(registry, result)
        self.assertEqual(original, registry)

    def test_set_layer_labels_adopts_v2_without_inference_or_history_loss(self):
        registry = self.registry()
        # Seed legacy nested rows that ARE representable under the strict v3
        # schema. Adoption must preserve them byte-for-byte and only add
        # layer=None / parent_frontier=None.
        registry["frontiers"][0]["status"] = "Continued"
        registry["frontiers"][0]["review_count"] = 1
        registry["frontiers"][0]["lifecycle"] = [
            {"to": "New", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
            {"to": "Active", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
            {"to": "Continued", "at_loop": 3, "ts": "2026-06-25T00:00:00Z"},
        ]
        registry["frontiers"][0]["review_decisions"] = [
            {
                "review_number": 1,
                "at_loop": 3,
                "decision": "Continued",
                "retire_category": None,
                "rationale_short": "Supplier evidence remains incomplete",
                "portfolio_actions": [],
            }
        ]
        registry["frontiers"][0]["evidence_pointers"] = [
            {"claim": "InP concentration", "evidence_id": "E-17"}
        ]
        registry["frontiers"][1]["source"] = "discovery"
        registry["frontiers"][1]["source_frontier"] = "F1"
        registry["frontiers"][1]["status"] = "Continued"
        registry["frontiers"][1]["review_count"] = 1
        registry["frontiers"][1]["lifecycle"] = [
            {"to": "New", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
            {"to": "Active", "at_loop": 1, "ts": "2026-06-22T00:00:00Z"},
            {"to": "Continued", "at_loop": 4, "ts": "2026-06-26T00:00:00Z"},
        ]
        registry["frontiers"][1]["review_decisions"] = [
            {
                "review_number": 1,
                "at_loop": 4,
                "decision": "Continued",
                "retire_category": None,
                "rationale_short": "Branch still productive",
                "portfolio_actions": [],
            }
        ]
        registry["portfolio_actions"] = [
            {
                "action": "continue",
                "frontier": "F1",
                "at_loop": 3,
                "reason": "Preserve the full decision history",
            }
        ]
        indexed_labels = [
            (0, "End demand"),
            (1, "System or platform"),
            (2, "Component or module"),
            (3, "Material or process"),
            (4, "Constrained input or equipment"),
            (5, "Geography or regulation"),
        ]
        original = copy.deepcopy(registry)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        updated = self.module.set_layer_labels(registry, indexed_labels)

        expected = copy.deepcopy(original)
        expected["version"] = 3
        expected["layer_labels"] = [label for _, label in indexed_labels]
        for frontier in expected["frontiers"]:
            frontier["layer"] = None
            frontier["parent_frontier"] = None
        self.assertEqual(expected, updated)
        self.assertEqual(original, registry)
        self.assertEqual(original_indexed_labels, indexed_labels)
        self.assertIsNot(registry, updated)
        for before, after in zip(registry["frontiers"], updated["frontiers"]):
            self.assertIsNot(before, after)
        self.assertEqual("F1", updated["frontiers"][1]["source_frontier"])
        self.assertIsNone(updated["frontiers"][1]["parent_frontier"])
        self.assertIs(updated, self.module.validate_registry(updated))

    def test_set_layer_labels_adoption_fails_atomically_on_unrepresentable_legacy_row(self):
        # A legacy nested row that is NOT representable under the strict v3
        # schema must make adoption FAIL ATOMICALLY: raise LifecycleError,
        # do not mutate the input registry, do not normalize/skip/migrate.
        registry = self.registry()
        # Old non-v3 review shape (lowercase "continue", key "reason", missing
        # the six canonical keys) is unrepresentable under strict v3.
        registry["frontiers"][0]["review_decisions"] = [
            {
                "decision": "continue",
                "at_loop": 3,
                "reason": "Supplier evidence remains incomplete",
            }
        ]
        indexed_labels = [
            (0, "End demand"),
            (1, "System or platform"),
            (2, "Component or module"),
            (3, "Material or process"),
            (4, "Constrained input or equipment"),
            (5, "Geography or regulation"),
        ]
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.LifecycleError):
            self.module.set_layer_labels(registry, indexed_labels)

        # Adoption must not mutate the input registry on failure.
        self.assertEqual(original, registry)
        self.assertEqual(2, registry["version"])
        self.assertNotIn("layer_labels", registry)

    def test_v2_ordinary_validation_adds_only_version_and_mixed_schema_checks(self):
        ordinary_cases = [
            self.registry(),
            {"version": 2},
            {
                "version": 2,
                "subject": None,
                "mode": "legacy-extension-mode",
                "frontiers": [
                    None,
                    {
                        "id": "legacy-id",
                        "source": "user",
                        "unknown_frontier_extension": {"preserve": True},
                    },
                ],
                "portfolio_limits": "legacy-value-left-to-existing-operations",
                "unknown_top_level_extension": ["preserve", "order"],
            },
            {"version": 2, "frontiers": "not-a-list-left-to-existing-operations"},
        ]
        for registry in ordinary_cases:
            original = copy.deepcopy(registry)
            with self.subTest(ordinary=registry):
                self.assertIs(registry, self.module.validate_registry(registry))
                self.assertEqual(original, registry)

        mixed_cases = [
            {"version": 2, "layer_labels": None},
            {"version": 2, "frontiers": [{"id": "F1", "layer": None}]},
            {"version": 2, "frontiers": [{"id": "F1", "parent_frontier": None}]},
        ]
        for registry in mixed_cases:
            original = copy.deepcopy(registry)
            with self.subTest(mixed=registry):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(registry)
                self.assertEqual(original, registry)

        for version in (None, "2", True):
            registry = {} if version is None else {"version": version}
            original = copy.deepcopy(registry)
            with self.subTest(invalid_version=version):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.validate_registry(registry)
                self.assertEqual(original, registry)

    def test_set_layer_labels_canonicalizes_and_validates_six_indexed_labels(self):
        indexed_labels = [
            (5, " Geography | regulation "),
            (2, " Component or module "),
            (0, " End demand "),
            (4, " Constrained input or equipment "),
            (1, " System or platform "),
            (3, " Material or process "),
        ]
        expected_labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography | regulation",
        ]
        registry = self.registry()
        original_registry = copy.deepcopy(registry)
        original_labels = copy.deepcopy(indexed_labels)

        updated = self.module.set_layer_labels(registry, indexed_labels)

        self.assertEqual(expected_labels, updated["layer_labels"])
        self.assertEqual(original_registry, registry)
        self.assertEqual(original_labels, indexed_labels)

        def with_index(original_index, replacement_index):
            return [
                (replacement_index if index == original_index else index, label)
                for index, label in indexed_labels
            ]

        invalid_indexes = {
            "index_missing": indexed_labels[:-1],
            "index_duplicate": [*indexed_labels, (0, "Duplicate index")],
            "index_negative": with_index(5, -1),
            "index_too_high": with_index(5, 6),
            "index_extra": [*indexed_labels, (6, "Extra")],
            "index_bool": with_index(1, True),
            "index_float": with_index(1, 1.0),
            "index_string": with_index(1, "1"),
        }

        def with_label(target_index, replacement_label):
            return [
                (index, replacement_label if index == target_index else label)
                for index, label in indexed_labels
            ]

        invalid_labels = {
            "label_bool": with_label(0, True),
            "label_integer": with_label(0, 1),
            "label_blank": with_label(0, "   "),
            "label_newline": with_label(0, "End\ndemand"),
            "label_carriage_return": with_label(0, "End\rdemand"),
            "label_unicode_line_separator": with_label(0, "End\u2028demand"),
            "label_unicode_paragraph_separator": with_label(0, "End\u2029demand"),
            "label_control_character": with_label(0, "End\x00demand"),
            "label_tab_control_character": with_label(0, "End\tdemand"),
            "label_leading_newline": with_label(0, "\nEnd demand"),
            "label_trailing_carriage_return": with_label(0, "End demand\r"),
            "label_leading_unicode_line_separator": with_label(0, "\u2028End demand"),
            "label_trailing_unicode_paragraph_separator": with_label(0, "End demand\u2029"),
            "label_leading_tab_control_character": with_label(0, "\tEnd demand"),
            "label_ascii_casefold_duplicate": with_label(0, "system OR PLATFORM"),
        }
        invalid_labels["label_unicode_casefold_duplicate"] = with_label(1, "STRASSE")
        invalid_labels["label_unicode_casefold_duplicate"][2] = (0, "Stra\u00dfe")

        for case, invalid in {**invalid_indexes, **invalid_labels}.items():
            registry = self.registry()
            original_registry = copy.deepcopy(registry)
            original_labels = copy.deepcopy(invalid)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.set_layer_labels(registry, invalid)
                self.assertEqual(original_registry, registry)
                self.assertEqual(original_labels, invalid)

    def test_set_layer_labels_v3_idempotence_replace_and_copy_on_write(self):
        labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        indexed_labels = list(enumerate(labels))

        unconfigured = self.v3_registry()
        unconfigured["extension"] = {"preserve": ["nested", "value"]}
        original_unconfigured = copy.deepcopy(unconfigured)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        configured = self.module.set_layer_labels(unconfigured, indexed_labels)

        expected_configured = copy.deepcopy(original_unconfigured)
        expected_configured["layer_labels"] = labels
        self.assertEqual(expected_configured, configured)
        self.assertEqual(original_unconfigured, unconfigured)
        self.assertEqual(original_indexed_labels, indexed_labels)
        self.assertIsNot(unconfigured, configured)
        self.assertIsNot(unconfigured["frontiers"][0], configured["frontiers"][0])
        self.assertIs(configured, self.module.validate_registry(configured))

        configured["frontiers"][0]["layer"] = 2
        original_configured = copy.deepcopy(configured)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        repeated = self.module.set_layer_labels(configured, indexed_labels)

        self.assertEqual(original_configured, repeated)
        self.assertEqual(original_configured, configured)
        self.assertEqual(original_indexed_labels, indexed_labels)
        self.assertIsNot(configured, repeated)
        self.assertIsNot(configured["frontiers"][0], repeated["frontiers"][0])
        self.assertIs(repeated, self.module.validate_registry(repeated))

        replacement_labels = ["Demand", *labels[1:]]
        replacement_indexed_labels = list(enumerate(replacement_labels))
        original_configured = copy.deepcopy(configured)
        original_replacement_labels = copy.deepcopy(replacement_indexed_labels)
        with self.assertRaises(self.module.LifecycleError):
            self.module.set_layer_labels(configured, replacement_indexed_labels)
        self.assertEqual(original_configured, configured)
        self.assertEqual(original_replacement_labels, replacement_indexed_labels)

        bound = self.module.make_registry("MXL", "ticker")
        bound = self.module.create_frontier(
            bound,
            name="Supply concentration",
            proposed_at_loop=1,
            source="initial",
            initial_status="Active",
        )
        bound = self.module.create_frontier(
            bound,
            name="Qualification dependency",
            proposed_at_loop=2,
            source="discovery",
            source_frontier="F1",
        )
        bound["layer_labels"] = labels
        bound["frontiers"][0]["layer"] = 0
        bound["frontiers"][1]["layer"] = 4
        bound["frontiers"][1]["parent_frontier"] = "F1"
        bound.pop("portfolio_limits")
        bound.pop("review_trigger")
        for optional in ("review_count", "max_reviews", "retire_category", "evidence_pointers"):
            bound["frontiers"][1].pop(optional)
        bound["extension"] = {"crlf_value": "line one\r\nline two"}
        bound["frontiers"][1]["extension"] = {"owner": "research"}
        self.module.validate_registry(bound)
        original_bound = copy.deepcopy(bound)
        original_replacement_labels = copy.deepcopy(replacement_indexed_labels)

        replaced = self.module.set_layer_labels(
            bound,
            replacement_indexed_labels,
            replace=True,
        )

        expected_replaced = copy.deepcopy(original_bound)
        expected_replaced["layer_labels"] = replacement_labels
        self.assertEqual(expected_replaced, replaced)
        self.assertEqual(original_bound, bound)
        self.assertEqual(original_replacement_labels, replacement_indexed_labels)
        self.assertIsNot(bound, replaced)
        for before, after in zip(bound["frontiers"], replaced["frontiers"]):
            self.assertIsNot(before, after)
        self.assertEqual([0, 4], [frontier["layer"] for frontier in replaced["frontiers"]])
        self.assertEqual("F1", replaced["frontiers"][1]["parent_frontier"])
        self.assertEqual("F1", replaced["frontiers"][1]["source_frontier"])
        self.assertNotIn("portfolio_limits", replaced)
        self.assertNotIn("review_trigger", replaced)
        self.assertNotIn("review_count", replaced["frontiers"][1])
        self.assertIs(replaced, self.module.validate_registry(replaced))

    def test_v2_adoption_preserves_unknown_extensions_defaults_and_user_source(self):
        labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        indexed_labels = list(enumerate(labels))
        registry = self.registry()
        registry["unknown_top_level_extension"] = {
            "raw_note": "line one\r\nline two",
            "ordered_values": ["alpha", "beta"],
            "nested": {"enabled": True, "threshold": 0},
        }
        registry["frontiers"][0]["unknown_frontier_extension"] = {
            "owner": "research",
            "tags": ["supply", "qualification"],
        }
        registry["frontiers"][1]["source"] = "user"
        registry["frontiers"][1]["source_frontier"] = None
        registry["frontiers"][1]["unknown_frontier_extension"] = {
            "user_note": "keep verbatim"
        }
        registry = json.loads(json.dumps(registry, indent=2).replace("\n", "\r\n"))
        original_registry = copy.deepcopy(registry)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        updated = self.module.set_layer_labels(registry, indexed_labels)

        expected = copy.deepcopy(original_registry)
        expected["version"] = 3
        expected["layer_labels"] = labels
        for frontier in expected["frontiers"]:
            frontier["layer"] = None
            frontier["parent_frontier"] = None
        self.assertEqual(expected, updated)
        self.assertEqual(original_registry, registry)
        self.assertEqual(original_indexed_labels, indexed_labels)
        self.assertEqual(
            original_registry["unknown_top_level_extension"],
            updated["unknown_top_level_extension"],
        )
        self.assertEqual("user", updated["frontiers"][1]["source"])
        self.assertIsNone(updated["frontiers"][1]["source_frontier"])
        self.assertEqual(["F1", "F2"], [frontier["id"] for frontier in updated["frontiers"]])
        self.assertIs(updated, self.module.validate_registry(updated))

    def test_v2_adoption_preserves_optional_omissions_without_materializing_defaults(self):
        registry = {
            "version": 2,
            "subject": "MXL",
            "mode": "ticker",
            "frontiers": [
                {
                    "id": "F1",
                    "name": "User-supplied frontier",
                    "proposed_at_loop": 1,
                    "source": "user",
                    "status": "New",
                }
            ],
            "extension": {"preserve": "without defaults"},
        }
        labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        indexed_labels = list(enumerate(labels))
        original_registry = copy.deepcopy(registry)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        updated = self.module.set_layer_labels(registry, indexed_labels)

        expected = copy.deepcopy(original_registry)
        expected["version"] = 3
        expected["layer_labels"] = labels
        expected["frontiers"][0]["layer"] = None
        expected["frontiers"][0]["parent_frontier"] = None
        self.assertEqual(expected, updated)
        self.assertEqual(original_registry, registry)
        self.assertEqual(original_indexed_labels, indexed_labels)
        for optional in ("portfolio_limits", "review_trigger"):
            self.assertNotIn(optional, updated)
        for optional in (
            "source_frontier",
            "review_count",
            "max_reviews",
            "retire_category",
            "lifecycle",
            "review_decisions",
            "evidence_pointers",
        ):
            self.assertNotIn(optional, updated["frontiers"][0])
        self.assertIs(updated, self.module.validate_registry(updated))

    def test_v2_adoption_rejects_ambiguous_or_nonconvertible_ids_without_writes(self):
        labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        indexed_labels = list(enumerate(labels))

        def without_frontier_field(field):
            registry = self.registry()
            registry["frontiers"][0].pop(field)
            return registry

        def with_frontier_field(field, value):
            registry = self.registry()
            registry["frontiers"][0][field] = value
            return registry

        cases = {
            "id_missing": without_frontier_field("id"),
            "id_bool": with_frontier_field("id", True),
            "id_integer": with_frontier_field("id", 1),
            "id_unprefixed": with_frontier_field("id", "1"),
            "id_zero": with_frontier_field("id", "F0"),
            "id_leading_zero": with_frontier_field("id", "F01"),
            "id_negative": with_frontier_field("id", "F-1"),
            "name_missing": without_frontier_field("name"),
            "name_non_string": with_frontier_field("name", None),
            "proposed_at_loop_missing": without_frontier_field("proposed_at_loop"),
            "proposed_at_loop_bool": with_frontier_field("proposed_at_loop", True),
            "proposed_at_loop_string": with_frontier_field("proposed_at_loop", "1"),
            "proposed_at_loop_zero": with_frontier_field("proposed_at_loop", 0),
            "source_missing": without_frontier_field("source"),
            "source_unknown": with_frontier_field("source", "manual"),
            "status_missing": without_frontier_field("status"),
            "status_noncanonical": with_frontier_field("status", "active"),
            "review_count_bool": with_frontier_field("review_count", True),
            "max_reviews_negative": with_frontier_field("max_reviews", -1),
            "lifecycle_non_list": with_frontier_field("lifecycle", {}),
            "review_decisions_non_list": with_frontier_field("review_decisions", {}),
            "evidence_pointers_non_list": with_frontier_field("evidence_pointers", {}),
            "portfolio_limits_non_object": {
                **self.registry(),
                "portfolio_limits": "3/5",
            },
            "review_trigger_non_object": {
                **self.registry(),
                "review_trigger": "every three loops",
            },
            "frontiers_non_list": {
                **self.registry(),
                "frontiers": {"F1": "not a list"},
            },
            "frontier_non_object": {
                **self.registry(),
                "frontiers": [None],
            },
            "subject_missing": {
                key: value for key, value in self.registry().items() if key != "subject"
            },
            "subject_non_string": {
                **self.registry(),
                "subject": None,
            },
            "mode_missing": {
                key: value for key, value in self.registry().items() if key != "mode"
            },
            "mode_unknown": {
                **self.registry(),
                "mode": "legacy-mode",
            },
        }
        duplicate = self.registry()
        duplicate["frontiers"][1]["id"] = "F1"
        cases["id_duplicate"] = duplicate
        retired_without_category = self.registry()
        retired_without_category["frontiers"][0]["status"] = "Retired"
        retired_without_category["frontiers"][0].pop("retire_category")
        cases["retired_without_category"] = retired_without_category
        active_with_category = self.registry()
        active_with_category["frontiers"][0]["retire_category"] = "blocked"
        cases["active_with_retire_category"] = active_with_category
        invalid_limit = self.registry()
        invalid_limit["portfolio_limits"]["max_active"] = True
        cases["portfolio_limit_bool"] = invalid_limit
        invalid_trigger = self.registry()
        invalid_trigger["review_trigger"] = {"every_loops": 0}
        cases["review_trigger_zero"] = invalid_trigger

        for case, registry in cases.items():
            original_registry = copy.deepcopy(registry)
            original_indexed_labels = copy.deepcopy(indexed_labels)
            with self.subTest(case=case):
                self.assertIs(registry, self.module.validate_registry(registry))
                with self.assertRaises(self.module.LifecycleError):
                    self.module.set_layer_labels(registry, indexed_labels)
                self.assertEqual(original_registry, registry)
                self.assertEqual(original_indexed_labels, indexed_labels)

    def test_v2_adoption_rejects_incoherent_source_frontier_without_parent_inference(self):
        labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]
        indexed_labels = list(enumerate(labels))

        invalid_cases = {}
        for source in ("discovery", "serendipity"):
            for source_frontier_state, source_frontier in (
                ("missing", None),
                ("null", None),
                ("self", "F2"),
                ("unknown", "F999"),
            ):
                registry = self.registry()
                frontier = registry["frontiers"][1]
                frontier["source"] = source
                if source_frontier_state == "missing":
                    frontier.pop("source_frontier")
                else:
                    frontier["source_frontier"] = source_frontier
                invalid_cases[f"{source}.{source_frontier_state}"] = registry

        for source in ("initial", "user"):
            registry = self.registry()
            registry["frontiers"][1]["source"] = source
            registry["frontiers"][1]["source_frontier"] = "F1"
            invalid_cases[f"{source}.non_null"] = registry

        for case, registry in invalid_cases.items():
            original_registry = copy.deepcopy(registry)
            original_indexed_labels = copy.deepcopy(indexed_labels)
            with self.subTest(case=case):
                self.assertIs(registry, self.module.validate_registry(registry))
                with self.assertRaises(self.module.LifecycleError):
                    self.module.set_layer_labels(registry, indexed_labels)
                self.assertEqual(original_registry, registry)
                self.assertEqual(original_indexed_labels, indexed_labels)

        valid = self.registry()
        valid["frontiers"][1]["source"] = "discovery"
        valid["frontiers"][1]["source_frontier"] = "F1"
        original_valid = copy.deepcopy(valid)
        original_indexed_labels = copy.deepcopy(indexed_labels)

        adopted = self.module.set_layer_labels(valid, indexed_labels)

        expected = copy.deepcopy(original_valid)
        expected["version"] = 3
        expected["layer_labels"] = labels
        for frontier in expected["frontiers"]:
            frontier["layer"] = None
            frontier["parent_frontier"] = None
        self.assertEqual(expected, adopted)
        self.assertEqual(original_valid, valid)
        self.assertEqual(original_indexed_labels, indexed_labels)
        self.assertEqual("F1", adopted["frontiers"][1]["source_frontier"])
        self.assertIsNone(adopted["frontiers"][1]["parent_frontier"])
        self.assertIsNone(adopted["frontiers"][1]["layer"])
        self.assertIs(adopted, self.module.validate_registry(adopted))

    def test_make_registry_creates_v3_with_empty_layer_labels(self):
        registry = self.module.make_registry("MXL", "ticker")

        self.assertEqual(
            {"version": 3, "layer_labels": []},
            {key: registry.get(key) for key in ("version", "layer_labels")},
        )

    def test_create_frontier_in_v3_defaults_layer_and_parent_to_none(self):
        registry = self.module.make_registry("MXL", "ticker")

        updated = self.module.create_frontier(
            registry,
            name="InP substrate supply concentration",
            proposed_at_loop=1,
            source="initial",
        )
        frontier = self.module.get_frontier(updated, "F1")

        required_keys = {"layer", "parent_frontier"}
        self.assertEqual(required_keys, required_keys.intersection(frontier))
        self.assertIsNone(frontier["layer"])
        self.assertIsNone(frontier["parent_frontier"])

    def test_create_frontier_validates_v3_input_and_complete_post_state(self):
        canonical_labels = [
            "End demand",
            "System or platform",
            "Component or module",
            "Material or process",
            "Constrained input or equipment",
            "Geography or regulation",
        ]

        invalid_provenance = self.v3_registry()
        invalid_provenance["frontiers"][0]["source"] = "discovery"
        invalid_provenance["frontiers"][0]["source_frontier"] = "F999"

        invalid_parent = self.v3_registry()
        invalid_parent["layer_labels"] = canonical_labels
        invalid_parent["frontiers"][0]["layer"] = 1
        invalid_parent["frontiers"][0]["parent_frontier"] = "F999"

        for case, registry in (
            ("invalid_pre_existing_provenance", invalid_provenance),
            ("invalid_pre_existing_parent", invalid_parent),
        ):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.create_frontier(
                        registry,
                        name="Must not be appended",
                        proposed_at_loop=2,
                        source="initial",
                    )
                self.assertEqual(original, registry)

        canonical_input = self.module.make_registry("MXL", "ticker")
        original = copy.deepcopy(canonical_input)
        with self.assertRaises(self.module.LifecycleError):
            self.module.create_frontier(
                canonical_input,
                name="Non-canonical persisted loop",
                proposed_at_loop="1",
                source="initial",
            )
        self.assertEqual(original, canonical_input)

        valid_v3 = self.module.make_registry("MXL", "ticker")
        original = copy.deepcopy(valid_v3)
        updated_v3 = self.module.create_frontier(
            valid_v3,
            name="Canonical v3 frontier",
            proposed_at_loop=1,
            source="initial",
        )
        self.assertEqual(original, valid_v3)
        self.assertIs(updated_v3, self.module.validate_registry(updated_v3))
        created_v3 = self.module.get_frontier(updated_v3, "F1")
        self.assertIsNone(created_v3["layer"])
        self.assertIsNone(created_v3["parent_frontier"])

        valid_v2 = self.registry()
        original = copy.deepcopy(valid_v2)
        updated_v2 = self.module.create_frontier(
            valid_v2,
            name="Ordinary v2 frontier",
            proposed_at_loop=2,
            source="initial",
        )
        self.assertEqual(original, valid_v2)
        self.assertIs(updated_v2, self.module.validate_registry(updated_v2))
        created_v2 = self.module.get_frontier(updated_v2, "F3")
        self.assertNotIn("layer", created_v2)
        self.assertNotIn("parent_frontier", created_v2)

    def test_bind_frontier_layer_requires_existing_bound_shallower_parent(self):
        bind = getattr(self.module, "bind_frontier_layer", None)
        self.assertIsNotNone(bind, "bind_frontier_layer must be available")

        labels_instruction = "frontier layer labels are unavailable; run set-layers"
        for case, registry in (
            ("v2", self.registry()),
            ("v3_without_labels", self.module.make_registry("MXL", "ticker")),
        ):
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError) as context:
                    bind(registry, "F1", layer=0)
                self.assertEqual(labels_instruction, str(context.exception))
                self.assertEqual(original, registry)

        configured = self.configured_v3_registry()
        original_configured = copy.deepcopy(configured)
        with_parent = bind(configured, "F1", layer=0)
        self.assertEqual(original_configured, configured)
        self.assertEqual(0, self.module.get_frontier(with_parent, "F1")["layer"])

        invalid_parent_cases = (
            ("unknown", 4, "F999"),
            ("unbound", 4, "F3"),
            ("self", 4, "F2"),
            ("not_shallower", 0, "F1"),
        )
        for case, layer, parent_frontier in invalid_parent_cases:
            original = copy.deepcopy(with_parent)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    bind(
                        with_parent,
                        "F2",
                        layer=layer,
                        parent_frontier=parent_frontier,
                    )
                self.assertEqual(original, with_parent)

        original_with_parent = copy.deepcopy(with_parent)
        bound = bind(with_parent, "F2", layer=4, parent_frontier="F1")
        self.assertEqual(original_with_parent, with_parent)
        self.assertEqual(
            {"layer": 4, "parent_frontier": "F1"},
            {
                key: self.module.get_frontier(bound, "F2")[key]
                for key in ("layer", "parent_frontier")
            },
        )
        self.assertIs(bound, self.module.validate_registry(bound))

    def test_parent_frontier_is_independent_from_source_frontier(self):
        registry = self.configured_v3_registry()
        source, parent, child = registry["frontiers"]
        child["source"] = "discovery"
        child["source_frontier"] = source["id"]
        self.module.validate_registry(registry)

        with_parent = self.module.bind_frontier_layer(registry, parent["id"], layer=0)
        original = copy.deepcopy(with_parent)
        bound = self.module.bind_frontier_layer(
            with_parent,
            child["id"],
            layer=3,
            parent_frontier=parent["id"],
        )
        self.assertEqual(original, with_parent)
        bound_child = self.module.get_frontier(bound, child["id"])
        self.assertEqual(source["id"], bound_child["source_frontier"])
        self.assertEqual(parent["id"], bound_child["parent_frontier"])

        same_relation = self.configured_v3_registry(2)
        same_relation["frontiers"][1]["source"] = "discovery"
        same_relation["frontiers"][1]["source_frontier"] = "F1"
        with_bound_source = self.module.bind_frontier_layer(same_relation, "F1", layer=0)
        original = copy.deepcopy(with_bound_source)
        same_relation_bound = self.module.bind_frontier_layer(
            with_bound_source,
            "F2",
            layer=5,
            parent_frontier="F1",
        )
        self.assertEqual(original, with_bound_source)
        same_child = self.module.get_frontier(same_relation_bound, "F2")
        self.assertEqual("F1", same_child["source_frontier"])
        self.assertEqual("F1", same_child["parent_frontier"])

        null_source = self.configured_v3_registry(2)
        with_parent = self.module.bind_frontier_layer(null_source, "F1", layer=1)
        original = copy.deepcopy(with_parent)
        null_source_bound = self.module.bind_frontier_layer(
            with_parent,
            "F2",
            layer=4,
            parent_frontier="F1",
        )
        self.assertEqual(original, with_parent)
        null_source_child = self.module.get_frontier(null_source_bound, "F2")
        self.assertIsNone(null_source_child["source_frontier"])
        self.assertEqual("F1", null_source_child["parent_frontier"])

    def test_binding_is_declarative_idempotent_and_clear_is_atomic(self):
        registry = self.configured_v3_registry(2)
        with_parent = self.module.bind_frontier_layer(registry, "F1", layer=0)
        bound = self.module.bind_frontier_layer(
            with_parent,
            "F2",
            layer=3,
            parent_frontier="F1",
        )

        original_bound = copy.deepcopy(bound)
        replaced = self.module.bind_frontier_layer(bound, "F2", layer=5)
        self.assertEqual(original_bound, bound)
        self.assertEqual(
            {"layer": 5, "parent_frontier": None},
            {
                key: self.module.get_frontier(replaced, "F2")[key]
                for key in ("layer", "parent_frontier")
            },
        )

        original_replaced = copy.deepcopy(replaced)
        repeated = self.module.bind_frontier_layer(replaced, "F2", layer=5)
        self.assertEqual(original_replaced, replaced)
        self.assertEqual(replaced, repeated)
        self.assertIsNot(replaced, repeated)
        self.assertIsNot(replaced["frontiers"], repeated["frontiers"])

        original_repeated = copy.deepcopy(repeated)
        cleared = self.module.bind_frontier_layer(repeated, "F2", layer=None)
        self.assertEqual(original_repeated, repeated)
        self.assertEqual(
            {"layer": None, "parent_frontier": None},
            {
                key: self.module.get_frontier(cleared, "F2")[key]
                for key in ("layer", "parent_frontier")
            },
        )

        original_cleared = copy.deepcopy(cleared)
        repeated_clear = self.module.bind_frontier_layer(cleared, "F2", layer=None)
        self.assertEqual(original_cleared, cleared)
        self.assertEqual(cleared, repeated_clear)
        self.assertIsNot(cleared, repeated_clear)

        invalid_requests = (
            ("parent_without_layer", "F2", None, "F1"),
            ("bool_layer", "F2", True, None),
            ("string_layer", "F2", "3", None),
            ("negative_layer", "F2", -1, None),
            ("too_deep_layer", "F2", 6, None),
            ("malformed_parent", "F2", 3, "frontier-1"),
            ("unknown_target", "F999", 3, None),
        )
        for case, frontier_id, layer, parent_frontier in invalid_requests:
            original = copy.deepcopy(cleared)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.bind_frontier_layer(
                        cleared,
                        frontier_id,
                        layer=layer,
                        parent_frontier=parent_frontier,
                    )
                self.assertEqual(original, cleared)

    def test_rebind_or_clear_cannot_invalidate_existing_children(self):
        registry = self.configured_v3_registry()
        registry = self.module.bind_frontier_layer(registry, "F1", layer=0)
        registry = self.module.bind_frontier_layer(
            registry,
            "F2",
            layer=2,
            parent_frontier="F1",
        )
        registry = self.module.bind_frontier_layer(
            registry,
            "F3",
            layer=5,
            parent_frontier="F2",
        )

        invalid_rebindings = (
            ("clear_root", "F1", None, None),
            ("root_below_child", "F1", 3, None),
            ("clear_middle", "F2", None, None),
            ("middle_same_as_child", "F2", 5, "F1"),
        )
        for case, frontier_id, layer, parent_frontier in invalid_rebindings:
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.bind_frontier_layer(
                        registry,
                        frontier_id,
                        layer=layer,
                        parent_frontier=parent_frontier,
                    )
                self.assertEqual(original, registry)

        original = copy.deepcopy(registry)
        valid_rebinding = self.module.bind_frontier_layer(registry, "F1", layer=1)
        self.assertEqual(original, registry)
        self.assertEqual(1, self.module.get_frontier(valid_rebinding, "F1")["layer"])
        self.assertIs(valid_rebinding, self.module.validate_registry(valid_rebinding))

    def test_retired_parent_remains_structurally_valid(self):
        registry = self.configured_v3_registry(2)
        registry["frontiers"][0]["status"] = "Retired"
        registry["frontiers"][0]["retire_category"] = "blocked"
        self._sync_lifecycle_to_status(registry["frontiers"][0])
        self.module.validate_registry(registry)

        with_retired_parent = self.module.bind_frontier_layer(registry, "F1", layer=1)
        original = copy.deepcopy(with_retired_parent)
        bound = self.module.bind_frontier_layer(
            with_retired_parent,
            "F2",
            layer=5,
            parent_frontier="F1",
        )

        self.assertEqual(original, with_retired_parent)
        self.assertEqual("Retired", self.module.get_frontier(bound, "F1")["status"])
        self.assertEqual("blocked", self.module.get_frontier(bound, "F1")["retire_category"])
        self.assertEqual("F1", self.module.get_frontier(bound, "F2")["parent_frontier"])
        self.assertIs(bound, self.module.validate_registry(bound))

    def test_create_frontier_accepts_explicit_layer_and_parent_without_changing_v2_shape(self):
        self.assertEqual(
            [
                "registry",
                "name",
                "proposed_at_loop",
                "source",
                "source_frontier",
                "layer",
                "parent_frontier",
                "initial_status",
                "ts",
            ],
            list(inspect.signature(self.module.create_frontier).parameters),
        )

        legacy = self.registry()
        original_legacy = copy.deepcopy(legacy)
        legacy_updated = self.module.create_frontier(
            legacy,
            name="Legacy shape",
            proposed_at_loop=2,
            source="initial",
            layer=None,
            parent_frontier=None,
        )
        self.assertEqual(original_legacy, legacy)
        legacy_created = self.module.get_frontier(legacy_updated, "F3")
        self.assertEqual(set(legacy["frontiers"][0]), set(legacy_created))
        self.assertNotIn("layer", legacy_created)
        self.assertNotIn("parent_frontier", legacy_created)

        for case, layer, parent_frontier in (
            ("layer", 0, None),
            ("parent", None, "F1"),
        ):
            original = copy.deepcopy(legacy)
            with self.subTest(case=f"v2_{case}"):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.create_frontier(
                        legacy,
                        name="Reject v3 facts",
                        proposed_at_loop=2,
                        source="initial",
                        layer=layer,
                        parent_frontier=parent_frontier,
                    )
                self.assertEqual(original, legacy)

        unconfigured = self.module.make_registry("MXL", "ticker")
        original_unconfigured = copy.deepcopy(unconfigured)
        unbound = self.module.create_frontier(
            unconfigured,
            name="Legal unbound v3 frontier",
            proposed_at_loop=1,
            source="initial",
            layer=None,
            parent_frontier=None,
        )
        self.assertEqual(original_unconfigured, unconfigured)
        self.assertEqual(
            {"layer": None, "parent_frontier": None},
            {
                key: self.module.get_frontier(unbound, "F1")[key]
                for key in ("layer", "parent_frontier")
            },
        )

        configured = self.configured_v3_registry(2)
        configured = self.module.bind_frontier_layer(configured, "F2", layer=0)
        original_configured = copy.deepcopy(configured)
        created = self.module.create_frontier(
            configured,
            name="Explicitly bound discovery",
            proposed_at_loop=3,
            source="discovery",
            source_frontier="F1",
            layer=4,
            parent_frontier="F2",
        )
        self.assertEqual(original_configured, configured)
        created_frontier = self.module.get_frontier(created, "F3")
        self.assertEqual("F1", created_frontier["source_frontier"])
        self.assertEqual("F2", created_frontier["parent_frontier"])
        self.assertEqual(4, created_frontier["layer"])

        invalid_creation_requests = (
            ("empty_labels", unconfigured, 0, None),
            ("parent_without_layer", configured, None, "F2"),
        )
        for case, registry, layer, parent_frontier in invalid_creation_requests:
            original = copy.deepcopy(registry)
            with self.subTest(case=case):
                with self.assertRaises(self.module.LifecycleError):
                    self.module.create_frontier(
                        registry,
                        name="Invalid explicit binding",
                        proposed_at_loop=3,
                        source="initial",
                        layer=layer,
                        parent_frontier=parent_frontier,
                    )
                self.assertEqual(original, registry)

    def test_layer_coverage_reports_presence_status_and_retire_facts(self):
        derive = getattr(self.module, "derive_frontier_layer_coverage", None)
        self.assertIsNotNone(derive, "derive_frontier_layer_coverage must be available")

        registry = self.layer_coverage_registry()
        original = copy.deepcopy(registry)
        coverage = derive(registry)

        self.assertEqual(original, registry)
        self.assertEqual(coverage, derive(registry))
        self.assertEqual(
            {
                "registry_version",
                "labels_configured",
                "layers",
                "lineage",
                "unbound_frontier_ids",
                "advisories",
            },
            set(coverage),
        )
        self.assertEqual(3, coverage["registry_version"])
        self.assertIs(coverage["labels_configured"], True)
        self.assertIsInstance(coverage["advisories"], list)
        self.assertEqual(
            [
                {
                    "index": 0,
                    "label": "End demand",
                    "frontier_ids": ["F2", "F10"],
                    "status_counts": {
                        "New": 0,
                        "Active": 1,
                        "Continued": 0,
                        "Retired": 1,
                    },
                    "frontiers": [
                        {"frontier_id": "F2", "status": "Active", "retire_category": None},
                        {
                            "frontier_id": "F10",
                            "status": "Retired",
                            "retire_category": "blocked",
                        },
                    ],
                },
                {
                    "index": 1,
                    "label": "System or platform",
                    "frontier_ids": ["F3", "F7"],
                    "status_counts": {
                        "New": 0,
                        "Active": 0,
                        "Continued": 0,
                        "Retired": 2,
                    },
                    "frontiers": [
                        {
                            "frontier_id": "F3",
                            "status": "Retired",
                            "retire_category": "blocked",
                        },
                        {
                            "frontier_id": "F7",
                            "status": "Retired",
                            "retire_category": "blocked",
                        },
                    ],
                },
                {
                    "index": 2,
                    "label": "Component or module",
                    "frontier_ids": ["F4", "F8"],
                    "status_counts": {
                        "New": 0,
                        "Active": 0,
                        "Continued": 0,
                        "Retired": 2,
                    },
                    "frontiers": [
                        {
                            "frontier_id": "F4",
                            "status": "Retired",
                            "retire_category": "blocked",
                        },
                        {
                            "frontier_id": "F8",
                            "status": "Retired",
                            "retire_category": "barren",
                        },
                    ],
                },
                {
                    "index": 3,
                    "label": "Material or process",
                    "frontier_ids": [],
                    "status_counts": {status: 0 for status in self.module.STATUSES},
                    "frontiers": [],
                },
                {
                    "index": 4,
                    "label": "Constrained input or equipment",
                    "frontier_ids": [],
                    "status_counts": {status: 0 for status in self.module.STATUSES},
                    "frontiers": [],
                },
                {
                    "index": 5,
                    "label": "Geography or regulation",
                    "frontier_ids": ["F1", "F6"],
                    "status_counts": {
                        "New": 1,
                        "Active": 0,
                        "Continued": 1,
                        "Retired": 0,
                    },
                    "frontiers": [
                        {"frontier_id": "F1", "status": "New", "retire_category": None},
                        {
                            "frontier_id": "F6",
                            "status": "Continued",
                            "retire_category": None,
                        },
                    ],
                },
            ],
            coverage["layers"],
        )
        self.assertEqual(
            ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"],
            [row["frontier_id"] for row in coverage["lineage"]],
        )
        self.assertEqual(
            {
                "frontier_id": "F6",
                "layer": 5,
                "parent_frontier": "F4",
                "source_frontier": "F10",
                "status": "Continued",
                "retire_category": None,
            },
            coverage["lineage"][5],
        )
        self.assertEqual(["F5", "F9"], coverage["unbound_frontier_ids"])

    def test_layer_advisories_distinguish_unrepresented_blocked_retired_and_unbound(self):
        registry = self.layer_coverage_registry()
        original = copy.deepcopy(registry)
        coverage = self.module.derive_frontier_layer_coverage(registry)

        self.assertEqual(original, registry)
        self.assertEqual(
            [
                {
                    "code": "LAYER_BLOCKED_ONLY",
                    "layer_indexes": [1],
                    "frontier_ids": ["F3", "F7"],
                },
                {
                    "code": "LAYER_RETIRED_ONLY",
                    "layer_indexes": [2],
                    "frontier_ids": ["F4", "F8"],
                },
                {
                    "code": "LAYER_UNREPRESENTED",
                    "layer_indexes": [3],
                    "frontier_ids": [],
                },
                {
                    "code": "LAYER_UNREPRESENTED",
                    "layer_indexes": [4],
                    "frontier_ids": [],
                },
                {
                    "code": "FRONTIER_LAYER_UNBOUND",
                    "layer_indexes": [],
                    "frontier_ids": ["F5", "F9"],
                },
            ],
            coverage["advisories"],
        )
        for advisory in coverage["advisories"]:
            self.assertEqual(
                {"code", "layer_indexes", "frontier_ids"},
                set(advisory),
            )

        formatter = getattr(self.module, "format_frontier_layer_advisories", None)
        self.assertIsNotNone(formatter, "format_frontier_layer_advisories must be available")
        formatted = formatter(coverage)
        self.assertEqual(
            [
                "LAYER_BLOCKED_ONLY",
                "LAYER_RETIRED_ONLY",
                "LAYER_UNREPRESENTED",
                "FRONTIER_LAYER_UNBOUND",
            ],
            [line.split(":", 1)[0] for line in formatted],
        )
        self.assertIn("F3, F7", formatted[0])
        self.assertIn("F4=Retired(blocked), F8=Retired(barren)", formatted[1])
        self.assertIn("Layers 3-4", formatted[2])
        self.assertIn("F5, F9", formatted[3])

        legacy = self.registry()
        original_legacy = copy.deepcopy(legacy)
        legacy_coverage = self.module.derive_frontier_layer_coverage(legacy)
        self.assertEqual(original_legacy, legacy)
        self.assertEqual(
            {
                "registry_version": 2,
                "labels_configured": False,
                "layers": [],
                "lineage": [],
                "unbound_frontier_ids": [],
                "advisories": [
                    {
                        "code": "LAYER_LABELS_UNCONFIGURED",
                        "layer_indexes": [],
                        "frontier_ids": [],
                    }
                ],
            },
            legacy_coverage,
        )

        unconfigured = self.layer_coverage_registry()
        unconfigured["layer_labels"] = []
        for frontier in unconfigured["frontiers"]:
            frontier["layer"] = None
            frontier["parent_frontier"] = None
        self.module.validate_registry(unconfigured)
        original_unconfigured = copy.deepcopy(unconfigured)
        unconfigured_coverage = self.module.derive_frontier_layer_coverage(unconfigured)
        self.assertEqual(original_unconfigured, unconfigured)
        numeric_ids = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"]
        self.assertEqual([], unconfigured_coverage["layers"])
        self.assertEqual(
            numeric_ids,
            [row["frontier_id"] for row in unconfigured_coverage["lineage"]],
        )
        self.assertEqual(numeric_ids, unconfigured_coverage["unbound_frontier_ids"])
        self.assertEqual(
            [
                {
                    "code": "LAYER_LABELS_UNCONFIGURED",
                    "layer_indexes": [],
                    "frontier_ids": [],
                },
                {
                    "code": "FRONTIER_LAYER_UNBOUND",
                    "layer_indexes": [],
                    "frontier_ids": numeric_ids,
                },
            ],
            unconfigured_coverage["advisories"],
        )

    def test_layer_advisory_order_range_compression_and_messages_are_stable(self):
        numeric_registry = self.layer_coverage_registry()
        numeric_registry_by_id = {
            frontier["id"]: frontier for frontier in numeric_registry["frontiers"]
        }
        numeric_registry_by_id["F2"]["status"] = "Retired"
        numeric_registry_by_id["F2"]["retire_category"] = "blocked"
        self._sync_lifecycle_to_status(numeric_registry_by_id["F2"])
        self.module.validate_registry(numeric_registry)
        coverage = self.module.derive_frontier_layer_coverage(numeric_registry)
        original_coverage = copy.deepcopy(coverage)

        expected = [
            "LAYER_BLOCKED_ONLY: Layer 0 (End demand) has only blocked retired frontiers: F2, F10.",
            "LAYER_BLOCKED_ONLY: Layer 1 (System or platform) has only blocked retired frontiers: F3, F7.",
            "LAYER_RETIRED_ONLY: Layer 2 (Component or module) has only retired frontiers: F4=Retired(blocked), F8=Retired(barren).",
            "LAYER_UNREPRESENTED: Layers 3-4 have no bound frontier.",
            "FRONTIER_LAYER_UNBOUND: Frontiers F5, F9 are not bound to a layer.",
        ]
        self.assertEqual(
            expected,
            self.module.format_frontier_layer_advisories(coverage),
        )
        self.assertEqual(
            [f"- {line}" for line in expected],
            self.module.format_frontier_layer_advisories(coverage, prefix="- "),
        )
        self.assertEqual(original_coverage, coverage)

        interrupted = self.configured_v3_registry(4)
        interrupted_by_id = {frontier["id"]: frontier for frontier in interrupted["frontiers"]}
        interrupted_by_id["F1"]["layer"] = 1
        interrupted_by_id["F1"]["status"] = "Retired"
        interrupted_by_id["F1"]["retire_category"] = "blocked"
        self._sync_lifecycle_to_status(interrupted_by_id["F1"])
        interrupted_by_id["F2"]["layer"] = 4
        interrupted_by_id["F2"]["status"] = "Retired"
        interrupted_by_id["F2"]["retire_category"] = "blocked"
        self._sync_lifecycle_to_status(interrupted_by_id["F2"])
        interrupted_by_id["F3"]["layer"] = 4
        interrupted_by_id["F3"]["status"] = "Retired"
        interrupted_by_id["F3"]["retire_category"] = "barren"
        self._sync_lifecycle_to_status(interrupted_by_id["F3"])
        self.module.validate_registry(interrupted)
        interrupted_coverage = self.module.derive_frontier_layer_coverage(interrupted)
        original_interrupted = copy.deepcopy(interrupted_coverage)
        self.assertEqual(
            [
                "LAYER_UNREPRESENTED: Layers 0 have no bound frontier.",
                "LAYER_BLOCKED_ONLY: Layer 1 (System or platform) has only blocked retired frontiers: F1.",
                "LAYER_UNREPRESENTED: Layers 2-3 have no bound frontier.",
                "LAYER_RETIRED_ONLY: Layer 4 (Constrained input or equipment) has only retired frontiers: F2=Retired(blocked), F3=Retired(barren).",
                "LAYER_UNREPRESENTED: Layers 5 have no bound frontier.",
                "FRONTIER_LAYER_UNBOUND: Frontiers F4 are not bound to a layer.",
            ],
            self.module.format_frontier_layer_advisories(interrupted_coverage),
        )
        self.assertEqual(original_interrupted, interrupted_coverage)

    def test_layer_coverage_does_not_infer_research_completion(self):
        registry = self.layer_coverage_registry()
        original = copy.deepcopy(registry)
        coverage = self.module.derive_frontier_layer_coverage(registry)
        advisory_lines = self.module.format_frontier_layer_advisories(coverage)

        self.assertEqual(original, registry)
        self.assertEqual(["registry"], list(inspect.signature(self.module.derive_frontier_layer_coverage).parameters))
        self.assertIn("status_counts", coverage["layers"][0])
        self.assertIn("status", coverage["layers"][0]["frontiers"][0])
        self.assertIn("retire_category", coverage["layers"][0]["frontiers"][0])

        serialized = json.dumps(
            {"coverage": coverage, "advisory_lines": advisory_lines},
            sort_keys=True,
        ).casefold()
        forbidden_vocabulary = (
            "peeled",
            "complete",
            "completion",
            "sufficient",
            "adequate",
            "adequacy",
            "confidence",
            "ready",
            "readiness",
            "action class",
            "action_class",
            "evidence grade",
            "evidence_grade",
            "loop count",
            "loop_count",
            "challenge completion",
        )
        for forbidden in forbidden_vocabulary:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_render_layer_coverage_markdown_is_deterministic_and_escapes_cells(self):
        render = getattr(self.module, "render_frontier_layer_coverage_md", None)
        self.assertIsNotNone(render, "render_frontier_layer_coverage_md must be available")

        registry = self.layer_coverage_registry()
        registry["layer_labels"][0] = "End | demand \\ path"
        self.module.validate_registry(registry)
        original = copy.deepcopy(registry)
        rendered = render(registry)

        expected = "\n".join(
            [
                "> Presence/status snapshot only. This does not establish research completeness, evidence adequacy, or action-class readiness.",
                "",
                "| Layer | Label | New | Active | Continued | Retired | Frontier facts |",
                "| --- | --- | --- | --- | --- | --- | --- |",
                "| 0 | End \\| demand \\\\ path | 0 | 1 | 0 | 1 | F2=Active, F10=Retired(blocked) |",
                "| 1 | System or platform | 0 | 0 | 0 | 2 | F3=Retired(blocked), F7=Retired(blocked) |",
                "| 2 | Component or module | 0 | 0 | 0 | 2 | F4=Retired(blocked), F8=Retired(barren) |",
                "| 3 | Material or process | 0 | 0 | 0 | 0 | none |",
                "| 4 | Constrained input or equipment | 0 | 0 | 0 | 0 | none |",
                "| 5 | Geography or regulation | 1 | 0 | 1 | 0 | F1=New, F6=Continued |",
                "",
                "### Structural Lineage",
                "",
                "| Frontier | Layer | Structural parent | Discovery source | Status | Retire category |",
                "| --- | --- | --- | --- | --- | --- |",
                "| F1 | 5 | F4 | none | New | none |",
                "| F2 | 0 | none | none | Active | none |",
                "| F3 | 1 | F2 | none | Retired | blocked |",
                "| F4 | 2 | F3 | none | Retired | blocked |",
                "| F5 | none | none | none | Continued | none |",
                "| F6 | 5 | F4 | F10 | Continued | none |",
                "| F7 | 1 | F2 | none | Retired | blocked |",
                "| F8 | 2 | F3 | none | Retired | barren |",
                "| F9 | none | none | none | Retired | superseded |",
                "| F10 | 0 | none | none | Retired | blocked |",
                "",
                "### Advisory Gaps",
                "",
                "- LAYER_BLOCKED_ONLY: Layer 1 (System or platform) has only blocked retired frontiers: F3, F7.",
                "- LAYER_RETIRED_ONLY: Layer 2 (Component or module) has only retired frontiers: F4=Retired(blocked), F8=Retired(barren).",
                "- LAYER_UNREPRESENTED: Layers 3-4 have no bound frontier.",
                "- FRONTIER_LAYER_UNBOUND: Frontiers F5, F9 are not bound to a layer.",
                "",
            ]
        )
        self.assertEqual(expected, rendered)
        self.assertEqual(rendered, render(registry))
        self.assertEqual(original, registry)
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))
        self.assertNotIn("<!--", rendered)
        self.assertNotIn("Frontier Layer Coverage", rendered)
        self.assertIsNone(re.search(r"\b20\d{2}-\d{2}-\d{2}\b", rendered))

        unconfigured = copy.deepcopy(registry)
        unconfigured["layer_labels"] = []
        for frontier in unconfigured["frontiers"]:
            frontier["layer"] = None
            frontier["parent_frontier"] = None
        self.module.validate_registry(unconfigured)
        original_unconfigured = copy.deepcopy(unconfigured)
        self.assertEqual(
            "\n".join(
                [
                    "> Presence/status snapshot only. This does not establish research completeness, evidence adequacy, or action-class readiness.",
                    "",
                    "### Advisory Gaps",
                    "",
                    "- LAYER_LABELS_UNCONFIGURED: Frontier layer labels are unavailable; run set-layers.",
                    "- FRONTIER_LAYER_UNBOUND: Frontiers F1, F2, F3, F4, F5, F6, F7, F8, F9, F10 are not bound to a layer.",
                    "",
                ]
            ),
            render(unconfigured),
        )
        self.assertEqual(original_unconfigured, unconfigured)

        empty = self.module.set_layer_labels(
            self.module.make_registry("MXL", "ticker"),
            list(enumerate(self.layer_labels())),
        )
        empty_rendered = render(empty)
        self.assertIn(
            "| Frontier | Layer | Structural parent | Discovery source | Status | Retire category |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "_No frontiers are registered._",
            empty_rendered,
        )
        self.assertIn(
            "- LAYER_UNREPRESENTED: Layers 0-5 have no bound frontier.",
            empty_rendered,
        )

        represented = self.module.make_registry("MXL", "ticker")
        represented["portfolio_limits"] = {
            "max_active": 10,
            "max_active_plus_new": 10,
        }
        for index in range(6):
            represented = self.module.create_frontier(
                represented,
                name=f"Layer {index} frontier",
                proposed_at_loop=index + 1,
                source="initial",
            )
        represented = self.module.set_layer_labels(
            represented,
            list(enumerate(self.layer_labels())),
        )
        for index in range(6):
            represented = self.module.bind_frontier_layer(
                represented,
                f"F{index + 1}",
                layer=index,
            )
        original_represented = copy.deepcopy(represented)
        represented_rendered = render(represented)
        self.assertIn("### Advisory Gaps\n\n- None at this snapshot.\n", represented_rendered)
        self.assertEqual(original_represented, represented)

    def test_managed_layer_markdown_neutralizes_marker_labels_without_changing_cli_text(self):
        marker = "<!-- SOFA:frontier-layer-coverage:start -->"
        label = f"System {marker} authority"
        registry = self.layer_coverage_registry()
        registry["layer_labels"][1] = label
        self.module.validate_registry(registry)
        original = copy.deepcopy(registry)

        coverage = self.module.derive_frontier_layer_coverage(registry)
        cli_advisories = self.module.format_frontier_layer_advisories(
            coverage,
            prefix="[ADVISORY] ",
        )
        rendered = self.module.render_frontier_layer_coverage_md(registry)
        encoded_label = (
            "System &lt;!-- SOFA:frontier-layer-coverage:start --&gt; authority"
        )

        self.assertIn(label, "\n".join(cli_advisories))
        self.assertNotIn("&lt;", "\n".join(cli_advisories))
        self.assertNotIn(marker, rendered)
        self.assertEqual(2, rendered.count(encoded_label))
        self.assertEqual(original, registry)

    def test_layer_renderer_sorts_frontier_lineage_and_unbound_ids_numerically(self):
        registry = self.layer_coverage_registry()
        original = copy.deepcopy(registry)
        rendered = self.module.render_frontier_layer_coverage_md(registry)

        self.assertEqual(original, registry)
        self.assertIn(
            "| 0 | End demand | 0 | 1 | 0 | 1 | F2=Active, F10=Retired(blocked) |",
            rendered,
        )
        lineage_rows = [
            line
            for line in rendered.splitlines()
            if re.fullmatch(r"\| F[1-9][0-9]* \|.*\|", line)
        ]
        self.assertEqual(
            ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10"],
            [line.split("|")[1].strip() for line in lineage_rows],
        )
        self.assertIn(
            "- FRONTIER_LAYER_UNBOUND: Frontiers F5, F9 are not bound to a layer.",
            rendered,
        )

    def test_make_registry_and_create_frontier_build_schema(self):
        registry = self.module.make_registry("MXL", "ticker")
        self.assertEqual(
            {
                "version": 3,
                "subject": "MXL",
                "mode": "ticker",
                "layer_labels": [],
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

    def test_loop_enforcer_reports_unknown_or_malformed_v3_without_traceback(self):
        loop_enforcer = load_loop_enforcer()
        malformed_v3 = self.v3_registry()
        malformed_v3["frontiers"][0].pop("layer")
        cases = [
            (
                "unsupported-version",
                {**self.registry(), "version": 99},
                "frontier registry invalid: unsupported registry version: 99",
            ),
            (
                "malformed-v3",
                malformed_v3,
                "frontier registry invalid: frontier F1.layer is required",
            ),
        ]

        for label, registry, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                (workspace / "frontier_registry.json").write_text(
                    json.dumps(registry, ensure_ascii=False),
                    encoding="utf-8",
                )
                (workspace / "evidence_ledger.md").write_text(
                    "## Loop 1: F1 - InP substrate supply concentration\n",
                    encoding="utf-8",
                )

                passed, violations = loop_enforcer.check_loop_depth(str(workspace))
                self.assertFalse(passed)
                self.assertEqual([expected], violations)

                completed = subprocess.run(
                    [sys.executable, str(LOOP_ENFORCER_SCRIPT), str(workspace)],
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(0, completed.returncode)
                self.assertIn("LOOP ENFORCER FAILED", completed.stdout)
                self.assertIn(f"[FAIL] {expected}", completed.stdout)
                self.assertNotIn("Traceback", completed.stdout + completed.stderr)

    def test_loop_enforcer_preserves_existing_v2_binding_and_count_semantics(self):
        loop_enforcer = load_loop_enforcer()
        registry = self.registry()
        original = copy.deepcopy(registry)
        stdout = StringIO()

        with redirect_stdout(stdout):
            passed, counts, violations = loop_enforcer.check_loop_depth_from_documents(
                "\n".join(
                    [
                        "## Loop 1: F1 - original display text",
                        "## Loop 2: F1 - renamed display text",
                    ]
                ),
                registry,
            )
            no_loops = loop_enforcer.check_loop_depth_from_documents(
                "# Evidence Ledger\n",
                registry,
            )
            unknown = loop_enforcer.check_loop_depth_from_documents(
                "## Loop 1: F9 - Unknown frontier\n",
                registry,
            )

        self.assertTrue(passed, violations)
        self.assertEqual({"F1": 2, "F2": 0}, counts)
        self.assertEqual([], violations)
        self.assertEqual(
            (False, {}, ["missing loop frontier binding headers"]),
            no_loops,
        )
        self.assertEqual(
            (False, {}, ["unknown frontier id in loop header: F9"]),
            unknown,
        )
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(original, registry)
        self.assertEqual(2, registry["version"])
        self.assertNotIn("layer_labels", registry)
        self.assertTrue(all("layer" not in frontier for frontier in registry["frontiers"]))

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
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 4, "F2": 2}))
        registry["frontiers"][0]["review_count"] = 1
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 3, "F2": 2}))
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 5, "F2": 2}))
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
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 3, "F2": 1}))

        registry["frontiers"][0]["review_count"] = 1
        self.assertEqual([], self.module.check_review_due(registry, {"F1": 2, "F2": 1}))
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 4, "F2": 1}))
        self.assertEqual(["F1"], self.module.check_review_due(registry, {"F1": 5, "F2": 1}))

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

    def test_review_action_rejects_before_boundary_without_mutating_input(self):
        registry = self.registry()
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F1",
                "Continued",
                {"F1": 1, "F2": 0},
                mode="ticker",
                action="review",
                rationale="not actually due",
                at_loop=1,
            )

        self.assertEqual(original, registry)
        self.assertEqual(0, self.module.get_frontier(registry, "F1")["review_count"])

    def test_review_action_accepts_overdue_loop_without_mutating_input(self):
        registry = self.registry()
        original = copy.deepcopy(registry)

        updated = self.module.transition(
            registry,
            "F1",
            "Continued",
            {"F1": 4, "F2": 0},
            mode="ticker",
            action="review",
            rationale="review recorded after one extra loop",
            at_loop=4,
        )

        self.assertEqual(original, registry)
        f1 = self.module.get_frontier(updated, "F1")
        self.assertEqual("Continued", f1["status"])
        self.assertEqual(1, f1["review_count"])
        self.assertEqual(4, f1["review_decisions"][0]["at_loop"])

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
        self.assertEqual("dead mapping direction", self.module.get_frontier(retired, "F1")["lifecycle"][-1]["rationale"])

    def test_standalone_retire_rejects_frontier_with_due_review_without_mutating_input(self):
        registry = self.registry(mode="ticker")
        original = copy.deepcopy(registry)

        with self.assertRaises(self.module.InvalidTransition):
            self.module.transition(
                registry,
                "F1",
                "Retired",
                {"F1": 3, "F2": 0},
                mode="ticker",
                action="retire",
                retire_category="answered_out",
                rationale="claims answered without review",
                at_loop=3,
            )

        self.assertEqual(original, registry)
        self.assertEqual("Active", self.module.get_frontier(registry, "F1")["status"])

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

    def test_valid_retire_categories_are_allowed_after_recorded_review_boundary(self):
        valid_categories = ["blocked", "invalidated", "barren", "superseded", "bad_pick", "answered_out"]

        for mode in ["ticker", "sector"]:
            for category in valid_categories:
                with self.subTest(mode=mode, category=category):
                    registry = self.registry(mode=mode)
                    registry["frontiers"][0]["review_count"] = 1
                    retired = self.module.transition(
                        registry,
                        "F1",
                        "Retired",
                        {"F1": 4, "F2": 0},
                        mode=mode,
                        action="retire",
                        retire_category=category,
                        rationale="resolved after first review window",
                        at_loop=4,
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
                    {"action": "retire", "frontier": "F2", "category": "answered_out", "reason": "legacy branch answered"},
                    {"action": "reprioritize", "frontier": "F1", "priority": "high", "reason": "raise review priority"},
                    {"action": "reject", "candidate": "Silicon photonics tangent", "reason": "does not change Layer 0 demand"},
                ],
            }
        )
        review_md = self.module.render_review_log_md(registry)
        discovery_md = self.module.render_discovery_log_md(registry)
        expected_actions = [
            "- Added F3 (source=discovery, source_frontier=F1): export permit gate",
            "- Retired F2 (category=answered_out): legacy branch answered",
            "- Reprioritized F1 to high: raise review priority",
            "- Rejected Silicon photonics tangent: does not change Layer 0 demand",
        ]
        self.assertEqual(
            "\n".join(
                [
                    "# Frontier Review Log",
                    "",
                    "## Frontier Review: F1 @ loop 3 (review 1/3)",
                    "**Decision**: Continued",
                    "**Rationale**: yield high",
                    "",
                    "### Portfolio Actions",
                    *expected_actions,
                    "",
                ]
            ),
            review_md,
        )
        self.assertEqual(
            "\n".join(
                [
                    "# Frontier Discovery Log",
                    "",
                    "## F1 @ loop 3 (review 1)",
                    *expected_actions,
                    "",
                ]
            ),
            discovery_md,
        )
        self.assertIn("## Frontier Review: F1 @ loop 3 (review 1/3)", review_md)
        self.assertIn("**Decision**: Continued", review_md)
        self.assertIn("Added F3", review_md)
        self.assertIn("Retired F2 (category=answered_out): legacy branch answered", review_md)
        self.assertIn("Reprioritized F1 to high: raise review priority", review_md)
        self.assertIn("Silicon photonics tangent", discovery_md)
        self.assertEqual(review_md, self.module.render_review_log_md(registry))
        self.assertEqual(discovery_md, self.module.render_discovery_log_md(registry))

    def test_review_and_discovery_renderers_encode_registered_markers_in_every_dynamic_field(self):
        script_dir = str(ROOT / "scripts")
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        from workspace_contract import artifact_contract_for_mode

        markers = []
        for block in artifact_contract_for_mode("ticker").managed_blocks:
            markers.extend([block.start_marker, block.end_marker])
        dynamic = " / ".join(markers)
        encoded = html.escape(dynamic, quote=False)
        registry = self.registry()
        frontier = registry["frontiers"][0]
        frontier["id"] = dynamic
        frontier["max_reviews"] = dynamic
        frontier["review_decisions"] = [
            {
                "review_number": dynamic,
                "at_loop": dynamic,
                "decision": dynamic,
                "retire_category": dynamic,
                "rationale_short": dynamic,
                "portfolio_actions": [
                    {
                        "action": "add",
                        "frontier": dynamic,
                        "source": dynamic,
                        "source_frontier": dynamic,
                        "reason": dynamic,
                    },
                    {
                        "action": "reject",
                        "candidate": dynamic,
                        "reason": dynamic,
                    },
                    {
                        "action": "retire",
                        "frontier": dynamic,
                        "category": dynamic,
                        "reason": dynamic,
                    },
                    {
                        "action": "reprioritize",
                        "frontier": dynamic,
                        "priority": dynamic,
                        "reason": dynamic,
                    },
                ],
            }
        ]
        original = copy.deepcopy(registry)

        review_md = self.module.render_review_log_md(registry)
        discovery_md = self.module.render_discovery_log_md(registry)

        for marker in markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, review_md)
                self.assertNotIn(marker, discovery_md)
        self.assertIn(
            f"## Frontier Review: {encoded} @ loop {encoded} "
            f"(review {encoded}/{encoded})",
            review_md,
        )
        self.assertIn(f"**Decision**: {encoded}", review_md)
        self.assertIn(f"**Rationale**: {encoded}", review_md)
        self.assertIn(f"**Retire category**: {encoded}", review_md)
        expected_actions = (
            f"Added {encoded} (source={encoded}, source_frontier={encoded}): {encoded}",
            f"Rejected {encoded}: {encoded}",
            f"Retired {encoded} (category={encoded}): {encoded}",
            f"Reprioritized {encoded} to {encoded}: {encoded}",
        )
        for action in expected_actions:
            self.assertIn(action, review_md)
            self.assertIn(action, discovery_md)
        self.assertIn(
            f"## {encoded} @ loop {encoded} (review {encoded})",
            discovery_md,
        )
        self.assertEqual(original, registry)
        self.assertEqual(
            ["registry"],
            list(inspect.signature(self.module.render_frontier_layer_coverage_md).parameters),
        )
        self.assertEqual(
            ["coverage", "prefix"],
            list(inspect.signature(self.module.format_frontier_layer_advisories).parameters),
        )

    def test_review_and_discovery_rendering_covers_empty_and_unknown_actions(self):
        empty_registry = self.registry()
        self.assertIn("_No frontier reviews recorded._", self.module.render_review_log_md(empty_registry))
        self.assertIn("_No discovery actions recorded._", self.module.render_discovery_log_md(empty_registry))

        registry = self.registry()
        registry["frontiers"][0]["review_decisions"].append(
            {
                "review_number": 1,
                "at_loop": 3,
                "decision": "Retired",
                "retire_category": "answered_out",
                "rationale_short": "answered by evidence",
                "portfolio_actions": [],
            }
        )
        registry["frontiers"][0]["review_decisions"].append(
            {
                "review_number": 2,
                "at_loop": 6,
                "decision": "Continued",
                "retire_category": None,
                "rationale_short": "new path remains useful",
                "portfolio_actions": [{"action": "custom", "reason": "manual audit marker"}],
            }
        )

        review_md = self.module.render_review_log_md(registry)
        discovery_md = self.module.render_discovery_log_md(registry)

        self.assertIn("**Retire category**: answered_out", review_md)
        self.assertIn("custom: manual audit marker", review_md)
        self.assertIn("custom: manual audit marker", discovery_md)

    # Note: the two replace_managed_block tests that previously lived here
    # (test_replace_managed_block_uses_v4_markers_and_rejects_malformed and
    # test_replace_managed_block_rejects_duplicate_or_misordered_markers) were
    # migrated to tests/test_workspace_contract.py when replace_managed_block
    # moved from frontier_lifecycle into workspace_contract (Phase 5). They
    # now use the registered block name "frontier-review-log" and ValueError,
    # and the framing-contract block is covered there too.


if __name__ == "__main__":
    unittest.main()
