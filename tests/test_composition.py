from pathlib import Path

from analint import Action, Contract, Entity, Spec
from analint.query import describe, spec_overview
from analint.validator.engine import build_spec, validate
from analint.validator.structural import validate_structural

FIXTURES = Path(__file__).parent / "fixtures"


def test_contract_content_is_composed_by_identity():
    class Account(Entity):
        balance: int = 0

    deposit = Action(id="deposit")
    contract = Contract(
        id="accounts",
        entities=[Account],
        actions=[deposit],
    )

    spec = Spec(
        id="shop",
        name="Shop",
        imports=[contract],
        entities=[Account],
        actions=[deposit],
    )

    assert spec.entities == [Account]
    assert spec.actions == [deposit]


def test_composed_loader_only_includes_explicit_contract_surface():
    spec, _, errors = build_spec(FIXTURES / "composed")

    assert errors == []
    assert spec is not None
    assert [contract.id for contract in spec.imports] == ["ledger"]
    assert [entity.__name__ for entity in spec.entities] == ["Ledger"]
    assert [action.id for action in spec.actions] == ["credit"]
    assert [scenario.id for scenario in spec.scenarios] == ["credit/once"]


def test_composed_spec_validates_end_to_end():
    result = validate(FIXTURES / "composed")

    assert not result.has_errors
    assert [scenario.scenario_id for scenario in result.scenario_results] == ["credit/once"]


def test_what_if_patch_extends_composed_spec_without_private_leak(tmp_path):
    patch = tmp_path / "hypothesis.py"
    patch.write_text(
        "\n".join(
            [
                "from analint import Invariant",
                "from tests.fixtures.composed.component import Ledger",
                "",
                "balance_has_an_upper_bound = Invariant(Ledger.balance <= 10)",
            ]
        )
    )

    spec, _, errors = build_spec(FIXTURES / "composed", extra=patch)

    assert errors == []
    assert spec is not None
    assert [item.id for item in spec.invariants] == [
        "balance_is_non_negative",
        "balance_has_an_upper_bound",
    ]
    assert [action.id for action in spec.actions] == ["credit"]


def test_multiple_specs_require_explicit_composition():
    spec, _, errors = build_spec(FIXTURES / "multiple_specs.py")

    assert spec is None
    assert len(errors) == 1
    assert "multiple Spec objects found" in str(errors[0])
    assert "Contract" in str(errors[0])


def test_duplicate_contract_ids_are_structural_errors():
    first = Contract(id="shared")
    second = Contract(id="shared")
    spec = Spec(id="root", name="Root", imports=[first, second])

    findings = validate_structural(spec)

    assert any("duplicate imported contract id 'shared'" in finding.message for finding in findings)


def test_contract_is_available_on_agent_query_surface():
    contract = Contract(id="payments", name="Payments", version="2.1.0")
    spec = Spec(id="root", name="Root", imports=[contract])

    overview = spec_overview(spec)
    detail = describe(spec, "contract", "payments")

    assert overview["contracts"] == [{"id": "payments", "name": "Payments", "version": "2.1.0"}]
    assert detail["kind"] == "contract"
    assert detail["version"] == "2.1.0"
