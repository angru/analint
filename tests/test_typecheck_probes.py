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

PROBES = Path(__file__).parent / "typecheck_probes"
POSITIVE = PROBES / "authoring_forms.py"
NEGATIVE = PROBES / "negative_forms.py"


def _ty_categories(probe: Path) -> list[str]:
    ty = shutil.which("ty")
    if ty is None:
        pytest.skip("ty is not on PATH")
    proc = subprocess.run(
        [ty, "check", str(probe)],
        capture_output=True,
        text=True,
    )
    return re.findall(r"error\[([a-z-]+)\]", proc.stdout + proc.stderr)


def test_probe_reproduces_the_documented_dsl_diagnostics():
    categories = _ty_categories(POSITIVE)
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
    # Only the two documented dual-view categories should appear — anything else is
    # an unexplained diagnostic the audit must account for.
    assert set(categories) <= {"invalid-argument-type", "invalid-assignment"}, (
        f"unexpected diagnostic category in the authoring probe: {set(categories)}"
    )


def test_negative_probes_are_rejected():
    # The DSL constructors are honestly typed, so clearly-wrong authoring (a bare
    # value where a Predicate is required) is still caught despite metaclass opacity.
    categories = _ty_categories(NEGATIVE)
    assert categories.count("invalid-argument-type") >= 3, (
        "negative probes should be rejected for passing non-Predicate arguments "
        f"(research/27); got {categories}"
    )
