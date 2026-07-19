import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_HOST_SPECIFIC_FRAGMENTS = (
    "docs/adapters/",
    "docs/architecture.md",
)
CACHE_DIR_NAMES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superpowers",
    ".tox",
    ".venv",
    ".git",
    "." + "worktrees",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}
ROOT_IGNORED_OUTPUT_DIR_NAMES = {
    "dive_packets",
    "reports",
    "workspace",
    "workspaces",
}
ROOT_GENERATED_FILE_NAMES = {
    "capability_report.md",
    "claim_ledger.md",
    "evidence_ledger.md",
    "research_workflow.md",
    "search_log.md",
    "state.json",
}
TEXT_SUFFIXES_TO_SCAN = {
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
BINARY_OR_TEMP_SUFFIXES = {
    ".bak",
    ".bin",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".orig",
    ".pdf",
    ".png",
    ".pyc",
    ".pyd",
    ".pyo",
    ".rej",
    ".so",
    ".swo",
    ".swp",
    ".tar",
    ".temp",
    ".tmp",
    ".zip",
}
FORBIDDEN_HOST_SPECIFIC_TERMS = (
    ".qoder" "workcn",
    "Qoder" "Work",
    "Todo" "Write",
    "AskUser" "Question",
    "Web" "Search",
    "Web" "Fetch",
)
MARKDOWN_INLINE_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)\n]+)\)")
MARKDOWN_REFERENCE_LINK = re.compile(
    r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)",
    re.MULTILINE,
)
EXTERNAL_LINK_SCHEMES = (
    "data:",
    "http:",
    "https:",
    "mailto:",
    "plugin:",
)
MARKDOWN_NETWORK_PATH = re.compile(r"^//[A-Za-z0-9.-]+(?=$|[/:?#])")
ALLOWED_NONLOCAL_REFERENCE = re.compile(
    r"(?:data:|https?://|mailto:|plugin:)[^\s<>)\]\"']+"
    r"|(?<![:/])//[A-Za-z0-9.-]+(?:/[^\s<>)\]\"']*)?",
    re.IGNORECASE,
)
RUNTIME_PLACEHOLDER_REFERENCE = re.compile(
    r"\{(?:PLUGIN_DIR|WORKSPACE)\}(?:[\\/][^\s<>)\]\"']*)?",
    re.IGNORECASE,
)
WINDOWS_DRIVE_PATH = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s`'\"<>|]*"
)
WINDOWS_UNC_PATH = re.compile(
    r"(?<![\\])\\\\[A-Za-z0-9._-]+[\\/][^\s`'\"<>|]*"
)
WINDOWS_ROOTED_PATH = re.compile(
    r"(?<![A-Za-z0-9_:\\])\\(?!\\)"
    r"(?:[A-Za-z0-9._~-]{2,}\\)+[A-Za-z0-9._~-]{2,}"
)
WINDOWS_ROOTED_SINGLE_TOKEN = re.compile(
    r"(?<!\S)\\(?!\\)[A-Za-z0-9._~-]{2,}(?=$|[\s`'\"<>|,;:)])"
)
FILE_URI_PATH = re.compile(
    r"(?<![A-Za-z0-9+.-])file:/{1,}(?=[%A-Za-z0-9._~-])[^\s`'\"<>]+",
    re.IGNORECASE,
)
POSIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_:./\\])/(?!/)"
    r"(?:(?:[A-Za-z0-9._~+-]+/)+[A-Za-z0-9._~+-]+|(?:tmp|home|Users))"
    r"(?=$|[\\/\s`'\"<>)\],.;:#?])",
    re.IGNORECASE,
)
POSIX_SINGLE_TOKEN_PATH = re.compile(
    r"(?<!\S)/(?!/)"
    r"(?!(?:tmp|home|Users)(?=$|[\\/\s`'\"<>)\],.;:#?]))"
    r"[A-Za-z0-9._~+-]{2,}(?=$|[\s`'\"<>)\],.;:#?])",
    re.IGNORECASE,
)
REPO_SELF_PREFIX = re.compile(
    r"(?<![A-Za-z0-9_./\\-])(?:\./)?SOFA[\\/][^\s`'\"<>]*",
    re.IGNORECASE,
)
ROOT_LEAK_LITERALS = (
    "project " + "serenity",
    "." + "worktrees",
    "serenity-osint-" + "v3.6.0",
    "docs/" + "superpowers",
)
TRAVERSAL_PATH_SEGMENT = re.compile(r"(?:^|[\\/])\.\.[\\/]")
TASK9_FIXTURE_MARKER = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"(?:task\s*9|task9|todo|fixme|tbd|template|placeholder|replace\s+me)"
    r"(?![A-Za-z0-9_-])"
    r"|\{(?:PLUGIN_DIR|WORKSPACE|SUBJECT|TICKER|DATE|LOOP_ID|FRONTIER_ID)\}"
    r"|\{\{|\}\}"
)
TEST_PATH_LITERAL_ALLOWLIST = {
    (
        "tests/test_dispatch_assembly.py",
        ".." + "/" + "escape",
    ): {
        "reason": "unsafe dispatch name-field traversal rejection",
        "expected_count": 1,
    },
    (
        "tests/test_dispatch_assembly.py",
        ".." + "/" + ".." + "/" + "etc/evil.md",
    ): {
        "reason": "dispatch output-path traversal rejection",
        "expected_count": 1,
    },
    (
        "tests/test_run_coverage.py",
        r'["\']' + "/" + "tmp",
    ): {
        "reason": "temporary-directory dependency guard regex",
        "expected_count": 1,
    },
    (
        "tests/test_run_coverage.py",
        '"' + "/" + 'tmp"',
    ): {
        "reason": "temporary-directory double-quoted negative assertion",
        "expected_count": 1,
    },
    (
        "tests/test_run_coverage.py",
        "'" + "/" + "tmp'",
    ): {
        "reason": "temporary-directory single-quoted negative assertion",
        "expected_count": 1,
    },
    (
        "tests/test_search_intel.py",
        "/" + "nonexistent/sofa/workspace",
    ): {
        "reason": "missing-workspace CLI negative fixture",
        "expected_count": 1,
    },
    (
        "tests/test_search_intel.py",
        "/" + "tmp",
    ): {
        "reason": "invalid-command CLI negative fixture",
        "expected_count": 1,
    },
    (
        "tests/test_sofa_contract.py",
        "./scouts/" + ".." + "/" + "scouts/loop_1_scout.md",
    ): {
        "reason": "dispatch delivery-path normalization fixture",
        "expected_count": 1,
    },
    (
        "tests/test_source_cache.py",
        ".." + "/" + "src-001.md",
    ): {
        "reason": "source-cache folder-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "/" + "workspace/research",
    ): {
        "reason": "user-supplied runtime workspace root may be absolute",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "/" + "tmp/outside.md",
    ): {
        "reason": "POSIX absolute workspace-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "C:" + "/" + "tmp/outside.md",
    ): {
        "reason": "Windows drive workspace-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "\\" * 2 + "server\\share\\outside.md",
    ): {
        "reason": "Windows UNC workspace-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "\\" + "tmp\\outside.md",
    ): {
        "reason": "Windows rooted workspace-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        ".." + "/" + "outside.md",
    ): {
        "reason": "relative workspace-escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "maps/" + ".." + "/" + "maps/dependency_ladder.md",
    ): {
        "reason": "worker-output relative normalization fixture",
        "expected_count": 1,
    },
    (
        "tests/test_workspace_contract.py",
        "./maps/" + ".." + "/" + "maps/dependency_ladder.md",
    ): {
        "reason": "main-thread artifact relative normalization fixture",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_generation.py",
        ".." + "/" + "escape.txt",
    ): {
        "reason": "observed-read workspace-containment escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_generation.py",
        "/" + "etc/passwd",
    ): {
        "reason": "observed-read POSIX-absolute path rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_generation.py",
        "C:" + "/" + "Windows/system32",
    ): {
        "reason": "observed-read Windows-drive path rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_generation.py",
        "a/" + ".." + "/" + ".." + "/" + "escape.txt",
    ): {
        "reason": "observed-read dot-segment escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        ".." + "/" + "escape",
    ): {
        "reason": "observed-read workspace traversal rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        ".." + "/" + "outside.md",
    ): {
        "reason": "emergent dispatch delivery escape rejection",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "/" + "RC-0001.json",
    ): {
        "reason": "f-string cycle JSON authority path suffix",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "/" + "RC-0001.md",
    ): {
        "reason": "f-string cycle mirror authority path suffix",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "/" + "loop",
    ): {
        "reason": "f-string representative worker output path fragment",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "/" + "reports/final.md",
    ): {
        "reason": "Packet A pointer validate POSIX-absolute rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "C:" + "/" + "reports/final.md",
    ): {
        "reason": "Packet A pointer strict-load Windows-drive rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "\\" * 2 + "server\\share\\final.md",
    ): {
        "reason": "Packet A request selected-source UNC rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "reports/" + ".." + "/" + "initial.md",
    ): {
        "reason": "Packet A cycle base raw-parent rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "/" + "claims/selected.md",
    ): {
        "reason": "Packet A cycle selected-source strict-load POSIX-absolute rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "evidence/" + ".." + "/" + "inherited.md",
    ): {
        "reason": "Packet A cycle inherited-artifact raw-parent rejection owner",
        "expected_count": 1,
    },
    (
        "tests/test_revisit_contract.py",
        "C:" + "/" + "evidence/accepted.md",
    ): {
        "reason": "Packet A cycle accepted-artifact Windows-drive rejection owner",
        "expected_count": 1,
    },
}


class TestSofaStructure(unittest.TestCase):
    def test_required_repo_tree_exists(self):
        required_paths = [
            "README.md",
            "README_CN.md",
            "requirements-dev.txt",
            "docs/installation.md",
            "docs/capability-setup.md",
            "docs/report-guide.md",
            "docs/architecture.md",
            "docs/codemap.md",
            "docs/adapters/codex.md",
            "docs/adapters/claude-code.md",
            "docs/adapters/qoder-work.md",
            "docs/adapters/generic-agent.md",
            "docs/adapters/zcode.md",
            "skills/sofa-analyze/SKILL.md",
            "skills/sofa-analyze/references/workflow-guide.md",
            "skills/sofa-analyze/references/ticker-dive-guide.md",
            "skills/sofa-analyze/references/sector-hunt-guide.md",
            "skills/sofa-analyze/references/sector-to-ultra-guide.md",
            "skills/sofa-analyze/references/search-strategy.md",
            "skills/sofa-analyze/references/final-report.md",
            "skills/sofa-analyze/references/method-card-spec.md",
            "skills/sofa-analyze/references/knowledge/methodology.md",
            "skills/sofa-analyze/method-cards/index.md",
            "scripts/archive_source.py",
            "scripts/capability_check.py",
            "scripts/frontier_lifecycle.py",
            "scripts/frontier_review.py",
            "scripts/generate_ultra_packet.py",
            "scripts/run_coverage.py",
            "scripts/prompts/frontier_review_prompt.md",
            # Task 6 observed-read readiness architecture (deep seam + tests).
            "scripts/revisit_contract/__init__.py",
            "scripts/revisit_contract/context.py",
            "scripts/revisit_contract/model.py",
            "scripts/revisit_contract/render.py",
            "scripts/revisit_contract/store.py",
            "scripts/revisit_contract/generation.py",
            "scripts/revisit_cycle.py",
            "scripts/sofa_contract/revisit_readiness.py",
            "tests/fixtures/revisit_completed_ticker",
            "tests/test_revisit_generation.py",
            "tests/test_revisit_readiness.py",
        ]
        missing = [path for path in required_paths if not (ROOT / path).exists()]
        self.assertEqual(
            [],
            missing,
            "Missing required SOFA paths:\n" + "\n".join(missing),
        )

    def test_method_cards_are_private_method_files(self):
        cards_dir = ROOT / "skills/sofa-analyze/method-cards"
        expected = [
            cards_dir / "supply-chain-mapping/METHOD.md",
            cards_dir / "customer-graph-discovery/METHOD.md",
            cards_dir / "financial-bridge/METHOD.md",
            cards_dir / "red-team/METHOD.md",
        ]
        missing = [str(path.relative_to(ROOT)) for path in expected if not path.exists()]
        self.assertEqual(
            [],
            missing,
            "Missing private method card files:\n" + "\n".join(missing),
        )
        skill_files = [str(path.relative_to(ROOT)) for path in cards_dir.glob("*/SKILL.md")]
        self.assertEqual(
            [],
            skill_files,
            "Method cards must not be user-invocable SKILL.md files:\n"
            + "\n".join(skill_files),
        )

    def test_host_specific_terms_are_confined_to_adapters(self):
        violations = []
        for path in ROOT.rglob("*"):
            if not _should_scan_path(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if any(fragment in rel for fragment in ALLOWED_HOST_SPECIFIC_FRAGMENTS):
                continue
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for term in FORBIDDEN_HOST_SPECIFIC_TERMS:
                    if term in line:
                        violations.append(f"{rel}:{line_number}: {term}")
        self.assertEqual(
            [],
            violations,
            "Host-specific terms outside adapters/architecture:\n"
            + "\n".join(violations),
        )

    def test_repository_owned_scan_includes_command_and_config_text(self):
        paths = (
            ROOT / ".github/workflows/ci.yml",
            ROOT / "requirements-dev.txt",
            ROOT / "scripts/init_workspace.py",
        )

        self.assertEqual(
            [path.relative_to(ROOT).as_posix() for path in paths],
            [
                path.relative_to(ROOT).as_posix()
                for path in paths
                if _should_scan_path(path)
            ],
        )

    def test_repository_owned_selector_excludes_ignored_root_outputs(self):
        selector = globals().get("_is_repository_owned_text_path")
        self.assertIsNotNone(selector, "Pure repository-owned selector is required")

        included = (
            Path(".github/workflows/ci.yml"),
            Path("requirements-dev.txt"),
            Path("scripts/init_workspace.py"),
            Path("docs/report-guide.md"),
            Path("docs/reports/guide.md"),
        )
        excluded = (
            Path("workspace/session/state.json"),
            Path("workspaces/session/evidence.md"),
            Path("reports/final.md"),
            Path("dive_packets/packet.json"),
            Path("claim_ledger.md"),
            Path("search_log.md"),
            Path("capability_report.md"),
            Path("evidence_ledger.md"),
            Path("research_workflow.md"),
            Path("state.json"),
            Path(".superpowers/review.md"),
            Path("." + "worktrees/review/tests/test_review.py"),
            Path("build/report.txt"),
            Path("dist/report.json"),
            Path("docs/__pycache__/cache.py"),
            Path("notes.tmp"),
        )
        self.assertEqual([], [path.as_posix() for path in included if not selector(path)])
        self.assertEqual([], [path.as_posix() for path in excluded if selector(path)])

    def test_path_shaped_detector_positive_and_negative_tables(self):
        detector = globals().get("_local_path_reference_findings")
        self.assertIsNotNone(detector, "Pure path-shaped detector is required")

        positives = (
            ("windows-drive-forward", "C:" + "/" + "developer/fixture.json", "absolute-local"),
            ("windows-drive-backward", "D:" + "\\" + "work\\fixture.json", "absolute-local"),
            ("windows-unc", "\\" * 2 + "server\\share\\fixture.json", "absolute-local"),
            ("windows-rooted", "\\" + "tmp\\fixture.json", "absolute-local"),
            ("file-uri", "file:" + "///" + "etc/sofa/config", "absolute-local"),
            ("posix-opt", "/" + "opt/sofa/config.toml", "absolute-local"),
            ("posix-var", "/" + "var/lib/sofa/data.json", "absolute-local"),
            ("posix-etc", "/" + "etc/sofa/config", "absolute-local"),
            ("posix-placeholder", "/" + "path/to/workspace", "absolute-local"),
            ("posix-tmp", "/" + "tmp", "absolute-local"),
            ("posix-home", "/" + "home/user", "absolute-local"),
            ("posix-users", "/" + "Users/name", "absolute-local"),
            ("repo-prefix-forward", "SO" + "FA/README.md", "repo-self-prefix"),
            ("repo-prefix-backward", "so" + "fa\\skills\\sofa-analyze", "repo-self-prefix"),
        )
        negatives = (
            "https://example.com/SOFA/README.md",
            "mailto:owner@example.com/SOFA/docs",
            "data:text/plain,SOFA/README.md",
            "plugin://catalog/SOFA/README.md",
            "//example.com/path",
            "./workspace",
            "scripts/init_workspace.py",
            ".." + "/" + "docs/report-guide.md",
            "vendor/" + "so" + "fa/config.toml",
            "pattern file:" + "/+" + "[^space]+",
            "{PLUGIN_DIR}/scripts/capability_check.py",
            "{WORKSPACE}/reports/final.md",
            "#!/usr/bin/env python3",
        )

        mismatched = []
        for label, text, expected_kind in positives:
            findings = detector(text)
            kinds = [kind for kind, _matched in findings]
            if kinds != [expected_kind]:
                mismatched.append((label, kinds))
        unexpected = [(text, detector(text)) for text in negatives if detector(text)]
        self.assertEqual([], mismatched)
        self.assertEqual([], unexpected)

    def test_path_shaped_detector_covers_command_boundaries(self):
        cases = (
            (
                "dot-slash-repo-prefix",
                "python ./" + "SO" + "FA/scripts/tool.py",
                "repo-self-prefix",
            ),
            ("bare-repo-prefix", "inspect " + "SO" + "FA/", "repo-self-prefix"),
            ("single-token-posix", "cd " + "/" + "opt", "absolute-local"),
            ("single-token-windows-rooted", "type " + "\\" + "boot.ini", "absolute-local"),
            (
                "percent-encoded-file-uri",
                "open file:" + "///" + "%2Fetc%2Fpasswd",
                "absolute-local",
            ),
        )
        negatives = (
            "regex " + "\\" + "d",
            "option=" + "/" + "opt",
        )

        mismatched = []
        for label, text, expected_kind in cases:
            kinds = [kind for kind, _matched in _local_path_reference_findings(text)]
            if kinds != [expected_kind]:
                mismatched.append((label, kinds))
        unexpected = [
            (text, _local_path_reference_findings(text))
            for text in negatives
            if _local_path_reference_findings(text)
        ]
        self.assertEqual([], mismatched)
        self.assertEqual([], unexpected)

    def test_test_literal_scanner_detects_future_unapproved_absolute_path(self):
        scanner = globals().get("_python_string_path_occurrences")
        self.assertIsNotNone(scanner, "AST string path scanner is required")

        absolute_path = "D:" + "\\" + "developer\\fixture.json"
        source = f"from pathlib import Path\nfixture = Path({absolute_path!r})\n"
        occurrences = scanner(Path("tests/test_future_fixture.py"), source)
        self.assertIn(("tests/test_future_fixture.py", absolute_path), occurrences)

    def test_test_literal_allowlist_reports_unexpected_and_stale_entries(self):
        classify = globals().get("_test_literal_allowlist_mismatches")
        self.assertIsNotNone(classify, "Allowlist mismatch classifier is required")

        unexpected_key = (
            "tests/test_future_fixture.py",
            "/" + "opt/future/fixture.json",
        )
        stale_key = (
            "tests/test_removed_fixture.py",
            ".." + "/" + "outside.md",
        )
        occurrences = {unexpected_key: ((1, ("absolute-local",)),)}
        allowlist = {
            stale_key: {
                "reason": "removed path-escape fixture",
                "expected_count": 1,
            }
        }

        unexpected, stale = classify(occurrences, allowlist)
        self.assertEqual({unexpected_key: 1}, unexpected)
        self.assertEqual({stale_key: (1, 0)}, stale)

    def test_test_path_literals_match_explicit_allowlist(self):
        scan = globals().get("_test_path_literal_occurrences")
        classify = globals().get("_test_literal_allowlist_mismatches")
        allowlist = globals().get("TEST_PATH_LITERAL_ALLOWLIST")
        self.assertIsNotNone(scan, "Repository test-literal scanner is required")
        self.assertIsNotNone(classify, "Allowlist mismatch classifier is required")
        self.assertIsNotNone(allowlist, "Explicit test-literal allowlist is required")

        occurrences = scan()
        unexpected, stale = classify(occurrences, allowlist)
        self.assertEqual({}, unexpected)
        self.assertEqual({}, stale)
        self.assertEqual(33, sum(entry["expected_count"] for entry in allowlist.values()))
        self.assertEqual(33, sum(len(records) for records in occurrences.values()))
        self.assertEqual(
            [],
            [key for key, entry in allowlist.items() if not entry["reason"].strip()],
        )

    def test_non_python_test_text_uses_line_reference_scan(self):
        scan = globals().get("_repository_text_line_violations")
        self.assertIsNotNone(scan, "Repository text line scanner is required")

        relative_path = Path("tests/fixtures/config.yml")
        absolute_path = "D:" + "\\" + "developer\\fixture.json"
        self.assertEqual(
            [
                "absolute-local:tests/fixtures/config.yml:1: "
                + absolute_path
            ],
            scan(relative_path, f"fixture: {absolute_path}\n"),
        )

    def test_python_test_ast_classifies_root_leak(self):
        relative_path = Path("tests/test_future_root_leak.py")
        root_leak = "project " + "serenity/fixture.json"
        source = f"fixture = {root_leak!r}\n"

        occurrences = _python_string_path_occurrences(relative_path, source)
        self.assertEqual(
            ((1, ("root-leak",)),),
            occurrences.get((relative_path.as_posix(), root_leak)),
        )

    def test_markdown_network_path_is_external_but_unc_is_local(self):
        markdown_path = ROOT / "docs/network-link-fixture.md"
        self.assertEqual(
            [],
            _markdown_link_violations(
                markdown_path,
                "[site](//example.com/path)",
            ),
        )

        unc_target = "\\" * 2 + "server\\share\\file.md"
        self.assertEqual(
            [
                "markdown-link-absolute:docs/network-link-fixture.md:1: "
                + unc_target
            ],
            _markdown_link_violations(
                markdown_path,
                f"[local]({unc_target})",
            ),
        )

    # ------------------------------------------------------------------
    # Task 6 architecture guards: lock the observed-read readiness design.
    #
    # Production (Task 6.4/6.5) is already correct, so each guard PASSES
    # immediately and locks current good state. A failure here means a
    # production regression re-introduced a forbidden marker or raw-I/O
    # call -- report it; do NOT weaken the guard or patch production in
    # this test-only packet.
    # ------------------------------------------------------------------

    def test_revisit_readiness_owns_semantic_io_and_cli_has_no_manual_union(self):
        # Guard 1: the deleted readiness internals must never return inside the
        # readiness seam or the CLI ``check`` adapter. (Note: the spelling in
        # the plan body, ``_evaluate_discovered_revisited_report``, is also
        # forbidden alongside the canonical ``_evaluate_discovered_revisit_report``.)
        readiness_source = (ROOT / "scripts" / "sofa_contract" / "revisit_readiness.py").read_text(encoding="utf-8")
        cli_source = (ROOT / "scripts" / "revisit_cycle.py").read_text(encoding="utf-8")
        combined = readiness_source + cli_source
        for forbidden in (
            "required_authority_paths",
            "_capture_dispatch_delivery_generations",
            "require_candidate",
            "_command_check_in_transaction",
            "_evaluate_discovered_revisit_report",
            "_evaluate_discovered_revisited_report",
        ):
            self.assertNotIn(
                forbidden,
                combined,
                f"deleted readiness internal {forbidden!r} re-introduced in "
                "revisit_readiness.py or revisit_cycle.py",
            )

    def test_revisit_readiness_module_has_no_raw_filesystem_calls(self):
        # Guard 2: the whole readiness module must do ALL semantic FS via
        # ObservedReadSession (read_required/read_optional/list_directory).
        # Reject raw I/O Call nodes anywhere in the module AST.
        readiness_path = ROOT / "scripts" / "sofa_contract" / "revisit_readiness.py"
        violations = _raw_io_call_violations(readiness_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [],
            violations,
            "revisit_readiness.py must route all semantic filesystem access "
            "through ObservedReadSession; raw I/O call nodes found:\n"
            + "\n".join(
                f"  line {lineno}: .{attr}()" if attr != "open" else f"  line {lineno}: open(...)"
                for lineno, attr in violations
            ),
        )

    def test_evaluate_pure_owners_have_no_raw_filesystem_calls(self):
        # Guard 3: the six extracted PURE preloaded-document owners in
        # evaluate.py must not do raw FS reads (the surrounding thin FS
        # adapters MAY). Walk each target function's AST subtree only.
        evaluate_path = ROOT / "scripts" / "sofa_contract" / "evaluate.py"
        tree = ast.parse(evaluate_path.read_text(encoding="utf-8"))
        target_owners = {
            "_evaluate_specific_ticker_report_document",
            "_check_state_workflow_documents",
            "_search_facts_from_records",
            "_check_dispatch_documents",
            "_check_worker_output_documents",
            "_derive_revisit_frontier_floor_issues_from_facts",
        }
        found_owners = set()
        failures = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name not in target_owners:
                continue
            found_owners.add(node.name)
            for lineno, attr in _raw_io_call_violations_for_node(node):
                failures.append(
                    f"{node.name}:line {lineno}: .{attr}()"
                    if attr != "open"
                    else f"{node.name}:line {lineno}: open(...)"
                )
        self.assertEqual(
            set(),
            target_owners - found_owners,
            "expected pure owner function definition(s) missing from evaluate.py: "
            + ", ".join(sorted(target_owners - found_owners)),
        )
        self.assertEqual(
            [],
            failures,
            "evaluate.py pure owners must accept preloaded facts only; raw I/O "
            "call nodes found:\n" + "\n".join(failures),
        )

    def test_revisit_contract_does_not_import_sofa_contract(self):
        # Guard 4a: dependency direction. revisit_contract must NOT depend on
        # sofa_contract (sofa_contract depends on revisit_contract, not vice-versa).
        revisit_contract_dir = ROOT / "scripts" / "revisit_contract"
        offenders = []
        for path in sorted(revisit_contract_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = node.module or ""
                if module == "sofa_contract" or module.startswith("sofa_contract."):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:line {node.lineno}: "
                        f"from {module} import ..."
                    )
        self.assertEqual(
            [],
            offenders,
            "scripts/revisit_contract/ must not import sofa_contract "
            "(wrong dependency direction):\n" + "\n".join(offenders),
        )

    def test_require_unchanged_except_is_imported_only_by_store(self):
        # Guard 4b: ``_require_unchanged_except`` is module-private (underscore)
        # and must be imported ONLY by scripts/revisit_contract/store.py in the
        # whole production tree. (Tests reference it for intrinsic store tests.)
        offenders = []
        for path in sorted((ROOT / "scripts").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel == "scripts/revisit_contract/store.py":
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                for alias in node.names:
                    if alias.name == "_require_unchanged_except":
                        offenders.append(f"{rel}:line {node.lineno}")
        self.assertEqual(
            [],
            offenders,
            "_require_unchanged_except must be imported only by "
            "scripts/revisit_contract/store.py; other importers found:\n"
            + "\n".join(offenders),
        )

    def test_revisit_cycle_cli_imports_public_check_seam_only(self):
        # Guard 4c: revisit_cycle.py ``command_check`` is a thin adapter calling
        # ``check_revisit_readiness`` (the public seam). It must NOT import any
        # generation type (those live behind the ObservedReadSession boundary).
        cli_source = (ROOT / "scripts" / "revisit_cycle.py").read_text(encoding="utf-8")
        self.assertIn(
            "check_revisit_readiness",
            cli_source,
            "revisit_cycle.py must import the public check_revisit_readiness seam",
        )
        for forbidden_type in (
            "GenerationClosure",
            "ObservedReadSession",
            "AuthorityDriftError",
            "FileGeneration",
        ):
            self.assertNotIn(
                forbidden_type,
                cli_source,
                f"revisit_cycle.py must not reference generation type "
                f"{forbidden_type!r} (it belongs behind the observed-read seam)",
            )

    def test_evaluate_routes_both_named_and_profile_to_readiness_seam(self):
        # Guard 4d: evaluate.py routes BOTH the named adapter
        # (``evaluate_revisit_report``) and the profile target
        # (``ContractProfile(target="revisit_report")`` in ``evaluate_workspace``)
        # to the single ``evaluate_revisit_readiness`` seam.
        evaluate_source = (ROOT / "scripts" / "sofa_contract" / "evaluate.py").read_text(encoding="utf-8")
        self.assertIn(
            "evaluate_revisit_readiness",
            evaluate_source,
            "evaluate.py must reference evaluate_revisit_readiness",
        )
        # The named adapter and the profile branch each reference the seam.
        tree = ast.parse(evaluate_source, filename="scripts/sofa_contract/evaluate.py")
        named_routes = False
        profile_routes = False
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            calls_to_seam = [
                call.func
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "evaluate_revisit_readiness"
            ]
            if not calls_to_seam:
                continue
            if node.name == "evaluate_revisit_report":
                named_routes = True
            elif node.name == "evaluate_workspace":
                profile_routes = True
        self.assertTrue(
            named_routes,
            "evaluate_revisit_report must delegate to evaluate_revisit_readiness",
        )
        self.assertTrue(
            profile_routes,
            "evaluate_workspace must route the revisit_report target to "
            "evaluate_revisit_readiness",
        )

    def test_revisit_package_and_cli_support_package_and_flat_imports(self):
        cases = (
            (
                "package",
                ROOT,
                "import scripts.revisit_contract; import scripts.revisit_cycle",
            ),
            (
                "flat",
                ROOT / "scripts",
                "import revisit_contract; import revisit_cycle",
            ),
        )
        for label, cwd, statement in cases:
            with self.subTest(mode=label):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", statement],
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_task9_fixture_text_is_strict_utf8_repo_relative_and_marker_free(self):
        fixture_root = ROOT / "tests" / "fixtures" / "revisit_completed_ticker"
        self.assertTrue(fixture_root.is_dir(), fixture_root)
        violations = []
        for path in sorted(fixture_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT)
            try:
                text = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                violations.append(f"invalid-utf8:{relative.as_posix()}:{exc.start}")
                continue
            if text.startswith("\ufeff"):
                violations.append(f"utf8-bom:{relative.as_posix()}")
            for match in TASK9_FIXTURE_MARKER.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                violations.append(
                    f"fixture-marker:{relative.as_posix()}:{line_number}:"
                    f"{match.group(0)}"
                )
            violations.extend(_repository_text_line_violations(relative, text))
            if path.suffix == ".md":
                violations.extend(_markdown_link_violations(path, text))
        self.assertEqual(
            [],
            sorted(violations),
            "Task 9 fixture must contain only strict UTF-8, repository-relative "
            "text without task/template markers:\n" + "\n".join(sorted(violations)),
        )

    def test_repository_file_references_are_self_contained(self):
        violations = []
        for path in _repo_text_files():
            text = path.read_text(encoding="utf-8")
            violations.extend(
                _repository_text_line_violations(path.relative_to(ROOT), text)
            )

            if path.suffix == ".md":
                violations.extend(_markdown_link_violations(path, text))

        self.assertEqual(
            [],
            sorted(violations),
            "Repository references must be relative and self-contained:\n"
            + "\n".join(sorted(violations)),
        )


def _should_scan_path(path):
    if not path.is_file():
        return False
    try:
        relative_path = path.relative_to(ROOT)
    except ValueError:
        return False
    return _is_repository_owned_text_path(relative_path)


def _is_repository_owned_text_path(relative_path):
    relative_path = Path(relative_path)
    if relative_path.is_absolute() or not relative_path.parts:
        return False
    if relative_path.parts[0] in ROOT_IGNORED_OUTPUT_DIR_NAMES:
        return False
    if len(relative_path.parts) == 1 and relative_path.name in ROOT_GENERATED_FILE_NAMES:
        return False
    if any(part in CACHE_DIR_NAMES for part in relative_path.parts):
        return False
    if relative_path.name.endswith("~"):
        return False
    suffix = relative_path.suffix.casefold()
    if suffix in BINARY_OR_TEMP_SUFFIXES:
        return False
    return suffix in TEXT_SUFFIXES_TO_SCAN


def _repo_text_files():
    return sorted(
        (path for path in ROOT.rglob("*") if _should_scan_path(path)),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def _visible_local_reference_text(text):
    if text.lstrip().startswith("#!"):
        return ""
    text = ALLOWED_NONLOCAL_REFERENCE.sub("", text)
    return RUNTIME_PLACEHOLDER_REFERENCE.sub("", text)


def _local_path_reference_findings(text):
    visible = _visible_local_reference_text(text)
    findings = []

    for match in FILE_URI_PATH.finditer(visible):
        findings.append(("absolute-local", match.group(0)))
    visible = FILE_URI_PATH.sub("", visible)

    for pattern in (
        WINDOWS_DRIVE_PATH,
        WINDOWS_UNC_PATH,
        WINDOWS_ROOTED_PATH,
        WINDOWS_ROOTED_SINGLE_TOKEN,
        POSIX_ABSOLUTE_PATH,
        POSIX_SINGLE_TOKEN_PATH,
    ):
        for match in pattern.finditer(visible):
            findings.append(("absolute-local", match.group(0)))
    for match in REPO_SELF_PREFIX.finditer(visible):
        findings.append(("repo-self-prefix", match.group(0)))
    return findings


def _repository_text_line_violations(relative_path, text):
    relative_path = Path(relative_path)
    if (
        relative_path.parts
        and relative_path.parts[0] == "tests"
        and relative_path.suffix.casefold() == ".py"
    ):
        return []

    rel = relative_path.as_posix()
    violations = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        visible = _visible_local_reference_text(line)
        for kind, matched in _local_path_reference_findings(line):
            violations.append(f"{kind}:{rel}:{line_number}: {matched}")
        lowered = visible.casefold()
        for literal in ROOT_LEAK_LITERALS:
            if literal.casefold() in lowered:
                violations.append(f"root-leak:{rel}:{line_number}: {literal}")
    return violations


def _python_string_path_occurrences(relative_path, source):
    relative_path = Path(relative_path).as_posix()
    occurrences = {}
    tree = ast.parse(source, filename=relative_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        kinds = [kind for kind, _matched in _local_path_reference_findings(node.value)]
        if TRAVERSAL_PATH_SEGMENT.search(node.value):
            kinds.append("traversal")
        visible = _visible_local_reference_text(node.value).casefold()
        if any(literal.casefold() in visible for literal in ROOT_LEAK_LITERALS):
            kinds.append("root-leak")
        if not kinds:
            continue
        key = (relative_path, node.value)
        occurrences.setdefault(key, []).append((node.lineno, tuple(sorted(set(kinds)))))
    return {key: tuple(records) for key, records in occurrences.items()}


# Raw filesystem Call attributes that the observed-read readiness seam forbids.
# ``ObservedReadSession.read_required``/``read_optional``/``list_directory`` are
# the ALLOWED seam (method calls on a session object, NOT these attributes).
FORBIDDEN_RAW_IO_ATTRS = frozenset(
    {
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "exists",
        "is_file",
        "is_dir",
        "iterdir",
        "glob",
        "rglob",
    }
)


def _raw_io_call_violations(source):
    """Return ``(lineno, attr_name)`` tuples for raw I/O Call nodes in ``source``.

    Targets the ``.<forbidden_attr>(...)`` Call pattern (ast.Attribute on an
    ast.Call) plus a bare ``open(...)`` builtin call. Walks the parsed AST so a
    forbidden name appearing only in a comment or string does NOT trip the check.
    """
    return _collect_raw_io_calls(ast.walk(ast.parse(source)))


def _raw_io_call_violations_for_node(node):
    """Scope the raw-I/O Call check to ``node``'s subtree (used per function)."""
    return _collect_raw_io_calls(ast.walk(node))


def _collect_raw_io_calls(nodes):
    violations = []
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_RAW_IO_ATTRS:
            violations.append((node.lineno, func.attr))
        elif isinstance(func, ast.Name) and func.id == "open":
            violations.append((node.lineno, "open"))
    return violations


def _test_path_literal_occurrences():
    occurrences = {}
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if not _should_scan_path(path):
            continue
        relative_path = path.relative_to(ROOT)
        per_file = _python_string_path_occurrences(
            relative_path,
            path.read_text(encoding="utf-8"),
        )
        for key, records in per_file.items():
            occurrences.setdefault(key, []).extend(records)
    return {key: tuple(records) for key, records in occurrences.items()}


def _test_literal_allowlist_mismatches(occurrences, allowlist):
    unexpected = {
        key: len(records)
        for key, records in occurrences.items()
        if key not in allowlist
    }
    stale = {}
    for key, entry in allowlist.items():
        expected_count = entry["expected_count"]
        actual_count = len(occurrences.get(key, ()))
        if actual_count != expected_count:
            stale[key] = (expected_count, actual_count)
    return unexpected, stale


def _markdown_link_violations(path, text):
    violations = []
    rel = path.relative_to(ROOT).as_posix()
    matches = list(MARKDOWN_INLINE_LINK.finditer(text))
    matches.extend(MARKDOWN_REFERENCE_LINK.finditer(text))
    for match in matches:
        target = _markdown_link_target(match.group("target"))
        if not target or target.startswith("#"):
            continue
        if _is_external_markdown_link(target):
            continue

        line_number = text.count("\n", 0, match.start()) + 1
        decoded_target = unquote(target)
        if _is_absolute_local_link(decoded_target):
            violations.append(
                f"markdown-link-absolute:{rel}:{line_number}: {target}"
            )
            continue

        local_target = decoded_target.split("#", 1)[0].split("?", 1)[0]
        if not local_target:
            continue
        resolved = (path.parent / local_target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            violations.append(
                f"markdown-link-outside:{rel}:{line_number}: {target}"
            )
            continue
        if not resolved.exists():
            violations.append(
                f"markdown-link-missing:{rel}:{line_number}: {target}"
            )
    return violations


def _markdown_link_target(raw_target):
    target = raw_target.strip()
    if target.startswith("<"):
        closing = target.find(">")
        if closing != -1:
            return target[1:closing]
    return target.split(maxsplit=1)[0] if target else ""


def _is_external_markdown_link(target):
    return (
        target.casefold().startswith(EXTERNAL_LINK_SCHEMES)
        or MARKDOWN_NETWORK_PATH.match(target) is not None
    )


def _is_absolute_local_link(target):
    return (
        target.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[\\/]", target) is not None
        or target.casefold().startswith("file:")
    )
