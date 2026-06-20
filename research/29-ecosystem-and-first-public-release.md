# Ecosystem & first public release (0.0.1)

**Date:** 2026-06-19

The P4 self-contained workbench is complete (research/26, all checkpoints ✅) and
the evidence gate is passed (research/25): no new verification primitive is
demanded. Roadmap §"Deferred ecosystem work" gated publication explicitly on
workbench completion — that milestone is now reached, so this phase makes analint
installable and contributable without changing any semantics.

This is a packaging/positioning phase, **not** an engine change. No DSL, kernel,
explorer or artifact behavior is touched. Success = a stranger can
`pip install analint`, run `analint check`, read how to contribute, and the
published metadata is honest about maturity.

## Decisions (locked with the user, 2026-06-19)

- **License: MIT.** Simplest permissive license, dominant across Python tooling
  (ruff, pydantic). `LICENSE` file + `pyproject` `license`/classifier.
- **Version: 0.0.1.** The internal `1.0.1` tracked roadmap milestones (v0.9 →
  v1.0 → v1.0.1), not a public contract. A `0.x` first release is the honest
  signal that the public API is not yet frozen — consistent with the roadmap
  principle "do not publish before names stabilize". User chose `0.0.1` over the
  more conventional `0.1.0` as the maximally-cautious "very early" marker.
- **`requires-python`: relax `==3.14.*` → `>=3.12`.** The real language floor is
  PEP 695 type parameters (`class Lifecycle[S]:`, `class Transition[S]:` in
  `models/lifecycle.py`), introduced in 3.12. The exact-3.14 pin was an
  artifact, not a requirement; it would exclude almost every installer. **Floor
  change must be proven by running the suite under 3.12, not just asserted**
  (review-gated honesty) — this caught a PEP 758 use in `examples/play.py`.
  **Dev tooling must also drop to the support floor:** ruff `target-version` and
  ty `python-version` go `3.14 → 3.12`. With ruff on `py314`, `ruff format`
  treats the except-group parentheses as redundant and *strips* them, silently
  re-introducing 3.14-only syntax on every format; on `py312` ruff instead flags
  the bare form as `invalid-syntax`. Keeping dev tooling above the floor is a
  standing false-green generator, not a neutral choice.

## Checkpoints (one reviewable chunk per commit; nothing irreversible without explicit go-ahead)

1. **Licensing + packaging metadata.** Add `LICENSE` (MIT). Fill `pyproject`:
   `license`, `authors`, `readme`, `keywords`, `classifiers`, `[project.urls]`,
   reset `version = "0.0.1"`, relax `requires-python`. Configure the sdist target
   so internal `research/` and `reviews/` are excluded while `examples/` and
   `tests/` ship (decide deliberately, do not rely on defaults).
2. **README + CONTRIBUTING + CHANGELOG.** README: add a License section and repo
   links; it is otherwise already a full public landing page (install,
   quickstart, DSL reference, CLI, MCP, examples). `CONTRIBUTING.md`: uv dev
   setup, `uv run pytest`, ruff/ty, snapshot regen, the research/review-gated
   workflow, commit conventions. `CHANGELOG.md` (Keep a Changelog): a single
   `0.0.1` entry honestly summarizing the engine's current scope and its bounds
   (bounded reachability; no liveness/temporal; safety + reachability only).
3. **Build + clean-install validation.** `uv build`; inspect wheel + sdist
   contents (no research/reviews, src + entry points present); `twine check`;
   install the built wheel into a throwaway venv on **Python 3.12** and smoke-test
   `analint check examples/...`, `analint --help`, the `mcp` extra. Run the full
   suite under 3.12 to prove the relaxed floor.
4. **Publish (irreversible — only after explicit confirmation).** TestPyPI
   dry-run first, then PyPI. Confirm GitHub repo visibility (currently unknown —
   `gh` not authed); if private, making it public is a separate explicit step.
   Tag `v0.0.1` + GitHub release. A PyPI version cannot be re-uploaded once
   taken, so this checkpoint is held until the user says go.

## Test-install findings: Typer vendored Click (the dev env was lying)

A real test-install (TestPyPI → fresh venv) surfaced two latent bugs that the dev
environment had masked, both rooted in one upstream change: **Typer 0.26.0 vendored
Click** (PR #1774 — "Typer no longer depends on Click as a third party dependency,
it vendors … Click", now importable as `typer._click`). The repo's lockfile was
pinned to `typer 0.25.1` — one minor below the change — so everything passed
locally while a fresh install pulled `typer 0.26.7`, which behaves differently.

1. **`ModuleNotFoundError: No module named 'click'`.** `cli.py` did `import click`,
   but Typer no longer pulls the external `click` package. First reflex was to
   *declare* `click`; the correct fix is that analint should **not import external
   Click at all** — the CLI layer is entirely Typer's. Removed the import; the
   `ctx`/command in the `resolve_command` override are an opaque `Any` pass-through
   to `super()`. External `click` is now a *dev-only* dependency (one test uses
   `click.unstyle`), not a runtime one.
2. **`analint <PATH>` shortcut silently broken under 0.26.x.** `_DefaultToCheck`
   caught `click.exceptions.UsageError` (external), but Typer raises its *vendored*
   `typer._click` `UsageError` — a different class, never caught, so the
   bare-path → `check` fallback died with "No such command". Rewritten to decide by
   inspecting `args[0]` (known command / option flag → leave; else prepend
   `check`), which is independent of any Click class identity and works on old and
   new Typer. `ty` also flagged this once the lock was current: the override's
   external-Click return type is not Liskov-compatible with the vendored-Click base.

Process lesson (matches the review-gated discipline): a lockfile below a
dependency's behavioural boundary is a standing false-green generator. Fix applied:
`uv lock --upgrade` to the latest of everything, so dev/CI run against the versions
users actually install. The bare-path regression test was adversarially confirmed
to fail on the broken version under `typer 0.26.7` before the fix was accepted.

## Deferred within this phase

- Full docs site (MkDocs/Material). The 726-line README covers the surface; a
  separate site is a follow-up, not a blocker for 0.0.1.
