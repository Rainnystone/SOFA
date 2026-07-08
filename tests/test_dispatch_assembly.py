import hashlib
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


def add_source_fixture(workspace: Path, title: str = "FY2025 10-K Coherent segment disclosure") -> None:
    (workspace / "sources").mkdir(exist_ok=True)
    excerpt = "Segment revenue detail.\n"
    (workspace / "sources" / "src-001.md").write_text(excerpt, encoding="utf-8")
    record = {
        "source_id": "src-001",
        "url": "https://www.sec.gov/acme-10k",
        "title": title,
        "retrieved": "2026-07-08",
        "grade": "A",
        "excerpt_path": "sources/src-001.md",
        "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }
    with open(workspace / "sources_index.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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
            self.assertEqual("frontier_scout", result.suggested_record_fields["role"])
            self.assertEqual("loop_7", result.suggested_record_fields["loop_id"])
            self.assertEqual(
                "scouts/loop7_substrate_supply.md",
                result.suggested_record_fields["delivery_path"],
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


class TestSuggestedRecordFields(unittest.TestCase):
    def test_loop_role_marks_dispatch_only_fields_incomplete(self):
        # scout has a loop in its filename template, so the assembler can fill
        # role/loop_id/delivery_path. dispatch_id, mechanism, and status are
        # properties of the dispatch act (not the packet), so they are always
        # main-thread-supplied and listed in incomplete_fields.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "7", "frontier_slug": "substrate_supply"},
                attach_digest=False,
            )
            self.assertEqual("loop_7", result.suggested_record_fields["loop_id"])
            self.assertEqual(
                ["dispatch_id", "mechanism", "status"],
                result.suggested_record_fields["incomplete_fields"],
            )

    def test_loopless_role_marks_loop_id_incomplete(self):
        # financial_bridge filename template is {ticker}_bridge.md (no loop),
        # so loop_id cannot be derived; sofa_contract still requires it on
        # delivered records. The assembler must flag loop_id as incomplete so
        # the main thread knows to bind the bridge to the relevant loop.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="financial",
                slot_values={"bridge_input": "Thesis with financial context."},
                name_fields={"ticker": "AXTI"},
                attach_digest=False,
            )
            self.assertIsNone(result.suggested_record_fields.get("loop_id"))
            self.assertIn(
                "loop_id",
                result.suggested_record_fields["incomplete_fields"],
            )

    def test_redteam_round_role_marks_loop_id_incomplete(self):
        # red_team uses round{round}_redteam.md (no loop field), so loop_id
        # is incomplete just like financial_bridge.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="redteam",
                slot_values={"round_input": "Thesis bundle."},
                name_fields={"round": "1"},
                attach_digest=False,
            )
            self.assertIsNone(result.suggested_record_fields.get("loop_id"))
            self.assertIn(
                "loop_id",
                result.suggested_record_fields["incomplete_fields"],
            )


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

    def test_no_digest_bypasses_existing_search_log(self):
        # The advertised recovery path: attach_digest=False must skip the
        # attachment even when search_log.jsonl exists (previously proven
        # only on logless fixtures).
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir), with_search_log=True)
            result = assemble_dispatch(
                repo_root=ROOT,
                workspace=workspace,
                role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "1", "frontier_slug": "substrate_supply"},
                attach_digest=False,
            )
            self.assertNotIn("### Prior Search Trace", result.dispatch_text)
            self.assertNotIn("prior_query_digest", result.attachments)

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

    def test_digest_with_market_data_terms_fails_loud_for_isolated_role(self):
        # The prior-query digest renders the raw query text, which may contain
        # market-data or action-class language. Attaching it unscreened to an
        # isolated role would reintroduce the exact terms the packet screening
        # just blocked. The assembler must screen the rendered digest per role
        # and fail loud so the main thread can clean the log or use --no-digest.
        market_log = (
            '{"loop_id": "loop_1", "result_status": "completed", '
            '"query": "ACME market cap target price", '
            '"evidence_refs": [], "notes": ""}\n'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            (workspace / "search_log.jsonl").write_text(market_log, encoding="utf-8")
            with self.assertRaisesRegex(AssemblyError, "DISPATCH_INPUT_MARKET_DATA|digest"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "2", "frontier_slug": "x"},
                )

    def test_digest_with_market_data_terms_passes_for_unscreened_role(self):
        # financial_bridge is not price-screened, so a digest carrying market
        # data must still attach for it.
        market_log = (
            '{"loop_id": "loop_1", "result_status": "completed", '
            '"query": "ACME market cap target price", '
            '"evidence_refs": [], "notes": ""}\n'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            (workspace / "search_log.jsonl").write_text(market_log, encoding="utf-8")
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="financial",
                slot_values={"bridge_input": "Thesis with financial context."},
                name_fields={"ticker": "ACME"},
            )
            self.assertIn("Prior Search Trace", result.dispatch_text)
            self.assertIn("prior_query_digest", result.attachments)

    def test_digest_with_action_terms_fails_loud_for_isolated_role(self):
        action_log = (
            '{"loop_id": "loop_1", "result_status": "completed", '
            '"query": "preliminary action class buy", '
            '"evidence_refs": [], "notes": ""}\n'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            (workspace / "search_log.jsonl").write_text(action_log, encoding="utf-8")
            with self.assertRaisesRegex(AssemblyError, "DISPATCH_INPUT_ACTION_LANGUAGE|digest"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "2", "frontier_slug": "x"},
                )


class TestSourceBibliographyAttachment(unittest.TestCase):
    def _assemble(self, workspace, role="scout", **kwargs):
        slot = primary_input_slot_name(role)
        name_fields = kwargs.pop(
            "name_fields", {"loop": "1", "frontier_slug": "substrate_supply"}
        )
        return assemble_dispatch(
            repo_root=ROOT,
            workspace=workspace,
            role=role,
            slot_values={slot: PACKET},
            name_fields=name_fields,
            attach_digest=False,
            **kwargs,
        )

    def test_attaches_identifiers_only_bibliography(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            add_source_fixture(workspace)
            result = self._assemble(workspace)
            self.assertIn("### Prior Source Index (identifiers only)", result.dispatch_text)
            self.assertIn("src-001", result.dispatch_text)
            self.assertIn("https://www.sec.gov/acme-10k", result.dispatch_text)
            self.assertIn("retrieved 2026-07-08", result.dispatch_text)
            self.assertNotIn("Segment revenue detail", result.dispatch_text)
            self.assertNotIn('"grade"', result.dispatch_text)
            self.assertIn("source_bibliography", result.attachments)

    def test_absent_or_empty_index_attaches_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = self._assemble(workspace)
            self.assertNotIn("Prior Source Index", result.dispatch_text)
            self.assertNotIn("source_bibliography", result.attachments)
            (workspace / "sources_index.jsonl").write_text("", encoding="utf-8")
            result = self._assemble(workspace)
            self.assertNotIn("Prior Source Index", result.dispatch_text)
            self.assertNotIn("source_bibliography", result.attachments)

    def test_no_sources_bypasses_populated_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            add_source_fixture(workspace)
            result = self._assemble(workspace, attach_sources=False)
            self.assertNotIn("Prior Source Index", result.dispatch_text)
            self.assertNotIn("source_bibliography", result.attachments)

    def test_market_data_title_blocks_scout_but_passes_bridge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            add_source_fixture(workspace, title="Analyst target price roundup")
            with self.assertRaises(AssemblyError) as ctx:
                self._assemble(workspace)
            self.assertIn("--no-sources", str(ctx.exception))
            bridge = self._assemble(
                workspace, role="financial_bridge", name_fields={"ticker": "COHR"}
            )
            self.assertIn("source_bibliography", bridge.attachments)

    def test_malformed_index_fails_loudly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            (workspace / "sources_index.jsonl").write_text("not json\n", encoding="utf-8")
            with self.assertRaises(AssemblyError):
                self._assemble(workspace)


class TestSourceBibliographyCli(unittest.TestCase):
    def test_no_sources_flag_bypasses_populated_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            add_source_fixture(workspace)
            packet_file = Path(temp_dir) / "packet.md"
            packet_file.write_text(PACKET, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "assemble_dispatch.py"),
                    "--workspace", str(workspace),
                    "--role", "scout",
                    "--packet-file", str(packet_file),
                    "--loop", "1",
                    "--frontier-slug", "substrate_supply",
                    "--no-sources",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("Prior Source Index", result.stdout)


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


class TestOutPathScreening(unittest.TestCase):
    def test_out_path_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "out_path|outside workspace|unsafe"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                    out_path="../../etc/evil.md",
                )

    def test_out_path_rejects_path_tokens(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "out_path|token"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                    out_path="{WORKSPACE}/escape.md",
                )

    def test_out_path_accepts_valid_relative_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="scout",
                slot_values={"frontier_packet": PACKET},
                name_fields={"loop": "1", "frontier_slug": "x"},
                attach_digest=False,
                out_path="scouts/custom_name.md",
            )
            self.assertEqual("scouts/custom_name.md", result.delivery_path)

    def test_out_path_rejects_delivery_folder_mismatch(self):
        # sofa_contract enforces that a delivered record's role matches its
        # delivery_path folder; an --out override pointing at another role's
        # folder would assemble a dispatch that the contract immediately
        # rejects. Refuse early with a clear error naming the folder.
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "delivery folder|redteam|scouts"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": PACKET},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                    out_path="redteam/scout.md",
                )


class TestSlotValueTokenScreening(unittest.TestCase):
    def test_slot_value_containing_workspace_token_raises(self):
        leaky_packet = PACKET + "\nReference: see {WORKSPACE}/scouts/x.md for context.\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "WORKSPACE|token|slot value"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": leaky_packet},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                )

    def test_slot_value_containing_plugin_dir_token_raises(self):
        leaky_packet = PACKET + "\nTemplate at {PLUGIN_DIR}/scripts/prompts/x.md\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            with self.assertRaisesRegex(AssemblyError, "PLUGIN_DIR|token|slot value"):
                assemble_dispatch(
                    repo_root=ROOT, workspace=workspace, role="scout",
                    slot_values={"frontier_packet": leaky_packet},
                    name_fields={"loop": "1", "frontier_slug": "x"},
                    attach_digest=False,
                )

    def test_clean_slot_value_without_tokens_passes(self):
        # A packet that mentions a path in prose WITHOUT the literal token is fine.
        clean_packet = PACKET + "\nReference: see the workspace scouts folder for context.\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = make_workspace(Path(temp_dir))
            result = assemble_dispatch(
                repo_root=ROOT, workspace=workspace, role="scout",
                slot_values={"frontier_packet": clean_packet},
                name_fields={"loop": "1", "frontier_slug": "x"},
                attach_digest=False,
            )
            self.assertNotIn("{WORKSPACE}", result.dispatch_text)
            self.assertNotIn("{PLUGIN_DIR}", result.dispatch_text)


SCRIPT = ROOT / "scripts" / "assemble_dispatch.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class TestAssembleDispatchCli(unittest.TestCase):
    def _write_packet(self, base: Path) -> Path:
        packet_path = base / "packet.md"
        packet_path.write_text(PACKET, encoding="utf-8")
        return packet_path

    def test_json_output_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = make_workspace(base)
            packet_path = self._write_packet(base)
            result = run_cli(
                "--workspace", str(workspace), "--role", "scout",
                "--packet-file", str(packet_path),
                "--loop", "7", "--frontier-slug", "substrate_supply",
                "--no-digest", "--json",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("frontier_scout", payload["role_slug"])
        self.assertEqual("scouts/loop7_substrate_supply.md", payload["delivery_path"])
        suggested = payload["suggested_record_fields"]
        self.assertEqual("frontier_scout", suggested["role"])
        self.assertEqual("loop_7", suggested["loop_id"])
        self.assertEqual(
            "scouts/loop7_substrate_supply.md", suggested["delivery_path"]
        )
        self.assertEqual(
            ["dispatch_id", "mechanism", "status"], suggested["incomplete_fields"]
        )
        self.assertIn("Frontier Packet", payload["dispatch_text"])

    def test_json_payload_has_documented_field_set_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = make_workspace(base)
            packet_path = self._write_packet(base)
            result = run_cli(
                "--workspace", str(workspace), "--role", "scout",
                "--packet-file", str(packet_path),
                "--loop", "7", "--frontier-slug", "substrate_supply",
                "--no-digest", "--json",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {
                "role_slug",
                "prompt_template",
                "delivery_path",
                "dispatch_text",
                "attachments",
                "suggested_record_fields",
            },
            set(payload),
        )

    def test_text_output_prints_dispatch_and_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = make_workspace(base)
            packet_path = self._write_packet(base)
            result = run_cli(
                "--workspace", str(workspace), "--role", "scout",
                "--packet-file", str(packet_path),
                "--loop", "7", "--frontier-slug", "substrate_supply",
                "--no-digest",
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("InP substrate qualified capacity", result.stdout)
        self.assertIn("scouts/loop7_substrate_supply.md", result.stderr)

    def test_screening_failure_exits_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = make_workspace(base)
            leaky_path = base / "leaky.md"
            leaky_path.write_text(
                PACKET + "\nContext: target price implies upside.\n", encoding="utf-8"
            )
            result = run_cli(
                "--workspace", str(workspace), "--role", "scout",
                "--packet-file", str(leaky_path),
                "--loop", "1", "--frontier-slug", "x", "--no-digest",
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("ASSEMBLY ERROR", result.stderr)
        self.assertIn("DISPATCH_INPUT_MARKET_DATA", result.stderr)

    def test_missing_name_field_exits_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            workspace = make_workspace(base)
            packet_path = self._write_packet(base)
            result = run_cli(
                "--workspace", str(workspace), "--role", "scout",
                "--packet-file", str(packet_path), "--loop", "1", "--no-digest",
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("frontier_slug", result.stderr)


if __name__ == "__main__":
    unittest.main()
