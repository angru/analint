"""Property slicing must never change what the monolithic exploration decides
(research/34 §5). The conformance gate compares both paths on every example;
the planted-defect probes each hide a violation behind one closure rule, so a
slice that drops the rule turns a red check green."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Absent,
    Action,
    Add,
    Bound,
    Count,
    Create,
    Entity,
    Field,
    Initial,
    Invariant,
    Lifecycle,
    NoDeadEnd,
    Not,
    Reachable,
    Scope,
    Set,
    Spec,
    Unreachable,
)
from analint.reporter.base import ValidationResult
from analint.validator.engine import validate
from analint.validator.explorer import build_canonical_initials, run_query, verify_invariants
from analint.validator.slicing import SliceAnalysis

EXAMPLES = Path(__file__).parent.parent / "examples"
EXAMPLE_DIRS = sorted(p.name for p in EXAMPLES.iterdir() if (p / "spec.py").exists())


def _shape(result: ValidationResult) -> dict:
    return {
        "verdict": str(result.verdict),
        "invariants": {
            r.invariant_id: (str(r.status), None if r.trace is None else len(r.trace))
            for r in result.invariant_results
        },
        "queries": {
            r.query_id: (str(r.status), None if r.trace is None else len(r.trace))
            for r in result.query_results
        },
        "exploration_findings": sorted(
            {(f.severity.value, f.location) for f in result.exploration_findings}
        ),
    }


@pytest.mark.parametrize("name", EXAMPLE_DIRS)
def test_sliced_check_agrees_with_the_whole_model(name):
    # Witness traces may differ in content (another equally short witness),
    # never in length: BFS is shortest on both, and dropping the stutters of
    # out-of-slice actions never lengthens a path.
    whole = _shape(validate(EXAMPLES / name, sliced=False))
    sliced = _shape(validate(EXAMPLES / name))
    assert sliced == whole


# ── planted defects: each closure rule guards one false green ─────────────────


class _S(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def _sliced_vs_whole(spec: Spec, *, query=None) -> tuple[str, str]:
    initials, error = build_canonical_initials(spec)
    assert initials is not None, error
    if query is not None:
        whole = run_query(query, spec, {})
        sliced = run_query(query, spec, {}, analysis=SliceAnalysis(spec))
        return str(whole.status), str(sliced.status)
    (whole,), _ = verify_invariants(spec, initials, max_states=1000)
    (sliced,), _ = verify_invariants(
        spec, initials, max_states=1000, cache={}, analysis=SliceAnalysis(spec)
    )
    return str(whole.status), str(sliced.status)


def test_effect_right_hand_side_pulls_its_writer_in():
    class A(Entity):
        x: int = Field(0, ge=0, le=9)

    class B(Entity):
        y: int = Field(0, ge=0, le=9)

    copy_y = Action(id="copy_y", effect=[Set(A.x, B.y)])
    raise_y = Action(id="raise_y", effect=[Set(B.y, 5)])
    spec = Spec(
        id="s",
        name="s",
        entities=[A, B],
        actions=[copy_y, raise_y],
        invariants=[Invariant(A.x < 5, id="x_small")],
    )
    assert _sliced_vs_whole(spec) == ("FAIL", "FAIL")


def test_guard_read_pulls_its_writer_in():
    class A(Entity):
        x: int = Field(0, ge=0, le=9)

    class B(Entity):
        armed: bool = False

    fire = Action(id="fire", pre=[B.armed], effect=[Set(A.x, 1)])
    arm = Action(id="arm", effect=[Set(B.armed, True)])
    spec = Spec(
        id="s",
        name="s",
        entities=[A, B],
        actions=[fire, arm],
        invariants=[Invariant(A.x == 0, id="never_fired")],
    )
    assert _sliced_vs_whole(spec) == ("FAIL", "FAIL")


def test_postcondition_read_pulls_its_writer_in():
    class A(Entity):
        x: int = Field(0, ge=0, le=9)

    class B(Entity):
        ok: bool = False

    # post holds only once B.ok was set elsewhere; with B.ok frozen at False,
    # bump would be a defect forever and x could never grow
    bump = Action(id="bump", pre=[A.x < 1], effect=[Add(A.x, 1)], post=[B.ok])
    allow = Action(id="allow", effect=[Set(B.ok, True)])
    spec = Spec(
        id="s",
        name="s",
        entities=[A, B],
        actions=[bump, allow],
        invariants=[Invariant(A.x == 0, id="x_zero")],
    )
    assert _sliced_vs_whole(spec) == ("FAIL", "FAIL")


def test_aggregate_over_created_slots_pulls_create_in():
    class Seat(Entity):
        taken: bool = False

    seats = Scope(Seat, keys=["a", "b"])
    s = Bound("s", seats)
    spec = Spec(
        id="s",
        name="s",
        entities=[Seat],
        scopes=[seats],
        actions=[
            Action(id="create_a", effect=[Create(seats["a"])]),
            Action(id="create_b", effect=[Create(seats["b"])]),
        ],
    )
    query = Unreachable(
        Count(s, Not(s.taken)) == 2,
        id="never_two_free",
        given=[Absent(seats["a"]), Absent(seats["b"])],
    )
    assert _sliced_vs_whole(spec, query=query) == ("FAIL", "FAIL")


def test_mixed_invariant_prunes_like_the_whole_model():
    class A(Entity):
        x: int = Field(0, ge=0, le=3)

    class B(Entity):
        y: int = Field(0, ge=0, le=3)

    inc_x = Action(id="inc_x", pre=[A.x < 3], effect=[Add(A.x, 1)])
    inc_y = Action(id="inc_y", pre=[B.y < 3], effect=[Add(B.y, 1)])
    # J prunes states where x outruns y; reaching x == 3 needs y to lead
    spec = Spec(
        id="s",
        name="s",
        entities=[A, B],
        actions=[inc_x, inc_y],
        invariants=[Invariant(A.x <= B.y, id="j")],
    )
    query = NoDeadEnd(A.x == 3, id="x_can_reach_3")
    whole, sliced = _sliced_vs_whole(spec, query=query)
    assert whole == sliced


def test_root_illegal_outside_the_slice_is_not_expanded():
    class Flag(Entity):
        start: bool = False
        on: bool = False

    class Other(Entity):
        bad: bool = False

    switch_on = Action(id="switch_on", pre=[Flag.start], effect=[Set(Flag.on, True)])
    # two roots: (start=F, bad=F) is legal; (start=T, bad=T) breaks `other_ok`,
    # an invariant outside Flag.on's slice — the whole model never expands it
    roots = Initial(vary=[Flag.start, Other.bad], where=[Flag.start == Other.bad])
    spec = Spec(
        id="s",
        name="s",
        entities=[Flag, Other],
        actions=[switch_on],
        invariants=[Invariant(Not(Other.bad), id="other_ok")],
        initial=roots,
    )
    query = Reachable(Flag.on, id="can_switch_on")
    assert _sliced_vs_whole(spec, query=query) == ("FAIL", "FAIL")


def test_independent_lifecycle_is_checked_on_its_own_slice():
    class Door(Entity):
        status: _S = Lifecycle(_S.OPEN, transitions={_S.OPEN: [_S.CLOSED]}, terminal=[_S.CLOSED])

    class Lamp(Entity):
        status: _S = Lifecycle(_S.OPEN, transitions={_S.OPEN: [_S.CLOSED]}, terminal=[_S.CLOSED])

    close_door = Action(id="close_door", effect=[Set(Door.status, _S.CLOSED)])
    close_lamp = Action(id="close_lamp", effect=[Set(Lamp.status, _S.CLOSED)])
    spec = Spec(
        id="s",
        name="s",
        entities=[Door, Lamp],
        actions=[close_door, close_lamp],
        invariants=[Invariant(Door.status != _S.CLOSED, id="door_open")],
    )
    initials, _ = build_canonical_initials(spec)
    (result,), _ = verify_invariants(
        spec, initials, max_states=100, cache={}, analysis=SliceAnalysis(spec)
    )
    assert str(result.status) == "FAIL"
    assert result.slice is not None
    assert result.slice["actions"] == 1  # close_lamp is not in the door's slice
    assert result.states_explored == 2


def test_out_of_slice_violation_is_reported_by_its_own_invariant():
    # The documented divergence (slicing module docstring): the whole model
    # counts a state that breaks an unrelated invariant as a NoDeadEnd dead end;
    # the slice does not. The violation itself still fails the run.
    class A(Entity):
        x: int = Field(0, ge=0, le=2)

    class B(Entity):
        broken: bool = False

    inc = Action(id="inc", pre=[A.x < 2], effect=[Add(A.x, 1)])
    break_b = Action(id="break_b", effect=[Set(B.broken, True)])
    spec = Spec(
        id="s",
        name="s",
        entities=[A, B],
        actions=[inc, break_b],
        invariants=[Invariant(Not(B.broken), id="b_intact")],
    )
    query = NoDeadEnd(A.x == 2, id="x_reaches_2")
    assert _sliced_vs_whole(spec, query=query) == ("FAIL", "PASS")
    assert _sliced_vs_whole(spec) == ("FAIL", "FAIL")  # b_intact fails either way


def test_cli_reports_the_slice_and_no_slice_restores_the_whole_model():
    import json

    from typer.testing import CliRunner

    from analint.cli import app

    runner = CliRunner()
    path = str(EXAMPLES / "fulfillment")
    sliced = json.loads(runner.invoke(app, ["check", path, "-f", "json"]).output)
    whole = json.loads(runner.invoke(app, ["check", path, "-f", "json", "--no-slice"]).output)

    assert all("slice" in q for q in sliced["queries"])
    assert all("slice" not in q for q in whole["queries"])
    assert [q["status"] for q in sliced["queries"]] == [q["status"] for q in whole["queries"]]


def test_queries_with_different_roots_never_share_a_slice_exploration():
    # Roots are cached by id(); a per-query root list freed after its query
    # must not let a later query's list (same id) reuse its exploration.
    class Lamp(Entity):
        armed: bool = False
        on: bool = False

    switch_on = Action(id="switch_on", pre=[Lamp.armed], effect=[Set(Lamp.on, True)])
    spec = Spec(id="s", name="s", entities=[Lamp], actions=[switch_on])
    analysis = SliceAnalysis(spec)
    cache: dict = {}
    disarmed = Unreachable(Lamp.on, id="disarmed", given=[Lamp(armed=False)])
    armed = Unreachable(Lamp.on, id="armed", given=[Lamp(armed=True)])
    for _ in range(50):  # give the allocator every chance to reuse ids
        assert str(run_query(disarmed, spec, cache, analysis=analysis).status) == "PASS"
        assert str(run_query(armed, spec, cache, analysis=analysis).status) == "FAIL"


class _Life(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def _closable_counter() -> Spec:
    class Ticket(Entity):
        status: _Life = Lifecycle(
            _Life.OPEN, transitions={_Life.OPEN: [_Life.CLOSED]}, terminal=[_Life.CLOSED]
        )
        x: int = Field(0, ge=0, le=2)

    inc = Action(id="inc", pre=[Ticket.x < 2], effect=[Add(Ticket.x, 1)])
    close = Action(id="close", effect=[Set(Ticket.status, _Life.CLOSED)])
    return Spec(
        id="s",
        name="s",
        entities=[Ticket],
        actions=[inc, close],
        invariants=[Invariant(Ticket.x <= 2, id="x_bounded")],
    )


def test_terminal_lock_dead_ends_are_seen_by_no_dead_end():
    # Closing freezes the ticket: x < 2 then has no way to reach 2.
    spec = _closable_counter()
    ticket = spec.entities[0]
    assert _sliced_vs_whole(spec, query=NoDeadEnd(ticket.x == 2, id="x_reaches_2")) == (
        "FAIL",
        "FAIL",
    )


def test_terminal_lock_alone_does_not_pull_the_closer_into_a_slice():
    # A lock only disables, so for reachability the closer is irrelevant.
    spec = _closable_counter()
    ticket = spec.entities[0]
    assert _sliced_vs_whole(spec, query=Reachable(ticket.x == 2, id="x_can_reach_2")) == (
        "PASS",
        "PASS",
    )
    assert _sliced_vs_whole(spec) == ("PASS", "PASS")
    piece = SliceAnalysis(spec).invariant_slice(spec.invariants[0])
    assert [a.id for a in piece.actions] == ["inc"]


# ── invariant trust (SliceAnalysis docstring) ─────────────────────────────────

_TRUST_SPEC = """
from analint import Action, Add, Entity, Field, Implies, Invariant, Reachable, Spec


class A(Entity):
    x: int = Field(0, ge=0, le=3)


class B(Entity):
    y: int = Field(0, ge=0, le=3)


inc_x = Action(id="inc_x", pre=[A.x < 3], effect=[Add(A.x, 1)])
inc_y = Action(id="inc_y", pre=[B.y < 3], effect=[Add(B.y, 1)])
spec = Spec(
    id="trust",
    name="trust",
    entities=[A, B],
    actions=[inc_x, inc_y],
    invariants=[Invariant({invariant}, id="j")],
    queries=[Reachable(A.x == 3, id="x_reaches_3")],
)
"""


def _run_both(tmp_path, invariant: str):
    entry = tmp_path / "spec.py"
    entry.write_text(_TRUST_SPEC.format(invariant=invariant))
    return validate(entry), validate(entry, sliced=False)


def test_a_failing_invariant_keeps_constraining_the_slices(tmp_path):
    # j prunes at x == 2, so x == 3 is unreachable in the whole model; an
    # unconstrained slice would walk past the violation and call it reachable.
    sliced, whole = _run_both(tmp_path, "A.x <= 1")
    assert [q.status for q in whole.query_results] == ["FAIL"]
    assert _shape(sliced) == _shape(whole)


def test_a_proven_mixed_invariant_does_not_glue_independent_processes(tmp_path):
    # j mentions A and B but always holds: once proven it prunes nothing, so
    # the query's slice stays with A's action alone.
    sliced, whole = _run_both(tmp_path, "Implies(A.x == 3, B.y >= 0)")
    assert _shape(sliced) == _shape(whole)
    assert sliced.query_results[0].slice["actions"] == 1
