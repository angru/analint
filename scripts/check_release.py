#!/usr/bin/env python
"""Verify built release artifacts in a temporary environment.

    uv build
    uv run --no-project python -I scripts/check_release.py --dist-dir dist

Requires uv on PATH. No project or development dependencies are needed by this
entry point. --python selects the clean environment's interpreter; an optional
--expected-version accepts a release tag such as v0.0.5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

ARCHIVE_TESTS = [
    "tests/test_release_verification.py",
    "tests/test_documentation.py",
    "tests/test_diagnostic_codes.py",
    "tests/test_impact.py",
    "tests/test_show_details.py",
    "tests/test_fixed_initial.py::test_fixed_roots_across_check_explore_and_trace",
    "tests/test_keys.py::test_key_verdicts_traces_artifacts_and_cache_agree",
]


def release_artifacts(dist: Path, expected: str) -> tuple[Path, Path, str]:
    """Refuse stale/mixed artifacts and wheel/sdist/tag version disagreement."""
    wheels, sources = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError(f"expected one wheel and one source archive in {dist}")
    wheel, source = wheels[0], sources[0]
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("expected exactly one wheel METADATA file")
        wheel_metadata = Parser().parsestr(archive.read(names[0]).decode())
    with tarfile.open(source) as archive:
        names = [n for n in archive.getnames() if n.count("/") == 1 and n.endswith("/PKG-INFO")]
        if len(names) != 1:
            raise ValueError("expected exactly one top-level source PKG-INFO file")
        member = archive.extractfile(names[0])
        if member is None:
            raise ValueError("source PKG-INFO is not a file")
        source_metadata = Parser().parsestr(member.read().decode())
        source_root = names[0].split("/")[0]
    for label, metadata in (("wheel", wheel_metadata), ("source", source_metadata)):
        if metadata["Name"] != "analint" or metadata["Version"] != expected.removeprefix("v"):
            raise ValueError(
                f"{label} metadata {metadata['Name']}=={metadata['Version']} "
                f"does not match analint=={expected.removeprefix('v')}"
            )
    return wheel, source, source_root


def run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--expected-version", help="expected version or v-prefixed release tag")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    expected = (
        args.expected_version
        or tomllib.loads((project / "pyproject.toml").read_text())["project"]["version"]
    )
    expected = expected.removeprefix("v")
    wheel, source, root_name = release_artifacts(args.dist_dir.resolve(), expected)
    # CLI entry points must not inherit an editable checkout through PYTHONPATH.
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    with tempfile.TemporaryDirectory(prefix="analint-release-") as directory:
        work = Path(directory)
        with tarfile.open(source) as archive:
            archive.extractall(work / "source", filter="data")
        root = work / "source" / root_name
        venv = work / "venv"
        run(["uv", "venv", "--python", args.python, str(venv)], work, env)
        python = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        run(["uv", "pip", "install", "--python", python, str(wheel)], work, env)
        probe = str(project / "scripts" / "release_smoke.py")
        command = [python, "-I", probe, "--source-root", str(root), "--expected-version", expected]
        run(command, work, env)
        run(["uv", "pip", "install", "--python", python, f"{wheel}[mcp]"], work, env)
        run([*command, "--mcp"], work, env)
        # Only add test tools after the runtime-only and optional-MCP checks.
        run(["uv", "pip", "install", "--python", python, "pytest", "click", "twine"], work, env)
        run([python, "-I", "-m", "twine", "check", "--strict", str(wheel), str(source)], work, env)
        run([python, "-I", "-m", "pytest", "--collect-only", "-qq"], root, env)
        run([python, "-I", "-m", "pytest", "-q", *ARCHIVE_TESTS], root, env)
    print(
        json.dumps(
            {
                "version": expected,
                "interpreter": args.python,
                "verified": ["CLI", "cache", "MCP stdio", "metadata", "source tests"],
                "artifacts": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, source)
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
