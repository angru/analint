"""Exercise the Worker Board handoff in an isolated Git repo with controlled check results."""

import json
import os
import shutil
import subprocess
from pathlib import Path


def test_only_clean_checked_and_reviewed_commit_can_be_handed_off(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts/agent"
    scripts.mkdir(parents=True)
    for name in ["review-commit.sh", "review-diff.sh", "checks.sh"]:
        shutil.copy(Path(__file__).with_name(name), scripts / name)
    (repo / ".gitignore").write_text("/.cache/\n")
    # Stub only uv. Git, the check wrapper, diff capture and exit handling are real.
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\n[ "$3" != pytest ] || exit "${PYTEST_STATUS:-0}"\n')
    uv.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PATH=str(tmp_path) + os.pathsep + env["PATH"], GIT_CONFIG_NOSYSTEM="1")
    env["GIT_CONFIG_GLOBAL"] = os.devnull

    def run(*args: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=repo, env=env | overrides, capture_output=True, text=True)

    def git(*args: str) -> str:
        result = run("git", *args)
        result.check_returncode()
        return result.stdout.strip()

    def step(*args: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        return run("sh", "scripts/agent/review-commit.sh", *args, **overrides)

    git("init", "-q")
    git("config", "user.name", "Smoke test")
    git("config", "user.email", "test@example.invalid")
    git("add", ".")
    git("commit", "-qm", "Base")
    base = json.loads(step("baseline").stdout)["baseSha"]
    (repo / "change.txt").write_text("first\n")
    git("add", "change.txt")
    git("commit", "-qm", "Implementation")
    head = git("rev-parse", "HEAD")

    assert step("verify", base, base).returncode != 0
    assert step("verify", base, head, PYTEST_STATUS="1").returncode != 0
    assert not (repo / ".cache/review/change.diff").exists()
    assert json.loads(step("verify", base, head).stdout) == {"base": base, "headSha": head}
    assert "+first" in (repo / ".cache/review/change.diff").read_text()
    for verdict in ("revise", "blocked"):
        assert step("handoff", head, head, verdict).returncode != 0
    assert step("handoff", head, base, "proceed").returncode != 0

    ref = f"reviewed/analint/{head}"
    assert run("git", "rev-parse", "--verify", f"refs/heads/{ref}").returncode != 0
    git("branch", ref, base)
    assert step("handoff", head, head, "proceed").returncode != 0
    assert git("rev-parse", ref) == base
    git("branch", "-D", ref)
    for _ in range(2):
        assert json.loads(step("handoff", head, head, "proceed").stdout) == {
            "headSha": head,
            "branch": ref,
        }
    assert git("rev-parse", ref) == head

    (repo / "untracked.txt").touch()
    assert step("verify", base, head).returncode != 0
    assert step("handoff", head, head, "proceed").returncode != 0
    git("add", ".")
    git("commit", "-qm", "Later commit")
    assert step("handoff", head, head, "proceed").returncode != 0
