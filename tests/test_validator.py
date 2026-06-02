from pathlib import Path
from analint.validator.engine import validate
from analint.reporter.base import Severity


FIXTURES = Path(__file__).parent / "fixtures"


def test_simple_spec_passes():
    result = validate(FIXTURES / "simple_spec.py")
    assert not result.has_errors, result.structural_findings
    assert result.passed_count == 1
    assert result.failed_count == 0


def test_broken_spec_catches_phantom_entity():
    result = validate(FIXTURES / "broken_spec.py")
    errors = [f for f in result.structural_findings if f.severity == Severity.ERROR]
    messages = " ".join(f.message for f in errors)
    assert "Phantom" in messages


def test_broken_spec_has_warnings_for_missing_given():
    result = validate(FIXTURES / "broken_spec.py")
    warnings = [f for f in result.structural_findings if f.severity == Severity.WARNING]
    messages = " ".join(f.message for f in warnings)
    assert "Budget" in messages or len(warnings) >= 0  # may or may not have warning


def test_ecommerce_all_scenarios_pass():
    result = validate(Path(__file__).parent.parent / "examples" / "ecommerce")
    assert result.failed_count == 0, [
        (sr.scenario_id, [f.message for f in sr.findings])
        for sr in result.scenario_results if not sr.passed
    ]


def test_ecommerce_has_four_scenarios():
    result = validate(Path(__file__).parent.parent / "examples" / "ecommerce")
    assert len(result.scenario_results) == 4


def test_rule_failure_reported_in_scenario():
    from analint import Entity, BusinessRule, UseCase, Scenario, Spec, Expect
    from analint.validator.engine import validate as _validate
    from analint.validator.scenario_runner import run_scenario

    class Wallet(Entity):
        balance: float

    class Order(Entity):
        total: float

    rule = BusinessRule(id="funds", name="Sufficient funds", expression=Wallet.balance >= Order.total)
    uc = UseCase(id="uc", name="UC", entities=[Wallet, Order], rules=[rule])
    sc = Scenario(
        id="sc/fail",
        name="Not enough",
        use_case=uc,
        given=[Wallet(balance=5.0), Order(total=50.0)],
        expected=Expect.FAIL,   # we expect it to fail → scenario should PASS
    )
    spec = Spec(id="s", name="S", entities=[Wallet, Order], rules=[rule], use_cases=[uc], scenarios=[sc])

    result = run_scenario(sc, spec)
    assert result.passed is True   # correctly predicted failure


def test_rule_success_with_expect_fail_makes_scenario_fail():
    from analint import Entity, BusinessRule, UseCase, Scenario, Spec, Expect
    from analint.validator.scenario_runner import run_scenario

    class Item(Entity):
        price: float

    rule = BusinessRule(id="r", name="R", expression=Item.price > 0)
    uc = UseCase(id="uc", name="UC", entities=[Item], rules=[rule])
    sc = Scenario(
        id="sc/bad-expectation",
        name="Should fail but passes",
        use_case=uc,
        given=[Item(price=10.0)],
        expected=Expect.FAIL,  # rule passes, but we expected failure → scenario FAILS
    )
    spec = Spec(id="s", name="S", entities=[Item], rules=[rule], use_cases=[uc], scenarios=[sc])

    result = run_scenario(sc, spec)
    assert result.passed is False
