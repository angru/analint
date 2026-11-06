"""Installed-package probes used by check_release.py, without dev dependencies."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k != "elapsed_ms"}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def code_block(path: Path, title: str) -> str:
    blocks = re.findall(
        rf'^```python title="{re.escape(title)}"\n(.*?)^```$',
        path.read_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    require(len(blocks) == 1, f"expected one {title} block in {path}")
    return blocks[0]


def executable(name: str) -> str:
    return str(Path(sys.executable).with_name(name + (".exe" if os.name == "nt" else "")))


def cli(*args: str, exit_code: int = 0) -> dict:
    result = subprocess.run(
        [executable("analint"), *args], capture_output=True, text=True, timeout=60
    )
    require(result.returncode == exit_code, f"{args}: {result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def verdict(report: dict, expected: str) -> None:
    require(report["schema"] == "analint.check/v1", "unexpected check schema")
    require(report["verdict"] == expected, f"expected {expected}: {report}")
    require(report["passed"] is (expected == "PASS"), "verdict and passed disagree")


def check_cli(tutorial: Path, identity: Path, hypothesis: Path) -> None:
    fresh = cli("check", str(tutorial), "--strict", "-f", "json")
    verdict(fresh, "PASS")
    verdict(
        cli("check", str(tutorial), "--what-if", str(hypothesis), "-f", "json", exit_code=1),
        "FAIL",
    )
    verdict(
        cli("check", str(tutorial), "--max-states", "1", "-f", "json", exit_code=4), "INCONCLUSIVE"
    )
    cold = cli("check", str(tutorial), "--cache", "-f", "json")
    warm = cli("check", str(tutorial), "--cache", "-f", "json")
    require(semantic(fresh) == semantic(cold) == semantic(warm), "cache changed the report")
    require(
        bool(list(Path(os.environ["ANALINT_CACHE_DIR"]).rglob("*.json.z"))), "cache was not written"
    )
    require(
        semantic(cli("check", str(tutorial), "--strict", "-f", "json")) == semantic(fresh),
        "what-if changed the root",
    )
    impact = cli("affects", "Item.owner", "-p", str(identity))
    require({w["action"] for w in impact["written_by"]} == {"create"}, "Create writer missing")
    require("created" in impact["scenarios"], "Create scenario missing")
    trace = cli("trace", "query", "-p", str(identity), "-f", "json")
    require([s["action"] for s in trace["steps"]] == ["create"], "wrong scoped trace")
    print("CLI PASS/FAIL/INCONCLUSIVE, what-if, cache and Create impact: PASS", flush=True)


async def check_mcp(tutorial: Path, identity: Path, hypothesis: Path) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = StdioServerParameters(command=executable("analint-mcp"), cwd=Path.cwd())
    async with (
        asyncio.timeout(60),
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        require(
            {t.name for t in tools.tools} == {"check", "show", "affects", "explore", "trace"},
            "wrong MCP tool set",
        )

        async def call(name: str, arguments: dict) -> dict:
            result = await session.call_tool(name, arguments)
            require(not result.isError, f"MCP {name} failed: {result}")
            return json.loads(result.content[0].text)

        for extra, expected in [
            ({}, "PASS"),
            ({"what_if": str(hypothesis)}, "FAIL"),
            ({"max_states": 1}, "INCONCLUSIVE"),
        ]:
            verdict(await call("check", {"path": str(tutorial), **extra}), expected)
        overview = await call("show", {"path": str(identity)})
        require(overview == cli("show", "-p", str(identity)), "MCP/CLI overview differs")
        impact = await call("affects", {"path": str(identity), "target": "Item.owner"})
        require(
            impact == cli("affects", "Item.owner", "-p", str(identity)), "MCP/CLI impact differs"
        )
        graph = await call("explore", {"path": str(identity)})
        require(
            graph["summary"]["states"] == 2 and graph["graph"] is None, "wrong compact exploration"
        )
        trace = await call("trace", {"path": str(identity), "query": "query"})
        require([s["action"] for s in trace["steps"]] == ["create"], "wrong MCP trace")
    print("MCP stdio initialization, five tools and verdicts: PASS", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--mcp", action="store_true")
    args = parser.parse_args()
    import analint

    require(
        version("analint") == analint.__version__ == args.expected_version,
        "wrong installed version",
    )
    require(
        Path(analint.__file__).absolute().is_relative_to(Path(sys.prefix).absolute()),
        "analint was imported outside the clean environment",
    )
    result = subprocess.run(
        [executable("analint"), "--version"], check=True, capture_output=True, text=True
    )
    require(result.stdout.strip() == f"analint {args.expected_version}", "wrong CLI version")
    tutorial = Path.cwd() / "ticket_spec"
    tutorial.mkdir(exist_ok=True)
    (tutorial / "__init__.py").touch()
    guide = args.source_root / "docs" / "getting-started.md"
    (tutorial / "spec.py").write_text(code_block(guide, "spec.py"))
    hypothesis = Path.cwd() / "hypothesis.py"
    hypothesis.write_text(code_block(guide, "hypothesis.py"))
    identity = Path.cwd() / "identity"
    identity.mkdir(exist_ok=True)
    (identity / "spec.py").write_text(
        code_block(args.source_root / "docs" / "dsl.md", "scope-identity-spec.py")
    )
    os.environ["ANALINT_CACHE_DIR"] = str(Path.cwd() / "cache")
    if args.mcp:
        asyncio.run(check_mcp(tutorial, identity, hypothesis))
    else:
        check_cli(tutorial, identity, hypothesis)


if __name__ == "__main__":
    main()
