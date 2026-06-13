"""Semantic conformance matrix: the fine-grained gate for the transition kernel
(research/20 §1, review 584d819).

One (action, initial state) is run through BOTH evaluation paths and the outcome
category is compared:

- ACCEPTED — the action runs and yields a legal transition;
- REJECTED — it is blocked before any effect (a guard / failed precondition);
- DEFECT   — it runs but violates legality afterwards (post / field / lifecycle).

The scenario category is derived robustly from existing semantics: a scenario is
run once expecting PASS and once expecting FAIL — ACCEPTED passes the first only,
REJECTED passes the second only (Expect.FAIL legitimises pre-execution rejection
only), DEFECT passes neither.

Cases where the two paths are known to disagree today are marked
``xfail(strict=True)``: while they diverge the test is an expected failure; once
the kernel unifies them the assertion passes, strict-xfail flips to a failure,
and that forces the marker (and the divergence) to be removed. So this file is
also the kernel's acceptance spec.
"""

from enum import StrEnum

import pytest

from analint import (
    Absent,
    Action,
    Create,
    Delete,
    Entity,
    Field,
    Lifecycle,
    Scenario,
    Scope,
    Set,
    Spec,
    Transition,
)
from analint.models.scenario import Expect
from analint.reporter.base import Severity
from analint.validator.explorer import build_initial, explore
from analint.validator.scenario_runner import run_scenario


def _scenario_cat(spec: Spec, action: Action, given: list) -> str:
    as_pass = run_scenario(Scenario(id="p", name="p", action=action, given=given), spec)
    as_fail = run_scenario(
        Scenario(id="f", name="f", action=action, given=given, expected=Expect.FAIL), spec
    )
    if as_pass.passed and not as_fail.passed:
        return "ACCEPTED"
    if as_fail.passed and not as_pass.passed:
        return "REJECTED"
    return "DEFECT"


def _explorer_cat(spec: Spec, action: Action, given: list) -> str:
    ctx, error = build_initial(spec, given)
    assert ctx is not None, error
    exp = explore(spec, [ctx], 1000)
    loc = f"action:{action.id}"
    if any(f.severity == Severity.ERROR and f.location == loc for f in exp.findings):
        return "DEFECT"
    if any(edge[1] == action.id for edge in exp.edges):
        return "ACCEPTED"
    return "REJECTED"


def _assert_agree(spec: Spec, action: Action, given: list, expected: str) -> None:
    s = _scenario_cat(spec, action, given)
    e = _explorer_cat(spec, action, given)
    assert s == e == expected, f"scenario={s} explorer={e} expected={expected}"


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


def _flag_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Flag], actions=[action])


def _doc_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Doc], actions=[action])


# ── agreed cases (must stay green) ───────────────────────────────────────────────


def test_pre_true_is_accepted():
    a = Action(id="go", pre=[Flag.done == False], effect=[Set(Flag.done, True)])  # noqa: E712
    _assert_agree(_flag_spec(a), a, [Flag(done=False)], "ACCEPTED")


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
    _assert_agree(_flag_spec(a), a, [Flag(done=False)], "ACCEPTED")


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
    _assert_agree(_flag_spec(a), a, [Flag(n=0)], "DEFECT")


def test_lifecycle_allowed_transition_is_accepted():
    a = Action(id="go", pre=[Doc.state == Status.A], effect=[Set(Doc.state, Status.B)])
    _assert_agree(_doc_spec(a), a, [Doc(state=Status.A)], "ACCEPTED")


# ── presence guards (Create/Delete) — must stay agreed through the kernel ────────


class Acct(Entity):
    bal: int = Field(0, ge=0, le=2)


accts = Scope(Acct, keys=["a"], id="accts")
a_ref = accts["a"]


def _scope_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Acct], scopes=[accts], actions=[action])


def test_create_on_absent_is_accepted():
    act = Action(id="open", effect=[Create(a_ref, bal=0)])
    _assert_agree(_scope_spec(act), act, [Absent(a_ref)], "ACCEPTED")


def test_create_on_present_is_rejected():
    act = Action(id="open", effect=[Create(a_ref, bal=0)])
    _assert_agree(_scope_spec(act), act, [a_ref(bal=0)], "REJECTED")


def test_delete_present_is_accepted():
    act = Action(id="close", effect=[Delete(a_ref)])
    _assert_agree(_scope_spec(act), act, [a_ref(bal=0)], "ACCEPTED")


def test_delete_absent_is_rejected():
    act = Action(id="close", effect=[Delete(a_ref)])
    _assert_agree(_scope_spec(act), act, [Absent(a_ref)], "REJECTED")


# ── known divergences — the kernel must remove these (then drop the xfail) ────────


@pytest.mark.xfail(
    reason="scenario runner does not yet validate lifecycle transitions; kernel unifies",
    strict=True,
)
def test_lifecycle_undeclared_transition_is_defect_in_both():
    a = Action(id="go", pre=[Doc.state == Status.A], effect=[Set(Doc.state, Status.C)])
    _assert_agree(_doc_spec(a), a, [Doc(state=Status.A)], "DEFECT")
