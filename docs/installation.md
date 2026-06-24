# Installation

SOFA is a framework repo. Minimal use does not require installing optional search or financial tools.

> **Interpreter name:** commands below use `python`. On Windows use `python` or `py`; some Linux distros only ship `python3`. Use whichever your system provides.

## Minimal Local Use

1. Place or clone the repo where your host agent can read it.
2. Use `SOFA/skills/sofa-analyze/SKILL.md` as the framework entry.
3. Run workspace initialization before research:

```bash
python SOFA/scripts/init_workspace.py "SUBJECT" "./workspace" --mode ticker
python SOFA/scripts/init_workspace.py "THEME" "./workspace" --mode sector
```

4. Run gates and validators from `SOFA/scripts/` as the workflow progresses.

## Boundaries

SOFA does not silently install optional tools, write credentials, or assume one host runtime. Host-specific mapping belongs in `docs/adapters/`.

## Recommended Checks

```bash
python -m compileall -q SOFA/scripts SOFA/tests
python -m unittest discover -s SOFA/tests -p "test_*.py"
```

## Next Steps

- Configure optional capabilities with `docs/capability-setup.md`.
- Pick the adapter that matches your host environment.
- Start from `SOFA Analyze` and keep evidence, workflow, capability, and claim ledgers inside the active research workspace.
