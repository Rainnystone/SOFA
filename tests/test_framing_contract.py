import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from framing_contract import (  # noqa: E402
    FRAMING_CONTRACT_FILENAME,
    MODES,
    REPORT_LANGUAGES,
    RESOLUTION_METHODS,
    RESEARCH_POSTURES,
    SCHEMA_VERSION,
    UNKNOWN_ACCEPTED,
    add_candidate,
    add_clarification,
    apply_field,
    empty_contract,
    evaluate_contract,
    load_contract,
    render_contract_markdown,
    resolve_subject,
    save_contract,
)


class FramingContractCoreTests(unittest.TestCase):
    def test_vocabulary_is_single_authority(self):
        self.assertEqual(SCHEMA_VERSION, "1.0")
        self.assertEqual(set(MODES), {"ticker", "sector"})
        self.assertEqual(
            set(RESOLUTION_METHODS),
            {"deterministic_quote", "framing_search", "user_confirmed"},
        )
        self.assertEqual(
            set(RESEARCH_POSTURES),
            {"fresh", "verify-narrative", "revisit", "compare"},
        )
        self.assertEqual(set(REPORT_LANGUAGES), {"zh", "en", "bilingual"})
        self.assertEqual(UNKNOWN_ACCEPTED, "unknown-accepted-by-user")

    def test_empty_contract_has_full_schema_with_empty_values(self):
        contract = empty_contract()
        self.assertEqual(contract["schema_version"], "1.0")
        self.assertEqual(
            sorted(contract),
            [
                "budget_appetite",
                "clarifications",
                "market_scope",
                "mode",
                "output_expectation",
                "report_language",
                "research_posture",
                "risk_appetite",
                "schema_version",
                "subject_resolution",
                "time_horizon",
            ],
        )
        self.assertEqual(
            sorted(contract["subject_resolution"]),
            [
                "candidates",
                "confirmed_name",
                "exchange",
                "resolution_method",
                "tickers",
            ],
        )
        self.assertEqual(contract["subject_resolution"]["tickers"], [])
        self.assertEqual(contract["clarifications"], [])

    def test_ticker_contract_requires_resolved_subject_and_preferences(self):
        contract = empty_contract()
        apply_field(contract, "mode", "ticker")
        apply_field(contract, "research_posture", "fresh")
        apply_field(contract, "time_horizon", "6-12 months")
        apply_field(contract, "market_scope", "US listed equities")
        apply_field(contract, "risk_appetite", UNKNOWN_ACCEPTED)
        apply_field(contract, "output_expectation", "watchlist with evidence map")
        apply_field(contract, "report_language", "zh")
        apply_field(contract, "budget_appetite", UNKNOWN_ACCEPTED)

        result = evaluate_contract(contract)
        self.assertFalse(result.complete)
        self.assertIn(
            ("FRAMING_FIELD_MISSING", "subject_resolution.confirmed_name"),
            {(issue.code, issue.field) for issue in result.issues},
        )
        self.assertIn(
            ("FRAMING_FIELD_MISSING", "subject_resolution.tickers"),
            {(issue.code, issue.field) for issue in result.issues},
        )
        self.assertIn(
            ("FRAMING_FIELD_MISSING", "subject_resolution.exchange"),
            {(issue.code, issue.field) for issue in result.issues},
        )
        self.assertIn(
            ("FRAMING_FIELD_MISSING", "subject_resolution.resolution_method"),
            {(issue.code, issue.field) for issue in result.issues},
        )

        resolve_subject(
            contract,
            name="Coherent Corp",
            tickers=["COHR"],
            exchange="NYSE",
            method="deterministic_quote",
        )
        result = evaluate_contract(contract, state_mode="ticker")
        self.assertTrue(result.complete)
        self.assertEqual(result.issues, ())

    def test_sector_contract_does_not_require_ticker_or_exchange(self):
        contract = empty_contract()
        apply_field(contract, "mode", "sector")
        apply_field(contract, "research_posture", "compare")
        apply_field(contract, "time_horizon", "next two earnings cycles")
        apply_field(contract, "market_scope", "AI optical supply chain")
        apply_field(contract, "risk_appetite", "drawdown sensitive")
        apply_field(contract, "output_expectation", "ranked queue")
        apply_field(contract, "report_language", "bilingual")
        apply_field(contract, "budget_appetite", "public sources only")
        resolve_subject(
            contract,
            name="AI optical components",
            tickers=[],
            exchange="",
            method="framing_search",
        )

        result = evaluate_contract(contract, state_mode="sector")
        self.assertTrue(result.complete)
        self.assertEqual(result.issues, ())

    def test_forbidden_sentinel_is_an_evaluate_failure_not_an_exception(self):
        # apply_field is a pure writer: it does NOT raise on a sentinel value
        # for a forbidden field. evaluate_contract owns the FRAMING_SENTINEL_FORBIDDEN
        # rule. This matches the spec's issue-code semantics and keeps the
        # forbidden-sentinel check out of dead-code paths.
        contract = empty_contract()
        apply_field(contract, "mode", UNKNOWN_ACCEPTED)
        apply_field(contract, "research_posture", UNKNOWN_ACCEPTED)
        result = evaluate_contract(contract)

        failures = {(issue.code, issue.field) for issue in result.issues}
        self.assertIn(("FRAMING_SENTINEL_FORBIDDEN", "mode"), failures)
        self.assertIn(("FRAMING_SENTINEL_FORBIDDEN", "research_posture"), failures)

    def test_mode_drift_is_detected_with_real_enum_values(self):
        # Mode-drift is tested with real enum values, not the sentinel: a
        # sentinel mode is already a FRAMING_SENTINEL_FORBIDDEN failure, and
        # evaluate_contract deliberately does not double-report drift on a
        # value that is not a usable mode. A genuine mode mismatch (contract
        # says sector, state says ticker) is the tripwire this test locks.
        contract = empty_contract()
        apply_field(contract, "mode", "sector")
        result = evaluate_contract(contract, state_mode="ticker")

        failures = {(issue.code, issue.field) for issue in result.issues}
        self.assertIn(("FRAMING_MODE_DRIFT", "mode"), failures)

    def test_candidates_clarifications_save_load_and_render_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            contract = empty_contract()
            apply_field(contract, "mode", "ticker")
            apply_field(contract, "research_posture", "verify-narrative")
            apply_field(contract, "time_horizon", "12 months")
            apply_field(contract, "market_scope", "US public market")
            apply_field(contract, "risk_appetite", "moderate")
            apply_field(contract, "output_expectation", "decision memo")
            apply_field(contract, "report_language", "zh")
            apply_field(contract, "budget_appetite", "standard")
            resolve_subject(
                contract,
                name="Coherent Corp",
                tickers=["COHR"],
                exchange="NYSE",
                method="deterministic_quote",
            )
            add_candidate(
                contract,
                name="II-VI Inc",
                ticker="IIVI",
                exchange="NASDAQ",
                reason_excluded="Renamed to Coherent Corp after merger history check.",
            )
            add_clarification(
                contract,
                question="行动导向还是观察导向？",
                answer="先观察，除非证据链非常强。",
            )

            save_contract(workspace, contract)
            raw = json.loads((workspace / FRAMING_CONTRACT_FILENAME).read_text())
            self.assertEqual(raw, contract)
            self.assertEqual(
                raw["subject_resolution"]["candidates"][0]["reason_excluded"],
                "Renamed to Coherent Corp after merger history check.",
            )
            loaded = load_contract(workspace)
            self.assertEqual(loaded, contract)

            rendered = render_contract_markdown(loaded)
            self.assertIn("| mode | complete | ticker |", rendered)
            self.assertIn("| subject_resolution.confirmed_name | complete | Coherent Corp |", rendered)
            self.assertIn("| II-VI Inc | IIVI | NASDAQ | Renamed to Coherent Corp after merger history check. |", rendered)
            self.assertIn("| 行动导向还是观察导向？ | 先观察，除非证据链非常强。 |", rendered)
            self.assertNotIn("Dispatch", rendered)
            self.assertNotIn("worker", rendered.lower())


class TestPackageImport(unittest.TestCase):
    """Namespace-import lock (PR #12 dual-import convention).

    The package must be importable both as a flat module (``framing_contract``)
    from ``scripts/`` on ``sys.path`` and as a namespace package
    (``scripts.framing_contract``) from the repo root. The namespace form is
    what ``sofa_contract.evaluate`` relies on when it does
    ``from ..framing_contract import ...`` under package execution.
    """

    def test_namespace_import_succeeds_from_repo_root(self):
        result = subprocess.run(
            [sys.executable, "-c", "import scripts.framing_contract"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_flat_import_succeeds_from_scripts_dir(self):
        result = subprocess.run(
            [sys.executable, "-c", "import framing_contract"],
            cwd=str(ROOT / "scripts"),
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
