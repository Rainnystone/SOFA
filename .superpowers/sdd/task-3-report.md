# Task 3 Report: Source Cache Core Package

## What Changed

Implemented the deterministic `source_cache` core package and its unit tests, limited to the owned Task 3 surface:

- Added `tests/test_source_cache.py` as the RED-first contract for constants, hashing, source-id helpers, append-only add flow, index evaluation, bibliography rendering, and both import styles.
- Added `scripts/source_cache/model.py` for package constants, validation helpers, hashing, source-id parsing/formatting, and core dataclasses/exceptions.
- Added `scripts/source_cache/store.py` for index path loading, validation/evaluation, append-only source insertion, dedupe by normalized excerpt hash, duplicate-URL notice reporting, and registered source-id helpers.
- Added `scripts/source_cache/render.py` for bibliography rendering with identifier-only output and loud failure on invalid index state.
- Added `scripts/source_cache/__init__.py` to export the exact public API named in the brief.

## RED Command / Output Summary

Command:

```bash
python3 -B -m unittest tests.test_source_cache
```

Result:

- Exit code: `1`
- Expected RED observed.
- Failure summary: `ModuleNotFoundError: No module named 'source_cache'`

## GREEN Command / Output Summary

Command:

```bash
python3 -B -m unittest tests.test_source_cache && python3 -B -m compileall -q scripts/source_cache
```

Result:

- Exit code: `0`
- `15` tests ran and passed.
- `compileall` completed cleanly with no output.

## Files Changed

- `tests/test_source_cache.py`
- `scripts/source_cache/__init__.py`
- `scripts/source_cache/model.py`
- `scripts/source_cache/store.py`
- `scripts/source_cache/render.py`

## Commits

- `7d6617a` `test: define source cache core behavior`
- `2ff3ef0` `feat: add source cache core`

## Self-Review

- Stayed within Task 3 ownership boundaries.
- Followed TDD in the required order: RED test, RED run, RED commit, implementation, GREEN run, implementation commit.
- Kept the package stdlib-only and avoided wiring any later-task integrations.
- Verified both namespace import (`import scripts.source_cache`) and flat import (`import source_cache`) through the test suite.

## Concerns

None.

---

## Fix Round 1: Review Findings

### What Changed

- Added a regression test that monkeypatches the module-level `open` used by `source_cache.store` during index append, verifies `SourceCacheError` is raised, and confirms `sources/src-001.md` is not left behind after append failure.
- Added a regression test that creates `sources/nested/orphan.md` and verifies `evaluate_index()` reports `SOURCE_EXCERPT_UNREGISTERED` for the nested file.
- Updated `add_source()` so index append/open/write failures remove the newly written excerpt before raising `SourceCacheError`.
- Updated `evaluate_index()` to recursively scan `sources/` so nested unregistered files are warned, while preserving the existing schema allowance for any POSIX path under `sources/`.

### RED Verification

Command:

```bash
python3 -B -m unittest tests.test_source_cache
```

Result before the fix:

- Exit code: `1`
- Expected failures observed:
  - append failure propagated raw `OSError` instead of `SourceCacheError`
  - nested orphan file was not reported in `evaluation.warnings`

### GREEN Verification

Command:

```bash
python3 -B -m unittest tests.test_source_cache && python3 -B -m compileall -q scripts/source_cache
```

Result after the fix:

- Exit code: `0`
- `17` tests ran and passed.
- `compileall` completed cleanly with no output.

### Files Changed In Fix Round

- `tests/test_source_cache.py`
- `scripts/source_cache/store.py`

### Fix Commit

- `fix: harden source cache append cleanup`

### Self-Review

- Kept the changes inside Task 3 owned files only.
- Preserved the append-only API and existing success path.
- Kept `excerpt_path` validation unchanged and fixed the recursive stray scan at evaluation time instead of narrowing schema rules.

### Concerns

None.
