"""Edits to parameter families cannot serve stale derived transitions (#11)."""

import gc
import weakref

import pytest

from analint import Action, Add, Entity, Event, Field, Param, Reachable, Scenario, Set, Spec
from analint.models.param import expand_action, refresh_bound_ids
from analint.validator import validate_spec
from analint.validator.kernel import Outcome, step


class Counter(Entity):
    n: int = Field(0, ge=0, le=4)


class Notice(Event):
    value: int


@pytest.mark.parametrize("edit", ["append", "replace", "nested"])
def test_guard_edits_refresh_the_scenario_and_expansion_identity(edit):
    p = Param("p", Counter)
    family = Action(id="tick", params=[p], pre=[p.n < 3], effect=[Add(p.n, 1)])
    bound = family.bind(p=Counter)
    scenario = Scenario(id="tick_once", action=bound, given=[Counter()])
    original = Spec(id="s", name="S", actions=[family], scenarios=[scenario])
    assert validate_spec(original).verdict == "PASS"
    if edit == "append":
        family.pre.append(p.n < 0)
    elif edit == "replace":
        family.pre = [p.n < 0]
    else:
        family.pre[0].right = 0
    refreshed = Spec(id="edited", name="Edited", actions=[family], scenarios=[scenario])
    assert refreshed.actions[0] is bound is family.bind(p=Counter)
    assert step(refreshed, bound, {Counter: Counter()}).outcome is Outcome.REJECTED
    assert validate_spec(refreshed).verdict == "FAIL"


def test_effect_post_emission_and_metadata_edits_are_rebound():
    p = Param("p", 1, 2)
    family = Action(
        id="tick",
        params=[p],
        effect=[Set(Counter.n, p)],
        post=[Counter.n == p],
        emits=[Notice(value=Counter.n + p)],
        tags=["old"],
    )
    bound = family.bind(p=1)
    family.effect[0].value = p + 1
    family.post[0].right = p + 1
    family.emits[0].value = Counter.n + p + 1
    family.name, family.description, family.tags = "Updated", "Current template", ["new"]
    assert family.bind(p=1) is bound
    spec = Spec(id="s", name="S", actions=[family])
    result = step(spec, bound, {Counter: Counter()})
    assert result.outcome is Outcome.ACCEPTED
    assert result.post_context[Counter].n == 2
    assert result.emitted[0].value == 4
    assert (bound.name, bound.description, bound.tags) == ("Updated", "Current template", ["new"])
    family.post = [Counter.n == 0]
    family.bind(p=1)
    assert step(spec, bound, {Counter: Counter()}).outcome is Outcome.DEFECT


@pytest.mark.parametrize("deep", [False, True])
def test_copied_families_do_not_refresh_original_bindings(deep):
    p = Param("p", 1)
    family = Action(id="original", params=[p], effect=[Set(Counter.n, p)])
    original = family.bind(p=1)
    copied = family.model_copy(deep=deep)
    copied.id = "copied"
    copied.effect = [Set(Counter.n, 2)]
    bound = copied.bind(p=1)
    assert bound is not original
    assert (original.id, bound.id) == ("original(p=1)", "copied(p=1)")
    spec = Spec(id="s", name="S", actions=[family, copied])
    assert step(spec, original, {Counter: Counter()}).post_context[Counter].n == 1
    assert step(spec, bound, {Counter: Counter()}).post_context[Counter].n == 2


def test_current_domains_and_where_clauses_are_checked_before_refresh():
    p = Param("p", 1, 2)
    family = Action(id="tick", params=[p], effect=[Set(Counter.n, p)])
    one, two = expand_action(family)
    family.where = [p == 2]
    remaining = expand_action(family)
    assert len(remaining) == 1 and remaining[0] is two
    with pytest.raises(ValueError, match="where"):
        family.bind(p=1)
    p.domain[:] = [1]
    with pytest.raises(ValueError, match="domain"):
        family.bind(p=2)
    assert expand_action(family) == []
    # Existing models are not silently re-expanded when membership changes.
    assert one.id == "tick(p=1)"


def test_failed_substitution_does_not_partially_refresh_a_bound_action():
    p = Param("p", Counter)
    family = Action(id="tick", params=[p], pre=[p.n < 3], effect=[Add(p.n, 1)])
    bound = family.bind(p=Counter)
    family.pre = [p.n < 0]
    family.effect = [Set(p.missing, 0)]
    with pytest.raises(TypeError, match="has no field"):
        family.bind(p=Counter)
    assert bound.pre[0].right == 3


def test_naming_existing_bindings_does_not_recheck_where():
    p = Param("p", 1)
    family = Action(params=[p], effect=[Set(Counter.n, p)])
    bound = family.bind(p=1)
    family.id, family.where = "named", [p == 0]
    refresh_bound_ids(family)
    assert bound.id == "named(p=1)" and bound.family == "named"


def test_releasing_a_family_releases_its_binding_memo_but_live_results_survive():
    p = Param("p", 1, 2)
    family = Action(id="tick", params=[p], effect=[Set(Counter.n, p)])
    retained, discarded = expand_action(family)
    owner_ref, discarded_ref = weakref.ref(family), weakref.ref(discarded)
    del family, discarded
    gc.collect()
    assert owner_ref() is None and discarded_ref() is None
    spec = Spec(id="s", name="S", actions=[retained])
    assert step(spec, retained, {Counter: Counter()}).post_context[Counter].n == 1


@pytest.mark.parametrize("cache", [False, True])
def test_reexpanded_edits_change_verification_without_stale_disk_cache(
    tmp_path, monkeypatch, cache
):
    monkeypatch.setenv("ANALINT_CACHE_DIR", str(tmp_path / "cache"))
    p = Param("p", Counter)
    family = Action(id="tick", params=[p], pre=[p.n < 2], effect=[Add(p.n, 1)])
    query = Reachable(Counter.n == 2, id="two")
    original = Spec(id="s", name="S", actions=[family], queries=[query])
    assert validate_spec(original, cache=cache).query_results[0].status == "PASS"
    family.effect = [Set(p.n, 0)]
    edited = Spec(id="s", name="S", actions=[family], queries=[query])
    for _ in range(2):
        report = validate_spec(edited, cache=cache)
        assert report.query_results[0].status == "FAIL"
        assert report.verdict == "FAIL"
