"""Direct unit tests for the transition kernel.

The agreement matrix in test_transition_conformance checks that scenario and
explorer reach the *same verdict*; it does not inspect the shared
``TransitionResult`` itself, so two callers could ignore the same broken field
and still agree. These tests call ``step()`` directly and assert its result, plus
two regressions for defects the agreement matrix did not cover.
"""

from analint import (
    Absent,
    Action,
    Add,
    Create,
    Delete,
    Entity,
    Event,
    Field,
    Invariant,
    Scenario,
    Scope,
    Set,
    Spec,
)
from analint.models.scenario import Expect
from analint.reporter.base import Severity
from analint.validator.explorer import build_initial, explore
from analint.validator.kernel import Outcome, step
from analint.validator.scenario_runner import run_scenario


class Box(Entity):
    n: int = Field(0, ge=0, le=9)
    flag: bool = Field(False)


class Pinged(Event):
    at: int


def _ctx(spec: Spec, given: list) -> dict:
    ctx, error = build_initial(spec, given)
    assert ctx is not None, error
    return ctx


def _spec(action: Action, **kw) -> Spec:
    return Spec(id="s", name="S", entities=[Box], actions=[action], **kw)


# ── TransitionResult shape ───────────────────────────────────────────────────────


def test_set_reports_outcome_post_and_changed_field():
    a = Action(id="go", effect=[Set(Box.n, 5)])
    spec = _spec(a)
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.outcome is Outcome.ACCEPTED
    assert r.entered is True
    assert r.changed_fields == {Box: {"n": (1, 5)}}
    assert r.post_context[Box].n == 5


def test_add_reports_changed_field():
    a = Action(id="go", effect=[Add(Box.n, 2)])
    spec = _spec(a)
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.changed_fields == {Box: {"n": (1, 3)}}


def test_effectless_accepts_with_empty_diff_and_same_context():
    a = Action(id="noop", post=[Box.n == 1])
    spec = _spec(a)
    ctx = _ctx(spec, [Box(n=1)])
    r = step(spec, a, ctx)
    assert r.outcome is Outcome.ACCEPTED
    assert r.entered is True
    assert r.changed_fields == {}
    assert r.post_context is ctx


def test_rejected_keeps_reason_and_is_not_entered():
    a = Action(id="go", pre=[Box.n == 9], effect=[Set(Box.n, 5)])
    spec = _spec(a)
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.outcome is Outcome.REJECTED
    assert r.entered is False
    assert r.post_context is None
    assert any("PRE failed" in f.message for f in r.findings)


def test_pre_evaluation_error_is_defect_and_not_entered():
    a = Action(id="go", pre=[Box.n > "bad"], effect=[Set(Box.n, 5)])
    spec = _spec(a)
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.outcome is Outcome.DEFECT
    assert r.entered is False
    assert r.post_context is None


def test_false_post_is_defect_but_entered_with_no_candidate():
    a = Action(id="go", effect=[Set(Box.n, 5)], post=[Box.n == 0])
    spec = _spec(a)
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.outcome is Outcome.DEFECT
    assert r.entered is True
    assert r.post_context is None


# ── presence is part of the state diff ───────────────────────────────────────────


class Acct(Entity):
    bal: int = Field(0, ge=0, le=9)


accts = Scope(Acct, keys=["a"], id="accts")
ref = accts["a"]


def _scope_spec(action: Action) -> Spec:
    return Spec(id="s", name="S", entities=[Acct], scopes=[accts], actions=[action])


def test_create_reports_presence_flip():
    a = Action(id="open", effect=[Create(ref, bal=2)])
    spec = _scope_spec(a)
    r = step(spec, a, _ctx(spec, [Absent(ref)]))
    assert r.outcome is Outcome.ACCEPTED
    assert r.changed_fields[ref]["@present"] == (False, True)


def test_delete_reports_presence_flip():
    a = Action(id="close", effect=[Delete(ref)])
    spec = _scope_spec(a)
    r = step(spec, a, _ctx(spec, [ref(bal=2)]))
    assert r.outcome is Outcome.ACCEPTED
    assert r.changed_fields[ref]["@present"] == (True, False)


# ── emitted payload materialisation ──────────────────────────────────────────────


def test_emitted_payload_is_materialised_against_next_state():
    a = Action(id="go", effect=[Set(Box.n, 5)], emits=[Pinged(at=Box.n)])
    spec = _spec(a, events=[Pinged])
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.outcome is Outcome.ACCEPTED
    assert len(r.emitted) == 1
    assert r.emitted[0].at == 5  # resolved against the post-state


def test_bare_event_class_passes_through():
    a = Action(id="go", effect=[Set(Box.n, 5)], emits=[Pinged])
    spec = _spec(a, events=[Pinged])
    r = step(spec, a, _ctx(spec, [Box(n=1)]))
    assert r.emitted == [Pinged]


# ── regressions for review 535ecb8 ───────────────────────────────────────────────


def test_illegal_initial_plus_false_pre_is_not_a_rejection():
    """An illegal initial state is a defect; Expect.FAIL must not pass it even
    when a precondition also rejects the action (review 535ecb8, P1#1)."""
    a = Action(id="go", pre=[Box.flag], effect=[Set(Box.flag, True)])
    inv = Invariant(Box.n == 1, id="initial_is_valid")
    spec = Spec(id="s", name="S", entities=[Box], actions=[a], invariants=[inv])
    sc = Scenario(id="t", name="t", action=a, given=[Box(n=0)], expected=Expect.FAIL)
    assert not run_scenario(sc, spec).passed


def test_explorer_does_not_expand_a_root_with_an_unevaluable_invariant():
    """An invariant that cannot be evaluated is a model defect, so its state is a
    witness with no outgoing edges (review 535ecb8, P1#2)."""
    a = Action(id="go", effect=[Set(Box.flag, True)])
    inv = Invariant(Box.n > "bad", id="bad")
    spec = Spec(id="s", name="S", entities=[Box], actions=[a], invariants=[inv])
    exp = explore(spec, [_ctx(spec, [Box(n=0)])], 1000)
    assert len(exp.states) == 1  # the illegal root is kept as a witness
    assert exp.edges == []  # but never expanded
    assert any(f.severity == Severity.ERROR for f in exp.findings)
