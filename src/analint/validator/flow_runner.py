"""Run a Flow: an initial state, then a sequence of actions and checkpoints.

Each action goes through the shared transition kernel and must be accepted; its
post-state becomes the next step's pre-state. Checkpoints (``Assert`` / a
required ``Emitted`` event) are evaluated against the state reached so far. The
first rejected action or failed checkpoint stops the flow and fails it, with the
trace of the actions that ran up to that point.
"""

from __future__ import annotations

from analint.models.action import Action
from analint.models.flow import Assert, Emitted, Flow
from analint.models.root import Spec
from analint.models.scope import Absent, instance_context_key
from analint.reporter.base import Finding, FlowResult, Severity
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.structural import _describe


def run_flow(flow: Flow, spec: Spec) -> FlowResult:
    loc = f"flow:{flow.id}"
    context = {instance_context_key(inst): inst for inst in flow.given}
    for scope in spec.scopes:
        for ref in scope:
            context.setdefault(ref, Absent(ref))

    findings: list[Finding] = []
    emitted_so_far: list = []
    trace: list[str] = []

    def fail(message: str) -> FlowResult:
        findings.append(Finding(Severity.ERROR, loc, message))
        return FlowResult(
            flow_id=flow.id,
            passed=False,
            findings=findings,
            steps_run=len(trace),
            trace=list(trace),
        )

    for index, entry in enumerate(flow.steps, start=1):
        if isinstance(entry, Action):
            result = step(spec, entry, context, trace=trace)
            if result.outcome is not Outcome.ACCEPTED:
                findings.extend(result.findings)
                reason = result.outcome.value
                return fail(
                    f"step {index} '{entry.id}' did not run ({reason}) — the journey "
                    f"cannot continue [after: {_trace_str(trace)}]"
                )
            assert result.post_context is not None  # ACCEPTED always materialises it
            context = result.post_context
            emitted_so_far.extend(result.emitted)
            trace.append(entry.id)
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
            seen = {(e if isinstance(e, type) else type(e)).__name__ for e in emitted_so_far}
            if entry.event_cls.__name__ not in seen:
                return fail(
                    f"checkpoint {index}: event '{entry.event_cls.__name__}' has not been "
                    f"emitted by this point [after: {_trace_str(trace)}]"
                )
        else:
            return fail(f"step {index} '{entry!r}' is not an Action, Assert(...) or Emitted(...)")

    return FlowResult(
        flow_id=flow.id, passed=True, findings=findings, steps_run=len(trace), trace=list(trace)
    )


def _trace_str(steps: list[str]) -> str:
    return " → ".join(steps) if steps else "(initial state)"
