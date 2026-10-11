"""The TLC backend (research/36 R6) must mirror the analint transition system
exactly: identical distinct-state counts on every exportable example, the same
verdicts on planted properties, and an explicit refusal where TLA+ cannot
follow analint. Skipped where Java or a TLC jar is missing (e.g. CI)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Absent,
    Action,
    Add,
    And,
    Create,
    Entity,
    Field,
    Implies,
    Initial,
    Invariant,
    Lifecycle,
    Not,
    Present,
    Scope,
    Set,
    Spec,
)
from analint.backends.tla import ExportError, Target, export_tla
from analint.backends.tlc import TlcUnavailable, find_tlc, run_tlc
from analint.validator.engine import prepare_model, validate
from analint.validator.explorer import build_canonical_initials, explore
from analint.validator.slicing import SliceAnalysis

try:
    find_tlc()
except TlcUnavailable as exc:  # pragma: no cover - depends on the machine
    pytest.skip(f"TLC unavailable: {exc}", allow_module_level=True)

ROOT = Path(__file__).parent.parent
EXAMPLES = sorted(p.name for p in (ROOT / "examples").iterdir() if (p / "spec.py").exists())
# sliced models: inert roots, frozen fields and switched-off flags
SLICED = [ROOT / "examples" / name for name in EXAMPLES] + [
    ROOT / "benchmarks" / "broker" / f"{name}.py"
    for name in ("m5_partners", "m5_profile_partners", "m6_methods")
]


@pytest.mark.parametrize("name", EXAMPLES)
def test_whole_model_state_counts_match(name):
    spec = prepare_model(ROOT / "examples" / name).spec
    initials, _ = build_canonical_initials(spec)
    if initials is None:
        pytest.skip("no canonical initial state")
    try:
        export = export_tla(spec, initials, target=Target("always", True))
    except ExportError as exc:
        pytest.skip(f"not exportable: {exc}")
    exp = explore(spec, initials, 100_000)
    assert not exp.capped
    outcome = run_tlc(export)
    assert outcome.distinct_states == len(exp.states), outcome.output[-2000:]


@pytest.mark.parametrize("path", SLICED, ids=lambda p: p.stem if p.suffix else p.name)
def test_slice_exports_match_the_sliced_explorations(path):
    # --tlc exports the very slice analint explored: projected roots, frozen
    # fields and inert roots must give the same state count
    spec = prepare_model(path).spec
    initials, _ = build_canonical_initials(spec)
    if initials is None or not spec.invariants:
        pytest.skip("no canonical invariants")
    verdicts = {r.invariant_id: r.status for r in validate(path).invariant_results}
    analysis = SliceAnalysis(spec)
    pieces = {}
    for inv in spec.invariants:
        piece = analysis.invariant_slice(inv)
        if piece.vars is not None:
            pieces[piece.key] = (inv, piece)
    if not pieces:
        pytest.skip("nothing sliced")
    for inv, piece in pieces.values():
        roots, numbers, inert = analysis.project_roots(piece, initials)
        sliced = analysis.sliced_spec(piece)
        try:
            export = export_tla(sliced, roots, target=Target("holds", inv.expression), inert=inert)
        except ExportError as exc:
            pytest.skip(f"not exportable: {exc}")
        exp = explore(sliced, roots, 100_000, root_numbers=numbers, inert_roots=inert)
        assert not exp.capped
        outcome = run_tlc(export)
        assert outcome.distinct_states == len(exp.states), (inv.id, outcome.output[-2000:])
        if outcome.status == "ok":
            assert verdicts[inv.id] in {"PASS", "NOT_CHECKED"}, inv.id
        elif outcome.violated == "Target":
            assert verdicts[inv.id] == "FAIL", inv.id


class _Door(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class _Box(Entity):
    n: int = Field(0, ge=0, le=3)
    door: _Door = Lifecycle(
        _Door.OPEN, transitions={_Door.OPEN: [_Door.CLOSED]}, terminal=[_Door.CLOSED]
    )


_BOX = Spec(
    id="box",
    name="box",
    entities=[_Box],
    actions=[
        Action(id="bump", pre=[_Box.n < 3], effect=[Add(_Box.n, 1)]),
        Action(id="close", pre=[_Box.n == 0], effect=[Set(_Box.door, _Door.CLOSED)]),
    ],
)


def _tlc(spec: Spec, target: Target):
    initials, _ = build_canonical_initials(spec)
    return run_tlc(export_tla(spec, initials, target=target))


def test_invariant_violation_comes_with_a_shortest_trace():
    outcome = _tlc(_BOX, Target("holds", _Box.n <= 1))
    assert (outcome.status, outcome.violated) == ("violation", "Target")
    assert outcome.trace == ["bump", "bump"]


def test_terminal_lock_freezes_the_entity():
    # a closed box can no longer be bumped: closed states keep n == 0
    outcome = _tlc(_BOX, Target("never", And(_Box.n == 1, _Box.door == _Door.CLOSED)))
    assert (outcome.status, outcome.distinct_states) == ("ok", 5)


def test_a_hard_field_bound_is_a_reported_defect():
    class Meter(Entity):
        n: int = Field(0, ge=0, le=1)

    spec = Spec(
        id="m", name="m", entities=[Meter], actions=[Action(id="bump", effect=[Add(Meter.n, 1)])]
    )
    outcome = _tlc(spec, Target("always", True))
    assert outcome.status == "violation"
    assert outcome.violated.startswith("NoDefect_")
    assert outcome.trace == ["bump"]  # the state from which the next bump breaks le=1


def test_presence_guards_creation_and_modification():
    class Seat(Entity):
        taken: bool = False

    class Tally(Entity):
        made: int = Field(0, ge=0, le=5)

    seats = Scope(Seat, keys=["a"])
    a = seats["a"]
    spec = Spec(
        id="s",
        name="s",
        entities=[Seat, Tally],
        scopes=[seats],
        actions=[
            # an absent slot can't be marked; a present one can't be made again
            Action(id="make", effect=[Create(a), Add(Tally.made, 1)]),
            Action(id="mark", effect=[Set(a.taken, True)]),
        ],
    )
    initials = [{a: Absent(a), Tally: Tally()}]
    outcome = run_tlc(export_tla(spec, initials, target=Target("always", True)))
    assert outcome.distinct_states == len(explore(spec, initials, 100).states) == 3


def test_a_root_illegal_outside_the_slice_stays_inert():
    class Flag(Entity):
        start: bool = False
        on: bool = False

    class Other(Entity):
        bad: bool = False

    # (start=T, bad=T) breaks other_ok, outside never_on's unconstrained
    # slice: the whole model never expands it, so the slice must not either
    never_on = Invariant(Not(Flag.on), id="never_on")
    spec = Spec(
        id="s",
        name="s",
        entities=[Flag, Other],
        actions=[Action(id="switch_on", pre=[Flag.start], effect=[Set(Flag.on, True)])],
        invariants=[Invariant(Not(Other.bad), id="other_ok"), never_on],
        initial=Initial(vary=[Flag.start, Other.bad], where=[Flag.start == Other.bad]),
    )
    initials, _ = build_canonical_initials(spec)
    analysis = SliceAnalysis(spec)
    piece = analysis.invariant_slice(never_on, unconstrained=True)
    roots, _, inert = analysis.project_roots(piece, initials)
    assert inert
    sliced = analysis.sliced_spec(piece)
    outcome = run_tlc(
        export_tla(sliced, roots, target=Target("holds", never_on.expression), inert=inert)
    )
    assert outcome.status == "ok"


def test_reading_a_slot_that_may_be_absent_is_refused():
    class Seat(Entity):
        taken: bool = False

    seats = Scope(Seat, keys=["a"])
    a = seats["a"]
    spec = Spec(
        id="s",
        name="s",
        entities=[Seat],
        scopes=[seats],
        actions=[
            Action(id="make", effect=[Create(a)]),
            Action(id="take", pre=[Present(a), a.taken == False], effect=[Set(a.taken, True)]),  # noqa: E712
        ],
    )
    initials = [{a: Absent(a)}]
    export_tla(spec, initials, target=Target("always", True))  # guarded reads export
    # a Present conjunct / antecedent guards the read, as analint short-circuits
    export_tla(spec, initials, target=Target("never", And(Present(a), a.taken == True)))  # noqa: E712
    export_tla(spec, initials, target=Target("always", Implies(Present(a), a.taken == False)))  # noqa: E712
    with pytest.raises(ExportError, match="absent"):
        export_tla(spec, initials, target=Target("never", And(a.taken == True, Present(a))))  # noqa: E712
    with pytest.raises(ExportError, match="absent"):
        export_tla(spec, initials, target=Target("never", a.taken == True))  # noqa: E712


def test_check_tlc_decides_what_the_budget_left_open(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Add, Entity, Field, Invariant, Reachable, Spec, Unreachable\n"
        "class Gauge(Entity):\n"
        "    n: int = Field(0, ge=0, le=30)\n"
        "tick = Action(pre=[Gauge.n < 30], effect=[Add(Gauge.n, 1)])\n"
        "bounded = Invariant(Gauge.n <= 30)\n"
        "below_25 = Invariant(Gauge.n < 25)\n"
        "never_31 = Unreachable(Gauge.n == 31)\n"
        "never_20 = Unreachable(Gauge.n == 20)\n"
        "reaches_30 = Reachable(Gauge.n == 30)\n"
        "reaches_31 = Reachable(Gauge.n == 31)\n"
        "spec = Spec(id='g', name='g', actions=[tick], invariants=[bounded, below_25],\n"
        "            queries=[never_31, never_20, reaches_30, reaches_31])\n"
    )
    # below_25 prunes at n == 25 (illegal states are not expanded): 30 is out of reach
    capped = validate(entry, max_states=5)
    assert {r.status for r in capped.invariant_results + capped.query_results} == {"INCONCLUSIVE"}
    decided = validate(entry, max_states=5, tlc=True)
    full = validate(entry, max_states=1000)

    def outcomes(result):
        out = {r.invariant_id: (r.status, r.trace) for r in result.invariant_results}
        return out | {r.query_id: (r.status, r.trace) for r in result.query_results}

    assert outcomes(decided) == outcomes(full)
    assert {k: s for k, (s, _) in outcomes(decided).items()} == {
        "bounded": "PASS",
        "below_25": "FAIL",
        "never_31": "PASS",
        "never_20": "FAIL",
        "reaches_30": "FAIL",
        "reaches_31": "FAIL",
    }
    assert {r.backend for r in decided.invariant_results + decided.query_results} == {"tlc"}
    assert outcomes(decided)["never_20"][1] == ["tick"] * 20
    assert decided.verdict == "FAIL"


@pytest.mark.parametrize(("open_at", "status"), [(30, "PASS"), (31, "NOT_CHECKED")])
def test_check_tlc_tells_a_never_applicable_invariant(tmp_path, open_at, status):
    # the seat exists only after n reaches open_at (31 is out of range: never)
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Absent, Action, Add, Create, Entity, Field, Initial, Invariant\n"
        "from analint import Scope, Spec\n"
        "class Gauge(Entity):\n"
        "    n: int = Field(0, ge=0, le=30)\n"
        "class Seat(Entity):\n"
        "    taken: bool = False\n"
        "seats = Scope(Seat, keys=['a'])\n"
        "a = seats['a']\n"
        "tick = Action(pre=[Gauge.n < 30], effect=[Add(Gauge.n, 1)])\n"
        f"make = Action(pre=[Gauge.n == {open_at}], effect=[Create(a)])\n"
        "seat_free = Invariant(a.taken == False)\n"
        "spec = Spec(id='g', name='g', actions=[tick, make], invariants=[seat_free],\n"
        "            initial=Initial(vary=[Gauge.n], where=[Gauge.n == 0], given=[Absent(a)]))\n"
    )
    assert [r.status for r in validate(entry, max_states=5).invariant_results] == ["INCONCLUSIVE"]
    decided = validate(entry, max_states=5, tlc=True)
    full = validate(entry, max_states=1000)
    assert [(r.status, r.backend) for r in decided.invariant_results] == [(status, "tlc")]
    assert [r.status for r in full.invariant_results] == [status]
