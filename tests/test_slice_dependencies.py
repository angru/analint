"""Explain why a contract enters the ordinary property closure."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from analint import (
    Action,
    Add,
    AlwaysHolds,
    Contract,
    DeadActions,
    Entity,
    Field,
    Invariant,
    Reachable,
    Spec,
)
from analint.cli import app
from analint.mcp_server import check_spec
from analint.reporter.json_reporter import result_to_dict
from analint.validator.engine import validate_spec


def contracts(coupling):
    class Orders(Entity):
        count: int = Field(0, ge=0, le=2)

    class Payments(Entity):
        count: int = Field(0, ge=0, le=2)

    guard = [Orders.count < 2]
    if coupling == "guard":
        guard.append(Payments.count > 0)
    order = Action(id="order", pre=guard, effect=[Add(Orders.count, 1)])
    pay = Action(id="pay", pre=[Payments.count < 2], effect=[Add(Payments.count, 1)])
    ordered = Reachable(Orders.count == 1, id="ordered", given=[Orders()])
    safe = AlwaysHolds(Orders.count <= 2, id="safe", given=[Orders()])
    link = Invariant(Orders.count <= Payments.count, id="funded")
    return Spec(
        id="shop",
        name="Shop",
        imports=[Contract(id="orders", actions=[order]), Contract(id="payments", actions=[pay])],
        invariants=[link] if coupling == "invariant" else [],
        queries=[ordered, safe, DeadActions(id="actions")],
    )


def parents(report):
    return {row["member"]: (row["from"], row["reason"]) for row in report["inclusions"]}


@pytest.mark.parametrize("coupling", ["independent", "guard", "invariant"])
@pytest.mark.parametrize("budget", [2, 100])
def test_contract_inclusion_paths_preserve_the_check(coupling, budget):
    spec = contracts(coupling)
    opts = {"checks": ["ordered"], "max_states": budget}
    plain = result_to_dict(validate_spec(spec, **opts))
    explained = result_to_dict(validate_spec(spec, **opts, explain_slice=True))
    prop = explained["queries"][0]
    report = prop.pop("slice_dependencies")
    assert "slice_dependencies" not in plain["queries"][0]
    for result in (plain, explained):
        result["queries"][0].pop("elapsed_ms")
    assert plain == explained
    assert report["mode"] == "constrained"
    expected = {
        "field:Orders.count": ("property", "property_reads"),
        "action:order": ("field:Orders.count", "writer_of_field"),
    }
    if coupling == "guard":
        expected["field:Payments.count"] = ("action:order", "action_reads")
    if coupling == "invariant":
        expected["invariant:funded"] = ("field:Orders.count", "pruning_invariant")
        expected["field:Payments.count"] = ("invariant:funded", "invariant_reads")
    if coupling != "independent":
        expected["action:pay"] = ("field:Payments.count", "writer_of_field")
    assert parents(report) == expected


def test_selected_safety_proof_keeps_its_own_unconstrained_reasons():
    result = validate_spec(contracts("invariant"), checks=["safe"], explain_slice=True)
    check = result.query_results[0]
    assert check.status == "PASS"
    assert check.slice_dependencies["mode"] == "unconstrained"
    assert set(parents(check.slice_dependencies)) == {"field:Orders.count", "action:order"}


def test_per_action_and_whole_model_checks_do_not_claim_field_paths():
    spec = contracts("guard")
    for query, sliced, mode in [
        ("actions", True, "no_property_closure"),
        ("ordered", False, "slicing_disabled"),
    ]:
        check = validate_spec(
            spec, checks=[query], sliced=sliced, explain_slice=True
        ).query_results[0]
        assert check.slice_dependencies == {
            "scope": "property_closure",
            "mode": mode,
            "inclusions": [],
        }


def test_cli_and_mcp_agree_on_paths_for_a_composed_model():
    path = str(Path(__file__).parent / "fixtures/composed")
    args = ["check", path, "--explain-slice"]
    runner = CliRunner()
    cli = json.loads(runner.invoke(app, [*args, "-f", "json"]).stdout)
    mcp = check_spec(path, explain_slice=True, compact=True)
    ir = cli["invariants"][0]
    assert ir["slice_dependencies"] == mcp["invariants"][0]["slice_dependencies"]
    assert ir["slice_dependencies"]["inclusions"]
    assert "Property closure" in runner.invoke(app, args).stdout


def test_same_slice_has_separate_inclusion_paths_for_each_property():
    class Pair(Entity):
        left: int = Field(0, ge=0, le=1)
        right: int = Field(0, ge=0, le=1)

    tick = Action(id="tick", pre=[Pair.left < 1], effect=[Add(Pair.left, 1), Add(Pair.right, 1)])
    queries = [Reachable(Pair.left == 1, id="left"), Reachable(Pair.right == 1, id="right")]
    spec = Spec(id="pair", name="Pair", actions=[tick], queries=queries)
    for check, source, other in zip(
        validate_spec(spec, explain_slice=True).query_results,
        ["left", "right"],
        ["right", "left"],
        strict=True,
    ):
        tree = parents(check.slice_dependencies)
        assert tree[f"field:Pair.{source}"] == ("property", "property_reads")
        assert tree["action:tick"] == (f"field:Pair.{source}", "writer_of_field")
        assert tree[f"field:Pair.{other}"] == ("action:tick", "action_writes")
