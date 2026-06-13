"""Normative semantic contract for the transition kernel.

One (action, initial state) is run through BOTH evaluation paths and the outcome
category is compared:

- ACCEPTED — the action runs and yields a legal transition;
- REJECTED — it is blocked before any effect (a guard / failed precondition);
- DEFECT   — the model cannot evaluate the transition or it violates legality.

The scenario category is derived robustly from existing semantics: a scenario is
run once expecting PASS and once expecting FAIL — ACCEPTED passes the first only,
REJECTED passes the second only (Expect.FAIL legitimises pre-execution rejection
only), DEFECT passes neither.

Target ordering for the shared ``step`` implementation:

    pre-state invariants -> pre/terminal/presence guards -> effects
    -> Field clamp/constraints -> Lifecycle transition -> post
    -> post-state invariants -> emitted payload materialisation

Evaluation errors and invariant violations are DEFECT, never REJECTED. Accepted
cases additionally assert the observable post-state in both paths. A DEFECT
before a legal successor exists creates no graph edge; a post-state invariant
violation may retain the candidate post-state/edge as a counterexample witness,
but that state must not be expanded.

The future internal result is expected to carry, at minimum:

    outcome, post_context, findings, emitted events, changed fields/state diff

Cases where the two paths are known to disagree today are marked
``xfail(strict=True)``: while they diverge the test is an expected failure; once
the kernel unifies them the assertion passes, strict-xfail flips to a failure,
and that forces the marker (and the divergence) to be removed. So this file is
the kernel's acceptance spec (research/20 §1, review ca537a2).
"""

from enum import StrEnum
from typing import Any

import pytest

from analint import (
    Absent,
    Action,
    Add,
    Assert,
    Create,
    Delete,
    Entity,
    Event,
    Field,
    Invariant,
    Lifecycle,
    Not,
    Present,
    Scenario,
    Scope,
    Set,
    Spec,
    Transition,
)
from analint.models.scenario import Expect
from analint.reporter.base import Severity
from analint.validator.explorer import build_initial, explore
from analint.validator.rule_checker import resolve
from analint.validator.scenario_runner import run_scenario


def _scenario_cat(spec: Spec, action: Action, given: list, then: list | None = None) -> str:
    as_pass = run_scenario(
        Scenario(id="p", name="p", action=action, given=given, then=then or []), spec
    )
    as_fail = run_scenario(
        Scenario(
            id="f",
            name="f",
            action=action,
            given=given,
            then=then or [],
            expected=Expect.FAIL,
        ),
        spec,
    )
    if as_pass.passed and not as_fail.passed:
        return "ACCEPTED"
    if as_fail.passed and not as_pass.passed:
        return "REJECTED"
    return "DEFECT"


def _explorer_result(spec: Spec, action: Action, given: list) -> tuple[str, dict | None, bool]:
    ctx, error = build_initial(spec, given)
    assert ctx is not None, error
    exp = explore(spec, [ctx], 1000)
    edges = [edge for edge in exp.edges if edge[1] == action.id]
    post = exp.states[edges[0][2]] if edges else None
    if any(f.severity == Severity.ERROR for f in exp.findings):
        return "DEFECT", post, bool(edges)
    if edges:
        return "ACCEPTED", post, True
    return "REJECTED", None, False


def _assert_agree(
    spec: Spec,
    action: Action,
    given: list,
    expected: str,
    *,
    expected_fields: list[tuple[Any, Any]] | None = None,
    expected_presence: list[tuple[Any, bool]] | None = None,
    expected_edge: bool | None = None,
) -> None:
    assertions = [Assert(field == value) for field, value in expected_fields or []]
    assertions.extend(
        Assert(Present(ref) if present else Not(Present(ref)))
        for ref, present in expected_presence or []
    )
    s = _scenario_cat(spec, action, given, assertions)
    e, post, has_edge = _explorer_result(spec, action, given)
    assert s == e == expected, f"scenario={s} explorer={e} expected={expected}"
    if expected_edge is not None:
        assert has_edge is expected_edge
    if expected != "ACCEPTED":
        return
    assert post is not None
    for field, value in expected_fields or []:
        assert resolve(field, post) == value
    for ref, present in expected_presence or []:
        assert bool(post[ref].__dict__.get("_analint_present", True)) is present


# ── shared entity shapes (actions self-disable so exploration is single-step) ────


class Flag(Entity):
    done: bool = Field(False)
    n: int = Field(0, ge=0, le=2)


class Status(StrEnum):
    A = "a"
    B = "b"
    C = "c"


class Doc(Entity):
    state: Status = Lifecycle(
        initial=Status.A,
        transitions=[Transition(Status.A, [Status.B])],  # A→B only; A→C undeclared
    )


class TerminalDoc(Entity):
    state: Status = Lifecycle(
        initial=Status.A,
        transitions=[Transition(Status.A, [Status.B])],
        terminal=[Status.B],
    )


def _flag_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Flag], actions=[action])


def _doc_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Doc], actions=[action])


def _terminal_doc_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[TerminalDoc], actions=[action])


# ── agreed cases (must stay green) ───────────────────────────────────────────────


def test_pre_true_is_accepted():
    a = Action(id="go", pre=[Flag.done == False], effect=[Set(Flag.done, True)])  # noqa: E712
    _assert_agree(
        _flag_spec(a),
        a,
        [Flag(done=False)],
        "ACCEPTED",
        expected_fields=[(Flag.done, True)],
    )


def test_pre_false_is_rejected():
    a = Action(id="go", pre=[Flag.done == True], effect=[Set(Flag.done, True)])  # noqa: E712
    _assert_agree(_flag_spec(a), a, [Flag(done=False)], "REJECTED")


def test_post_true_is_accepted():
    a = Action(
        id="go",
        pre=[Flag.done == False],  # noqa: E712
        effect=[Set(Flag.done, True)],
        post=[Flag.done == True],  # noqa: E712
    )
    _assert_agree(
        _flag_spec(a),
        a,
        [Flag(done=False)],
        "ACCEPTED",
        expected_fields=[(Flag.done, True)],
    )


def test_post_false_is_defect():
    a = Action(
        id="go",
        pre=[Flag.done == False],  # noqa: E712
        effect=[Set(Flag.done, True)],
        post=[Flag.done == False],  # noqa: E712  contradicts the effect
    )
    _assert_agree(_flag_spec(a), a, [Flag(done=False)], "DEFECT")


def test_effectless_post_false_is_defect():
    a = Action(id="go", post=[Flag.done == True])  # noqa: E712  false at done=False
    _assert_agree(_flag_spec(a), a, [Flag(done=False)], "DEFECT")


def test_hard_field_violation_is_defect():
    a = Action(id="go", pre=[Flag.n == 0], effect=[Set(Flag.n, 9)])  # 9 > le=2
    _assert_agree(_flag_spec(a), a, [Flag(n=0)], "DEFECT", expected_edge=False)


def test_lifecycle_allowed_transition_is_accepted():
    a = Action(id="go", pre=[Doc.state == Status.A], effect=[Set(Doc.state, Status.B)])
    _assert_agree(
        _doc_spec(a),
        a,
        [Doc(state=Status.A)],
        "ACCEPTED",
        expected_fields=[(Doc.state, Status.B)],
    )


def test_simultaneous_effects_use_the_pre_state():
    class Pair(Entity):
        left: int = 1
        right: int = 2

    swap = Action(
        id="swap",
        pre=[Pair.left == 1, Pair.right == 2],
        effect=[Set(Pair.left, Pair.right), Set(Pair.right, Pair.left)],
    )
    spec = Spec(id="s", name="S", entities=[Pair], actions=[swap])
    _assert_agree(
        spec,
        swap,
        [Pair()],
        "ACCEPTED",
        expected_fields=[(Pair.left, 2), (Pair.right, 1)],
    )


def test_saturating_field_clamps_before_post():
    class Gauge(Entity):
        value: int = Field(1, ge=0, le=2, saturate=True)

    raise_gauge = Action(
        id="raise",
        pre=[Gauge.value == 1],
        effect=[Add(Gauge.value, 9)],
        post=[Gauge.value == 2],
    )
    spec = Spec(id="s", name="S", entities=[Gauge], actions=[raise_gauge])
    _assert_agree(
        spec,
        raise_gauge,
        [Gauge()],
        "ACCEPTED",
        expected_fields=[(Gauge.value, 2)],
    )


def test_effect_evaluation_error_is_defect():
    a = Action(id="go", effect=[Set(Flag.n, Flag.n + "bad")])
    _assert_agree(_flag_spec(a), a, [Flag()], "DEFECT", expected_edge=False)


def test_post_evaluation_error_is_defect():
    a = Action(id="go", post=[Flag.n > "bad"])
    _assert_agree(_flag_spec(a), a, [Flag()], "DEFECT", expected_edge=False)


def test_post_invariant_violation_is_defect():
    a = Action(id="go", pre=[Flag.n == 0], effect=[Set(Flag.n, 1)])
    invariant = Invariant(Flag.n == 0, id="n_stays_zero")
    spec = Spec(id="s", name="S", entities=[Flag], actions=[a], invariants=[invariant])
    _assert_agree(spec, a, [Flag(n=0)], "DEFECT", expected_edge=True)


def test_terminal_set_is_rejected():
    a = Action(id="go", effect=[Set(TerminalDoc.state, Status.A)])
    _assert_agree(
        _terminal_doc_spec(a),
        a,
        [TerminalDoc(state=Status.B)],
        "REJECTED",
    )


# ── presence guards (Create/Delete) — must stay agreed through the kernel ────────


class Acct(Entity):
    bal: int = Field(0, ge=0, le=2)


accts = Scope(Acct, keys=["a"], id="accts")
a_ref = accts["a"]


def _scope_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Acct], scopes=[accts], actions=[action])


def test_create_on_absent_is_accepted():
    act = Action(id="open", effect=[Create(a_ref, bal=0)])
    _assert_agree(
        _scope_spec(act),
        act,
        [Absent(a_ref)],
        "ACCEPTED",
        expected_fields=[(a_ref.bal, 0)],
        expected_presence=[(a_ref, True)],
    )


def test_create_on_present_is_rejected():
    act = Action(id="open", effect=[Create(a_ref, bal=0)])
    _assert_agree(_scope_spec(act), act, [a_ref(bal=0)], "REJECTED")


def test_delete_present_is_accepted():
    act = Action(id="close", effect=[Delete(a_ref)])
    _assert_agree(
        _scope_spec(act),
        act,
        [a_ref(bal=0)],
        "ACCEPTED",
        expected_presence=[(a_ref, False)],
    )


def test_delete_absent_is_rejected():
    act = Action(id="close", effect=[Delete(a_ref)])
    _assert_agree(_scope_spec(act), act, [Absent(a_ref)], "REJECTED")


def test_post_over_deleted_entity_is_defect():
    act = Action(id="close", effect=[Delete(a_ref)], post=[a_ref.bal == 0])
    _assert_agree(
        _scope_spec(act),
        act,
        [a_ref(bal=0)],
        "DEFECT",
        expected_edge=False,
    )


# ── unified by the kernel (formerly scenario↔explorer divergences) ───────────────


def test_lifecycle_undeclared_transition_is_defect_in_both():
    a = Action(id="go", pre=[Doc.state == Status.A], effect=[Set(Doc.state, Status.C)])
    _assert_agree(
        _doc_spec(a),
        a,
        [Doc(state=Status.A)],
        "DEFECT",
        expected_edge=False,
    )


def test_pre_evaluation_error_is_defect_in_both():
    a = Action(id="go", pre=[Flag.n > "bad"], effect=[Set(Flag.n, 1)])
    _assert_agree(_flag_spec(a), a, [Flag()], "DEFECT", expected_edge=False)


class TerminalAccount(Entity):
    state: Status = Lifecycle(
        initial=Status.A,
        transitions=[Transition(Status.A, [Status.B])],
        terminal=[Status.B],
    )


terminal_accounts = Scope(TerminalAccount, keys=["a"], id="terminal_accounts")
terminal_ref = terminal_accounts["a"]


def test_delete_terminal_entity_is_rejected_in_both():
    act = Action(id="close", effect=[Delete(terminal_ref)])
    spec = Spec(
        id="s",
        name="S",
        entities=[TerminalAccount],
        scopes=[terminal_accounts],
        actions=[act],
    )
    _assert_agree(
        spec,
        act,
        [terminal_ref(state=Status.B)],
        "REJECTED",
        expected_edge=False,
    )


class Raised(Event):
    value: int


def test_emitted_payload_evaluation_error_is_defect():
    act = Action(id="raise", emits=[Raised(value=Flag.n + "bad")])
    scenario = Scenario(id="s", name="S", action=act, given=[Flag()])
    spec = Spec(id="s", name="S", entities=[Flag], events=[Raised], actions=[act])
    result = run_scenario(scenario, spec)
    assert not result.passed


# ── known divergences — the kernel must remove these (then drop the xfail) ────────


@pytest.mark.xfail(
    reason="pre-state invariant failure is still treated as action rejection in scenarios",
    strict=True,
)
def test_invalid_initial_invariant_is_defect_in_both():
    a = Action(id="go", effect=[Set(Flag.done, True)])
    invariant = Invariant(Flag.n == 1, id="initial_is_valid")
    spec = Spec(id="s", name="S", entities=[Flag], actions=[a], invariants=[invariant])
    _assert_agree(spec, a, [Flag(n=0)], "DEFECT", expected_edge=False)
