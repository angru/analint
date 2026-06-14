"""Run a Flow: an initial state, then a sequence of actions and checkpoints.

Each action goes through the shared transition kernel and must be accepted; its
post-state becomes the next step's pre-state. The reached state must also stay a
legal world — applicable invariants are checked on the initial state and after
every accepted action. Checkpoints (``Assert`` / a required ``Emitted`` event)
are evaluated against the state reached so far. The first illegal state, rejected
action or failed checkpoint stops the flow and fails it, with the trace of the
actions that ran up to that point.
"""

from __future__ import annotations

from analint.models.action import Action
from analint.models.flow import Assert, Emitted, Flow
from analint.models.root import Spec
from analint.reporter.base import Finding, FlowResult, Severity
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.state_checks import build_snapshot_context, check_invariants
from analint.validator.structural import _describe


def run_flow(flow: Flow, spec: Spec) -> FlowResult:
    loc = f"flow:{flow.id}"
    context = build_snapshot_context(spec, flow.given or [])

    findings: list[Finding] = []
    emitted_so_far: list = []
    trace: list[str] = []

    def fail(message: str) -> FlowResult:
        findings.append(Finding(Severity.ERROR, loc, message))
        return FlowResult(
            flow_id=flow.id,
            passed=False,
            findings=findings,
            actions_run=len(trace),
            trace=list(trace),
        )

    # The journey must start from a legal world and stay in one after every step
    # (applicability is presence-aware and recomputed against each state).
    inv_findings = check_invariants(spec, context, "INVARIANT")
    if inv_findings:
        findings.extend(inv_findings)
        return fail("the flow starts from a state that violates an invariant")

    for index, entry in enumerate(flow.steps, start=1):
        if isinstance(entry, Action):
            result = step(spec, entry, context, trace=trace)
            if result.outcome is not Outcome.ACCEPTED:
                findings.extend(result.findings)
                return fail(
                    f"step {index} '{entry.id}' did not run ({result.outcome.value}) — the "
                    f"journey cannot continue [after: {_trace_str(trace)}]"
                )
            assert result.post_context is not None  # ACCEPTED always materialises it
            context = result.post_context
            emitted_so_far.extend(result.emitted)
            trace.append(entry.id)
            post_inv = check_invariants(spec, context, "INVARIANT (post)")
            if post_inv:
                findings.extend(post_inv)
                return fail(
                    f"step {index} '{entry.id}' reaches a state that violates an invariant "
                    f"[after: {_trace_str(trace)}]"
                )
        elif isinstance(entry, Assert):
            try:
                ok = evaluate(entry.predicate, context)
            except Exception as exc:
                return fail(
                    f"checkpoint {index} evaluation error: {exc} "
                    f"({_describe(entry.predicate)}) [after: {_trace_str(trace)}]"
                )
            if not ok:
                return fail(
                    f"checkpoint {index} failed: {_describe(entry.predicate)} "
                    f"[after: {_trace_str(trace)}]"
                )
        elif isinstance(entry, Emitted):
            # Compare the class object, not its name: two events can share a name.
            seen = {e if isinstance(e, type) else type(e) for e in emitted_so_far}
            if entry.event_cls not in seen:
                return fail(
                    f"checkpoint {index}: event '{entry.event_cls.__name__}' has not been "
                    f"emitted by this point [after: {_trace_str(trace)}]"
                )
        else:
            return fail(f"step {index} '{entry!r}' is not an Action, Assert(...) or Emitted(...)")

    return FlowResult(
        flow_id=flow.id, passed=True, findings=findings, actions_run=len(trace), trace=list(trace)
    )


def _trace_str(steps: list[str]) -> str:
    return " → ".join(steps) if steps else "(initial state)"
