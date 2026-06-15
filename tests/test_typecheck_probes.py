"""Preserve the DSL's authoring diagnostics as a regression signal (P4.0a).

research/27 documents the DSL's dual view: instance access is honestly typed, but
class-level comparisons build a ``Predicate`` the checker reads as ``bool``
(metaclass opacity), and lifecycle declarations read as their value type. These
are ACCEPTED, documented boundaries — not bugs to silence. This test runs ``ty``
on ``typecheck_probes/authoring_forms.py`` and asserts those diagnostics still
appear, so if the DSL's type surface changes (a fix, or an accidental regression)
the change is caught and research/27 must be revisited.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROBE = Path(__file__).parent / "typecheck_probes" / "authoring_forms.py"


def _ty_categories() -> list[str]:
    ty = shutil.which("ty")
    if ty is None:
        pytest.skip("ty is not on PATH")
    proc = subprocess.run(
        [ty, "check", str(PROBE)],
        capture_output=True,
        text=True,
    )
    return re.findall(r"error\[([a-z-]+)\]", proc.stdout + proc.stderr)


def test_probe_reproduces_the_documented_dsl_diagnostics():
    categories = _ty_categories()
    assert categories, (
        "the authoring probe produced no ty diagnostics — the DSL's documented "
        "dual-view boundary may have changed; revisit research/27"
    )
    # Metaclass opacity: class-level comparisons read as bool where Predicate is
    # expected — the dominant, accepted authoring diagnostic.
    assert "invalid-argument-type" in categories, (
        "expected the class-level 'Predicate vs bool' diagnostic (research/27 §2)"
    )
    # Lifecycle declaration opacity: `Lifecycle[T]` reads as `T`.
    assert "invalid-assignment" in categories, (
        "expected the lifecycle-declaration diagnostic (research/27 §2)"
    )
