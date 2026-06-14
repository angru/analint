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
    assert result.steps_run == 2


def test_flow_fails_when_a_step_is_rejected():
    flow = Flow(id="f", given=[Counter(n=5)], steps=[bump])  # bump pre n<5 is false at n=5
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert result.steps_run == 0
    assert any("did not run" in f.message for f in result.findings)


def test_flow_fails_on_a_false_checkpoint_with_the_trace_so_far():
    flow = Flow(id="f", given=[Counter(n=0)], steps=[bump, Assert(Counter.n == 5)])
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert result.steps_run == 1  # the action ran; the checkpoint after it failed
    assert any("checkpoint" in f.message and "bump" in f.message for f in result.findings)


def test_flow_emitted_checkpoint_fails_when_event_absent():
    flow = Flow(id="f", given=[Counter(n=0)], steps=[bump, Emitted(Other)])
    result = run_flow(flow, _spec(flow))
    assert not result.passed
    assert any("Other" in f.message and "emitted" in f.message for f in result.findings)


def test_flow_without_given_with_checkpoints_warns():
    flow = Flow(id="f", steps=[bump, Assert(Counter.n == 1)])
    findings = validate_structural(_spec(flow))
    assert any("checkpoints but no given" in f.message for f in findings)
