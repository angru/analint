"""Run TLC on an exported module and read its verdict (research/36 R6).

TLC ships in ``tla2tools.jar`` and inside Apalache's jar (which Quint
downloads). The jar is ``$ANALINT_TLC_JAR`` or, failing that, the newest
Quint-managed Apalache jar; Java is ``$JAVA_HOME/bin/java``, ``java`` on PATH,
or a Homebrew OpenJDK.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from analint.backends.tla import TlaExport


class TlcUnavailable(Exception):
    """No Java or no TLC jar on this machine."""


@dataclass
class TlcResult:
    status: str  # "ok" | "violation" | "error"
    violated: str | None = None  # the violated invariant's name
    trace: list[str] = field(default_factory=list)  # action ids from the root
    distinct_states: int | None = None
    seconds: float = 0.0
    output: str = ""


def _java() -> str | None:
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(str(Path(os.environ["JAVA_HOME"]) / "bin" / "java"))
    if shutil.which("java"):
        candidates.append(shutil.which("java") or "")
    candidates += sorted(glob.glob("/opt/homebrew/opt/openjdk*/bin/java"), reverse=True)
    candidates += sorted(glob.glob("/usr/lib/jvm/*/bin/java"), reverse=True)
    for java in candidates:
        try:
            done = subprocess.run([java, "-version"], capture_output=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            return java
    return None


def _jar() -> str | None:
    explicit = os.environ.get("ANALINT_TLC_JAR")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    found = sorted(
        glob.glob(
            str(Path.home() / ".quint" / "apalache-dist-*" / "apalache" / "lib" / "apalache.jar")
        )
    )
    return found[-1] if found else None


def find_tlc() -> tuple[str, str]:
    java, jar = _java(), _jar()
    if java is None:
        raise TlcUnavailable("no working Java found (set JAVA_HOME)")
    if jar is None:
        raise TlcUnavailable(
            "no TLC jar found: set ANALINT_TLC_JAR to tla2tools.jar (or install Quint, "
            "whose Apalache distribution bundles TLC)"
        )
    return java, jar


_STATE = re.compile(r"^State \d+: <(\w+)")
_VIOLATED = re.compile(r"Error: Invariant (\w+) is violated")
_DISTINCT = re.compile(r"([\d,]+) distinct states found")


def run_tlc(export: TlaExport, *, timeout: float | None = None) -> TlcResult:
    java, jar = find_tlc()
    with tempfile.TemporaryDirectory(prefix="analint-tlc-") as tmp:
        module = Path(tmp) / f"{export.module_name}.tla"
        config = Path(tmp) / f"{export.module_name}.cfg"
        module.write_text(export.module)
        config.write_text(export.config)
        command = [
            java,
            "-XX:+UseParallelGC",
            "-cp",
            jar,
            "tlc2.TLC",
            "-workers",
            "auto",
            "-metadir",
            str(Path(tmp) / "states"),
            "-config",
            config.name,
            module.name,
        ]
        started = time.perf_counter()
        try:
            done = subprocess.run(command, cwd=tmp, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return TlcResult("error", seconds=time.perf_counter() - started, output="timeout")
        seconds = time.perf_counter() - started
    output = done.stdout + done.stderr
    distinct = _DISTINCT.findall(output)
    result = TlcResult(
        "error",
        distinct_states=int(distinct[-1].replace(",", "")) if distinct else None,
        seconds=seconds,
        output=output,
    )
    violated = _VIOLATED.search(output)
    if violated:
        result.status = "violation"
        result.violated = violated.group(1)
        result.trace = [
            export.actions[m.group(1)]
            for line in output.splitlines()
            if (m := _STATE.match(line)) and m.group(1) in export.actions
        ]
    elif "Model checking completed. No error has been found." in output:
        result.status = "ok"
    return result
