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
