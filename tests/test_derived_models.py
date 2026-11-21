"""Differential and planted checks for projected safety proofs."""

from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Action,
    Add,
    And,
    Create,
    Entity,
    Event,
    Field,
    Implies,
    Initial,
    Invariant,
    Lifecycle,
    Not,
    Or,
    Present,
    Scope,
    Set,
    Spec,
    Unreachable,
)
from analint.reporter.json_reporter import result_to_dict
from analint.validator import derived_proof, explorer
from analint.validator.derived_model import derive
from analint.validator.engine import prepare_model, validate, validate_spec
from analint.validator.exploration_cache import use_store
from analint.validator.explorer import (
    build_canonical_initials,
    resolve_query_initials,
    verify_invariants,
)
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.slicing import SliceAnalysis
from analint.validator.state_checks import check_invariants

ROOT = Path(__file__).resolve().parents[1]


def _check(spec, target, *, budget=128):
    analysis = SliceAnalysis(spec)
    roots, error = build_canonical_initials(spec)
    assert roots is not None, error
    if isinstance(target, Invariant):
        exact = analysis.invariant_slice(target, unconstrained=True)
    else:
        exact = analysis.predicate_slice(target.predicate, canonical=True)
    attempt = derived_proof.attempt(target, analysis, exact, roots, budget)
    assert attempt is not None
    return attempt


def test_two_roots_do_not_share_a_hidden_postcondition_value():
    class Account(Entity):
        pro: bool = False
        balance: int = 0
        audit: bool = False

    limit = Invariant(Account.balance <= 10, id="limit")
    spec = Spec(
        id="accounts",
        name="accounts",
        initial=Initial(vary=[Account.pro]),
        actions=[
            Action(
                id="credit",
                pre=[Account.balance < 20],
                effect=[Add(Account.balance, 10), Set(Account.audit, True)],
                post=[Implies(Not(Account.pro), Account.balance <= 10)],
            )
        ],
        invariants=[limit],
    )
    probe = _check(spec, limit)
    assert probe.projection.fields == ["Account.balance", "Account.pro"]
    assert probe.replayed is not None
    witness, graph = probe.replayed
    assert graph.roots[graph.root_of(witness.witness_key)] == 2
    assert witness.trace == ["credit", "credit"]
    assert validate_spec(spec).invariant_results[0].trace == witness.trace


def test_hidden_writer_is_revisited_and_swap_reads_one_pre_state():
    class Pair(Entity):
        left: int = 0
        right: int = 1
        source: int = 0
        audit: bool = False

    unsafe = Unreachable(Pair.left == 2, id="unsafe")
    distinct = Invariant(Pair.left != Pair.right, id="distinct")
    swap = Action(
        id="swap",
        effect=[Set(Pair.left, Pair.right), Set(Pair.right, Pair.left), Set(Pair.audit, True)],
    )
    load = Action(id="load", effect=[Set(Pair.right, Pair.source)])
    source = Action(id="source", effect=[Set(Pair.source, 2)])
    probe = _check(
        Spec(id="pair", name="pair", actions=[swap, load, source], queries=[unsafe]), unsafe
    )
    assert probe.projection.fields == ["Pair.left", "Pair.right", "Pair.source"]
    assert probe.replayed is not None
    assert probe.replayed[0].trace == ["source", "load", "swap"]
    assert _check(
        Spec(id="swap", name="swap", actions=[swap], invariants=[distinct]), distinct
    ).proved


@pytest.mark.parametrize(
    "value, saturate, status", [(2, False, "PASS"), (2, "high", "FAIL"), (-1, "high", "PASS")]
)
def test_retained_bound_defects_or_clamps(value, saturate, status):
    class Counter(Entity):
        x: int = Field(0, ge=0, le=1, saturate=saturate)
        done: bool = False

    query = Unreachable(Counter.x == 1, id="one")
    spec = Spec(
        id="bounded",
        name="bounded",
        actions=[Action(id="over", effect=[Set(Counter.x, value), Set(Counter.done, True)])],
        queries=[query],
    )
    probe = _check(spec, query)
    assert not probe.proved
    result = validate_spec(spec)
    assert result.query_results[0].status == status
    assert any(f.code == "transition.field_constraint" for f in probe.graph.findings) == (
        status == "PASS"
    )
    if status == "FAIL":
        assert probe.replayed is not None


def test_erased_hard_bound_produces_a_spurious_candidate():
    class Counter(Entity):
        x: int = Field(0, le=1)
        done: bool = False

    query = Unreachable(Counter.done, id="unfinished")
    spec = Spec(
        id="bounded",
        name="bounded",
        actions=[Action(id="over", effect=[Set(Counter.x, 2), Set(Counter.done, True)])],
        queries=[query],
    )
    probe = _check(spec, query)
    assert probe.candidate is not None
    assert probe.replayed is None
    result = validate_spec(spec)
    assert result.query_results[0].status == "PASS"
    assert result.query_results[0].model["recheck"]["status"] == "PASS"
    assert result.exploration_findings


def test_replay_rejects_a_hidden_unrepresentable_effect():
    class Poison(int):
        def __add__(self, other):
            return []

    class Data(Entity):
        visible: bool = False
        hidden: int = Poison(0)

    query = Unreachable(Data.visible, id="invisible")
    spec = Spec(
        id="unrepresentable",
        name="Unrepresentable effect",
        actions=[Action(id="show", effect=[Set(Data.visible, True), Add(Data.hidden, 1)])],
        queries=[query],
    )
    probe = _check(spec, query)
    assert probe.candidate is not None and probe.replayed is None
    report = validate_spec(spec)
    assert report.query_results[0].status == "PASS"
    assert report.verdict == "FAIL"


def test_hidden_terminal_lock_is_retained():
    class State(StrEnum):
        OPEN = "open"
        CLOSED = "closed"

    class Item(Entity):
        state: State = Lifecycle(
            State.OPEN, transitions={State.OPEN: [State.CLOSED]}, terminal=[State.CLOSED]
        )
        moved: bool = False
        audit: bool = False

    check = Unreachable(Item.moved, id="locked")
    spec = Spec(
        id="lock",
        name="lock",
        initial=Initial(given=[Item(state=State.CLOSED)]),
        actions=[Action(id="move", effect=[Set(Item.moved, True), Set(Item.audit, True)])],
        queries=[check],
    )
    probe = _check(spec, check)
    assert "Item.state" in probe.projection.fields
    assert probe.proved


def test_slots_cannot_supply_fields_while_absent():
    class Item(Entity):
        active: bool = False
        hidden: bool = False

    class Audit(Entity):
        created: bool = False

    items = Scope(Item, keys=["first"], initially_present=False)
    (first,) = tuple(items)
    inv = Invariant(first.active, id="active")
    guarded = Unreachable(And(Present(first), first.active), id="no_active")
    spec = Spec(
        id="presence",
        name="presence",
        actions=[
            Action(id="create", effect=[Create(first, active=True), Set(Audit.created, True)])
        ],
        scopes=[items],
        queries=[guarded],
        invariants=[inv],
    )
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    assert roots is not None
    exact = analysis.invariant_slice(inv, unconstrained=True)
    projection = derive(analysis, inv.expression, exact)
    assert projection is not None
    assert projection.context(roots[0])[first].__dict__["_analint_present"] is False
    assert derived_proof.attempt(inv, analysis, exact, roots, 128) is None
    report = validate_spec(spec)
    assert report.invariant_results[0].status == "PASS"
    assert report.query_results[0].trace == ["create"]


def test_replay_observes_invalid_endpoint_even_when_exact_search_caps():
    class Data(Entity):
        x: int = 0
        hidden: int = 0

    limit = Invariant(Data.x <= 1, id="limit")
    forbidden = Unreachable(Data.x == 2, id="forbidden")
    spec = Spec(
        id="capped",
        name="capped",
        max_states=12,
        invariants=[limit],
        queries=[forbidden],
        actions=[
            *[Action(id=f"noise_{n}", effect=[Set(Data.hidden, n)]) for n in range(1, 12)],
            Action(id="advance", pre=[Data.x < 2], effect=[Add(Data.x, 1), Set(Data.hidden, 0)]),
        ],
    )
    roots, _ = build_canonical_initials(spec)
    exact, _ = verify_invariants(spec, roots, max_states=12)
    assert exact[0].status == "INCONCLUSIVE"
    report = validate_spec(spec)
    for result in [*report.invariant_results, *report.query_results]:
        assert result.status == "FAIL"
        assert result.trace == ["advance", "advance"]
        assert result.model["relation"] == "under-approx: replayed"
        assert result.model["recheck"]["status"] == "INCONCLUSIVE"


def test_excluded_visible_writer_and_predicate_error_do_not_prove_pass():
    class Data(Entity):
        number: int = 0
        hidden: bool = False

    class Signal(Event):
        ready: bool

    unreachable = Unreachable(Data.number == 1, id="one")
    signal = Action(
        id="signal", pre=[Signal.ready], effect=[Set(Data.number, 1), Set(Data.hidden, True)]
    )
    spec = Spec(id="excluded", name="excluded", actions=[signal], queries=[unreachable])
    report = validate_spec(spec)
    assert report.query_results[0].status == "INCONCLUSIVE"
    assert report.exploration_findings[0].location == "action:signal"

    error = Unreachable(1 // Data.number == 1, id="divide")
    write = Action(id="write", effect=[Set(Data.number, 2), Set(Data.hidden, True)])
    spec = Spec(id="error", name="error", actions=[write], queries=[error])
    probe = _check(spec, error)
    assert not probe.proved and probe.candidate is None
    assert validate_spec(spec).query_results[0].status == "FAIL"


def test_drop_disjunction_as_a_unit():
    class Data(Entity):
        visible: bool = False
        hidden: bool = False

    query = Unreachable(Data.visible, id="invisible")
    spec = Spec(
        id="disjunction",
        name="Disjunction",
        initial=Initial(vary=[Data.hidden]),
        actions=[
            Action(
                id="show",
                pre=[Or(Data.visible, Data.hidden)],
                effect=[Set(Data.visible, True)],
            )
        ],
        queries=[query],
    )
    probe = _check(spec, query)
    assert probe.replayed is not None
    replay, graph = probe.replayed
    assert replay.trace == ["show"]
    assert graph.roots[graph.root_of(replay.witness_key)] == 2
    assert probe.graph.roots[probe.graph.root_of(probe.candidate)] == 1


@pytest.mark.parametrize("checks", [None, ["too_far"]])
def test_exact_coverage_keeps_a_later_hidden_transition_defect(checks):
    class Data(Entity):
        x: int = 0
        audit: int = Field(0, le=1)

    spec = Spec(
        id="coverage",
        name="Coverage",
        actions=[
            Action(id="advance", pre=[Data.x < 2], effect=[Add(Data.x, 1), Add(Data.audit, 1)])
        ],
        queries=[Unreachable(Data.x > 2, id="too_far")],
    )
    report = validate_spec(spec, checks=checks)
    assert report.query_results[0].status == "PASS"
    assert report.query_results[0].model["relation"] == "over-approx"
    assert report.verdict == "FAIL"
    [finding] = report.exploration_findings
    assert finding.code == "transition.field_constraint"
    assert "advance → advance" in finding.message


@pytest.mark.parametrize("checks", [None, ["safe", "forbidden"]])
def test_projection_cold_warm_and_exact_reports(tmp_path, monkeypatch, checks):
    class Data(Entity):
        x: int = 0
        audit: bool = False

    spec = Spec(
        id="cache",
        name="cache",
        actions=[
            Action(id="advance", pre=[Data.x < 1], effect=[Add(Data.x, 1), Set(Data.audit, True)])
        ],
        invariants=[Invariant(Data.x <= 1, id="safe")],
        queries=[Unreachable(Data.x == 2, id="forbidden")],
    )

    def run():
        result = result_to_dict(validate_spec(spec, checks=checks))
        for item in [*result["invariants"], *result["queries"]]:
            item.pop("elapsed_ms", None)
        return result

    with use_store(tmp_path):
        cold = run()
        with monkeypatch.context() as warm_cache:

            def miss(*args, **kwargs):
                pytest.fail("warm exact or projected graph missed the cache")

            warm_cache.setattr(explorer, "_explore", miss)
            warm = run()
        assert explorer._STORE is not None and explorer._STORE.hits > 0
    assert cold == warm
    for item in [*warm["invariants"], *warm["queries"]]:
        assert item["status"] == "PASS"
        assert item["model"]["relation"] == "over-approx"
        assert item["model"]["retained_fields"] == ["Data.x"]
    monkeypatch.setattr(derived_proof, "attempt", lambda *_: None)
    exact = run()
    assert exact["verdict"] == warm["verdict"]
    assert exact["exploration"] == warm["exploration"]


TARGETS = [
    *sorted((ROOT / "examples").glob("*/spec.py")),
    *sorted((ROOT / "benchmarks").glob("*.py")),
    *sorted((ROOT / "benchmarks/broker").glob("m*.py")),
]


@pytest.mark.parametrize(
    "entry", [p for p in TARGETS if p.name != "__init__.py"], ids=lambda p: str(p.relative_to(ROOT))
)
def test_example_and_benchmark_differential(entry, monkeypatch):
    projected = validate(entry)
    monkeypatch.setattr(derived_proof, "attempt", lambda *_: None)
    exact = validate(entry)
    # Library modules that do not declare an entry point have no checks.
    assert projected.load_errors == exact.load_errors
    assert projected.verdict == exact.verdict
    assert projected.exploration_findings == exact.exploration_findings
    projected_checks = [
        *projected.invariant_results,
        *(result for result in projected.query_results if result.kind == "Unreachable"),
    ]
    exact_checks = [
        *exact.invariant_results,
        *(result for result in exact.query_results if result.kind == "Unreachable"),
    ]
    assert [(result.status, result.trace, result.findings) for result in projected_checks] == [
        (result.status, result.trace, result.findings) for result in exact_checks
    ]
    if not any(result.trace is not None for result in projected_checks):
        return
    spec = prepare_model(entry).spec
    for result in projected.invariant_results:
        if result.trace is not None:
            target = next(inv for inv in spec.invariants if inv.id == result.invariant_id)
            roots, _ = build_canonical_initials(spec)
            assert _replays(spec, roots, result.trace, target.expression, False)
    for result in projected.query_results:
        if result.kind == "Unreachable" and result.trace is not None:
            target = next(query for query in spec.queries if query.id == result.query_id)
            roots, _ = resolve_query_initials(target, spec)
            assert _replays(spec, roots, result.trace, target.predicate, True)


def _replays(spec, roots, trace, predicate, expected):
    actions = {action.id: action for action in spec.actions}
    for context in roots:
        for action_id in trace:
            if check_invariants(spec, context, "pre"):
                break
            result = step(spec, actions[action_id], context)
            if result.outcome != Outcome.ACCEPTED:
                break
            context = result.post_context
        else:
            if evaluate(predicate, context) == expected:
                return True
    return False
