import errno
import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.revisit_contract import generation as generation_mod
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


class TestUnexpectedIoBoundary(_WorkspaceMixin, unittest.TestCase):
    def test_initial_lstat_eio_propagates_unchanged(self) -> None:
        (self.workspace / "authority.txt").write_bytes(b"authority\n")
        session = ObservedReadSession(self.workspace)

        with mock.patch.object(
            generation_mod.os,
            "lstat",
            side_effect=OSError(errno.EIO, "lstat fault"),
        ):
            with self.assertRaises(OSError) as raised:
                session.read_optional("authority.txt")

        self.assertEqual(errno.EIO, raised.exception.errno)

    def test_initial_resolve_eio_propagates_unchanged(self) -> None:
        (self.workspace / "authority.txt").write_bytes(b"authority\n")
        session = ObservedReadSession(self.workspace)

        with mock.patch.object(
            Path,
            "resolve",
            side_effect=OSError(errno.EIO, "resolve fault"),
        ):
            with self.assertRaises(OSError) as raised:
                session.read_optional("authority.txt")

        self.assertEqual(errno.EIO, raised.exception.errno)

    def test_initial_payload_and_directory_eio_propagate_unchanged(self) -> None:
        (self.workspace / "authority.txt").write_bytes(b"authority\n")
        (self.workspace / "authorities").mkdir()
        for operation, patch_target, relative_path, kwargs in (
            ("read", "read_bytes", "authority.txt", {}),
            ("list", "iterdir", "authorities", {"recursive": False}),
        ):
            with self.subTest(operation=operation):
                session = ObservedReadSession(self.workspace)
                with mock.patch.object(
                    Path,
                    patch_target,
                    side_effect=OSError(errno.EIO, f"{operation} fault"),
                ):
                    with self.assertRaises(OSError) as raised:
                        if operation == "read":
                            session.read_optional(relative_path)
                        else:
                            session.list_directory(relative_path, **kwargs)
                self.assertEqual(errno.EIO, raised.exception.errno)

    def test_closure_recheck_payload_and_directory_eio_propagate_unchanged(self) -> None:
        (self.workspace / "authority.txt").write_bytes(b"authority\n")
        (self.workspace / "authorities").mkdir()
        for operation, patch_target, relative_path, kwargs in (
            ("read", "read_bytes", "authority.txt", {}),
            ("list", "iterdir", "authorities", {"recursive": False}),
        ):
            with self.subTest(operation=operation):
                session = ObservedReadSession(self.workspace)
                if operation == "read":
                    session.read_optional(relative_path)
                else:
                    session.list_directory(relative_path, **kwargs)
                closure = session.freeze()

                with mock.patch.object(
                    Path,
                    patch_target,
                    side_effect=OSError(errno.EIO, f"{operation} recheck fault"),
                ):
                    with self.assertRaises(OSError) as raised:
                        closure.require_unchanged()
                self.assertEqual(errno.EIO, raised.exception.errno)

    def test_expected_access_denial_remains_stable_present_invalid(self) -> None:
        (self.workspace / "authority.txt").write_bytes(b"authority\n")
        session = ObservedReadSession(self.workspace)
        denied = PermissionError(errno.EACCES, "access denied")

        with mock.patch.object(Path, "read_bytes", side_effect=denied):
            with self.assertRaises(RevisitContractError):
                session.read_optional("authority.txt")
            session.freeze().require_unchanged()


class TestObservedFileGeneration(_WorkspaceMixin, unittest.TestCase):
    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_absence_to_broken_or_outside_symlink_is_exact_drift(self) -> None:
        outside = Path(self._tempdir) / "outside.txt"
        outside.write_bytes(b"outside\n")
        cases = (
            ("broken", self.workspace / "never-created.txt"),
            ("outside", outside),
        )
        for label, target in cases:
            with self.subTest(case=label):
                lexical = self.workspace / f"{label}.txt"
                session = ObservedReadSession(self.workspace)
                self.assertIsNone(session.read_optional(lexical.name))
                lexical.symlink_to(target)

                with self.assertRaises(AuthorityDriftError) as drift:
                    session.freeze().require_unchanged()
                self.assertEqual(lexical.name, drift.exception.drift.relative_path)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_file_to_broken_or_outside_symlink_is_exact_drift(self) -> None:
        outside = Path(self._tempdir) / "outside.txt"
        outside.write_bytes(b"same\n")
        cases = (
            ("broken", self.workspace / "never-created.txt"),
            ("outside", outside),
        )
        for label, target in cases:
            with self.subTest(case=label):
                lexical = self.workspace / f"{label}.txt"
                lexical.write_bytes(b"same\n")
                session = ObservedReadSession(self.workspace)
                self.assertEqual(b"same\n", session.read_required(lexical.name))
                lexical.unlink()
                lexical.symlink_to(target)

                with self.assertRaises(AuthorityDriftError) as drift:
                    session.freeze().require_unchanged()
                self.assertEqual(lexical.name, drift.exception.drift.relative_path)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_stable_broken_or_outside_symlink_is_present_invalid(self) -> None:
        outside = Path(self._tempdir) / "outside.txt"
        outside.write_bytes(b"outside\n")
        cases = (
            ("broken", self.workspace / "never-created.txt"),
            ("outside", outside),
        )
        for label, target in cases:
            with self.subTest(case=label):
                lexical = self.workspace / f"stable-{label}.txt"
                lexical.symlink_to(target)
                session = ObservedReadSession(self.workspace)

                with self.assertRaises(RevisitContractError):
                    session.read_optional(lexical.name)

                generations = session.freeze().generations
                self.assertEqual(1, len(generations))
                self.assertNotIsInstance(generations[0], AbsentGeneration)
                GenerationClosure(
                    workspace=self.workspace.resolve(),
                    generations=generations,
                ).require_unchanged()

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_missing_child_below_outside_parent_symlink_is_not_absent(self) -> None:
        outside = Path(self._tempdir) / "outside-directory"
        outside.mkdir()
        parent = self.workspace / "escaped-parent"
        parent.symlink_to(outside, target_is_directory=True)
        session = ObservedReadSession(self.workspace)

        with self.assertRaises(RevisitContractError):
            session.read_optional("escaped-parent/missing.txt")

        generations = session.freeze().generations
        self.assertEqual(1, len(generations))
        self.assertNotIsInstance(generations[0], AbsentGeneration)
        GenerationClosure(
            workspace=self.workspace.resolve(),
            generations=generations,
        ).require_unchanged()

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_missing_child_binds_inside_parent_symlink_target(self) -> None:
        first_parent = self.workspace / "first-parent"
        second_parent = self.workspace / "second-parent"
        first_parent.mkdir()
        second_parent.mkdir()
        lexical_parent = self.workspace / "linked-parent"
        lexical_parent.symlink_to(first_parent, target_is_directory=True)
        session = ObservedReadSession(self.workspace)

        self.assertIsNone(
            session.read_optional("linked-parent/missing.txt")
        )
        lexical_parent.unlink()
        lexical_parent.symlink_to(second_parent, target_is_directory=True)
        self.assertIsNone(
            session.read_optional("linked-parent/missing.txt")
        )

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual(
            "linked-parent/missing.txt",
            drift.exception.drift.relative_path,
        )

    def test_stable_directory_is_present_invalid_for_file_access(self) -> None:
        directory = self.workspace / "not-a-file"
        directory.mkdir()
        session = ObservedReadSession(self.workspace)

        with self.assertRaises(RevisitContractError):
            session.read_optional("not-a-file")

        session.freeze().require_unchanged()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_is_classified_without_opening_it(self) -> None:
        fifo = self.workspace / "input.fifo"
        os.mkfifo(fifo)
        session = ObservedReadSession(self.workspace)

        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("FIFO must never be opened"),
        ) as read_bytes:
            with self.assertRaises(RevisitContractError):
                session.read_optional("input.fifo")

        read_bytes.assert_not_called()
        session.freeze().require_unchanged()

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

    def test_stable_file_is_present_invalid_for_optional_directory_access(
        self,
    ) -> None:
        (self.workspace / "not-a-directory").write_bytes(b"file\n")
        session = ObservedReadSession(self.workspace)

        with self.assertRaises(RevisitContractError):
            session.list_directory(
                "not-a-directory",
                recursive=False,
                optional=True,
            )

        session.freeze().require_unchanged()

    def test_cross_operation_access_reuses_first_lexical_node_state(self) -> None:
        directory = self._make_dir("cross-directory")
        directory_session = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError):
            directory_session.read_optional("cross-directory")
        directory.rmdir()
        directory.write_bytes(b"replacement\n")
        with self.assertRaises(AuthorityDriftError) as directory_drift:
            directory_session.list_directory(
                "cross-directory",
                recursive=False,
                optional=True,
            )
        self.assertEqual(
            "cross-directory",
            directory_drift.exception.drift.relative_path,
        )

        lexical_file = self.workspace / "cross-file"
        lexical_file.write_bytes(b"file\n")
        file_session = ObservedReadSession(self.workspace)
        with self.assertRaises(RevisitContractError):
            file_session.list_directory(
                "cross-file",
                recursive=False,
                optional=True,
            )
        lexical_file.unlink()
        lexical_file.mkdir()
        with self.assertRaises(AuthorityDriftError) as file_drift:
            file_session.read_optional("cross-file")
        self.assertEqual("cross-file", file_drift.exception.drift.relative_path)

    def test_member_add_drifts(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        (d / "b.txt").write_bytes(b"b\n")
        with self.assertRaises(AuthorityDriftError) as ctx:
            session.freeze().require_unchanged()
        self.assertEqual(ctx.exception.drift.relative_path, "d/b.txt")

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

    def test_recursive_child_disappearance_reports_exact_child_path(self) -> None:
        nested = self._make_dir() / "sub"
        nested.mkdir()
        child = nested / "deep.txt"
        child.write_bytes(b"deep\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=True)
        child.unlink()

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual("d/sub/deep.txt", drift.exception.drift.relative_path)

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_recursive_directory_member_escape_reports_exact_child_path(
        self,
    ) -> None:
        root = self._make_dir()
        nested = root / "sub"
        nested.mkdir()
        (nested / "deep.txt").write_bytes(b"deep\n")
        outside = Path(self._tempdir) / "outside"
        outside.mkdir()
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=True)
        shutil.rmtree(nested)
        nested.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual("d/sub", drift.exception.drift.relative_path)

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

    def test_nonrecursive_then_recursive_reuses_direct_membership(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        first = session.list_directory("d", recursive=False)
        (d / "b.txt").write_bytes(b"b\n")
        second = session.list_directory("d", recursive=False)
        self.assertEqual(first, second)
        self.assertEqual(
            {e.relative_path for e in second}, {"d/a.txt"}
        )
        recursive_entries = session.list_directory("d", recursive=True)
        self.assertNotIn(
            "d/b.txt",
            {e.relative_path for e in recursive_entries},
        )
        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual("d/b.txt", drift.exception.drift.relative_path)

    def test_direct_membership_is_physically_observed_once(self) -> None:
        root = self._make_dir()
        nested = root / "sub"
        nested.mkdir()
        (nested / "deep.txt").write_bytes(b"deep\n")
        observed: list[str] = []
        real_iterdir = Path.iterdir

        def counting_iterdir(path: Path):
            try:
                relative = path.resolve().relative_to(self.workspace.resolve())
            except ValueError:
                relative = path
            observed.append(relative.as_posix())
            return real_iterdir(path)

        session = ObservedReadSession(self.workspace)
        with mock.patch.object(Path, "iterdir", counting_iterdir):
            session.list_directory("d", recursive=False)
            recursive_entries = session.list_directory("d", recursive=True)

        self.assertIn(
            "d/sub/deep.txt",
            {entry.relative_path for entry in recursive_entries},
        )
        self.assertEqual(1, observed.count("d"))
        self.assertEqual(1, observed.count("d/sub"))

    def test_parent_membership_injects_child_first_observation_once(self) -> None:
        root = self._make_dir()
        (root / "child.txt").write_bytes(b"child\n")
        inspected: list[str] = []
        real_inspect = generation_mod._inspect_node

        def counting_inspect(workspace: Path, relative: str):
            inspected.append(relative)
            return real_inspect(workspace, relative)

        session = ObservedReadSession(self.workspace)
        with mock.patch.object(
            generation_mod,
            "_inspect_node",
            counting_inspect,
        ):
            entries = session.list_directory("d", recursive=False)

        self.assertEqual(["d/child.txt"], [entry.relative_path for entry in entries])
        self.assertEqual(1, inspected.count("d/child.txt"))

    def test_parent_scan_rejects_changed_explicit_child_observation(self) -> None:
        root = self._make_dir()
        child = root / "child"
        child.write_bytes(b"first\n")
        session = ObservedReadSession(self.workspace)
        self.assertEqual(b"first\n", session.read_required("d/child"))
        child.unlink()
        child.mkdir()

        with self.assertRaises(AuthorityDriftError) as drift:
            session.list_directory("d", recursive=False)
        self.assertEqual("d/child", drift.exception.drift.relative_path)

    def test_direct_directory_generation_is_cached_in_closure(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.list_directory("d", recursive=False)
        gen = session.freeze().generations
        self.assertEqual(len(gen), 1)
        assert isinstance(gen[0], DirectoryGeneration)
        self.assertEqual(gen[0].relative_path, "d")

    @unittest.skipUnless(CAN_SYMLINK, "requires symbolic links")
    def test_directory_to_broken_or_outside_symlink_is_exact_drift(self) -> None:
        outside = Path(self._tempdir) / "outside"
        outside.mkdir()
        cases = (
            ("broken", self.workspace / "never-created"),
            ("outside", outside),
        )
        for label, target in cases:
            with self.subTest(case=label):
                directory = self._make_dir(label)
                session = ObservedReadSession(self.workspace)
                session.list_directory(label, recursive=False)
                directory.rmdir()
                directory.symlink_to(target, target_is_directory=True)

                with self.assertRaises(AuthorityDriftError) as drift:
                    session.freeze().require_unchanged()
                self.assertEqual(label, drift.exception.drift.relative_path)

    def test_directory_disappearance_is_exact_drift(self) -> None:
        directory = self._make_dir("disappearing")
        session = ObservedReadSession(self.workspace)
        session.list_directory("disappearing", recursive=False)
        directory.rmdir()

        with self.assertRaises(AuthorityDriftError) as drift:
            session.freeze().require_unchanged()
        self.assertEqual(
            "disappearing",
            drift.exception.drift.relative_path,
        )

    def test_freeze_closes_session(self) -> None:
        d = self._make_dir()
        (d / "a.txt").write_bytes(b"a\n")
        session = ObservedReadSession(self.workspace)
        session.read_required("d/a.txt")
        closure = session.freeze()
        # A post-freeze observation is a programming error, not an invalid
        # workspace-input error that a readiness owner may translate.
        operations = (
            lambda: session.read_required("d/a.txt"),
            lambda: session.read_optional("d/a.txt"),
            lambda: session.list_directory("d", recursive=False),
            session.freeze,
        )
        for operation in operations:
            with self.assertRaises(RuntimeError) as raised:
                operation()
            self.assertNotIsInstance(
                raised.exception,
                RevisitContractError,
            )
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
