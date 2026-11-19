"""Parameterized actions: one declaration over finite domains (research/15)."""

from analint import Action, Add, Entity, Field, Param, Scenario, Set, Spec, Subtract
from analint.reporter.base import Severity
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import validate_structural


class Red(Entity):
    coins: int = Field(0, ge=0, le=5)


class Blue(Entity):
    coins: int = Field(0, ge=0, le=5)


def _transfer() -> Action:
    src = Param("src", Red, Blue)
    dst = Param("dst", Red, Blue)
    amount = Param("amount", 1, 2)
    return Action(
        id="transfer",
        params=[src, dst, amount],
        where=[src != dst],
        pre=[src.coins >= amount, dst.coins <= 5 - amount],
        effect=[Subtract(src.coins, amount), Add(dst.coins, amount)],
    )


def test_expansion_respects_domains_and_where():
    spec = Spec(id="s", name="S", entities=[Red, Blue], actions=[_transfer()])
    # 2 src × 2 dst × 2 amounts = 8, minus 4 self-transfers filtered by where
    assert len(spec.actions) == 4
    assert {a.id for a in spec.actions} == {
        "transfer(src=Red, dst=Blue, amount=1)",
        "transfer(src=Red, dst=Blue, amount=2)",
        "transfer(src=Blue, dst=Red, amount=1)",
        "transfer(src=Blue, dst=Red, amount=2)",
    }
    assert all(a.family == "transfer" for a in spec.actions)


def test_bind_is_memoized_and_identical_to_expansion():
    transfer = _transfer()
    bound = transfer.bind(src=Red, dst=Blue, amount=2)
    spec = Spec(id="s", name="S", entities=[Red, Blue], actions=[transfer])
    assert any(a is bound for a in spec.actions)
    assert transfer.bind(src=Red, dst=Blue, amount=2) is bound


def test_bound_action_substitutes_values_and_runs():
    transfer = _transfer()
    bound = transfer.bind(src=Red, dst=Blue, amount=2)
    sc = Scenario(id="sc", name="SC", action=bound, given=[Red(coins=3), Blue(coins=0)])
    spec = Spec(id="s", name="S", entities=[Red, Blue], actions=[transfer], scenarios=[sc])
    result = run_scenario(sc, spec)
    assert result.passed, [f.message for f in result.findings]


def test_bind_rejects_binding_outside_domain():
    transfer = _transfer()
    try:
        transfer.bind(src=Red, dst=Blue, amount=99)
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "domain" in str(e)


def test_bind_rejects_where_violation():
    transfer = _transfer()
    try:
        transfer.bind(src=Red, dst=Red, amount=1)
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "where" in str(e)


def test_bind_rejects_wrong_param_names():
    transfer = _transfer()
    try:
        transfer.bind(source=Red, dst=Blue, amount=1)
        raise AssertionError("should have raised")
    except TypeError as e:
        assert "needs exactly" in str(e)


def test_param_field_on_class_without_field_is_clear_error():
    class Wallet(Entity):
        balance: int = 0

    holder = Param("holder", Wallet)
    broken = Action(id="broken", params=[holder], pre=[holder.coins >= 1])
    try:
        broken.bind(holder=Wallet)
        raise AssertionError("should have raised")
    except TypeError as e:
        assert "has no field 'coins'" in str(e)


def test_scenario_coverage_is_per_family():
    transfer = _transfer()
    sc = Scenario(
        id="sc",
        name="SC",
        action=transfer.bind(src=Red, dst=Blue, amount=1),
        given=[Red(coins=3), Blue(coins=0)],
    )
    spec = Spec(id="s", name="S", entities=[Red, Blue], actions=[transfer], scenarios=[sc])
    warnings = [
        f
        for f in validate_structural(spec)
        if f.severity == Severity.WARNING and "has no scenarios" in f.message
    ]
    # one binding example covers the whole transfer family
    assert not warnings


def test_reachability_explores_all_bindings():
    from analint import Reachable
    from analint.validator.explorer import run_query

    transfer = _transfer()
    mint_red = Action(id="mint_red", pre=[Red.coins <= 3], effect=[Add(Red.coins, 1)])
    spec = Spec(id="s", name="S", entities=[Red, Blue], actions=[transfer, mint_red])
    result = run_query(Reachable(Blue.coins >= 2, id="q"), spec, cache={})
    assert result.status == "PASS"
    assert result.trace is not None
    assert any(step.startswith("transfer(") for step in result.trace)


def test_param_range_domain_matches_field_vocabulary():
    p = Param("amount", ge=1, le=3)
    assert p.domain == [1, 2, 3]


def test_param_enum_class_expands_to_members():
    from enum import StrEnum

    class Room(StrEnum):
        FOYER = "foyer"
        BAR = "bar"

    p = Param("room", Room)
    assert p.domain == [Room.FOYER, Room.BAR]


def test_param_bool_expands():
    p = Param("flag", bool)
    assert p.domain == [False, True]


def test_param_rejects_bare_int_and_mixed_forms():
    try:
        Param("n", int)
        raise AssertionError("should have raised")
    except TypeError as e:
        assert "infinite domain" in str(e)
    try:
        Param("n", 1, 2, ge=1, le=3)
        raise AssertionError("should have raised")
    except TypeError as e:
        assert "not both" in str(e)
    try:
        Param("n", ge=5, le=1)
        raise AssertionError("should have raised")
    except TypeError as e:
        assert "greater than" in str(e)


def test_bind_memo_does_not_serve_another_parents_instance():
    """Copied private state must not reuse another declaration's bindings."""
    from analint.models.param import bind_action

    class Box(Entity):
        n: int = 0

    v = Param("v", ge=0, le=1)
    stale_parent = Action(id="stale", params=[v], effect=[Set(Box.n, v)])
    stale = bind_action(stale_parent, {"v": 1})
    fresh_parent = stale_parent.model_copy(update={"id": "fresh", "effect": [Set(Box.n, 0)]})

    bound = bind_action(fresh_parent, {"v": 1})

    assert bound is not stale
    assert bound.id == "fresh(v=1)"


def test_numeric_param_operators_bind_without_identity_wrappers():
    import operator

    from analint.models.param import _resolve, _subst_pred
    from analint.validator.rule_checker import compile_predicate, evaluate, resolve

    p, q = Param("p", 2, 3), Param("q", 1, 4)
    for left, right in [(p, q), (p, 2), (2, p)]:
        for op in [operator.add, operator.sub, operator.mul]:
            expression = op(left, right)
            for pv in p.domain:
                for qv in q.domain:
                    binding = {"p": pv, "q": qv}
                    expected = op(_resolve(left, binding), _resolve(right, binding))
                    assert resolve(_resolve(expression, binding), {}) == expected
        for op in [operator.eq, operator.ne, operator.lt, operator.le, operator.gt, operator.ge]:
            predicate = op(left, right)
            for pv in p.domain:
                for qv in q.domain:
                    binding = {"p": pv, "q": qv}
                    expected = op(_resolve(left, binding), _resolve(right, binding))
                    bound = _subst_pred(predicate, binding)
                    assert evaluate(bound, {}) == expected
                    assert compile_predicate(bound)({}) == expected
    assert hash(p) == id(p)


def test_margin_family_filters_and_guards_use_direct_param_math():
    m, lev, notional = Param("m", 1, 2), Param("lev", 2, 3), Param("notional", 4, 5)
    family = Action(
        id="margin",
        params=[m, lev, notional],
        where=[m * lev <= notional, notional < (m + 1) * lev],
        pre=[lev <= Red.coins],
        effect=[Set(Blue.coins, 2 * m)],
    )
    spec = Spec(id="s", name="S", actions=[family])
    expected = {
        (mv, lv, nv)
        for mv in (1, 2)
        for lv in (2, 3)
        for nv in (4, 5)
        if mv * lv <= nv < (mv + 1) * lv
    }
    assert len(spec.actions) == len(expected)
    for mv, lv, nv in expected:
        bound = family.bind(m=mv, lev=lv, notional=nv)
        scenario = Scenario(id="s", action=bound, given=[Red(coins=3), Blue()])
        assert run_scenario(scenario, spec).passed


def test_param_field_multiplication_binds_to_state_reads():
    from analint.models.param import _resolve
    from analint.validator.rule_checker import resolve

    holder = Param("holder", Red)
    for expr in (holder.coins * 2, 2 * holder.coins):
        assert resolve(_resolve(expr, {"holder": Red}), {Red: Red(coins=3)}) == 6
