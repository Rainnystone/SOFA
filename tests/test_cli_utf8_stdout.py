"""Cross-platform regression tests for UTF-8 stdout/stderr on CLI scripts.

On Windows, when a script's stdout is a pipe (the common case when a parent
agent or ``subprocess.run(..., capture_output=True)`` captures output), the
default stream encoding is the system's ANSI code page (often cp1252), not
UTF-8. Several SOFA CLI scripts print non-ASCII text -- bilingual section
names such as ``## 综合分析笔记`` / ``## 盲区报告`` (emitted by the synthesis
and gate checks), or A-share / HK company names via ``json.dumps(...,
ensure_ascii=False)``. Printing those under a non-UTF-8 pipe raises
``UnicodeEncodeError`` and kills the script with exit 1 mid-output, even when
the underlying check passed.

``scripts/validate_dossier.py`` already defends against this with
``sys.stdout.reconfigure(encoding="utf-8")`` at its CLI entry. These tests
make the same guarantee portable and explicit for every other CLI that emits
non-ASCII.

The reproduction does NOT require Windows: spawning the script under
``PYTHONIOENCODING=latin-1`` (with ``PYTHONUTF8`` removed) forces the same
non-UTF-8 legacy encoding on any OS, so an un-fixed script crashes here on
Linux/macOS/Windows alike. The ``reconfigure`` call overrides that env, so a
fixed script prints cleanly everywhere. This keeps the tests green on macOS
while proving the Windows fix.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Every CLI script that prints non-ASCII (bilingual section names or
# ensure_ascii=False company names) must force UTF-8 on its stdio at __main__
# entry, exactly like validate_dossier.py does today.
CLI_SCRIPTS_WITH_NON_ASCII_OUTPUT = (
    "gate_check.py",
    "fetch_financials.py",
    "synthesis_checker.py",
    "scorecard_validator.py",
    "timeliness_checker.py",
    "redteam_debate_validator.py",
    "loop_enforcer.py",
    "frontier_review.py",
    "search_intel.py",
    "assemble_dispatch.py",
    "framing_intake.py",
    # validate_dossier.py is the reference implementation: already fixed.
    "validate_dossier.py",
)

RECONFIGURE_SENTINEL = "sys.stdout.reconfigure(encoding=\"utf-8\")"


def _legacy_encoding_env():
    """An environment that forces a non-UTF-8 stdout, mirroring a Windows pipe.

    latin-1 is chosen because it is byte-transparent on every platform and
    cannot encode CJK / any non-ASCII char, so ``print("## 综合分析笔记")``
    raises ``UnicodeEncodeError`` deterministically.
    """
    env = {key: value for key, value in os.environ.items()}
    env["PYTHONIOENCODING"] = "latin-1"
    env.pop("PYTHONUTF8", None)
    return env


def _run_script(script: Path, *args, cwd: Path):
    """Run a CLI capturing raw bytes under a non-UTF-8 stdout environment.

    Bytes (not ``text=True``) are captured so the parent process's own locale
    decoding does not mask the child's behavior. The child's own
    encoding is what we are testing: an un-fixed script raises
    ``UnicodeEncodeError`` (its traceback lands in stderr, partial stdout is
    lost); a fixed script emits clean UTF-8 bytes regardless of the env.
    """
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        env=_legacy_encoding_env(),
    )


class TestCliStdoutForcesUtf8(unittest.TestCase):
    """Structural invariant: each non-ASCII CLI reconfigures stdio in __main__."""

    def test_all_cli_scripts_force_utf8_stdio(self):
        missing = []
        for name in CLI_SCRIPTS_WITH_NON_ASCII_OUTPUT:
            script = SCRIPTS / name
            self.assertTrue(script.exists(), f"{script} does not exist")
            source = script.read_text(encoding="utf-8")
            main_marker = 'if __name__ == "__main__":'
            main_index = source.find(main_marker)
            self.assertGreater(
                main_index, -1,
                f"{name} has no `{main_marker}` block",
            )
            # The reconfigure call must sit inside the __main__ block.
            reconfigure_index = source.find(RECONFIGURE_SENTINEL)
            if reconfigure_index == -1 or reconfigure_index < main_index:
                missing.append(name)
        self.assertEqual(
            [], missing,
            "These CLI scripts emit non-ASCII output but do not force UTF-8 "
            "stdio inside their __main__ block (add the reconfigure call like "
            "validate_dossier.py):\n" + "\n".join(missing),
        )


class TestCliStdoutBehaviorUnderLegacyEncoding(unittest.TestCase):
    """Behavioral: un-fixed scripts crash on a non-UTF-8 pipe; fixed ones don't.

    These spawn real subprocesses so the reconfigure-at-CLI-entry path is
    exercised (importing the functions directly bypasses __main__ entirely).
    """

    def _make_workspace(self):
        temp_dir = tempfile.TemporaryDirectory()
        workspace = Path(temp_dir.name) / "ws"
        workspace.mkdir(parents=True, exist_ok=True)
        self.addCleanup(temp_dir.cleanup)
        return workspace

    def test_synthesis_checker_prints_violation_under_legacy_encoding(self):
        # An empty workflow is missing the required Synthesis Notes section, so
        # synthesis_checker prints a violation that contains the bilingual
        # section name "## 综合分析笔记". Under a latin-1 pipe this must still
        # reach stdout as valid UTF-8 instead of crashing with
        # UnicodeEncodeError.
        workspace = self._make_workspace()
        (workspace / "research_workflow.md").write_text("# Empty\n", encoding="utf-8")

        result = _run_script(
            SCRIPTS / "synthesis_checker.py", str(workspace), cwd=ROOT,
        )

        # The check legitimately fails (exit 1), but the violation text must
        # have been printed intact (clean UTF-8 bytes) rather than lost to an
        # encoding crash.
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertIn("综合分析笔记", stdout)
        self.assertNotIn("UnicodeEncodeError", stderr)

    def test_gate_check_stage3_prints_non_ascii_missing_under_legacy_encoding(self):
        # gate_check stage_3 -> stage_4 runs the synthesis checker and appends
        # its violations (which include "## 综合分析笔记") to the gate output.
        # With an empty workflow this is a missing-item; the bilingual name must
        # survive the latin-1 pipe as valid UTF-8.
        workspace = self._make_workspace()
        (workspace / "state.json").write_text(
            json.dumps({"mode": "ticker", "stages_completed": ["stage_3"]}),
            encoding="utf-8",
        )
        (workspace / "research_workflow.md").write_text("# Empty\n", encoding="utf-8")
        (workspace / "evidence_ledger.md").write_text("# Evidence Ledger\n", encoding="utf-8")

        result = _run_script(
            SCRIPTS / "gate_check.py", str(workspace), "stage_3", "stage_4", cwd=ROOT,
        )

        # Gate legitimately fails; the non-ASCII missing-item text must print.
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertIn("综合分析笔记", stdout)
        self.assertNotIn("UnicodeEncodeError", stderr)

    def test_search_intel_digest_json_survives_legacy_encoding(self):
        # search_intel.py can print captured Chinese queries via
        # ensure_ascii=False JSON; this must work under a legacy pipe too.
        workspace = self._make_workspace()
        (workspace / "search_log.jsonl").write_text(
            json.dumps(
                {
                    "loop_id": "stage_0",
                    "query": "ACME 公司 主体确认",
                    "result_status": "completed",
                    "evidence_refs": ["https://example.com/profile"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        result = _run_script(
            SCRIPTS / "search_intel.py", "digest", str(workspace), "--json", cwd=ROOT,
        )

        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertEqual(0, result.returncode, stderr)
        self.assertIn("ACME 公司 主体确认", stdout)
        self.assertNotIn("UnicodeEncodeError", stderr)

    def test_validate_dossier_stdout_survives_legacy_encoding(self):
        # Regression guard: validate_dossier.py is already fixed. It must keep
        # printing its non-ASCII warnings cleanly under a legacy-encoding pipe.
        workspace = self._make_workspace()
        (workspace / "state.json").write_text(
            json.dumps({"mode": "ticker"}), encoding="utf-8",
        )
        (workspace / "research_workflow.md").write_text(
            "# Workflow\n## Synthesis Notes / 综合分析笔记\n\nshort\n",
            encoding="utf-8",
        )
        (workspace / "evidence_ledger.md").write_text("# Ledger\n", encoding="utf-8")

        result = _run_script(
            SCRIPTS / "validate_dossier.py", str(workspace), cwd=ROOT,
        )

        # The script must not have died to a UnicodeEncodeError. Whether it
        # reports VALID or FAILED depends on the minimal fixture; the contract
        # here is only that non-ASCII printing did not crash the pipe.
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertNotIn("UnicodeEncodeError", stderr)
        self.assertNotEqual(result.returncode, -1)


if __name__ == "__main__":
    unittest.main()
