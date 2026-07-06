import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from worker_role_catalog import all_worker_roles

from dispatch_assembly import (
    AssemblyError,
    assemble_dispatch,
    primary_input_slot_name,
)


PACKET = (
    "### Frontier Packet\n"
    "- Frontier: InP substrate qualified capacity\n"
    "- Key Claims: C1 qualified substrate supply is concentrated\n"
    "- Expected Evidence: filings, supplier pages, archived pages\n"
    "- Challenge Focus: capacity double counting\n"
    "- Stop/Continue Criteria: two loops without delta\n"
)

LEDGER = "# Evidence Ledger\n\n## Loop 1: F1 - Substrate supply\n"

SEARCH_RECORD = (
    '{"loop_id": "loop_1", "result_status": "completed", '
    '"query": "InP substrate qualified supplier", '
    '"evidence_refs": ["https://www.sec.gov/acme-10k"], "notes": "CONTAMINANT"}\n'
)


def make_workspace(base: Path, with_search_log: bool = False) -> Path:
    workspace = base / "workspace"
    workspace.mkdir()
    if with_search_log:
        (workspace / "evidence_ledger.md").write_text(LEDGER, encoding="utf-8")
        (workspace / "search_log.jsonl").write_text(SEARCH_RECORD, encoding="utf-8")
    return workspace


class TestScoutAssembly(unittest.TestCase):
    def test_fills_slots_computes_path_and_strips_meta(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT,
                workspace=workspace,
                role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "7", "frontier_slug": "substrate_supply"},
                attach_digest=False,
            )

            self.assertEqual("frontier_scout", result.role_slug)
            self.assertEqual("scouts/loop7_substrate_supply.md", result.delivery_path)
            self.assertIn(PACKET.strip(), result.dispatch_text)
            self.assertIn(
                str(workspace / "scouts" / "loop7_substrate_supply.md"),
                result.dispatch_text,
            )
            self.assertNotIn("{PLUGIN_DIR}", result.dispatch_text)
            self.assertNotIn("{WORKSPACE}", result.dispatch_text)
            self.assertNotIn("[主线程粘贴完整 Frontier Packet]", result.dispatch_text)
            self.assertNotIn("## Placeholders", result.dispatch_text)
            self.assertEqual(
                {"role": "frontier_scout", "loop_id": "loop_7",
                 "delivery_path": "scouts/loop7_substrate_supply.md"},
                result.suggested_record_fields,
            )

    def test_missing_name_field_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "frontier_slug"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "7"},
                    attach_digest=False,
                )

    def test_missing_required_slot_value_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "frontier_packet"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={},
                    name_fields={"loop": "7", "frontier_slug": "x"},
                    attach_digest=False,
                )

    def test_unsafe_name_field_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "unsafe"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "7", "frontier_slug": "../escape"},
                    attach_digest=False,
                )


class TestScreening(unittest.TestCase):
    def test_market_data_blocks_scout_but_not_bridge(self):
        leaky = PACKET + "\nContext: the market cap looks mispriced.\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "DISPATCH_INPUT_MARKET_DATA"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": leaky},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                )
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="financial",
                slot_values={"bridge_input": leaky},
                name_fields={"ticker": "AXTI"},
                attach_digest=False,
            )
            self.assertEqual("financials/AXTI_bridge.md", result.delivery_path)


class TestRedTeamAssembly(unittest.TestCase):
    def test_appends_sections_and_keeps_output_brackets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="redteam",
                slot_values={"round_input": "Thesis bundle: claims C1-C3 with grades."},
                name_fields={"round": "2"},
                attach_digest=False,
            )

            self.assertEqual("redteam/round2_redteam.md", result.delivery_path)
            self.assertIn("## 本轮输入（主线程提供）", result.dispatch_text)
            self.assertIn("Thesis bundle: claims C1-C3 with grades.", result.dispatch_text)
            self.assertIn("## 交付文件路径", result.dispatch_text)
            self.assertIn("[主线程必须回答的问题]", result.dispatch_text)


class TestDigestAttachment(unittest.TestCase):
    def test_digest_attached_when_log_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir), with_search_log=True)
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "2", "frontier_slug": "x"},
            )

            self.assertIn("### Prior Search Trace (negative trace only)", result.dispatch_text)
            self.assertIn("prior_query_digest", result.attachments)
            self.assertNotIn("CONTAMINANT", result.dispatch_text)

    def test_malformed_log_fails_loud(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir), with_search_log=True)
            with (workspace / "search_log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("{not json\n")
            with self.assertRaisesRegex(AssemblyError, "digest"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "2", "frontier_slug": "x"},
                )

    def test_no_log_means_no_digest_and_no_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "2", "frontier_slug": "x"},
            )

            self.assertNotIn("Prior Search Trace", result.dispatch_text)
            self.assertEqual([], result.attachments)


class TestEveryCatalogRoleAssembles(unittest.TestCase):
    def test_all_roles_assemble_from_generic_input(self):
        name_fields = {
            "loop": "1", "frontier_slug": "generic", "round": "1",
            "ticker": "TEST", "version": "1",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            for role in all_worker_roles():
                with self.subTest(slug=role.slug):
                    input_slot = primary_input_slot_name(role.slug)
                    result = assemble_dispatch(
                        repo_root=ROOT, workspace=workspace, role=role.slug,
                        slot_values={input_slot: "Bounded task input for testing."},
                        name_fields=name_fields,
                        attach_digest=False,
                    )
                    self.assertTrue(result.delivery_path.startswith(f"{role.delivery_folder}/"))
                    self.assertNotIn("{PLUGIN_DIR}", result.dispatch_text)
                    self.assertNotIn("{WORKSPACE}", result.dispatch_text)


class TestPackageImport(unittest.TestCase):
    def test_package_namespace_import_works_from_repo_root(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import scripts.dispatch_assembly as da; "
                "print(da.assemble_dispatch.__name__)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("assemble_dispatch", result.stdout)


if __name__ == "__main__":
    unittest.main()
