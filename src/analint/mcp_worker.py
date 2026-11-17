"""One fresh model-loading process per MCP request.

The server stays alive, but Python module identities and exploration state live
only for one request. Within that request normal imports preserve shared class
identity. The CLI and in-process library keep their existing loading contract.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

_OPERATIONS = {"check_spec", "explore_spec", "trace_spec", "show_spec", "affects_target"}


class _Operation[**P](Protocol):
    __name__: str

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> dict: ...


def isolated_request[**P](function: _Operation[P]) -> Callable[P, dict]:
    operation = function.__name__

    @wraps(function)
    def call(*args: P.args, **kwargs: P.kwargs) -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "analint.mcp_worker"],
            input=json.dumps({"operation": operation, "args": args, "kwargs": kwargs}),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    return call


def main() -> None:
    from analint import mcp_server

    request = json.load(sys.stdin)
    operation = request["operation"]
    if operation not in _OPERATIONS:
        raise ValueError(f"unknown model operation: {operation}")
    function = getattr(mcp_server, operation).__wrapped__
    # Dependencies are loaded above through their ordinary caches. Model imports
    # must read source even after same-size edits within a filesystem timestamp
    # interval. Use an empty private cache namespace, without deleting users'
    # bytecode or writing new cache files.
    with TemporaryDirectory(prefix="analint-import-") as directory:
        sys.pycache_prefix = str(Path(directory) / "bytecode")
        sys.dont_write_bytecode = True
        with contextlib.redirect_stdout(sys.stderr):
            result = function(*request["args"], **request["kwargs"])
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
