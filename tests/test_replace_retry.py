"""Tests for the Windows-aware atomic replace helper in frontier_review.

`os.replace` can raise PermissionError on Windows when the destination is
held open by another process (OneDrive sync, antivirus, an editor). The
`replace_with_retry` helper retries transient failures on Windows while
keeping the POSIX path a single attempt with zero behavior change.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REVIEW_SCRIPT = ROOT / "scripts/frontier_review.py"


def load_review_module():
    script_dir = str(REVIEW_SCRIPT.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("frontier_review_under_test", REVIEW_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReplaceWithRetry(unittest.TestCase):
    def setUp(self):
        self.module = load_review_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dst = Path(self.tmp.name) / "target.txt"
        self.dst.write_text("original", encoding="utf-8")

    def _src(self, content: str) -> Path:
        src = Path(self.tmp.name) / "source.txt"
        src.write_text(content, encoding="utf-8")
        return src

    def test_succeeds_first_try_no_retry(self):
        # When os.replace succeeds immediately, it must be called exactly once.
        src = self._src("new content")
        with mock.patch.object(self.module.os, "replace", wraps=os.replace) as spy:
            self.module.replace_with_retry(src, self.dst)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.dst.read_text(encoding="utf-8"), "new content")
        self.assertFalse(src.exists())

    def test_raises_after_exhausting_retries(self):
        # When os.replace keeps failing on Windows, the original error must
        # propagate after retries are exhausted. Like os.replace, the helper
        # does not clean up src on failure (write_text owns temp cleanup).
        src = self._src("new content")

        def always_fail(s, d):
            raise PermissionError("locked")

        with mock.patch.object(self.module.os, "replace", side_effect=always_fail):
            with self.assertRaises(PermissionError):
                self.module.replace_with_retry(
                    src, self.dst, retries=2, delay=0, is_windows=True
                )
        # Destination is untouched because no replace ever succeeded.
        self.assertEqual(self.dst.read_text(encoding="utf-8"), "original")

    def test_succeeds_after_transient_failure(self):
        # A PermissionError on the first attempt followed by a real successful
        # replace on retry must not raise, and must complete the move.
        src = self._src("new content")
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(s, d):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("transient lock")
            # On retry, perform the real atomic move.
            return real_replace(s, d)

        with mock.patch.object(self.module.os, "replace", side_effect=flaky_replace):
            self.module.replace_with_retry(
                src, self.dst, retries=3, delay=0, is_windows=True
            )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(self.dst.read_text(encoding="utf-8"), "new content")

    def test_posix_does_not_retry(self):
        # On non-Windows platforms the helper must NOT retry: a single failure
        # propagates immediately (zero behavior change vs. the old os.replace).
        src = self._src("new content")
        calls = {"n": 0}

        def fail(s, d):
            calls["n"] += 1
            raise PermissionError("locked")

        with mock.patch.object(self.module.os, "replace", side_effect=fail):
            with self.assertRaises(PermissionError):
                self.module.replace_with_retry(
                    src, self.dst, retries=5, delay=0, is_windows=False
                )
        # Tried exactly once — no retry on POSIX.
        self.assertEqual(calls["n"], 1)
        self.assertEqual(self.dst.read_text(encoding="utf-8"), "original")

    def test_non_permission_error_not_retried(self):
        # Only PermissionError (the Windows lock symptom) should be retried.
        # Other OSError subtypes must surface immediately even on Windows.
        src = self._src("new content")
        with mock.patch.object(self.module.os, "replace", side_effect=FileNotFoundError("gone")):
            with self.assertRaises(FileNotFoundError):
                self.module.replace_with_retry(
                    src, self.dst, retries=3, delay=0, is_windows=True
                )


if __name__ == "__main__":
    unittest.main()
