import ast
import re
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
        self.assertEqual(17, sum(entry["expected_count"] for entry in allowlist.values()))
        self.assertEqual(17, sum(len(records) for records in occurrences.values()))
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
