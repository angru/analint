"""An action's own guard must retain the writers that enable it (#41)."""

from itertools import permutations

import pytest

from analint import Action, Add, And, DeadActions, Entity, Field, Not, Set, Spec
from analint.validator.engine import validate_spec
from analint.validator.slicing import SliceAnalysis


def _model(order=(0, 1, 2), off=True, defect=False, missing_writer=False):
    class Market(Entity):
        news: bool = not off

    class Wallet(Entity):
        n: int = Field(0, ge=0, le=3)

    starts = Action(id="news_starts", pre=[Market.news != off], effect=[Set(Market.news, off)])
    ends = Action(
        id="news_ends",
        pre=[Market.news == off],
        effect=[Set(Market.news, not off)],
        post=[Not(And())] if defect else [],
    )
    trade = Action(id="trade", pre=[Market.news != off, Wallet.n < 3], effect=[Add(Wallet.n, 1)])
    actions = [starts, ends, trade]
    query = DeadActions(id="dead")
    spec = Spec(
        id="flags",
        name="Flags",
        actions=[actions[i] for i in order if not missing_writer or i != 0],
        queries=[query],
    )
    return spec, starts, ends, trade


@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("off", [False, True])
@pytest.mark.parametrize("budget", [2, 4, 8, 100])
def test_dead_actions_agrees_across_orders_budgets_and_flag_polarity(order, off, budget):
    spec, _, _, _ = _model(order, off)
    whole = validate_spec(spec, sliced=False, max_states=budget)
    sliced = validate_spec(spec, sliced=True, max_states=budget)
    assert sliced.query_results[0].status in {"PASS", "INCONCLUSIVE"}
    if whole.query_results[0].status == "PASS":
        assert sliced.query_results[0].status == "PASS"
    # Smaller slices may finish within a budget that caps the whole graph.
    if budget >= 8:
        assert sliced.query_results[0].status == whole.query_results[0].status == "PASS"


def test_action_slice_retains_enabling_writer_without_disabling_property_optimization():
    spec, starts, ends, trade = _model()
    analysis = SliceAnalysis(spec)
    assert analysis.flags
    piece = analysis.action_slice(ends, canonical=True)
    assert {a.id for a in piece.actions} == {starts.id, ends.id}
    # The guard of trade already holds when the flag is on: its property slice
    # can still omit the writer that only disables it.
    trade_slice = analysis.action_slice(trade, canonical=True)
    assert starts.id not in {a.id for a in trade_slice.actions}
    property_slice = analysis.predicate_slice(trade.effect[0].field == 3, canonical=True)
    assert starts.id not in {a.id for a in property_slice.actions}


@pytest.mark.parametrize("defect", [False, True])
def test_real_dead_action_and_hidden_transition_defect_remain_failures(defect):
    spec, _, _, _ = _model(defect=defect, missing_writer=not defect)
    for sliced in (False, True):
        result = validate_spec(spec, sliced=sliced)
        assert result.verdict == "FAIL"
        if defect:
            assert any(f.location == "action:news_ends" for f in result.exploration_findings)
        else:
            assert any("news_ends" in f.message for f in result.query_results[0].findings)


def test_cold_warm_cache_does_not_restore_false_dead_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    spec, _, _, _ = _model()
    for cache in (False, True, True):
        assert validate_spec(spec, cache=cache).verdict == "PASS"


@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("off", [False, True])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("budget", [1, 2, 4, 20])
def test_local_enabler_from_off_roots_keeps_order_budget_and_root_parity(order, off, owned, budget):
    from analint import Initial

    spec, _, ends, _ = _model(order, off)
    market = ends.effect[0].field.entity_cls
    initial = Initial(given=[market(news=off)])
    if owned:
        spec.queries[0].initial = initial
    else:
        spec.initial = initial
    whole = validate_spec(spec, sliced=False, max_states=budget)
    sliced = validate_spec(spec, sliced=True, max_states=budget)
    assert sliced.query_results[0].status in {"PASS", "INCONCLUSIVE"}
    if budget >= 20:
        assert sliced.verdict == whole.verdict == "PASS"
    if whole.query_results[0].status == "PASS":
        assert sliced.query_results[0].status == "PASS"


def _coupled_enabler(*, late_defect=False, off=False):
    from analint import Initial, Reachable

    class Box(Entity):
        flag: bool = off

    class Counter(Entity):
        n: int = Field(0, ge=0, le=2)

    arm = Action(
        id="arm",
        pre=[Box.flag == off],
        effect=[Set(Box.flag, not off)],
        post=[Counter.n < 1] if late_defect else [],
    )
    reset = Action(
        id="reset",
        pre=[Box.flag != off, Counter.n < 2],
        effect=[Set(Box.flag, off), Add(Counter.n, 1)],
    )
    target = Reachable(Counter.n == 2, id="target")
    spec = Spec(
        id="coupled",
        name="Coupled",
        actions=[arm, reset],
        queries=[DeadActions(id="dead"), target],
        initial=Initial(),
    )
    return spec, arm, reset


@pytest.mark.parametrize("off", [False, True])
@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("late_defect", [False, True])
def test_later_enabler_defect_and_repeated_paths_survive_optimization(
    off, selected, late_defect, tmp_path, monkeypatch
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    spec, arm, _ = _coupled_enabler(late_defect=late_defect, off=off)
    options = {"checks": ["target"]} if selected else {}
    whole = validate_spec(spec, sliced=False, **options)
    for cache in (False, True, True):
        result = validate_spec(spec, cache=cache, **options)
        assert result.verdict == whole.verdict == ("FAIL" if late_defect else "PASS")
        if late_defect:
            assert any(
                f.location == f"action:{arm.id}" and "reset" in f.message
                for f in result.exploration_findings
            )


@pytest.mark.parametrize("late_defect", [False, True])
def test_only_local_enablers_qualify_for_narrow_defect_coverage(late_defect):
    from analint.validator.explorer import build_canonical_initials

    spec, arm, reset = _coupled_enabler(late_defect=late_defect)
    analysis = SliceAnalysis(spec)
    initials, _ = build_canonical_initials(spec)
    narrow = analysis.local_enabler_slice(arm, initials, canonical=True)
    if late_defect:
        assert narrow is None
    else:
        assert {a.id for a in narrow.actions} == {arm.id}
        assert reset.id in {a.id for a in analysis.action_slice(arm, canonical=True).actions}


@pytest.mark.parametrize("late_defect", [False, True])
def test_enabler_coverage_retains_native_tlc_verdicts(late_defect):
    from analint.backends.tlc import TlcUnavailable, find_tlc

    try:
        find_tlc()
    except TlcUnavailable as exc:
        pytest.skip(str(exc))
    spec, _, _ = _coupled_enabler(late_defect=late_defect)
    native = validate_spec(spec, checks=["target"])
    fallback = validate_spec(spec, checks=["target"], max_states=1, tlc=True)
    assert fallback.verdict == native.verdict == ("FAIL" if late_defect else "PASS")


def test_capped_local_enabler_probe_widens_even_after_firing():
    from analint.validator.explorer import build_canonical_initials, cover_actions

    spec, arm, _ = _coupled_enabler()
    analysis = SliceAnalysis(spec)
    initials, _ = build_canonical_initials(spec)
    wide = analysis.action_slice(arm, canonical=True)
    covered = cover_actions(analysis, initials, 2, {}, canonical=True)
    assert covered[id(arm)].capped
    assert any(
        piece.key == wide.key and graph is covered[id(arm)]
        for runs in analysis.explored.values()
        for piece, graph in runs
    )


def test_local_terminal_lock_only_rejects_and_does_not_hide_defects():
    from enum import Enum

    from analint import Lifecycle
    from analint.validator.explorer import build_canonical_initials

    class Status(Enum):
        OPEN = "open"
        CLOSED = "closed"

    class Box(Entity):
        flag: bool = False
        status: Status = Lifecycle(
            Status.OPEN, transitions={Status.OPEN: [Status.CLOSED]}, terminal=[Status.CLOSED]
        )

    arm = Action(id="arm", pre=[Not(Box.flag)], effect=[Set(Box.flag, True)])
    close = Action(id="close", effect=[Set(Box.flag, False), Set(Box.status, Status.CLOSED)])
    spec = Spec(id="locked", name="Locked", actions=[arm, close], queries=[DeadActions(id="dead")])
    analysis = SliceAnalysis(spec)
    initials, _ = build_canonical_initials(spec)
    assert analysis.local_enabler_slice(arm, initials, canonical=True) is not None
    assert validate_spec(spec).verdict == validate_spec(spec, sliced=False).verdict == "PASS"
