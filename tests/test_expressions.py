"""Arithmetic expression AST: field math as serializable nodes (research/15)."""

from analint import (
    Action,
    AlwaysHolds,
    Assert,
    Entity,
    Field,
    Invariant,
    Param,
    Scenario,
    Set,
    Spec,
)
from analint.reporter.base import Severity
from analint.validator.explorer import run_query
from analint.validator.rule_checker import evaluate
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import _describe, validate_structural


class Wallet(Entity):
    balance: float = 100.0


class Order(Entity):
    total: float = 30.0


def _ctx(*instances):
    return {type(inst): inst for inst in instances}


def test_field_arithmetic_in_predicates():
    pred = Wallet.balance - Order.total >= 0
    assert evaluate(pred, _ctx(Wallet(balance=50.0), Order(total=30.0)))
    assert not evaluate(pred, _ctx(Wallet(balance=10.0), Order(total=30.0)))


def test_chained_sum_expression():
    class A(Entity):
        x: int = 1

    class B(Entity):
        x: int = 2

    class C(Entity):
        x: int = 3

    total = A.x + B.x + C.x
    assert evaluate(total == 6, _ctx(A(), B(), C()))
    assert evaluate(2 * A.x + 1 == 3, _ctx(A(), B(), C()))


def test_expression_describes_readably():
    assert _describe(Wallet.balance - Order.total >= 0) == ("(Wallet.balance - Order.total) >= 0")


def test_set_with_expression_is_simultaneous():
    class Acc(Entity):
        a: int = 10
        b: int = 0

    swapish = Action(
        id="act",
        effect=[
            Set(Acc.a, Acc.a - 4),
            Set(Acc.b, Acc.a + 1),  # must read the OLD a (10), not 6
        ],
    )
    sc = Scenario(
        id="sc",
        name="SC",
        action=swapish,
        given=[Acc()],
        then=[Assert(Acc.a == 6), Assert(Acc.b == 11)],
    )
    spec = Spec(id="s", name="S", entities=[Acc], actions=[swapish], scenarios=[sc])
    result = run_scenario(sc, spec)
    assert result.passed, [f.message for f in result.findings]


def test_invariant_over_expression_in_explorer():
    class Left(Entity):
        coins: int = Field(0, ge=0, le=3)

    class Right(Entity):
        coins: int = Field(0, ge=0, le=3)

    mint_left = Action(
        id="mint_left", pre=[Left.coins <= 2], effect=[Set(Left.coins, Left.coins + 1)]
    )
    mint_right = Action(
        id="mint_right", pre=[Right.coins <= 2], effect=[Set(Right.coins, Right.coins + 1)]
    )
    spec = Spec(id="s", name="S", entities=[Left, Right], actions=[mint_left, mint_right])
    result = run_query(AlwaysHolds(Left.coins + Right.coins <= 4, id="q"), spec, cache={})
    assert result.status == "FAIL"
    assert result.trace is not None and len(result.trace) == 5  # 3 + 2 mints


def test_param_inside_field_expression():
    class Pot(Entity):
        coins: int = Field(5, ge=0, le=9)

    n = Param("n", 2, 3)
    take = Action(
        id="take",
        params=[n],
        pre=[Pot.coins >= n],
        effect=[Set(Pot.coins, Pot.coins - n)],
    )
    bound = take.bind(n=3)
    sc = Scenario(id="sc", name="SC", action=bound, given=[Pot()], then=[Assert(Pot.coins == 2)])
    spec = Spec(id="s", name="S", entities=[Pot], actions=[take], scenarios=[sc])
    assert run_scenario(sc, spec).passed


def test_expression_refs_feed_coverage_warnings():
    inv = Invariant(Wallet.balance - Order.total >= 0, id="inv")
    act = Action(id="act", pre=[Wallet.balance > 0])
    sc = Scenario(id="sc", name="SC", action=act, given=[Wallet()])
    spec = Spec(
        id="s", name="S", entities=[Wallet], actions=[act], scenarios=[sc], invariants=[inv]
    )
    errors = [f for f in validate_structural(spec) if f.severity == Severity.ERROR]
    # the invariant's expression references Order, which is not registered
    assert any("'Order' not in spec.entities" in f.message for f in errors)
