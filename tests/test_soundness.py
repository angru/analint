"""Tests for the false-green paths from the research/14 audit.

A verifier sells trust in PASS: every test here pins a case where the old
engine would have answered green for the wrong reason.
"""

from analint import (
    Action,
    AlwaysHolds,
    Entity,
    Event,
    Expect,
    Reachable,
    Scenario,
    Set,
    Spec,
    Subtract,
    Unreachable,
)
from analint.reporter.base import Severity
from analint.validator.explorer import build_initial, run_query
from analint.validator.rule_checker import UnsupportedPredicateError, evaluate
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import validate_structural


def _errors(findings):
    return [f for f in findings if f.severity == Severity.ERROR]


# ── §7.1: unknown predicate must never read as True ───────────────────────────


def test_evaluate_raises_on_foreign_object():
    try:
        evaluate(object(), {})  # type: ignore[arg-type]
        raise AssertionError("should have raised")
    except UnsupportedPredicateError:
        pass


def test_action_rejects_non_predicate_in_pre_at_construction():
    from pydantic import ValidationError

    try:
        Action(id="act", pre=[object()])
        raise AssertionError("should have raised")
    except ValidationError:
        pass  # typed pydantic fields reject foreign objects before anything runs


def test_structural_rejects_non_predicate_nested_in_and():
    from analint import And

    class Item(Entity):
        price: float = 1.0

    action = Action(id="act", pre=[And(Item.price > 0, "price is fine")])  # type: ignore[arg-type]
    spec = Spec(id="s", name="S", entities=[Item], actions=[action])
    assert any("is not a predicate" in f.message for f in _errors(validate_structural(spec)))


def test_structural_rejects_unknown_then_entry():
    class Item(Entity):
        price: float = 1.0

    action = Action(id="act", pre=[Item.price > 0])
    sc = Scenario(
        id="sc", name="SC", action=action, given=[Item()], then=["price should be positive"]
    )  # a string is not a check
    spec = Spec(id="s", name="S", entities=[Item], actions=[action], scenarios=[sc])
    assert any(
        "must be Assert(...) or Emitted(...)" in f.message
        for f in _errors(validate_structural(spec))
    )


# ── §7.2: evaluation errors must not read as "no violation" ───────────────────


def test_always_holds_with_type_broken_predicate_fails_not_passes():
    class Box(Entity):
        label: str = "abc"

    rename = Action(id="rename", pre=[Box.label == "abc"], effect=[Set(Box.label, "def")])
    # str > int raises TypeError at evaluation time — the old engine swallowed
    # it and reported PASS without having checked anything
    query = AlwaysHolds(Box.label > 5, id="q")
    spec = Spec(id="s", name="S", entities=[Box], actions=[rename])
    result = run_query(query, spec, cache={})
    assert result.status == "FAIL"
    assert any("evaluation error" in f.message for f in result.findings)


def test_pre_evaluation_error_is_reported_not_swallowed():
    class Box(Entity):
        label: str = "abc"

    broken = Action(id="broken", pre=[Box.label > 5], effect=[Set(Box.label, "x")])
    spec = Spec(id="s", name="S", entities=[Box], actions=[broken])
    cache: dict = {}
    run_query(Reachable(Box.label == "x", id="q"), spec, cache)
    exp = next(iter(cache.values()))
    assert any("pre evaluation error" in f.message for f in exp.findings)


def test_unreachable_over_never_applicable_predicate_is_not_vacuous_pass():
    class Ping(Event):
        size: int

    class Box(Entity):
        label: str = "abc"

    noop = Action(id="noop", pre=[Box.label == "abc"], effect=[Set(Box.label, "x")])
    # Ping is an event: it is never part of the explored state, so the old
    # engine would scan zero applicable states and report a vacuous PASS
    query = Unreachable(Ping.size > 100, id="q")
    spec = Spec(id="s", name="S", entities=[Box], events=[Ping], actions=[noop])
    result = run_query(query, spec, cache={})
    assert result.status == "FAIL"
    assert any("not applicable in any explored state" in f.message for f in result.findings)


# ── §7.3: Expect.FAIL must mean pre-execution rejection only ──────────────────


def test_expect_fail_passes_on_precondition_rejection():
    class Item(Entity):
        price: float = 0.0

    action = Action(id="act", pre=[Item.price > 0])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item()], expected=Expect.FAIL)
    spec = Spec(id="s", name="S", entities=[Item], actions=[action], scenarios=[sc])
    assert run_scenario(sc, spec).passed


def test_expect_fail_does_not_legitimise_broken_postcondition():
    class Item(Entity):
        price: float = 10.0

    action = Action(
        id="act",
        pre=[Item.price > 0],  # passes — nothing blocks the action
        effect=[Subtract(Item.price, 1)],
        post=[Item.price == 0],  # broken postcondition: 9 != 0
    )
    sc = Scenario(id="sc", name="SC", action=action, given=[Item()], expected=Expect.FAIL)
    spec = Spec(id="s", name="S", entities=[Item], actions=[action], scenarios=[sc])
    result = run_scenario(sc, spec)
    assert not result.passed
    assert any("expected the action to be blocked" in f.message for f in result.findings)


def test_expect_fail_when_action_simply_succeeds_still_fails():
    class Item(Entity):
        price: float = 10.0

    action = Action(id="act", pre=[Item.price > 0], effect=[Subtract(Item.price, 1)])
    sc = Scenario(id="sc", name="SC", action=action, given=[Item()], expected=Expect.FAIL)
    spec = Spec(id="s", name="S", entities=[Item], actions=[action], scenarios=[sc])
    assert not run_scenario(sc, spec).passed


# ── §7.6: unsupported state domains are rejected, not crashed on ──────────────


def test_unhashable_field_value_rejected_before_exploration():
    class Bag(Entity):
        items: list = []  # noqa: RUF012 — deliberately unsupported

    spec = Spec(id="s", name="S", entities=[Bag], actions=[])
    initial, error = build_initial(spec, given=[Bag(items=[1, 2])])
    assert initial is None
    assert error is not None and "unhashable" in error


# ── §7.5: event-driven actions are reported as excluded, not silently dead ────


def test_event_payload_action_reported_excluded_and_not_dead():
    from analint import DeadActions

    class Ping(Event):
        size: int

    class Counter(Entity):
        total: int = 0

    handler = Action(id="handler", on=Ping, pre=[Ping.size > 0], effect=[Set(Counter.total, 1)])
    spec = Spec(id="s", name="S", entities=[Counter], events=[Ping], actions=[handler])
    cache: dict = {}
    result = run_query(DeadActions(id="q"), spec, cache)
    exp = next(iter(cache.values()))
    assert "handler" in exp.excluded
    assert result.status == "PASS"  # excluded ≠ dead
    assert any("not assessed" in f.message for f in result.findings)
