import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_HOST_SPECIFIC_FRAGMENTS = (
    "docs/adapters/",
    "docs/architecture.md",
)
CACHE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".git",
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


def _should_scan_path(path):
    if not path.is_file():
        return False
    if any(part in CACHE_DIR_NAMES for part in path.parts):
        return False
    if path.name.endswith("~"):
        return False
    if path.suffix in BINARY_OR_TEMP_SUFFIXES:
        return False
    return path.suffix in TEXT_SUFFIXES_TO_SCAN
