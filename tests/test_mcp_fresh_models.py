"""A persistent server must inspect the source currently on disk."""

import asyncio
import json
import os
import py_compile
import sys
from subprocess import CompletedProcess

import pytest

from analint.mcp_server import check_spec
from analint.mcp_worker import isolated_request

SOURCE = """from analint import Action, AlwaysHolds, Entity, Scenario, Spec
class Item(Entity):
    value: int = 0
action = Action(pre=[Item.value == LIMIT])
scenario = Scenario(name="zero", action=action, given=[Item()])
query = AlwaysHolds(Item.value == LIMIT, id="query")
spec = Spec(id="s", name="S", actions=[action], scenarios=[scenario], queries=[query])
"""


def test_worker_failure_preserves_exception_summary():
    @isolated_request
    def unsupported() -> dict:
        return {}

    with pytest.raises(RuntimeError, match="ValueError: unknown model operation: unsupported"):
        unsupported()


@pytest.mark.parametrize("stderr", ["", "large output\n" * 1000 + "X" * 3000 + "\nerror summary"])
def test_worker_failure_diagnostics_are_bounded(monkeypatch, stderr):
    monkeypatch.setattr(
        "analint.mcp_worker.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 7, stdout="", stderr=stderr),
    )
    with pytest.raises(RuntimeError) as caught:
        check_spec("unused")
    message = str(caught.value)
    assert "check_spec worker exited with code 7" in message
    assert len(message) < 2100
    assert message.endswith("error summary" if stderr else "(no stderr)")


def write_same_stat(path, text):
    stat = path.stat()
    assert len(text.encode()) == stat.st_size
    path.write_text(text)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_helper_observes_same_size_same_timestamp_edit(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(SOURCE.replace("LIMIT", "0"))
    py_compile.compile(str(entry), doraise=True)
    assert check_spec(str(entry))["verdict"] == "PASS"
    write_same_stat(entry, SOURCE.replace("LIMIT", "1"))
    assert check_spec(str(entry))["verdict"] == "FAIL"
    write_same_stat(entry, SOURCE.replace("LIMIT", "0"))
    assert check_spec(str(entry))["verdict"] == "PASS"


@pytest.mark.parametrize("packaged", [False, True])
def test_long_lived_stdio_session_observes_edits(tmp_path, packaged):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    directory = tmp_path / "model"
    directory.mkdir()
    entry = directory / "spec.py"
    if packaged:
        (directory / "__init__.py").write_text("")
        source = directory / "rules.py"
        entry.write_text("from .rules import action, query, scenario, spec\n")
    else:
        source = entry
    source.write_text(SOURCE.replace("LIMIT", "0"))
    py_compile.compile(str(source), doraise=True)
    patch = tmp_path / "patch.py"
    patch.write_text("raise ValueError('broken hypothesis')\n")

    async def exercise():
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "analint.mcp_server"],
            env={**os.environ},
        )
        async with (
            asyncio.timeout(60),
            stdio_client(server) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            async def call(tool_name, **kwargs):
                response = await session.call_tool(tool_name, {"path": str(entry), **kwargs})
                assert not response.isError, response
                return json.loads(response.content[0].text)

            assert (await call("check"))["verdict"] == "PASS"
            before = await call("show", kind="action", name="action")
            write_same_stat(source, SOURCE.replace("LIMIT", "1"))
            assert (await call("check"))["verdict"] == "FAIL"
            assert await call("show", kind="action", name="action") != before
            assert (await call("affects", target="Item.value"))["schema"] == "analint.affects/v1"
            assert (await call("explore"))["schema"] == "analint.exploration/v1"
            assert (await call("trace", query="query"))["status"] == "FAIL"
            failed = await call("check", what_if=str(patch))
            assert failed["verdict"] == "FAIL"
            assert "broken hypothesis" in failed["load_errors"][0]
            write_same_stat(source, SOURCE.replace("LIMIT", "0"))
            assert (await call("check"))["verdict"] == "PASS"
            assert (await call("trace", query="query"))["status"] == "PASS"
            patch.write_text(
                "from analint import AlwaysHolds\nfrom analint_spec import Item\n"
                if not packaged
                else "from analint import AlwaysHolds\nfrom model.rules import Item\n"
            )
            with patch.open("a") as stream:
                stream.write("hypothesis = AlwaysHolds(Item.value == 1)\n")
            assert (await call("check", what_if=str(patch)))["verdict"] == "FAIL"
            assert (await call("check"))["verdict"] == "PASS"

    asyncio.run(exercise())
