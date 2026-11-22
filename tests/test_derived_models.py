"""Differential and planted checks for projected safety proofs."""

from enum import StrEnum
from pathlib import Path

import pytest

from analint import (
    Action,
    Add,
    And,
    Bound,
    Create,
    DeadActions,
    Entity,
    Event,
    Field,
    ForAll,
    Implies,
    Initial,
    Invariant,
    Lifecycle,
    NoDeadEnd,
    Not,
    Or,
    Present,
    Reachable,
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
    blockers = probe.report()["attempts"][0]["proof_blockers"]
    assert any(b["code"] == "transition.field_constraint" for b in blockers) == (status == "PASS")
    if status == "PASS":
        [blocker] = blockers
        assert blocker["location"] == "action:over"
        assert "Counter.x" in blocker["message"]
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
    item = Bound("item", items)
    all_active = Invariant(ForAll(item, item.active), id="all_active")
    guarded = Unreachable(And(Present(first), first.active), id="no_active")
    spec = Spec(
        id="presence",
        name="presence",
        actions=[
            Action(id="create", effect=[Create(first, active=True), Set(Audit.created, True)])
        ],
        scopes=[items],
        queries=[guarded],
        invariants=[inv, all_active],
    )
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    assert roots is not None
    exact = analysis.invariant_slice(inv, unconstrained=True)
    projection = derive(analysis, inv.expression, exact)
    assert projection is not None
    assert projection.context(roots[0])[first].__dict__["_analint_present"] is False
    assert derived_proof.attempt(inv, analysis, exact, roots, 128) is None
    assert (
        derived_proof.attempt(
            all_active,
            analysis,
            analysis.invariant_slice(all_active, unconstrained=True),
            roots,
            128,
        )
        is None
    )
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
    assert report.query_results[0].model is None  # relevant exclusion prevents projection
    assert report.exploration_findings[0].code == "exploration.action_excluded"

    error = Unreachable(1 // Data.number == 1, id="divide")
    write = Action(id="write", effect=[Set(Data.number, 2), Set(Data.hidden, True)])
    spec = Spec(id="error", name="error", actions=[write], queries=[error])
    probe = _check(spec, error)
    assert not probe.proved and probe.candidate is None
    [evaluation_error] = probe.report()["attempts"][0]["proof_blockers"]
    assert evaluation_error["code"] == "query.evaluation_error"
    assert "division" in evaluation_error["message"]
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
        model = item["model"]
        expected = "exact" if item in warm["queries"] and checks is not None else "over-approx"
        assert model["relation"] == expected
        relations = [a["relation"] for a in model["attempts"]]
        assert relations == (["over-approx", "exact"] if expected == "exact" else ["over-approx"])
        assert item["model"]["retained_fields"] == ["Data.x"]
    monkeypatch.setattr(derived_proof, "attempt", lambda *_: None)
    exact = run()
    assert exact["verdict"] == warm["verdict"]
    assert exact["exploration"] == warm["exploration"]
    if checks is not None:
        [projected_inv] = warm["invariants"]
        [exact_inv] = exact["invariants"]
        assert projected_inv["slice"] == exact_inv["slice"]
        assert projected_inv["states_explored"] == exact_inv["states_explored"]


TARGETS = [
    *sorted((ROOT / "examples").glob("*/spec.py")),
    *sorted((ROOT / "benchmarks").glob("*.py")),
    *sorted((ROOT / "benchmarks/broker").glob("m*.py")),
]


@pytest.mark.parametrize(
    "entry", [p for p in TARGETS if p.name != "__init__.py"], ids=lambda p: str(p.relative_to(ROOT))
)
def test_example_and_benchmark_differential(entry, monkeypatch):
    # The standalone broker increments default to budgets up to five million.
    # Keep their differential bounded and use the live model budgets for M4/M6.
    broker_increment = entry.parent == ROOT / "benchmarks" / "broker" and entry.stem not in {
        "m4",
        "m6",
    }
    budget = 2000 if broker_increment else None
    proofs = set()
    attempt = derived_proof.attempt

    def observe(target, *args):
        probe = attempt(target, *args)
        if probe is not None and probe.proved:
            proofs.add(target.id)
        return probe

    def without_projection(**kwargs):
        with monkeypatch.context() as exact_run:
            exact_run.setattr(derived_proof, "attempt", lambda *_: None)
            exact_run.setattr(derived_proof, "cover_defects", lambda *_, **__: None)
            exact_run.setattr(derived_proof, "cover_family", lambda *_, **__: {})
            exact_run.setattr(derived_proof, "reach_witness", lambda *_: None)
            exact_run.setattr(derived_proof, "derive", lambda *_, **__: None)
            return validate(entry, max_states=budget, **kwargs)

    monkeypatch.setattr(derived_proof, "attempt", observe)
    projected = validate(entry, max_states=budget)
    exact = without_projection()
    # Library modules that do not declare an entry point have no checks.
    assert projected.load_errors == exact.load_errors
    if projected.verdict != exact.verdict:
        assert (exact.verdict, projected.verdict) == ("INCONCLUSIVE", "PASS")
        assert any(
            actual.model
            and actual.model["relation"] in ("over-approx", "under-approx: replayed")
            and expected.status == "INCONCLUSIVE"
            for actual, expected in zip(
                [*projected.invariant_results, *projected.query_results],
                [*exact.invariant_results, *exact.query_results],
                strict=True,
            )
        )
    assert projected.exploration_findings == exact.exploration_findings
    assert projected.model_findings == exact.model_findings
    projected_checks = [*projected.invariant_results, *projected.query_results]
    exact_checks = [*exact.invariant_results, *exact.query_results]

    def compare(actual, expected):
        if getattr(actual, "kind", None) != "NoDeadEnd" and (
            actual.status == "PASS" and expected.status == "INCONCLUSIVE"
        ):
            assert actual.model["relation"] in ("over-approx", "under-approx: replayed")
        else:
            assert (actual.status, actual.trace, actual.findings) == (
                expected.status,
                expected.trace,
                expected.findings,
            )

    for actual, expected in zip(projected_checks, exact_checks, strict=True):
        compare(actual, expected)
        # DeadActions counts distinct graphs used by its per-action strategy.
        # Projected coverage can change what exact graphs are already available.
        if getattr(actual, "kind", None) == "DeadActions":
            assert actual.slice["per_action"] == expected.slice["per_action"]
        elif actual.model is None or actual.model["relation"] in (None, "exact"):
            assert (actual.states_explored, actual.slice) == (
                expected.states_explored,
                expected.slice,
            )

    def check_id(check):
        return check.invariant_id if hasattr(check, "invariant_id") else check.query_id

    def requested(run, name):
        return next(
            check
            for check in [*run.invariant_results, *run.query_results]
            if check_id(check) == name
        )

    full_proofs = proofs.copy()
    for result in exact_checks:
        name = check_id(result)
        assert name not in full_proofs or result.status != "FAIL", name
        proofs.clear()
        selected = validate(entry, max_states=budget, checks=[name])
        control = without_projection(checks=[name])
        actual = requested(selected, name)
        expected = requested(control, name)
        assert name not in proofs or expected.status != "FAIL", name
        assert selected.exploration_findings == control.exploration_findings
        assert selected.model_findings == control.model_findings
        compare(actual, expected)

    if not any(result.trace is not None for result in projected_checks):
        return
    spec = prepare_model(entry).spec
    for result in projected.invariant_results:
        if result.trace is not None:
            target = next(inv for inv in spec.invariants if inv.id == result.invariant_id)
            roots, _ = build_canonical_initials(spec)
            assert _replays(spec, roots, result.trace, target.expression, False)
    for result in projected.query_results:
        if (
            result.kind in ("Reachable", "Unreachable")
            and result.trace is not None
            and (result.status == "PASS" if result.kind == "Reachable" else result.status == "FAIL")
        ):
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


def test_projection_preserves_equal_values_with_different_arithmetic(tmp_path):
    value = 2**56

    class Data(Entity):
        number: int = value
        audit: bool = False

    forbidden = Unreachable(
        Data.number // 3 < value // 3,
        id="forbidden",
        given_any=[[Data()], [Data(number=float(value), audit=True)]],
    )
    spec = Spec(
        id="numeric",
        name="numeric",
        actions=[
            Action(
                id="reset",
                effect=[Set(Data.number, value), Set(Data.audit, False)],
            )
        ],
        queries=[forbidden],
    )

    def probe():
        analysis = SliceAnalysis(spec)
        roots, error = resolve_query_initials(forbidden, spec)
        assert roots is not None, error
        piece = analysis.predicate_slice(forbidden.predicate, canonical=False)
        return derived_proof.attempt(forbidden, analysis, piece, roots, 128)

    with use_store(tmp_path):
        for _ in range(2):
            attempt = probe()
            assert attempt is not None
            assert attempt.result.status == "FAIL"
            assert attempt.replayed is not None
            result, graph = attempt.replayed
            assert result.trace == []
            assert list(graph.roots.values()) == [2]
        assert explorer._STORE is not None and explorer._STORE.hits == 1
    assert validate_spec(spec, checks=["forbidden"]).query_results[0].status == "FAIL"


@pytest.mark.parametrize("outcome, status", [("ok", "PASS"), ("violation", "FAIL")])
def test_tlc_records_deciding_exact_query_attempt(monkeypatch, outcome, status):
    from analint.backends.tlc import TlcResult
    from analint.reporter.terminal import _model_note
    from analint.validator import tlc_fallback

    class Data(Entity):
        reached: bool = False
        hidden: int = 0

    spec = Spec(
        id="backend",
        name="Backend",
        max_states=8,
        actions=[
            *[Action(id=f"noise_{n}", effect=[Set(Data.hidden, n)]) for n in range(1, 9)],
            Action(id="enter", pre=[Data.hidden == 8], effect=[Set(Data.reached, True)]),
        ],
        queries=[Unreachable(Data.reached, id="forbidden")],
    )
    monkeypatch.setattr(tlc_fallback, "find_tlc", lambda: None)
    monkeypatch.setattr(
        tlc_fallback,
        "run_tlc",
        lambda *_args, **_kwargs: TlcResult(
            outcome, trace=["noise_8", "enter"], distinct_states=10
        ),
    )
    [result] = validate_spec(spec, tlc=True).query_results
    assert result.status == status
    model = result.model
    assert model["relation"] == "exact"
    assert [(a["backend"], a["status"]) for a in model["attempts"]] == [
        ("native", "FAIL"),
        ("native", "INCONCLUSIVE"),
        ("tlc", status),
    ]
    assert model["recheck"] == model["attempts"][-1]
    assert model["recheck"]["states_explored"] == 10
    assert _model_note(model) == ", system backend, exact"


@pytest.mark.parametrize("excluded", [False, True])
def test_projection_can_prove_safety_when_exact_is_inconclusive(excluded):
    class Data(Entity):
        reached: bool = False
        hidden: int = 0

    class Signal(Event):
        ready: bool

    noise = (
        [Action(id="signal", pre=[Signal.ready], effect=[Set(Data.hidden, 1)])]
        if excluded
        else [Action(id=f"noise_{n}", effect=[Set(Data.hidden, n)]) for n in range(1, 9)]
    )
    spec = Spec(
        id="strengthening",
        name="Selected safety proof",
        max_states=8,
        actions=[
            *noise,
            Action(id="reset", effect=[Set(Data.reached, False), Set(Data.hidden, 0)]),
        ],
        queries=[Unreachable(Data.reached, id="forbidden")],
    )
    [full] = validate_spec(spec).query_results
    [selected] = validate_spec(spec, checks=["forbidden"]).query_results
    assert full.status == ("PASS" if excluded else "INCONCLUSIVE")
    assert full.model["relation"] == ("over-approx" if excluded else None)
    assert selected.status == "PASS"
    assert selected.model["relation"] == "over-approx"
    assert selected.model["attempts"][0]["states_explored"] == 1


def test_capped_projection_reports_its_budget_blocker():
    class Data(Entity):
        x: int = 0
        audit: bool = False

    check = Unreachable(Data.x == 99, id="forbidden")
    spec = Spec(
        id="capped_projection",
        name="Capped projection",
        actions=[
            Action(id="inc", pre=[Data.x < 3], effect=[Add(Data.x, 1), Set(Data.audit, True)])
        ],
        queries=[check],
    )
    probe = _check(spec, check, budget=8)
    first = probe.report()["attempts"][0]
    assert first["status"] == "INCONCLUSIVE"
    assert not first["complete"]
    [blocker] = first["proof_blockers"]
    assert blocker["code"] == "check.budget_exhausted"
    assert "2-state budget" in blocker["message"]


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_reachability_and_action_entry_require_concrete_replay(selected, allowed):
    class Data(Entity):
        allowed: bool = False
        ready: bool = False
        audit: bool = False
        done: bool = False

    prepare = Action(
        id="prepare", pre=[Data.allowed], effect=[Set(Data.ready, True), Set(Data.audit, True)]
    )
    consume = Action(id="consume", pre=[Data.ready], effect=[Set(Data.done, True)])
    reach = Reachable(Data.ready, id="reach", given=[Data(allowed=allowed)])
    dead = DeadActions(id="dead", given=[Data(allowed=allowed)])
    spec = Spec(id="replay", name="Replay", actions=[prepare, consume], queries=[reach, dead])
    report = validate_spec(spec, checks=["reach", "dead"] if selected else None)
    exact = validate_spec(spec, sliced=False, checks=["reach", "dead"] if selected else None)
    reached, fired = report.query_results
    for actual, expected in zip(report.query_results, exact.query_results, strict=True):
        assert (actual.status, actual.trace) == (expected.status, expected.trace)
    if allowed:
        assert reached.trace == ["prepare"]
        assert reached.model["relation"] == "under-approx: replayed"
        assert fired.model["relation"] == "under-approx: replayed"
        assert any(
            attempt.get("trace") == ["prepare", "consume"] for attempt in fired.model["attempts"]
        )
    else:
        assert reached.model["relation"] == "exact"
        assert not reached.model["attempts"][0]["replayed"]
        assert fired.model is None
        assert "consume, prepare" in fired.findings[0].message


@pytest.mark.parametrize("both_legal_paths", [False, True])
def test_reachability_replays_each_root_even_when_their_projections_merge(both_legal_paths):
    class Data(Entity):
        allowed: bool = False
        ready: bool = False
        audit: bool = False

    reach = Reachable(
        Data.ready,
        id="reach",
        given_any=[(Data(allowed=True),), (Data(allowed=both_legal_paths, audit=True),)],
    )
    spec = Spec(
        id="two_roots",
        name="Two roots",
        actions=[
            Action(
                id="prepare",
                pre=[Data.allowed],
                effect=[Set(Data.ready, True), Set(Data.audit, True)],
            )
        ],
        queries=[reach],
    )
    [actual] = validate_spec(spec, checks=["reach"]).query_results
    [exact] = validate_spec(spec, sliced=False, checks=["reach"]).query_results
    assert actual.status == exact.status
    assert actual.model is not None
    if both_legal_paths:
        assert actual.model["root_numbers"] == [1, 2]
        assert actual.trace == exact.trace == ["prepare"]
    else:
        assert actual.model["relation"] == "exact"
        assert any(
            attempt.get("root") == 2 and attempt.get("replayed") is False
            for attempt in actual.model["attempts"]
        )
        assert "init #2" in actual.findings[0].message


def test_reachability_evaluation_error_overrides_root_witness():
    class Data(Entity):
        divisor: int = 1
        audit: bool = False

    query = Reachable(1 // Data.divisor == 1, id="reach")
    spec = Spec(
        id="errors",
        name="Errors",
        actions=[Action(id="zero", effect=[Set(Data.divisor, 0), Set(Data.audit, True)])],
        queries=[query],
    )
    [actual] = validate_spec(spec).query_results
    assert actual.status == "FAIL"
    assert actual.findings[0].code == "query.evaluation_error"
    assert actual.model["relation"] == "exact"
    assert actual.model["attempts"][0]["evaluation_errors"]


def test_no_dead_end_does_not_use_an_invented_recovery_path():
    class Data(Entity):
        goal: bool = True
        trapped: bool = False

    query = NoDeadEnd(Data.goal, id="recovery")
    spec = Spec(
        id="trap",
        name="Trap",
        actions=[
            Action(id="trap", effect=[Set(Data.goal, False), Set(Data.trapped, True)]),
            Action(id="recover", pre=[Not(Data.trapped)], effect=[Set(Data.goal, True)]),
        ],
        queries=[query],
    )
    for checks in (None, ["recovery"]):
        [actual] = validate_spec(spec, checks=checks).query_results
        [exact] = validate_spec(spec, sliced=False, checks=checks).query_results
        assert (actual.status, actual.trace, actual.findings) == (
            exact.status,
            exact.trace,
            exact.findings,
        )
        assert actual.status == "FAIL"
        assert actual.trace == ["trap"]
        assert actual.model["relation"] == "exact"


@pytest.mark.parametrize("checks", [None, ["safe"]])
def test_projected_safety_keeps_defect_in_an_omitted_writer(checks):
    class Data(Entity):
        ready: bool = False
        hidden: bool = False
        count: int = Field(0, le=0)

    safe = Invariant(Implies(Data.ready, Data.ready), id="safe")
    spec = Spec(
        id="hidden_defect",
        name="Hidden defect",
        actions=[
            Action(id="enable", effect=[Set(Data.hidden, True)]),
            Action(id="bad", pre=[Data.hidden], effect=[Set(Data.ready, True), Add(Data.count, 1)]),
        ],
        invariants=[safe],
    )
    report = validate_spec(spec, checks=checks)
    assert report.verdict == "FAIL"
    [finding] = report.exploration_findings
    assert finding.code == "transition.field_constraint"
    assert "enable → bad" in finding.message
    assert "action:enable" in report.invariant_results[0].model["omitted_writers"]


@pytest.mark.parametrize("checks", [None, ["safe"]])
def test_complete_projected_coverage_needs_no_exact_graph(monkeypatch, checks):
    class Data(Entity):
        a: bool = False
        b: bool = False
        c: bool = False

    spec = Spec(
        id="cycle",
        name="Dependency cycle",
        actions=[
            Action(id="first", pre=[Data.b], effect=[Set(Data.a, True)]),
            Action(id="second", pre=[Data.c], effect=[Set(Data.b, True)]),
            Action(id="third", pre=[Data.a], effect=[Set(Data.c, True)]),
        ],
        invariants=[Invariant(Implies(Data.a, Data.a), id="safe")],
    )
    # The invariant holds even after weakening first's guard.
    # Each action projection drops one input from the cyclic dependencies.
    explore = explorer._explore
    exact = []

    def observe(*args, **kwargs):
        if kwargs.get("projection") is None:
            exact.append(args[0])
        return explore(*args, **kwargs)

    monkeypatch.setattr(explorer, "_explore", observe)
    report = validate_spec(spec, checks=checks)
    assert report.verdict == "PASS"
    assert report.invariant_results[0].model["relation"] == "over-approx"
    assert not exact


def test_replayed_unreachable_uses_exact_slice_root_attribution():
    class Data(Entity):
        reached: bool = False
        audit: bool = False

    class Other(Entity):
        flag: bool = False

    check = Unreachable(Data.reached, id="forbidden")
    spec = Spec(
        id="merged_roots",
        name="Merged exact roots",
        initial=Initial(vary=[Other.flag]),
        actions=[Action(id="reach", effect=[Set(Data.reached, True), Set(Data.audit, True)])],
        queries=[check],
    )
    probe = _check(spec, check)
    assert probe.replayed is not None
    replay, graph = probe.replayed
    assert not graph.multiple_roots
    assert [finding.code.value for finding in replay.findings] == ["query.reached_forbidden"]


def test_action_coverage_budget_scales_with_exact_budget():
    class Data(Entity):
        value: int = 0
        audit: bool = False

    target = Action(id="target", pre=[Data.value == 0], effect=[Set(Data.value, 1)])
    spec = Spec(
        id="scaling_coverage",
        name="Scaling coverage",
        actions=[
            target,
            Action(
                id="grow",
                pre=[Data.value < 4100],
                effect=[Add(Data.value, 1), Set(Data.audit, True)],
            ),
        ],
    )
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    piece = analysis.action_slice(target, canonical=True)
    proof = derived_proof.cover_defects(target, analysis, piece, roots, 20_000, canonical=True)
    assert proof is not None
    assert proof[1].state_count == 4101


@pytest.mark.parametrize("overflow", [False, True])
def test_refines_spurious_counterexample_or_transition_defect(overflow):
    class Data(Entity):
        value: int = Field(default=0, le=1)
        limit: int = 1
        audit: bool = False

    guards = [Data.value < Data.limit]
    if not overflow:
        guards.append(Data.value < 1)
    increment = Action(
        id="increment",
        pre=guards,
        effect=[Add(Data.value, 1), Set(Data.audit, True)],
    )
    target = Unreachable(Data.value == 2 if overflow else Data.value == 1, id="safety")
    spec = Spec(
        id="refine_guard",
        name="Refine a dropped bound",
        initial=Initial(given=[Data(limit=int(overflow))]),
        actions=[increment],
        queries=[target],
    )
    probe = _check(spec, target)
    assert probe.proved
    first, final = probe.report()["attempts"]
    if overflow:
        assert first["proof_blockers"]
    else:
        assert not first["proof_blockers"]
        assert first["candidate_trace"] == ["increment"]
        assert first["replayed"] is False
    assert final["widened_fields"] == ["Data.limit"]
    assert final["clean"]
    assert final["states_explored"] == (2 if overflow else 1)


def test_refines_a_non_replaying_reachability_witness():
    class Data(Entity):
        environment: bool = True
        allowed: bool = False
        done: bool = False
        audit: bool = False

    query = Reachable(Data.done, id="reach")
    spec = Spec(
        id="refine_witness",
        name="Refine a non-replaying witness",
        actions=[
            Action(
                id="shortcut",
                pre=[Data.environment, Data.allowed],
                effect=[Set(Data.done, True), Set(Data.audit, True)],
            ),
            Action(id="unlock", effect=[Set(Data.allowed, True)]),
        ],
        queries=[query],
    )
    [result] = validate_spec(spec, checks=["reach"]).query_results
    assert result.model["relation"] == "under-approx: replayed"
    assert result.trace == ["unlock", "shortcut"]
    first, refined, _ = result.model["attempts"]
    assert first["replayed"] is False
    assert refined["widened_fields"] == ["Data.allowed"]


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("query", [False, True])
def test_transition_blocker_cleared_on_its_action_slice(monkeypatch, selected, query):
    class Data(Entity):
        value: int = Field(default=0, le=1)
        limit: int = 1
        audit: bool = False

    class Other(Entity):
        noise: int = 0
        audit: bool = False

    # Skip refinement to exercise the independent action coverage fallback.
    monkeypatch.setattr(derived_proof, "_MAX_REFINEMENTS", 0)
    predicate = And(Data.value == 2, Other.noise == 99)
    target = (
        Unreachable(predicate, id="safety") if query else Invariant(Not(predicate), id="safety")
    )
    spec = Spec(
        id="clear_blocker",
        name="Clear a speculative transition blocker",
        actions=[
            Action(
                id="increment",
                pre=[Data.value < Data.limit],
                effect=[Add(Data.value, 1), Set(Data.audit, True)],
            ),
            Action(
                id="noise",
                pre=[Other.noise < 10],
                effect=[Add(Other.noise, 1), Set(Other.audit, True)],
            ),
        ],
        invariants=[] if query else [target],
        queries=[target] if query else [],
    )
    report = validate_spec(spec, checks=["safety"] if selected else None)
    [result] = report.query_results if query else report.invariant_results
    assert report.verdict == "PASS"
    assert not report.exploration_findings
    assert result.model["relation"] == "over-approx"
    assert result.model["attempts"][-1]["covered_transition_actions"] == ["increment"]


def test_dead_actions_reuses_complete_exact_coverage(monkeypatch):
    class Counter(Entity):
        value: int = 0

    increment = Action(id="increment", pre=[Counter.value == 0], effect=[Add(Counter.value, 1)])
    spec = Spec(id="reuse_exact", name="Reuse exact coverage", actions=[increment])
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    piece = analysis.action_slice(increment, canonical=True)
    cache = {}
    exact, _ = explorer.explore_slice(analysis, piece, roots, 128, cache)

    def unexpected_probe(*args, **kwargs):
        pytest.fail("complete exact coverage already establishes action entry")

    monkeypatch.setattr(derived_proof, "cover_defects", unexpected_probe)
    firing_proofs = []
    covered = explorer.cover_actions(
        analysis, roots, 128, cache, canonical=True, firing_proofs=firing_proofs
    )
    assert covered[id(increment)] is exact
    assert exact.fired == {"increment"}
    assert not firing_proofs


def test_supporting_transition_defect_has_an_independent_coverage_obligation():
    class Data(Entity):
        value: int = Field(default=0, le=1)
        audit: bool = False

    reset = Action(id="reset", effect=[Set(Data.value, 0)])
    broken = Action(id="broken", effect=[Set(Data.value, 2), Set(Data.audit, True)])
    spec = Spec(id="independent_coverage", name="Independent coverage", actions=[reset, broken])
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    covered = explorer.cover_actions(analysis, roots, 128, {}, canonical=True)
    assert not covered[id(reset)].findings
    [finding] = covered[id(broken)].findings
    assert finding.location == "action:broken"
    assert finding.code == "transition.field_constraint"


def test_reachability_replays_an_alternative_before_widening():
    class Data(Entity):
        outcome: int = 0
        allowed: bool = False
        audit: bool = False

    query = Reachable(Data.outcome > 0, id="reach")
    spec = Spec(
        id="other_witness",
        name="Alternative projected witness",
        actions=[
            Action(
                id="invented",
                pre=[Data.allowed],
                effect=[Set(Data.outcome, 1), Set(Data.audit, True)],
            ),
            Action(id="actual", effect=[Set(Data.outcome, 2), Set(Data.audit, True)]),
        ],
        queries=[query],
    )
    [result] = validate_spec(spec, checks=["reach"]).query_results
    assert result.trace == ["actual"]
    first, replay = result.model["attempts"]
    assert first["candidate_trace"] == ["actual"]
    assert first["widened_fields"] == []
    assert replay["relation"] == "under-approx: replayed"


@pytest.mark.parametrize("checks", [None, ["recover"]])
def test_rank_two_refines_and_avoids_the_exact_recovery_graph(monkeypatch, checks):
    class Data(Entity):
        progress: int = 0
        ready: bool = False
        audit: bool = False

    query = NoDeadEnd(Data.progress == 2, id="recover")
    spec = Spec(
        id="recovery",
        name="Recovery",
        initial=Initial(vary=[Data.ready]),
        invariants=[Invariant(Data.progress <= 2, id="valid")],
        actions=[
            Action(
                id="first",
                pre=[Data.progress == 0],
                effect=[Set(Data.progress, 1), Set(Data.ready, True)],
            ),
            Action(
                id="audit",
                pre=[Data.progress == 2],
                effect=[Set(Data.progress, 2), Set(Data.audit, True)],
            ),
            Action(
                id="finish",
                pre=[And(Data.ready, Data.progress == 1)],
                effect=[Set(Data.progress, 2)],
            ),
        ],
        queries=[query],
    )
    exact = validate_spec(spec, sliced=False, checks=checks)

    def unexpected_exact(*args, **kwargs):
        pytest.fail("the full set of derived proofs should avoid exact slice exploration")

    monkeypatch.setattr(explorer, "explore_slice", unexpected_exact)
    actual = validate_spec(spec, checks=checks)
    [actual_query], [exact_query] = actual.query_results, exact.query_results
    assert actual.verdict == exact.verdict == "PASS"
    assert actual_query.trace == exact_query.trace is None
    assert actual_query.model["relation"] == "over-approx"
    assert actual_query.model["recheck"] is None
    first, second = actual_query.model["attempts"]
    assert first["ranks"] == [1]
    assert second["widened_fields"] == ["Data.ready"]
    assert second["ranks"] == [1, 1, 2]
    assert second["recovery_actions"] == ["finish", "first"]


@pytest.mark.parametrize("checks", [None, ["recover"]])
@pytest.mark.parametrize(
    "case, status",
    [
        ("inert_root", "FAIL"),
        ("terminal_lock", "FAIL"),
        ("hard_bound", "FAIL"),
        ("clamp", "PASS"),
        ("hidden_credit", "FAIL"),
        ("invalid_successor", "FAIL"),
    ],
)
def test_recovery_preserves_concrete_kernel_and_invariant_obligations(case, status, checks):
    class Phase(StrEnum):
        OPEN = "open"
        TERMINAL = "terminal"

    class Data(Entity):
        goal: bool = True
        audit: bool = False
        credit: bool = True
        count: int = Field(0, le=1, saturate="high" if case == "clamp" else False)
        phase: Phase = Lifecycle(
            initial=Phase.OPEN,
            transitions={Phase.OPEN: [Phase.TERMINAL]},
            terminal=[Phase.TERMINAL],
        )

    enter_effects = [Set(Data.goal, False), Set(Data.audit, True)]
    recover_effects = [Set(Data.goal, True)]
    recover_guards = []
    invariants = []
    if case == "terminal_lock":
        enter_effects.append(Set(Data.phase, Phase.TERMINAL))
    if case in {"hard_bound", "clamp"}:
        recover_effects.append(Set(Data.count, 2))
    if case == "hidden_credit":
        recover_guards.append(Data.credit)
        enter_effects.append(Set(Data.credit, False))
    if case in {"inert_root", "invalid_successor"}:
        invariants.append(Invariant(Not(Data.audit), id="valid"))
    query = NoDeadEnd(
        Data.goal,
        id="recover",
        given=[Data(goal=False, audit=True)] if case == "inert_root" else [],
    )
    actions = [
        Action(id="enter", effect=enter_effects),
        Action(id="restore", pre=recover_guards, effect=recover_effects),
    ]
    if case == "hidden_credit":
        actions.append(
            Action(id="enter_with_credit", pre=[Data.credit], effect=[Set(Data.goal, False)])
        )
    spec = Spec(
        id="recovery",
        name="Recovery",
        actions=actions,
        invariants=invariants,
        queries=[query],
    )
    [actual] = validate_spec(spec, checks=checks).query_results
    [exact] = validate_spec(spec, sliced=False, checks=checks).query_results
    assert actual.status == exact.status == status
    assert actual.trace == exact.trace
    assert actual.findings == exact.findings
    if status == "FAIL":
        assert actual.model["relation"] == "exact"
        assert actual.model["recheck"]["status"] == "FAIL"
    else:
        assert actual.model["relation"] == "over-approx"
        assert actual.model["attempts"][-1]["widened_fields"] == ["Data.count"]


def test_recovery_requires_invariants_outside_its_cone():
    class Job(Entity):
        done: bool = True
        audit: bool = False

    class Budget(Entity):
        valid: bool = True

    query = NoDeadEnd(Job.done, id="recover")
    spec = Spec(
        id="recovery",
        name="Recovery",
        actions=[
            Action(id="start", effect=[Set(Job.done, False), Set(Job.audit, True)]),
            Action(id="finish", effect=[Set(Job.done, True)]),
            Action(id="break_budget", effect=[Set(Budget.valid, False)]),
        ],
        invariants=[Invariant(Budget.valid, id="valid_budget")],
        queries=[query],
    )
    result = validate_spec(spec, checks=["recover"])
    [actual] = result.query_results
    assert result.verdict == "FAIL"
    assert actual.status == "PASS"  # exact slice omits the unrelated invariant
    assert actual.model["relation"] == "exact"
    assert actual.model["attempts"][0]["proof_blockers"] == [
        "invariant lacks a system proof: valid_budget"
    ]


def test_relevant_event_exclusion_blocks_the_recovery_certificate():
    class Job(Entity):
        done: bool = True
        audit: bool = False

    class Notification(Event):
        ready: bool

    query = NoDeadEnd(Job.done, id="recover")
    spec = Spec(
        id="recovery",
        name="Recovery",
        actions=[
            Action(id="start", effect=[Set(Job.done, False), Set(Job.audit, True)]),
            Action(id="finish", effect=[Set(Job.done, True)]),
            Action(id="external", pre=[Notification.ready], effect=[Set(Job.done, False)]),
        ],
        queries=[query],
    )
    [actual] = validate_spec(spec, checks=["recover"]).query_results
    [exact] = validate_spec(spec, sliced=False, checks=["recover"]).query_results
    assert actual.status == exact.status == "INCONCLUSIVE"
    assert actual.findings == exact.findings
    assert actual.model["attempts"][0]["proof_blockers"] == [
        "incomplete diagnostic coverage: external"
    ]
    assert actual.model["recheck"]["complete"] is False


def test_recovery_does_not_rank_a_type_only_change_that_exact_keys_merge():
    threshold = 2**53

    class Data(Entity):
        value: float = float(threshold)
        audit: bool = False

    goal = Data.value == threshold + 1
    query = NoDeadEnd(goal, id="recover")
    spec = Spec(
        id="recovery",
        name="Recovery",
        actions=[
            Action(id="integer", effect=[Set(Data.value, threshold)]),
            Action(id="advance", pre=[Data.value == threshold], effect=[Add(Data.value, 1)]),
            Action(
                id="audit",
                pre=[goal],
                effect=[Set(Data.value, threshold + 1), Set(Data.audit, True)],
            ),
        ],
        queries=[query],
    )
    [actual] = validate_spec(spec).query_results
    [exact] = validate_spec(spec, sliced=False).query_results
    assert actual.status == exact.status == "FAIL"
    assert actual.findings == exact.findings
    assert actual.model["attempts"][0]["proof_blockers"] == [
        "exact state keys can merge distinct projected values"
    ]


def test_recovery_cap_rechecks_with_the_full_budget(monkeypatch):
    class Job(Entity):
        progress: int = 0
        audit: bool = False

    query = NoDeadEnd(Job.progress == 2, id="recover")
    spec = Spec(
        id="recovery",
        name="Recovery",
        actions=[
            Action(
                id="advance",
                pre=[Job.progress < 2],
                effect=[Add(Job.progress, 1)],
            ),
            Action(
                id="audit",
                pre=[Job.progress == 2],
                effect=[Set(Job.progress, 2), Set(Job.audit, True)],
            ),
        ],
        queries=[query],
    )
    monkeypatch.setattr(derived_proof, "_witness_budget", lambda _: 2)
    [actual] = validate_spec(spec, max_states=16).query_results
    assert actual.status == "PASS"
    assert actual.model["relation"] == "exact"
    [probe, exact] = actual.model["attempts"]
    assert probe["budget"] == 2
    assert probe["proof_blockers"] == ["projected state budget exhausted"]
    assert exact["budget"] == 16
    assert exact["states_explored"] == 4


def test_own_root_projected_coverage_shares_one_work_allowance(monkeypatch):
    class Data(Entity):
        x: bool = False
        y: bool = False

    first = Action(id="first", effect=[Set(Data.x, True)])
    second = Action(id="second", effect=[Set(Data.y, True)])
    spec = Spec(id="work_limit", name="Work limit", actions=[first, second])
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    remaining = []

    def spend_allowance(*args, work=None, **kwargs):
        assert work is not None
        remaining.append(work[0])
        work[0] = 0
        return None

    monkeypatch.setattr(derived_proof, "cover_defects", spend_allowance)
    covered = explorer.cover_actions(
        analysis, roots, 128, {}, canonical=False, limit_projection_work=True
    )
    assert remaining == [128, 0]
    assert covered[id(first)].fired == {"first"}
    assert covered[id(second)].fired == {"second"}


@pytest.mark.parametrize("defect", ["post", "guard"])
def test_family_coverage_keeps_clean_targets_and_falls_back_for_defect(defect, monkeypatch):
    class Data(Entity):
        value: int = Field(default=0, le=1)
        audit: bool = False

    # Both variants read the same fields. Only the faulty guard admits an
    # overflow at 1, or the faulty postcondition rejects the later result.
    clean = Action(
        id="advance(clean)",
        family="advance",
        pre=[Data.value < 1],
        effect=[Add(Data.value, 1)],
    )
    faulty = Action(
        id="advance(faulty)",
        family="advance",
        pre=[Data.value <= 1] if defect == "guard" else [Data.value == 1],
        effect=[Add(Data.value, 1)] if defect == "guard" else [Set(Data.value, 0)],
        post=[] if defect == "guard" else [Data.value == 1],
    )
    writer = Action(id="audit", effect=[Set(Data.value, 1), Set(Data.audit, True)])
    spec = Spec(id="family", name="Family", actions=[clean, faulty, writer])
    roots, _ = build_canonical_initials(spec)
    analysis = SliceAnalysis(spec)
    probes = []
    original = derived_proof.cover_defects

    def record(action, *args, **kwargs):
        probes.append(action.id)
        return original(action, *args, **kwargs)

    monkeypatch.setattr(derived_proof, "cover_defects", record)
    covered = explorer.cover_actions(analysis, roots, 128, {}, canonical=True)
    assert clean.id not in probes
    assert faulty.id in probes
    assert covered[id(clean)].state_count == 2
    assert not covered[id(clean)].findings
    assert any(f.location == f"action:{faulty.id}" for f in covered[id(faulty)].findings)
    with monkeypatch.context() as exact:
        exact.setattr(derived_proof, "cover_defects", lambda *_, **__: None)
        exact.setattr(derived_proof, "derive", lambda *_, **__: None)
        expected = explorer.cover_actions(SliceAnalysis(spec), roots, 128, {}, canonical=True)
    assert covered[id(faulty)].findings == expected[id(faulty)].findings


def test_own_root_family_cap_falls_back_to_full_exact_budget(monkeypatch):
    class Data(Entity):
        value: int = 0
        audit: bool = False

    first = Action(
        id="grow(first)", family="grow", pre=[Data.value < 3], effect=[Add(Data.value, 1)]
    )
    second = Action(
        id="grow(second)", family="grow", pre=[Data.value < 2], effect=[Add(Data.value, 1)]
    )
    writer = Action(id="audit", effect=[Set(Data.value, 1), Set(Data.audit, True)])
    spec = Spec(id="own_cap", name="Own root cap", actions=[first, second, writer])
    query = DeadActions(given=[Data(value=1)], id="usable")
    spec.queries.append(query)
    monkeypatch.setattr(derived_proof, "_witness_budget", lambda _: 2)
    original = derived_proof.explore
    projected = []
    exact_budgets = []
    explore_slice = explorer.explore_slice

    def record(model, *args, **kwargs):
        graph = original(model, *args, **kwargs)
        if any(action is first for action in model.actions):
            projected.append(graph.capped)
        return graph

    def record_exact(analysis, piece, initials, max_states, *args, **kwargs):
        exact_budgets.append(max_states)
        return explore_slice(analysis, piece, initials, max_states, *args, **kwargs)

    monkeypatch.setattr(derived_proof, "explore", record)
    monkeypatch.setattr(explorer, "explore_slice", record_exact)
    actual = validate_spec(spec, max_states=32)
    assert projected == [True]
    assert exact_budgets and set(exact_budgets) == {32}
    with monkeypatch.context() as exact:
        exact.setattr(derived_proof, "derive", lambda *_, **__: None)
        expected = validate_spec(spec, max_states=32)
    assert actual.verdict == expected.verdict == "PASS"
    assert actual.exploration_findings == expected.exploration_findings
    assert actual.query_results[0].findings == expected.query_results[0].findings
    assert actual.query_results[0].states_explored == expected.query_results[0].states_explored


def test_safety_first_round_scales_with_exact_budget():
    class Data(Entity):
        value: int = 0
        audit: bool = False

    invariant = Invariant(Data.value <= 4100, id="limit")
    spec = Spec(
        id="scaling_safety",
        name="Scaling safety",
        invariants=[invariant],
        actions=[
            Action(
                id="grow",
                pre=[Data.value < 4100],
                effect=[Add(Data.value, 1), Set(Data.audit, True)],
            ),
        ],
    )
    probe = _check(spec, invariant, budget=20_000)
    assert probe.proved
    assert probe.graph.state_count == 4101
    assert not probe.previous_rounds


def test_firing_replay_uses_deduplicated_exact_roots(monkeypatch):
    class Data(Entity):
        ready: bool = False
        audit: bool = False
        unused: bool = False

    target = Action(id="target", pre=[Data.ready])
    enable = Action(id="enable", effect=[Set(Data.ready, True), Set(Data.audit, True)])
    spec = Spec(
        id="firing_roots",
        name="Firing roots",
        actions=[target, enable],
        initial=Initial(vary=[Data.unused]),
    )
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    piece = analysis.action_slice(target, canonical=True)
    assert len(roots) == 2
    proof = derived_proof.cover_defects(target, analysis, piece, roots, 128, canonical=True)
    assert proof is not None

    replay_path = derived_proof._replay_path

    def check_root_count(analysis, projection, graph, witness, root, number, multiple, **kwargs):
        assert not multiple
        return replay_path(analysis, projection, graph, witness, root, number, multiple, **kwargs)

    monkeypatch.setattr(derived_proof, "_replay_path", check_root_count)
    witness = derived_proof.firing_witness(target, analysis, piece, roots, proof)
    assert witness["root"] == 1
    assert witness["trace"] == ["enable", "target"]


def test_dead_actions_uses_a_concrete_prefix_when_projected_replay_fails(monkeypatch):
    class Data(Entity):
        progress: int = 0
        audit: bool = False

    advance = Action(id="advance", pre=[Data.progress < 100], effect=[Add(Data.progress, 1)])
    audit = Action(
        id="audit",
        pre=[Data.progress == 0],
        effect=[Set(Data.progress, 0), Set(Data.audit, True)],
    )
    target = Action(id="target", pre=[Data.progress == 1])
    spec = Spec(id="firing", name="Firing", actions=[advance, audit, target])
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    original = derived_proof.firing_witness

    def miss(action, *args):
        return None if action is target else original(action, *args)

    monkeypatch.setattr(derived_proof, "firing_witness", miss)
    witnesses = []
    covered = explorer.cover_actions(
        analysis, roots, 512, {}, canonical=True, firing_proofs=witnesses
    )
    witness = next(item for item in witnesses if item["action"] == "target")
    assert witness["trace"] == ["advance", "target"]
    assert witness["source"] == "concrete prefix"
    assert witness["states_explored"] == 128
    assert witness["complete"] is False
    assert not covered[id(target)].capped
    assert target.id in covered[id(target)].fired


def test_full_reachability_reuses_a_witness_on_a_capped_exact_graph(monkeypatch):
    class Data(Entity):
        value: int = 0
        audit: bool = False

    grow = Action(id="grow", effect=[Add(Data.value, 1), Set(Data.audit, True)])
    spec = Spec(
        id="exact_witness",
        name="Reuse exact witness",
        actions=[grow],
        queries=[Reachable(Data.value == 1, id="reach")],
    )
    analysis = SliceAnalysis(spec)
    roots, _ = build_canonical_initials(spec)
    cache = explorer.ExplorationStorage(analysis)
    piece = analysis.predicate_slice(spec.queries[0].predicate, canonical=True)
    exp, _ = explorer.explore_slice(analysis, piece, roots, 5, cache)
    assert exp.capped

    def unexpected_projection(*args, **kwargs):
        pytest.fail("exact graph already witnessed reachability")

    # Keep coverage complete so this test distinguishes exact witness reuse
    # from the independent cap on per-action defect coverage.
    monkeypatch.setattr(explorer, "cover_actions", lambda *args, **kwargs: {})
    monkeypatch.setattr(derived_proof, "reach_witness", unexpected_projection)
    result = explorer.run_query(spec.queries[0], spec, cache, max_states=5, analysis=analysis)
    assert result.status == "PASS"
    assert result.trace == ["grow"]
    assert result.states_explored == exp.state_count


def test_projected_attempt_keeps_candidate_report_after_releasing_graph():
    class Data(Entity):
        value: int = 0
        audit: bool = False

    invariant = Invariant(Data.value == 0, id="limit")
    spec = Spec(
        id="compact_candidate",
        name="Compact candidate",
        invariants=[invariant],
        actions=[Action(id="change", effect=[Set(Data.value, 1), Set(Data.audit, True)])],
    )
    analysis = SliceAnalysis(spec)
    analysis.retain_derived_graphs = False
    roots, _ = build_canonical_initials(spec)
    exact = analysis.invariant_slice(invariant, unconstrained=True)
    probe = derived_proof.attempt(invariant, analysis, exact, roots, 128)
    assert probe.replayed is not None
    assert not probe.graph.keys
    attempt = probe.report(replayed=True)["attempts"][0]
    assert attempt["states_explored"] == 2
    assert attempt["candidate_trace"] == ["change"]
    assert attempt["replayed"] is True
    assert probe.report(replayed=True)["attempts"][0] == attempt
