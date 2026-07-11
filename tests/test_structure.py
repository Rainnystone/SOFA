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
    ".worktrees",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}
TEXT_SUFFIXES_TO_SCAN = {
    ".md",
    ".py",
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
URL_LITERAL = re.compile(
    r"(?:data:|https?://|mailto:|plugin:)[^\s<>)\]\"']+",
    re.IGNORECASE,
)
ABSOLUTE_LOCAL_LITERAL = re.compile(
    r"(?P<windows>(?<![A-Za-z0-9_])[A-Za-z]:[\\/])"
    r"|(?P<unc>(?<![\\])\\\\[A-Za-z0-9._-]+[\\/])"
    r"|(?P<posix>/(?:path/to|tmp|home|Users)(?![A-Za-z0-9_.-]))",
    re.IGNORECASE,
)
REPO_SELF_PREFIX = re.compile(
    r"(?<![A-Za-z0-9_.-])SOFA/(?:scripts|tests|skills|docs)"
    r"(?:/|(?=[\s`'\".,;:)]|$))"
)
ROOT_LEAK_LITERALS = (
    "project serenity",
    ".worktrees",
    "serenity-osint-v3.6.0",
    "docs/superpowers",
)


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

    def test_repository_file_references_are_self_contained(self):
        violations = []
        for path in _repo_text_files():
            rel = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")

            if "tests" not in path.relative_to(ROOT).parts:
                for line_number, line in enumerate(text.splitlines(), start=1):
                    local_text = URL_LITERAL.sub("", line)
                    for match in ABSOLUTE_LOCAL_LITERAL.finditer(local_text):
                        violations.append(
                            f"absolute-local:{rel}:{line_number}: {match.group(0)}"
                        )
                    match = REPO_SELF_PREFIX.search(local_text)
                    if match:
                        violations.append(
                            f"repo-self-prefix:{rel}:{line_number}: {match.group(0)}"
                        )
                    lowered = local_text.casefold()
                    for literal in ROOT_LEAK_LITERALS:
                        if literal.casefold() in lowered:
                            violations.append(
                                f"root-leak:{rel}:{line_number}: {literal}"
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
    relative_parts = path.relative_to(ROOT).parts
    if any(part in CACHE_DIR_NAMES for part in relative_parts):
        return False
    if path.name.endswith("~"):
        return False
    if path.suffix in BINARY_OR_TEMP_SUFFIXES:
        return False
    return path.suffix in TEXT_SUFFIXES_TO_SCAN


def _repo_text_files():
    return sorted(
        (path for path in ROOT.rglob("*") if _should_scan_path(path)),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def _markdown_link_violations(path, text):
    violations = []
    rel = path.relative_to(ROOT).as_posix()
    matches = list(MARKDOWN_INLINE_LINK.finditer(text))
    matches.extend(MARKDOWN_REFERENCE_LINK.finditer(text))
    for match in matches:
        target = _markdown_link_target(match.group("target"))
        if not target or target.startswith("#"):
            continue
        if target.casefold().startswith(EXTERNAL_LINK_SCHEMES):
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


def _is_absolute_local_link(target):
    return (
        target.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[\\/]", target) is not None
        or target.casefold().startswith("file:")
    )
