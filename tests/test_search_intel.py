import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "search_intel.py"
sys.path.insert(0, str(ROOT / "scripts"))

from capability_policy import (
    build_prior_query_digest,
    build_search_yield_stats,
    render_prior_query_digest,
    render_search_yield_stats,
)


LEDGER = """# Evidence Ledger

## Loop 1: F1 - Substrate supply

notes

## Loop 2: F1 - Substrate supply

notes

## Loop 3: F2 - Hidden customers

notes
"""


RECORDS = [
    {
        "loop_id": "stage_0",
        "query": "ACME 公司 主体确认",
        "result_status": "completed",
        "evidence_refs": ["https://example.com/profile"],
    },
    {
        "loop_id": "loop_1",
        "query": "ACME 10-K substrate supplier",
        "result_status": "completed",
        "evidence_refs": ["https://www.sec.gov/acme-10k", "CNINFO:600000"],
        "dead_ends": [
            {
                "query": "ACME substrate market share",
                "category": "no_result",
            }
        ],
        "notes": "CONTAMINANT: social-media rumor, not evidence.",
        "grade": "CONTAMINANT",
        "finding": "CONTAMINANT should stay out of the digest.",
    },
    {
        "loop_id": "loop_1",
        "query": "ACME 10-K substrate supplier",
        "result_status": "degraded_approved",
        "degraded_reason": "anysearch rate limited",
        "gaps": ["substrate pricing"],
        "dead_ends": [
            {
                "query": "substrate spot price 2026",
                "category": "tool_degraded",
            }
        ],
    },
    {
        "loop_id": "loop_2",
        "query": "ACME 10-K substrate supplier",
        "result_status": "completed",
        "evidence_refs": ["https://www.sec.gov/acme-10k"],
    },
    {
        "loop_id": "loop_3",
        "query": "hidden hyperscaler customer ACME",
        "result_status": "completed",
        "evidence_refs": ["https://web.archive.org/acme-2019"],
        "dead_ends": [
            {
                "query": "ACME customer list",
                "category": "blocked_source",
            }
        ],
    },
    {
        "dispatch_id": "dispatch_0007",
        "query": "orphan dispatch query",
        "result_status": "completed",
        "evidence_refs": [],
    },
    {
        "loop_id": "loop_9",
        "query": "loop without ledger header",
        "result_status": "completed",
        "evidence_refs": [],
    },
]


def make_workspace(base: Path) -> Path:
    workspace = base / "workspace"
    workspace.mkdir()
    (workspace / "evidence_ledger.md").write_text(LEDGER, encoding="utf-8")
    (workspace / "search_log.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in RECORDS) + "\n",
        encoding="utf-8",
    )
    return workspace


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class TestPriorQueryDigest(unittest.TestCase):
    def test_groups_are_frontier_stage0_and_unbound_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            groups = build_prior_query_digest(workspace)

        self.assertEqual(["stage_0", "F1", "F2", "unbound"], [g.group_id for g in groups])

    def test_f1_group_merges_loops_and_splits_refs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            groups = build_prior_query_digest(workspace)

        by_group = {group.group_id: group for group in groups}
        self.assertEqual(["loop_1", "loop_2"], by_group["F1"].loop_keys)
        self.assertEqual(["ACME 10-K substrate supplier"], by_group["F1"].queries)
        self.assertEqual(
            {"no_result", "tool_degraded"},
            {dead_end.category for dead_end in by_group["F1"].dead_ends},
        )
        self.assertEqual(["www.sec.gov"], by_group["F1"].visited_hosts)
        self.assertEqual(["CNINFO:600000"], by_group["F1"].source_identifiers)

    def test_url_refs_store_hostnames_without_credentials_or_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            extra_record = {
                "loop_id": "loop_1",
                "query": "ACME secure source lookup",
                "result_status": "completed",
                "evidence_refs": [
                    "https://example.com:8443/a",
                    "https://user:pass@secure.example.com/path",
                ],
            }
            with (workspace / "search_log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(extra_record, ensure_ascii=False) + "\n")

            groups = build_prior_query_digest(workspace)

        by_group = {group.group_id: group for group in groups}
        self.assertIn("example.com", by_group["F1"].visited_hosts)
        self.assertIn("secure.example.com", by_group["F1"].visited_hosts)
        self.assertNotIn("example.com:8443", by_group["F1"].visited_hosts)
        self.assertNotIn("user:pass@secure.example.com", by_group["F1"].visited_hosts)

    def test_unbound_group_collects_dispatch_only_and_unmapped_loops(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            groups = build_prior_query_digest(workspace)

        by_group = {group.group_id: group for group in groups}
        self.assertIn("orphan dispatch query", by_group["unbound"].queries)
        self.assertIn("loop without ledger header", by_group["unbound"].queries)

    def test_ledger_headers_with_leading_space_do_not_bind_frontiers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "evidence_ledger.md").write_text(
                "# Evidence Ledger\n\n ## Loop 1: F1 - Indented header\n",
                encoding="utf-8",
            )
            (workspace / "search_log.jsonl").write_text(
                json.dumps(
                    {
                        "loop_id": "loop_1",
                        "query": "query with invalid ledger binding",
                        "result_status": "completed",
                        "evidence_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            groups = build_prior_query_digest(workspace)

        by_group = {group.group_id: group for group in groups}
        self.assertNotIn("F1", by_group)
        self.assertIn("query with invalid ledger binding", by_group["unbound"].queries)

    def test_rendered_digest_carries_negative_trace_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            groups = build_prior_query_digest(workspace)
            rendered = render_prior_query_digest(groups)
            payload = json.dumps(
                [dataclasses.asdict(group) for group in groups],
                ensure_ascii=False,
            )

        self.assertIn("### Prior Search Trace (negative trace only)", rendered)
        self.assertIn("ACME 公司 主体确认", rendered)
        self.assertIn("[blocked_source] ACME customer list", rendered)
        self.assertNotIn("CONTAMINANT", rendered)
        self.assertNotIn("substrate pricing", rendered)
        self.assertNotIn("anysearch rate limited", rendered)
        self.assertNotIn("CONTAMINANT", payload)
        self.assertNotIn("substrate pricing", payload)
        self.assertNotIn("anysearch rate limited", payload)

    def test_missing_workspace_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"

            with self.assertRaises(ValueError):
                build_prior_query_digest(missing)

    def test_workspace_without_search_log_renders_empty_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "evidence_ledger.md").write_text(LEDGER, encoding="utf-8")

            groups = build_prior_query_digest(workspace)
            rendered = render_prior_query_digest(groups)

        self.assertEqual([], groups)
        self.assertIn("(no recorded searches)", rendered)


class TestSearchYieldStats(unittest.TestCase):
    def test_loops_are_ordered_stage0_numeric_then_unbound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            stats = build_search_yield_stats(workspace)

        self.assertEqual(
            ["stage_0", "loop_1", "loop_2", "loop_3", "loop_9", "unbound"],
            [entry.loop_key for entry in stats],
        )

    def test_loop_1_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            stats = build_search_yield_stats(workspace)

        by_loop = {entry.loop_key: entry for entry in stats}
        self.assertEqual(2, by_loop["loop_1"].record_count)
        self.assertEqual(1, by_loop["loop_1"].distinct_queries)
        self.assertEqual(
            {"no_result": 1, "tool_degraded": 1},
            by_loop["loop_1"].dead_end_counts,
        )
        self.assertAlmostEqual(2.0, by_loop["loop_1"].dead_end_rate)
        self.assertEqual(2, by_loop["loop_1"].unique_refs)
        self.assertEqual(2, by_loop["loop_1"].first_seen_refs)

    def test_stats_count_repeated_dead_end_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            duplicate_records = [
                {
                    "loop_id": "loop_4",
                    "query": "ACME repeated query one",
                    "result_status": "completed",
                    "dead_ends": [
                        {
                            "query": "ACME repeated failed route",
                            "category": "no_result",
                        }
                    ],
                    "evidence_refs": [],
                },
                {
                    "loop_id": "loop_4",
                    "query": "ACME repeated query two",
                    "result_status": "completed",
                    "dead_ends": [
                        {
                            "query": "ACME repeated failed route",
                            "category": "no_result",
                        }
                    ],
                    "evidence_refs": [],
                },
            ]
            with (workspace / "search_log.jsonl").open("a", encoding="utf-8") as handle:
                for record in duplicate_records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

            stats = build_search_yield_stats(workspace)

        by_loop = {entry.loop_key: entry for entry in stats}
        self.assertEqual({"no_result": 2}, by_loop["loop_4"].dead_end_counts)
        self.assertAlmostEqual(1.0, by_loop["loop_4"].dead_end_rate)

    def test_first_seen_refs_deduplicate_across_loops(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            stats = build_search_yield_stats(workspace)

        by_loop = {entry.loop_key: entry for entry in stats}
        self.assertEqual(1, by_loop["stage_0"].first_seen_refs)
        self.assertEqual(1, by_loop["loop_2"].unique_refs)
        self.assertEqual(0, by_loop["loop_2"].first_seen_refs)
        self.assertEqual(1, by_loop["loop_3"].first_seen_refs)

    def test_rendered_stats_are_labeled_advisory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            stats = build_search_yield_stats(workspace)
            rendered = render_search_yield_stats(stats)

        self.assertIn("### Search Yield Statistics (advisory only)", rendered)
        self.assertIn("| loop_1 | 2 | 1 |", rendered)

    def test_missing_workspace_raises_value_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"

            with self.assertRaises(ValueError):
                build_search_yield_stats(missing)

    def test_workspace_without_search_log_renders_empty_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "evidence_ledger.md").write_text(LEDGER, encoding="utf-8")

            stats = build_search_yield_stats(workspace)
            rendered = render_search_yield_stats(stats)

        self.assertEqual([], stats)
        self.assertIn(
            "| (no records) | 0 | 0 | 0 (-) | 0.00 | 0 | 0 |",
            rendered,
        )

    def test_malformed_jsonl_raises_value_error_with_line_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with (workspace / "search_log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{not valid json\n")

            with self.assertRaisesRegex(ValueError, "line 8"):
                build_search_yield_stats(workspace)


class TestSearchIntelCli(unittest.TestCase):
    def test_digest_json_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            result = run_cli("digest", str(workspace), "--json")

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual(
            ["stage_0", "F1", "F2", "unbound"],
            [group["group_id"] for group in payload],
        )
        self.assertNotIn("CONTAMINANT", result.stdout)

    def test_digest_frontier_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            result = run_cli("digest", str(workspace), "--frontier", "F2")

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("#### F2", result.stdout)
        self.assertNotIn("#### F1", result.stdout)

    def test_stats_text_output_is_advisory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            result = run_cli("stats", str(workspace))

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("advisory only", result.stdout)

    def test_stats_loop_filter_accepts_numeric_loop_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))

            result = run_cli("stats", str(workspace), "--loop", "1")

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("| loop_1 | 2 | 1 |", result.stdout)
        self.assertNotIn("| loop_2 |", result.stdout)
        self.assertNotIn("(no records)", result.stdout)

    def test_malformed_search_log_exits_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with (workspace / "search_log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{not valid json\n")

            result = run_cli("stats", str(workspace))

        self.assertEqual(1, result.returncode)
        self.assertIn("SEARCH INTEL ERROR", result.stderr)

    def test_missing_workspace_exits_1(self):
        result = run_cli("digest", "/nonexistent/sofa/workspace")

        self.assertEqual(1, result.returncode)
        self.assertIn("SEARCH INTEL ERROR", result.stderr)

    def test_empty_but_valid_workspace_exits_0(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_cli("digest", temp_dir)

        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        self.assertIn("(no recorded searches)", result.stdout)


if __name__ == "__main__":
    unittest.main()
