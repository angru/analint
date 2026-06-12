"""Parameterized actions: one declaration over finite domains (research/15)."""

from analint import Action, Add, Entity, Field, Param, Scenario, Spec, Subtract
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
