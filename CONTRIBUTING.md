# Contributing to analint

Thanks for your interest in analint. This is an early public release (`0.0.1`):
issues, reproductions, and example specs are especially welcome.

All new repository content — code, comments, docs, commit messages — is written in
**English**. (Some historical research notes are in Russian; leave them as-is.)

## Development setup

analint uses [uv](https://docs.astral.sh/uv/) and targets **Python 3.12+**.

```bash
git clone https://github.com/angru/analint
cd analint
uv sync                      # create the env and install dev dependencies
uv run analint examples/ecommerce/   # smoke test
```

## Running the checks

```bash
uv run pytest                # full test suite
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run ty check              # type check (src/)
```

A few specific things to know about the test suite:

- `tests/test_characterization.py` is the behavioural regression oracle: a
  committed golden snapshot (`tests/snapshots/examples.json`) of every example's
  verdict, per-scenario results, and per-query graph hashes/traces. If you
  **intentionally** change behaviour, regenerate it — never mechanically, always
  after confirming the new snapshot is correct:

  ```bash
  UPDATE_SNAPSHOT=1 uv run pytest tests/test_characterization.py
  ```

  See `tests/snapshots/README.md` for the regen rule and expected deltas.
- `tests/test_transition_conformance.py` is the fine-grained kernel gate. Agreed
  semantics stay green; known target changes are `xfail(strict=True)`, so fixing
  one produces an XPASS until its marker is deliberately removed.

## Trying the CLI

```bash
uv run analint check .                      # validate the spec in the cwd
uv run analint show action <id> -p <spec>   # inspect one action
uv run analint affects <Entity.field> -p <spec>   # blast radius of a field
uv run analint explore -p <spec>            # bounded reachability exploration
uv run analint check . --what-if file.py    # test a hypothesis without editing files
```

Exit codes: `0` ok · `1` findings · `2` usage · `3` spec failed to load · `4`
inconclusive (a query exhausted its exploration budget — it proved nothing). JSON
output carries a three-valued `verdict` (`PASS`/`FAIL`/`INCONCLUSIVE`).

## How the project works

- **`ROADMAP.md` is the single source of truth** for status and priorities.
  `research/` holds dated design rationale that the roadmap links to;
  `AGENTS.md` is a detailed map of the codebase.
- The project is **review-gated and fail-closed by design**: a verification
  feature that hides a defect is the worst possible outcome here. Prefer
  `INCONCLUSIVE` / `NOT_CHECKED` over a silent pass. When you add or change a
  verification path, adversarially self-probe it — plant a defect the new path
  should catch and confirm the overall verdict actually goes `FAIL`.
- Keep changes semantically focused: one behavioural change per commit, with the
  characterization snapshot updated deliberately in the same commit.

## Pull requests

1. Branch from `main`.
2. Make the change; add or update tests and (if behaviour changed) the snapshot.
3. Ensure `pytest`, `ruff`, and `ty` are green.
4. Open a PR describing **what guarantee changed**, not just the diff.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
