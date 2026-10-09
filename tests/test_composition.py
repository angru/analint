from pathlib import Path

from analint import Action, Contract, Entity, Spec
from analint.query import describe, spec_overview
from analint.reporter.base import Severity
from analint.validator.engine import build_spec, prepare_model, validate
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


# ── Orphan behaviour and naming (research/35 R3/R4) ───────────────────────────


def _orphans(model) -> list[str]:
    return [f.location for f in model.structural_findings if "not part of the model" in f.message]


def test_unexported_behaviour_is_excluded_and_reported():
    model = prepare_model(FIXTURES / "composed")

    assert "reset-private" not in [action.id for action in model.spec.actions]
    assert _orphans(model) == ["action:reset-private"]


_PARAM_SPEC = """
from analint import Action, Add, Contract, Entity, Field, Param, Scope, Spec


class Counter(Entity):
    value: int = Field(0, ge=0, le=2)


counters = Scope(Counter, keys=["a", "b"])
c = Param("c", counters)
tick = Action(params=[c], pre=[c.value < 2], effect=[Add(c.value, 1)])
part = Contract(id="part", entities=[Counter], scopes=[counters], actions=[tick])
spec = Spec(id="p", name="p", imports=[part])
"""


def test_composed_param_action_is_named_after_expansion(tmp_path):
    # The Spec expands `tick` at import time, before the loader names it.
    entry = tmp_path / "spec.py"
    entry.write_text(_PARAM_SPEC)
    patch = tmp_path / "hypothesis.py"
    patch.write_text(
        "from analint import Action, Param, Subtract\n"
        "from analint_spec import counters\n"
        "d = Param('d', counters)\n"
        "untick = Action(params=[d], pre=[d.value > 0], effect=[Subtract(d.value, 1)])\n"
    )

    model = prepare_model(entry, what_if=patch)

    assert [action.id for action in model.spec.actions] == [
        "tick(c=Counter['a'])",
        "tick(c=Counter['b'])",
        "untick(d=Counter['a'])",
        "untick(d=Counter['b'])",
    ]
    assert not model.has_structural_errors
    assert _orphans(model) == []


def test_explicit_list_reports_the_omitted_action(tmp_path):
    entry = tmp_path / "spec.py"
    entry.write_text(
        "from analint import Action, Spec\n"
        "listed = Action()\n"
        "forgotten = Action()\n"
        "spec = Spec(id='s', name='s', actions=[listed])\n"
    )

    model = prepare_model(entry)

    assert [action.id for action in model.spec.actions] == ["listed"]
    assert _orphans(model) == ["action:forgotten"]


def test_reference_closure_derives_model_from_behaviour():
    """research/35 R2 probe 3: an entity referenced only by a scenario's
    ``given`` (and lifecycles, events, scopes reached from behaviour) join the
    model without being listed."""
    from enum import StrEnum

    from analint import Event, Lifecycle, Scenario, Scope, Set

    class Phase(StrEnum):
        OPEN = "open"
        DONE = "done"

    class Task(Entity):
        phase: Phase = Lifecycle(Phase.OPEN, transitions={Phase.OPEN: [Phase.DONE]})

    class Witness(Entity):
        seen: bool = False

    class Closed(Event):
        ok: bool = True

    class Slot(Entity):
        used: bool = False

    slots = Scope(Slot, keys=["a"], id="slots")
    close = Action(
        id="close",
        pre=[Task.phase == Phase.OPEN],
        effect=[Set(Task.phase, Phase.DONE), Set(slots["a"].used, True)],
        emits=[Closed],
    )
    sc = Scenario(id="close/ok", name="close", action=close, given=[Task(), Witness()])
    spec = Spec(id="s", name="s", imports=[Contract(id="tasks", actions=[close], scenarios=[sc])])

    assert spec.entities == [Task, Slot, Witness]
    assert spec.events == [Closed]
    assert spec.scopes == [slots]
    assert [lc.initial for lc in spec.lifecycles] == [Phase.OPEN]
    assert not [f for f in validate_structural(spec) if f.severity == Severity.ERROR]


def test_two_scopes_over_one_entity_across_contracts_is_an_error():
    """research/35 R2 probe 4: closure must not silently merge two universes."""
    from analint import Scope, Set

    class Slot(Entity):
        used: bool = False

    left = Scope(Slot, keys=["a"], id="left")
    right = Scope(Slot, keys=["b"], id="right")
    use_left = Action(id="use_left", effect=[Set(left["a"].used, True)])
    use_right = Action(id="use_right", effect=[Set(right["b"].used, True)])
    spec = Spec(
        id="s",
        name="s",
        imports=[
            Contract(id="l", actions=[use_left]),
            Contract(id="r", actions=[use_right]),
        ],
    )

    assert spec.scopes == [left, right]
    errors = [f.message for f in validate_structural(spec) if f.severity == Severity.ERROR]
    assert any("more than one Scope" in m for m in errors)


def test_what_if_entity_is_derived_and_can_fail(tmp_path):
    """A what-if invariant over an entity bound nowhere (so no module scan can
    see it) is derived by closure and verified: FAIL, not skipped."""
    patch = tmp_path / "hypothesis.py"
    patch.write_text(
        "from analint import Entity, Invariant\n"
        "def _domain():\n"
        "    class Probe(Entity):\n"
        "        armed: bool = False\n"
        "    return Probe\n"
        "probe_is_armed = Invariant(_domain().armed == True)\n"
    )

    result = validate(FIXTURES / "composed", extra=patch)

    by_id = {r.invariant_id: r for r in result.invariant_results}
    assert by_id["probe_is_armed"].status == "FAIL"


def test_listed_param_action_is_a_member_without_imports(tmp_path):
    """A Spec without imports that lists a Param action keeps its declaration:
    the rebuilt Spec must not see the already-expanded instances as declared."""
    entry = tmp_path / "spec.py"
    entry.write_text(
        _PARAM_SPEC.replace(
            'spec = Spec(id="p", name="p", imports=[part])',
            'spec = Spec(id="p", name="p", actions=[tick])',
        )
    )

    model = prepare_model(entry)

    assert [action.id for action in model.spec.actions] == [
        "tick(c=Counter['a'])",
        "tick(c=Counter['b'])",
    ]
    assert _orphans(model) == []
