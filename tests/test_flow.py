from analint import (
    Action,
    Add,
    Assert,
    Emitted,
    Entity,
    Event,
    Field,
    Flow,
    Spec,
)
from analint.validator.flow_runner import run_flow
from analint.validator.structural import validate_structural


class Counter(Entity):
    n: int = Field(0, ge=0, le=5)


class Ticked(Event):
    at: int


class Other(Event):
    x: int


bump = Action(
    id="bump",
    pre=[Counter.n < 5],
    effect=[Add(Counter.n, 1)],
    emits=[Ticked(at=Counter.n)],
)


def _spec(flow: Flow) -> Spec:
    return Spec(
        id="s", name="S", entities=[Counter], events=[Ticked, Other], actions=[bump], flows=[flow]
    )


def test_flow_threads_post_state_and_passes():
    flow = Flow(
        id="f",
        given=[Counter(n=0)],
        steps=[bump, Assert(Counter.n == 1), bump, Assert(Counter.n == 2), Emitted(Ticked)],
    )
    result = run_flow(flow, _spec(flow))
    assert result.passed
    assert result.trace == ["bump", "bump"]
    assert result.actions_run == 2


def test_flow_fails_when_a_step_is_rejected():
    flow = Flow(id="f", given=[Counter(n=5)], steps=[bump])  # bump pre n<5 is false at n=5
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert result.actions_run == 0
    assert any("did not run" in f.message for f in result.findings)


def test_flow_fails_on_a_false_checkpoint_with_the_trace_so_far():
    flow = Flow(id="f", given=[Counter(n=0)], steps=[bump, Assert(Counter.n == 5)])
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert result.actions_run == 1  # the action ran; the checkpoint after it failed
    assert any("checkpoint" in f.message and "bump" in f.message for f in result.findings)


def test_flow_emitted_checkpoint_fails_when_event_absent():
    flow = Flow(id="f", given=[Counter(n=0)], steps=[bump, Emitted(Other)])
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert any("Other" in f.message and "emitted" in f.message for f in result.findings)


# ── review 2015619 regressions ───────────────────────────────────────────────────


def test_flow_fails_on_a_state_that_violates_an_invariant():
    from analint import Invariant, Set

    class Box(Entity):
        n: int = 0

    break_it = Action(id="break", pre=[Box.n == 1], effect=[Set(Box.n, -1)])
    flow = Flow(id="f", given=[Box(n=1)], steps=[break_it])
    spec = Spec(
        id="s",
        name="S",
        entities=[Box],
        actions=[break_it],
        invariants=[Invariant(Box.n >= 0, id="non_negative")],
        flows=[flow],
    )
    result = run_flow(flow, spec)
    assert not result.passed
    assert any("invariant" in f.message.lower() for f in result.findings)


def test_flow_starting_from_an_illegal_state_fails():
    from analint import Invariant

    class Box(Entity):
        n: int = 0

    noop = Action(id="noop", pre=[Box.n == 5])
    flow = Flow(id="f", given=[Box(n=0)], steps=[noop])
    spec = Spec(
        id="s",
        name="S",
        entities=[Box],
        actions=[noop],
        invariants=[Invariant(Box.n >= 1, id="at_least_one")],
        flows=[flow],
    )
    result = run_flow(flow, spec)
    assert not result.passed
    assert any("starts from a state" in f.message for f in result.findings)


def test_flow_step_must_be_the_registered_action_object():
    from analint import Set

    class Box(Entity):
        n: int = 0

    registered = Action(id="same", effect=[Set(Box.n, 1)])
    foreign = Action(id="same", effect=[Set(Box.n, 2)])  # same id, different object
    flow = Flow(id="f", given=[Box()], steps=[foreign])
    spec = Spec(id="s", name="S", entities=[Box], actions=[registered], flows=[flow])
    findings = validate_structural(spec)
    assert any("different object" in f.message for f in findings)


def test_emitted_checkpoint_distinguishes_event_classes_by_identity():
    from analint import Set

    class Box(Entity):
        n: int = 0

    registered_signal = type("Signal", (Event,), {"__annotations__": {}})
    foreign_signal = type("Signal", (Event,), {"__annotations__": {}})  # same name
    emit = Action(id="emit", effect=[Set(Box.n, 1)], emits=[registered_signal()])
    flow = Flow(id="f", given=[Box()], steps=[emit, Emitted(foreign_signal)])
    spec = Spec(
        id="s", name="S", entities=[Box], events=[registered_signal], actions=[emit], flows=[flow]
    )
    result = run_flow(flow, spec)
    assert not result.passed  # foreign Signal class was never emitted


def test_given_is_a_partial_snapshot_not_a_defaults_world():
    class Box(Entity):
        n: int = 0

    tick = Action(id="tick", pre=[Box.n == 0], effect=[Add(Box.n, 1)])
    # listed -> the journey runs; not listed -> the pre is not applicable, rejected
    listed = Flow(id="listed", given=[Box(n=0)], steps=[tick, Assert(Box.n == 1)])
    empty = Flow(id="empty", given=[], steps=[tick])  # Box absent -> tick cannot run
    spec = Spec(id="s", name="S", entities=[Box], actions=[tick], flows=[listed, empty])
    assert run_flow(listed, spec).passed
    assert not run_flow(empty, spec).passed


def test_create_makes_an_invariant_applicable_and_a_bad_create_fails():
    from analint import Absent, Create, Field, Invariant, Scope

    class Account(Entity):
        balance: int = Field(0, ge=-5, le=5)

    accounts = Scope(Account, keys=["a"], id="accounts")
    ref = accounts["a"]
    inv = Invariant(ref.balance >= 0, id="non_negative")

    # absent -> invariant N/A; Create(0) -> it becomes applicable and holds
    open_ok = Action(id="open_ok", effect=[Create(ref, balance=0)])
    ok_flow = Flow(id="ok", given=[Absent(ref)], steps=[open_ok, Assert(ref.balance == 0)])
    spec_ok = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[open_ok],
        invariants=[inv],
        flows=[ok_flow],
    )
    assert run_flow(ok_flow, spec_ok).passed

    # Create(-1) -> the now-applicable invariant is violated -> flow fails
    open_bad = Action(id="open_bad", effect=[Create(ref, balance=-1)])
    bad_flow = Flow(id="bad", given=[Absent(ref)], steps=[open_bad])
    spec_bad = Spec(
        id="s",
        name="S",
        entities=[Account],
        scopes=[accounts],
        actions=[open_bad],
        invariants=[inv],
        flows=[bad_flow],
    )
    assert not run_flow(bad_flow, spec_bad).passed
