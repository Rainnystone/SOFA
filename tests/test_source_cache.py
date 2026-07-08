import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_cache import (  # noqa: E402
    BIBLIOGRAPHY_HEADING,
    EXCERPT_MAX_CHARS,
    GRADES,
    SCHEMA_FIELDS,
    SOURCE_ID_PATTERN,
    SOURCE_INDEX_FILENAME,
    SOURCES_DIRNAME,
    SourceCacheError,
    add_source,
    evaluate_index,
    excerpt_sha256,
    format_source_id,
    has_registered_source_id_reference,
    parse_source_number,
    registered_source_ids,
    render_source_bibliography,
    source_ids_in_text,
)

EXCERPT = "Segment revenue detail: datacom transceivers grew 40% YoY.\n"


def add_fixture_source(workspace: Path, **overrides):
    payload = {
        "url": "https://www.sec.gov/acme-10k",
        "title": "FY2025 10-K – Coherent Corp",
        "retrieved": "2026-07-08",
        "grade": "A",
        "excerpt_text": EXCERPT,
    }
    payload.update(overrides)
    return add_source(workspace, **payload)


class SourceCacheVocabularyTests(unittest.TestCase):
    def test_constants_are_single_authority(self):
        self.assertEqual(SOURCE_INDEX_FILENAME, "sources_index.jsonl")
        self.assertEqual(SOURCES_DIRNAME, "sources")
        self.assertEqual(GRADES, ("A", "B", "C", "D"))
        self.assertEqual(EXCERPT_MAX_CHARS, 16000)
        self.assertEqual(BIBLIOGRAPHY_HEADING, "### Prior Source Index (identifiers only)")
        self.assertEqual(SOURCE_ID_PATTERN.pattern, r"\bsrc-\d{3,}\b")
        self.assertEqual(
            SCHEMA_FIELDS,
            ("source_id", "url", "title", "retrieved", "grade", "excerpt_path", "sha256"),
        )
        self.assertEqual(format_source_id(7), "src-007")
        self.assertEqual(parse_source_number("src-042"), 42)
        self.assertEqual(parse_source_number("src-1000"), 1000)
        self.assertIsNone(parse_source_number("SRC-042"))
        self.assertEqual(source_ids_in_text("supported by src-001 and src-002"), ("src-001", "src-002"))
        self.assertEqual(source_ids_in_text("later archive src-1000"), ("src-1000",))
        self.assertEqual(source_ids_in_text("no citations here"), ())

    def test_hash_normalizes_line_endings(self):
        self.assertEqual(
            excerpt_sha256("line one\r\nline two\r\n"),
            excerpt_sha256("line one\nline two\n"),
        )

    def test_registered_source_id_helpers_require_valid_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.assertEqual(registered_source_ids(workspace), frozenset())
            self.assertFalse(has_registered_source_id_reference(workspace, "supported by src-001"))
            add_fixture_source(workspace)
            self.assertEqual(registered_source_ids(workspace), frozenset({"src-001"}))
            self.assertTrue(has_registered_source_id_reference(workspace, "supported by src-001"))
            self.assertFalse(has_registered_source_id_reference(workspace, "supported by src-999"))
            (workspace / SOURCE_INDEX_FILENAME).write_text("not json\n", encoding="utf-8")
            self.assertEqual(registered_source_ids(workspace), frozenset())
            self.assertFalse(has_registered_source_id_reference(workspace, "supported by src-001"))


class AddSourceTests(unittest.TestCase):
    def test_add_creates_excerpt_and_appends_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = add_fixture_source(workspace)
            self.assertTrue(result.created)
            self.assertEqual("src-001", result.source_id)
            excerpt_file = workspace / SOURCES_DIRNAME / "src-001.md"
            self.assertEqual(EXCERPT, excerpt_file.read_text(encoding="utf-8"))
            lines = (workspace / SOURCE_INDEX_FILENAME).read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            record = json.loads(lines[0])
            self.assertEqual(sorted(SCHEMA_FIELDS), sorted(record))
            self.assertEqual("sources/src-001.md", record["excerpt_path"])
            self.assertEqual(excerpt_sha256(EXCERPT), record["sha256"])

    def test_append_only_and_sequential_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            add_fixture_source(workspace)
            first_line = (workspace / SOURCE_INDEX_FILENAME).read_text(encoding="utf-8")
            second = add_fixture_source(
                workspace,
                url="https://www.sec.gov/acme-10k-risk",
                title="FY2025 10-K – Risk Factors",
                excerpt_text="Risk factors: single-source substrate dependency.\n",
            )
            self.assertEqual("src-002", second.source_id)
            content = (workspace / SOURCE_INDEX_FILENAME).read_text(encoding="utf-8")
            self.assertTrue(content.startswith(first_line))
            self.assertEqual(2, len(content.splitlines()))

    def test_identical_content_dedupes_to_existing_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            add_fixture_source(workspace)
            duplicate = add_fixture_source(
                workspace,
                url="https://mirror.example.com/acme-10k",
                title="Same excerpt, different mirror",
                excerpt_text=EXCERPT.replace("\n", "\r\n"),
            )
            self.assertFalse(duplicate.created)
            self.assertEqual("src-001", duplicate.source_id)
            self.assertEqual(
                1, len((workspace / SOURCE_INDEX_FILENAME).read_text(encoding="utf-8").splitlines())
            )
            self.assertFalse((workspace / SOURCES_DIRNAME / "src-002.md").exists())

    def test_same_url_different_content_is_allowed_with_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            add_fixture_source(workspace)
            second = add_fixture_source(
                workspace,
                excerpt_text="A different section of the same filing.\n",
            )
            self.assertTrue(second.created)
            self.assertEqual(("src-001",), second.url_duplicates)

    def test_add_fails_loudly_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            cases = (
                {"grade": "E"},
                {"retrieved": "07/08/2026"},
                {"url": "  "},
                {"title": ""},
                {"excerpt_text": "   \n"},
                {"excerpt_text": "x" * (EXCERPT_MAX_CHARS + 1)},
            )
            for overrides in cases:
                with self.subTest(overrides=overrides):
                    with self.assertRaises(SourceCacheError):
                        add_fixture_source(workspace, **overrides)
            self.assertFalse((workspace / SOURCE_INDEX_FILENAME).exists())
            self.assertFalse((workspace / SOURCES_DIRNAME).exists())


class EvaluateIndexTests(unittest.TestCase):
    def test_absent_and_empty_index_evaluate_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            evaluation = evaluate_index(workspace)
            self.assertEqual((), evaluation.records)
            self.assertEqual((), evaluation.issues)
            (workspace / SOURCE_INDEX_FILENAME).write_text("", encoding="utf-8")
            evaluation = evaluate_index(workspace)
            self.assertEqual((), evaluation.records)
            self.assertEqual((), evaluation.issues)

    def test_validation_issue_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            add_fixture_source(workspace)
            index = workspace / SOURCE_INDEX_FILENAME
            valid_line = index.read_text(encoding="utf-8").splitlines()[0]
            valid = json.loads(valid_line)

            missing = dict(valid, source_id="src-002", excerpt_path="sources/src-002.md", sha256="0" * 64)
            duplicate = dict(valid, source_id="src-003", excerpt_path="sources/src-001.md")
            bad_grade = dict(valid, source_id="src-004", grade="Z", sha256="1" * 64)
            index.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in (valid, missing, duplicate, bad_grade))
                + "\n",
                encoding="utf-8",
            )
            (workspace / SOURCES_DIRNAME / "notes.md").write_text("stray\n", encoding="utf-8")

            evaluation = evaluate_index(workspace)
            codes = {issue.code for issue in evaluation.issues}
            self.assertIn("SOURCE_EXCERPT_MISSING", codes)
            self.assertIn("SOURCE_HASH_DUPLICATE", codes)
            self.assertIn("SOURCE_INDEX_MALFORMED", codes)
            warning_codes = {warning.code for warning in evaluation.warnings}
            self.assertEqual({"SOURCE_EXCERPT_UNREGISTERED"}, warning_codes)

    def test_unparseable_line_is_malformed_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / SOURCE_INDEX_FILENAME).write_text("not json\n", encoding="utf-8")
            evaluation = evaluate_index(workspace)
            self.assertEqual((), evaluation.records)
            self.assertEqual(["SOURCE_INDEX_MALFORMED"], [issue.code for issue in evaluation.issues])


class BibliographyTests(unittest.TestCase):
    def test_bibliography_carries_identifiers_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            add_fixture_source(workspace)
            text = render_source_bibliography(workspace)
            self.assertIn(BIBLIOGRAPHY_HEADING, text)
            self.assertIn("src-001", text)
            self.assertIn("FY2025 10-K – Coherent Corp", text)
            self.assertIn("https://www.sec.gov/acme-10k", text)
            self.assertIn("retrieved 2026-07-08", text)
            self.assertNotIn("grade", text.lower())
            self.assertNotIn("Segment revenue detail", text)

    def test_bibliography_empty_when_no_records_and_loud_when_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            self.assertEqual("", render_source_bibliography(workspace))
            (workspace / SOURCE_INDEX_FILENAME).write_text("", encoding="utf-8")
            self.assertEqual("", render_source_bibliography(workspace))
            (workspace / SOURCE_INDEX_FILENAME).write_text("not json\n", encoding="utf-8")
            with self.assertRaises(SourceCacheError):
                render_source_bibliography(workspace)


class TestPackageImport(unittest.TestCase):
    """Namespace-import lock (PR #12 dual-import convention)."""

    def test_namespace_import_succeeds_from_repo_root(self):
        result = subprocess.run(
            [sys.executable, "-c", "import scripts.source_cache"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_flat_import_succeeds_from_scripts_dir(self):
        result = subprocess.run(
            [sys.executable, "-c", "import source_cache"],
            cwd=str(ROOT / "scripts"),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
