"""The generated scaling families produce their closed-form state counts (P4.4).

This is a correctness test for the benchmark generators (not a timing gate): if a
family's reachable-state count drifts from its formula, the scaling
characterization is measuring the wrong thing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from analint.validator.explorer import build_canonical_initials, explore

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from scaling_models import conserved_transfer, counter_grid, workflow_product


def _reachable(spec, budget: int) -> int:
    initials, error = build_canonical_initials(spec)
    assert initials is not None, error
    return len(explore(spec, initials, budget).states)


@pytest.mark.parametrize(
    "builder, args",
    [
        (counter_grid, (2, 9)),
        (counter_grid, (3, 4)),
        (conserved_transfer, (3, 5)),
        (conserved_transfer, (4, 4)),
        (workflow_product, (2,)),
        (workflow_product, (4,)),
    ],
)
def test_family_matches_its_closed_form(builder, args):
    spec, expected = builder(*args)
    assert _reachable(spec, expected + 10) == expected
