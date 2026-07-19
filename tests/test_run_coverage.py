import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_coverage.py"


def _read_source() -> str:
    """Read run_coverage.py source without importing it (used for static checks)."""
    return SCRIPT.read_text(encoding="utf-8")


def _coverage_available() -> bool:
    return importlib.util.find_spec("coverage") is not None


def _load_module():
    """Import run_coverage.py as a module so we can unit-test its pure functions."""
    spec = importlib.util.spec_from_file_location("run_coverage_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRunCoverageStructure(unittest.TestCase):
    """Static/structural guarantees that hold whether or not coverage is installed."""

    def test_script_exists(self):
        self.assertTrue(SCRIPT.exists(), f"Expected cross-platform coverage runner at {SCRIPT}")

    def test_no_tmp_dependency(self):
        # The runner must not build paths from POSIX-only literals like /tmp.
        source = _read_source()
        self.assertNotRegex(source, r'["\']/tmp')
        self.assertNotIn('"/tmp"', source)
        self.assertNotIn("'/tmp'", source)

    def test_uses_sys_executable(self):
        # The runner must invoke the interpreter portably via sys.executable. It
        # must NOT call a bare "python3" string that would be absent on Windows.
        source = _read_source()
        self.assertIn("sys.executable", source)
        self.assertNotIn('"python3"', source)
        self.assertNotIn("'python3'", source)

    def test_default_threshold_is_ninety(self):
        # The project documents lifecycle coverage at >= 90%; the runner's
        # default --fail-under must be 90 so the existing gate stays meaningful.
        module = _load_module()
        self.assertEqual(module.DEFAULT_FAIL_UNDER, 90)

    def test_build_argv_is_portable(self):
        # The generated argv must use sys.executable and module form (-m coverage),
        # never a bare interpreter name string.
        module = _load_module()
        run_args, report_args = module.build_argv(90)
        for argv in (run_args, report_args):
            self.assertEqual(argv[0], sys.executable)
            self.assertIn("-m", argv)
            self.assertIn("coverage", argv)
        # report must carry the threshold.
        self.assertIn("90", report_args)

    def test_default_frontier_argv_remains_exactly_compatible(self):
        module = _load_module()
        self.assertEqual(
            [
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "run",
                    "--source",
                    "scripts",
                    "-m",
                    "unittest",
                    "tests/test_frontier_lifecycle.py",
                ],
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "report",
                    "--include",
                    "scripts/frontier_lifecycle.py",
                    "--fail-under",
                    "90",
                ],
            ],
            module.build_argv(90),
        )

    def test_revisit_target_builds_locked_test_and_include_argv(self):
        module = _load_module()
        run_args, report_args = module.build_argv(90, target="revisit")
        self.assertEqual(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--source",
                "scripts",
                "-m",
                "unittest",
                "tests/test_revisit_contract.py",
            ],
            run_args,
        )
        self.assertEqual(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--include",
                "scripts/revisit_contract/*.py,scripts/revisit_cycle.py",
                "--fail-under",
                "90",
            ],
            report_args,
        )

    def test_parse_args_selects_revisit_without_changing_frontier_default(self):
        module = _load_module()
        self.assertEqual("frontier", module.parse_args([]).target)
        self.assertEqual(
            "revisit",
            module.parse_args(["--target", "revisit"]).target,
        )
        with self.assertRaises(SystemExit):
            module.parse_args(["--target", "unknown"])


@unittest.skipUnless(_coverage_available(), "coverage not installed in this environment")
class TestRunCoverageBehavior(unittest.TestCase):
    """End-to-end CLI behavior. Requires the `coverage` package."""

    def _run(self, *extra_args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra_args],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_passes_when_threshold_is_zero(self):
        # A --fail-under of 0 always passes regardless of measured coverage.
        for target in ("frontier", "revisit"):
            with self.subTest(target=target):
                result = self._run(
                    "--target",
                    target,
                    "--fail-under",
                    "0",
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"Expected exit 0 with --fail-under 0, got "
                    f"{result.returncode}\nstdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}",
                )

    def test_fails_when_threshold_unreachable(self):
        # A --fail-under of 101 is impossible to satisfy, so the runner must exit
        # non-zero. This mirrors the semantics of the old run_coverage.sh.
        for target in ("frontier", "revisit"):
            with self.subTest(target=target):
                result = self._run(
                    "--target",
                    target,
                    "--fail-under",
                    "101",
                )
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
