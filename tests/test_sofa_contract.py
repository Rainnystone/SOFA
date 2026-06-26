import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sofa_contract import ContractIssue, ContractProfile, ContractResult
from sofa_contract.workspace import iter_jsonl_records, read_json_file, read_text_file


class TestContractResultModel(unittest.TestCase):
    def test_contract_result_groups_failures_and_warnings(self):
        result = ContractResult()
        result.fail(
            code="SEARCH_LOG_EMPTY",
            message="search log has no completed records",
            path="search_log.jsonl",
            evidence="0 valid records",
        )
        result.warn(
            code="LEGACY_SEARCH_LOG",
            message="legacy Markdown search log was used",
            path="search_log.md",
            evidence="1 table row",
        )

        self.assertFalse(result.passed)
        self.assertEqual(["SEARCH_LOG_EMPTY"], [issue.code for issue in result.failures])
        self.assertEqual(["LEGACY_SEARCH_LOG"], [issue.code for issue in result.warnings])
        self.assertIn("SEARCH_LOG_EMPTY", result.failures[0].display())
        self.assertIn("search_log.jsonl", result.failures[0].display())

    def test_contract_profile_records_validation_target(self):
        profile = ContractProfile(
            mode="ticker",
            target="final_report",
            from_stage="stage_5",
            to_stage="stage_6",
        )

        self.assertEqual("ticker", profile.mode)
        self.assertEqual("final_report", profile.target)
        self.assertEqual("stage_5", profile.from_stage)
        self.assertEqual("stage_6", profile.to_stage)


class TestWorkspaceReaders(unittest.TestCase):
    def test_json_and_text_readers_return_none_for_missing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            self.assertIsNone(read_text_file(workspace / "missing.md"))
            self.assertIsNone(read_json_file(workspace / "missing.json"))

    def test_json_reader_rejects_non_object_top_level_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata.json"
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, r"metadata\.json.*JSON file must be an object"):
                read_json_file(path)

    def test_jsonl_reader_skips_blank_lines_and_preserves_line_numbers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "search_log.jsonl"
            path.write_text(
                "\n".join(
                    [
                        "",
                        json.dumps({"query": "first"}),
                        json.dumps({"query": "second"}),
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            records = list(iter_jsonl_records(path))

            self.assertEqual(
                [
                    (2, {"query": "first"}),
                    (3, {"query": "second"}),
                ],
                records,
            )


if __name__ == "__main__":
    unittest.main()
