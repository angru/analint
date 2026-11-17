"""Python must never discard part of a symbolic condition before validation."""

import pytest

from analint import And, Bound, Count, Entity, ForAll, Key, Not, Or, Param, Scope, Sum
from analint.validator.engine import validate
from analint.validator.rule_checker import evaluate


class Account(Entity):
    balance: int = 0
    enabled: bool = True


accounts = Scope(Account, keys=["a"])
bound = Bound("account", accounts)
param = Param("account", accounts)


@pytest.mark.parametrize(
    "value",
    [
        Account.balance >= 0,
        Account.enabled,
        accounts["a"].enabled,
        bound.enabled,
        param.enabled,
        param,
        Account.balance + 1,
        Key(accounts["a"]),
        Sum(bound, bound.balance),
        Count(bound, bound.enabled),
        ForAll(bound, bound.enabled),
    ],
)
def test_symbolic_values_reject_truth_conversion(value):
    with pytest.raises(TypeError, match="use And/Or/Not"):
        bool(value)


@pytest.mark.parametrize(
    "expression",
    [
        "(Account.balance >= 0) and Account.enabled",
        "(Account.balance >= 0) or Account.enabled",
        "not Account.enabled",
        "0 <= Account.balance <= 100",
        "1 if Account.enabled else 0",
    ],
)
def test_invalid_python_conditions_fail_loading(tmp_path, expression):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Entity, Scenario, Spec\n"
        "class Account(Entity):\n"
        "    balance: int = -10\n"
        "    enabled: bool = True\n"
        f"a = Action(pre=[{expression}])\n"
        "s = Scenario(name='negative balance', action=a, given=[Account()])\n"
        "spec = Spec(id='s', name='S', actions=[a], scenarios=[s])\n"
    )
    result = validate(entry)
    assert result.verdict == "FAIL"
    assert any("use And/Or/Not" in error for error in result.load_errors)


def test_supported_combinators_preserve_both_operands():
    context = {Account: Account(balance=-10, enabled=True)}
    assert not evaluate(And(Account.balance >= 0, Account.enabled), context)
    assert evaluate(Or(Account.balance >= 0, Account.enabled), context)
    assert not evaluate(Not(Account.enabled), context)
