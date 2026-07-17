import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.revisit_contract.generation import (
    AbsentGeneration,
    AuthorityDriftError,
    DirectoryGeneration,
    FileGeneration,
    GenerationClosure,
    GenerationDrift,
    ObservedEntry,
    ObservedReadSession,
)
from scripts.revisit_contract.model import RevisitContractError


def _can_create_symlink() -> bool:
    """Probe whether the host can actually create a symbolic link.

    ``hasattr(os, "symlink")`` is True on Windows but creating a link still
    requires Developer Mode or administrator privileges, so the attribute test
    alone lets symlink-based tests run and fail with ``OSError`` on
    unprivileged Windows. This probe attempts a real throwaway link and returns
    False on any ``OSError`` so ``skipUnless`` gates skip those tests honestly.
    """
    if not hasattr(os, "symlink"):
        return False
    directory = tempfile.mkdtemp()
    try:
        target = os.path.join(directory, "target.txt")
        link = os.path.join(directory, "link.txt")
        open(target, "w", encoding="utf-8").close()
        try:
            os.symlink(target, link)
        except OSError:
            return False
        return True
    finally:
        shutil.rmtree(directory, ignore_errors=True)


CAN_SYMLINK = _can_create_symlink()


class _WorkspaceMixin:
    """Shared setUp creating an isolated workspace directory."""

    def setUp(self) -> None:
        self._tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tempdir, True)
        self.workspace = Path(self._tempdir) / "ws"
        self.workspace.mkdir(parents=True, exist_ok=True)


class TestObservedFileGeneration(_WorkspaceMixin, unittest.TestCase):
    def test_repeated_read_returns_first_payload_and_closure_detects_drift(self) -> None:
        target = self.workspace / "a.txt"
        target.write_bytes(b"first\n")
        session = ObservedReadSession(self.workspace)
        first = session.read_required("a.txt")
        self.assertEqual(first, b"first\n")
        # Mutate the file on disk after the first observation.
        target.write_bytes(b"second\n")
        # First observation wins: cached bytes are returned unchanged.
        second = session.read_required("a.txt")
        self.assertEqual(second, b"first\n")
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertIn("a.txt", str(ctx.exception))
        self.assertEqual(ctx.exception.drift.relative_path, "a.txt")

    def test_optional_absence_detects_later_appearance(self) -> None:
        session = ObservedReadSession(self.workspace)
        self.assertIsNone(session.read_optional("ghost.txt"))
        # The path appears before closure verification.
        (self.workspace / "ghost.txt").write_bytes(b"appeared\n")
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "ghost.txt")

    def test_optional_absence_remains_first_observation_after_appearance(
        self,
    ) -> None:
        session = ObservedReadSession(self.workspace)
        self.assertIsNone(session.read_optional("ghost.txt"))

        (self.workspace / "ghost.txt").write_bytes(b"appeared\n")

        self.assertIsNone(session.read_optional("ghost.txt"))
        with self.assertRaises(RevisitContractError) as missing:
            session.read_required("ghost.txt")
        self.assertIn(
            "required authority is missing: ghost.txt",
            str(missing.exception),
        )

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual(drift.exception.drift.relative_path, "ghost.txt")

    def test_optional_present_then_byte_drift(self) -> None:
        target = self.workspace / "opt.txt"
        target.write_bytes(b"one\n")
        session = ObservedReadSession(self.workspace)
        self.assertEqual(session.read_optional("opt.txt"), b"one\n")
        target.write_bytes(b"two\n")
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "opt.txt")

    def test_required_file_disappearance_drifts(self) -> None:
        target = self.workspace / "req.txt"
        target.write_bytes(b"keep\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("req.txt")
        target.unlink()
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "req.txt")

    def test_required_missing_records_absence_before_raising_and_later_appearance_drifts(
        self,
    ) -> None:
        session = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError) as ctx:
            session.read_required("missing.txt")
        self.assertIn("missing.txt", str(ctx.exception))
        # Absence tombstone must have been recorded before the raise, so a
        # later appearance still drifts.
        (self.workspace / "missing.txt").write_bytes(b"late\n")
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx2:
            closure.require_unchanged()
        self.assertEqual(ctx2.exception.drift.relative_path, "missing.txt")

    def test_required_missing_tombstone_is_absent_generation(self) -> None:
        session = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError):
            session.read_required("absent.txt")
        generations = session.freeze().generations
        absent = [g for g in generations if g.relative_path == "absent.txt"]
        self.assertEqual(len(absent), 1)
        self.assertIsInstance(absent[0], AbsentGeneration)

    def test_optional_missing_tombstone_is_absent_generation(self) -> None:
        session = ObservedReadSession(self.workspace)
        self.assertIsNone(session.read_optional("opt-absent.txt"))
        generations = session.freeze().generations
        absent = [g for g in generations if g.relative_path == "opt-absent.txt"]
        self.assertEqual(len(absent), 1)
        self.assertIsInstance(absent[0], AbsentGeneration)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_same_byte_symlink_retarget_drifts(self) -> None:
        # Target A holds the same bytes as target B, but a lexical symlink
        # retargeted from one to the other must still drift.
        target_a = self.workspace / "a_payload.txt"
        target_b = self.workspace / "b_payload.txt"
        target_a.write_bytes(b"shared\n")
        target_b.write_bytes(b"shared\n")
        link = self.workspace / "link.txt"
        os.symlink(target_a, link)
        session = ObservedReadSession(self.workspace)
        session.read_required("link.txt")
        # Retarget to B with identical bytes.
        link.unlink()
        os.symlink(target_b, link)
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "link.txt")

    def test_file_generation_captures_sha256_and_payload(self) -> None:
        target = self.workspace / "hashed.txt"
        target.write_bytes(b"hash-me\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("hashed.txt")
        generations = session.freeze().generations
        gen = [g for g in generations if g.relative_path == "hashed.txt"]
        self.assertEqual(len(gen), 1)
        self.assertIsInstance(gen[0], FileGeneration)
        assert isinstance(gen[0], FileGeneration)  # for type checkers
        self.assertEqual(gen[0].payload, b"hash-me\n")
        self.assertEqual(
            gen[0].sha256,
            hashlib.sha256(b"hash-me\n").hexdigest(),
        )

    def test_rejects_absolute_and_escape_paths(self) -> None:
        session = ObservedReadSession(self.workspace)
        for bad in (
            "/etc/passwd",
            "C:/Windows/system32",
            "../escape.txt",
            "a/../../escape.txt",
            "",
            "a/\x00b",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(RevisitContractError):
                    session.read_required(bad)

    def test_normalize_backslash_and_dot_segments(self) -> None:
        # Backslash is a separator, "." collapses, but the stored relative
        # path is canonical POSIX form.
        (self.workspace / "sub").mkdir()
        target = self.workspace / "sub" / "x.txt"
        target.write_bytes(b"canon\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("sub/./x.txt")
        generations = session.freeze().generations
        gen = [g for g in generations if g.relative_path.endswith("x.txt")]
        self.assertEqual(len(gen), 1)
        self.assertEqual(gen[0].relative_path, "sub/x.txt")


class TestObservedDirectoryGeneration(_WorkspaceMixin, unittest.TestCase):
    def _make_dir(self, name: str = "d") -> Path:
        d = self.workspace / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_optional_absent_dir_returns_empty_and_later_appearance_drifts(self) -> None:
        session = ObservedReadSession(self.workspace)
        self.assertEqual(
            session.list_directory("ghost", recursive=False, optional=True), ()
        )
        # Absence tombstone recorded; later appearance drifts.
        (self.workspace / "ghost").mkdir()
        (self.workspace / "ghost" / "x.txt").write_bytes(b"x\n")
        closure = session.freeze()
        with self.assertRaises(AuthorityDriftError) as ctx:
            closure.require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "ghost")

    def test_absence_is_shared_across_directory_recursion_modes(self) -> None:
        session = ObservedReadSession(self.workspace)
        self.assertEqual(
            session.list_directory("ghost", recursive=False, optional=True), ()
        )

        ghost = self.workspace / "ghost"
        ghost.mkdir()
        (ghost / "x.txt").write_bytes(b"x\n")

        self.assertEqual(
            session.list_directory("ghost", recursive=True, optional=True), ()
        )
        with self.assertRaises(RevisitContractError) as missing:
            session.list_directory("ghost", recursive=True)
        self.assertIn(
            "required directory is missing: ghost",
            str(missing.exception),
        )

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual(drift.exception.drift.relative_path, "ghost")

    def test_required_absent_dir_records_tombstone_before_raising(self) -> None:
        session = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError) as ctx:
            session.list_directory("ghost-req", recursive=False)
        self.assertIn("ghost-req", str(ctx.exception))
        # Tombstone recorded before the raise.
        generations = session.freeze().generations
        absent = [g for g in generations if g.relative_path == "ghost-req"]
        self.assertEqual(len(absent), 1)
        self.assertIsInstance(absent[0], AbsentGeneration)
        # And later appearance still drifts.
        session2 = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError):
            session2.list_directory("ghost-req", recursive=False)
        (self.workspace / "ghost-req").mkdir()
        with self.assertRaises(AuthorityDriftError):
            session2.freeze().require_unchanged()

    def test_member_add_drifts(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        (d / "b.txt").write_bytes(b"b\n")
        with self.assertRaises(AuthorityDriftError) as ctx:
            session.freeze().require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "d")

    def test_member_remove_drifts(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        (d / "a.txt").unlink()
        with self.assertRaises(AuthorityDriftError):
            session.freeze().require_unchanged()

    def test_member_rename_drifts(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        (d / "a.txt").rename(d / "z.txt")
        with self.assertRaises(AuthorityDriftError):
            session.freeze().require_unchanged()

    def test_member_type_change_drifts(self) -> None:
        d = self._make_dir()
        (d / "leaf").write_bytes(b"file\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        (d / "leaf").unlink()
        (d / "leaf").mkdir()
        (d / "leaf" / "inside.txt").write_bytes(b"x\n")
        with self.assertRaises(AuthorityDriftError):
            session.freeze().require_unchanged()

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_member_symlink_retarget_drifts(self) -> None:
        d = self._make_dir()
        target_a = d / "t_a.txt"
        target_b = d / "t_b.txt"
        target_a.write_bytes(b"shared\n")
        target_b.write_bytes(b"shared\n")
        link = d / "link.txt"
        os.symlink(target_a, link)
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        link.unlink()
        os.symlink(target_b, link)
        with self.assertRaises(AuthorityDriftError):
            session.freeze().require_unchanged()

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_recursive_listing_does_not_follow_directory_symlink_member(
        self,
    ) -> None:
        d = self._make_dir()
        real = d / "real"
        real.mkdir()
        (real / "deep.txt").write_bytes(b"deep\n")
        link = d / "link"
        os.symlink(real, link)

        entries = ObservedReadSession(self.workspace).list_directory(
            "d", recursive=True
        )
        by_path = {entry.relative_path: entry for entry in entries}

        self.assertEqual(by_path["d/link"].kind, "other")
        self.assertEqual(by_path["d/link"].resolved_target, real.resolve())
        self.assertNotIn("d/link/deep.txt", by_path)
        self.assertIn("d/real/deep.txt", by_path)

    def test_recursive_scope_observes_nested_members(self) -> None:
        d = self._make_dir()
        nested = d / "sub"
        nested.mkdir()
        (nested / "deep.txt").write_bytes(b"deep\n")
        (d / "top.txt").write_bytes(b"top\n")
        session = ObservedReadSession(self.workspace)
        entries = session.list_directory("d", recursive=True)
        rels = {e.relative_path for e in entries}
        self.assertIn("d/top.txt", rels)
        self.assertIn("d/sub/deep.txt", rels)
        # Mutating the deep file changes membership scope only when recursive.
        # Non-recursive observation should NOT drift on a nested add.
        session2 = ObservedReadSession(self.workspace)
        session2.list_directory("d", recursive=False)
        (nested / "deeper.txt").write_bytes(b"x\n")
        # Non-recursive: nested change is out of scope, no drift.
        session2.freeze().require_unchanged()

    def test_recursive_nested_add_drifts(self) -> None:
        d = self._make_dir()
        (d / "top.txt").write_bytes(b"top\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=True)
        (d / "sub").mkdir()
        (d / "sub" / "new.txt").write_bytes(b"new\n")
        with self.assertRaises(AuthorityDriftError):
            session.freeze().require_unchanged()

    def test_member_order_is_deterministic_by_relative_posix_path(self) -> None:
        d = self._make_dir()
        for name in ("zeta.txt", "alpha.txt", "mid.txt"):
            (d / name).write_bytes(name.encode())
        session = ObservedReadSession(self.workspace)
        entries = session.list_directory("d", recursive=False)
        self.assertEqual(
            [e.relative_path for e in entries],
            ["d/alpha.txt", "d/mid.txt", "d/zeta.txt"],
        )

    def test_listing_does_not_read_file_contents(self) -> None:
        d = self._make_dir()
        member = d / "payload.txt"
        member.write_bytes(b"original\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        # Listing should not have captured payload, so the generation must be a
        # DirectoryGeneration and the file's bytes drift is invisible at the
        # membership level (only membership/target/kind are observed).
        generations = session.freeze().generations
        gen = [g for g in generations if g.relative_path == "d"]
        self.assertEqual(len(gen), 1)
        self.assertIsInstance(gen[0], DirectoryGeneration)

    def test_listing_caches_first_observation_per_recursive_key(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        first = session.list_directory("d", recursive=False)
        (d / "b.txt").write_bytes(b"b\n")
        second = session.list_directory("d", recursive=False)
        # First observation wins: same entries, no b.txt.
        self.assertEqual(first, second)
        self.assertEqual(
            {e.relative_path for e in second}, {"d/a.txt"}
        )
        # A recursive observation is a SEPARATE key and reflects nothing new
        # because b.txt was added after the non-recursive capture but the
        # recursive capture happens now (first recursive observation).
        recursive_entries = session.list_directory("d", recursive=True)
        self.assertIn("d/b.txt", {e.relative_path for e in recursive_entries})

    def test_directory_generation_is_cached_in_closure(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        gen = session.freeze().generations
        self.assertEqual(len(gen), 1)
        assert isinstance(gen[0], DirectoryGeneration)
        self.assertEqual(gen[0].relative_path, "d")
        self.assertFalse(gen[0].recursive)

    def test_freeze_closes_session(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("d/a.txt")
        closure = session.freeze()
        # After freeze, further observations raise a clear error.
        with self.assertRaises(RevisitContractError):
            session.read_required("d/a.txt")
        with self.assertRaises(RevisitContractError):
            session.read_optional("d/a.txt")
        with self.assertRaises(RevisitContractError):
            session.list_directory("d", recursive=False)
        with self.assertRaises(RevisitContractError):
            session.freeze()
        # The closure itself is immutable: generations is a tuple.
        self.assertIsInstance(closure.generations, tuple)

    def test_require_unchanged_except_excludes_exact_member_path(self) -> None:
        from scripts.revisit_contract.generation import _require_unchanged_except

        d = self._make_dir()
        (d / "keep.txt").write_bytes(b"keep\n")
        (d / "churn.txt").write_bytes(b"churn1\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        # Mutate churn.txt content (membership is unchanged, kind unchanged,
        # target unchanged) -> no drift at all from list_directory.
        (d / "churn.txt").write_bytes(b"churn2\n")
        closure = session.freeze()
        # Excluding the exact member path should skip it on both sides.
        _require_unchanged_except(closure, ("d/churn.txt",))
        # But excluding a path that still drifts on membership must still raise.
        (d / "extra.txt").write_bytes(b"x\n")
        with self.assertRaises(AuthorityDriftError):
            _require_unchanged_except(closure, ("d/churn.txt",))

    def test_require_unchanged_except_rejects_non_string_exclusion(self) -> None:
        from scripts.revisit_contract.generation import _require_unchanged_except

        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        closure = session.freeze()
        with self.assertRaises(RevisitContractError):
            _require_unchanged_except(closure, ("d/a.txt", None))  # type: ignore[arg-type]

    def test_require_unchanged_except_excludes_file_generation_entirely(self) -> None:
        from scripts.revisit_contract.generation import _require_unchanged_except

        target = self.workspace / "f.txt"
        target.write_bytes(b"v1\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("f.txt")
        closure = session.freeze()
        # Mutate the excluded file: with exclusion, no drift.
        target.write_bytes(b"v2\n")
        _require_unchanged_except(closure, ("f.txt",))
        # Without exclusion, drifts.
        with self.assertRaises(AuthorityDriftError):
            closure.require_unchanged()


if __name__ == "__main__":
    unittest.main()
