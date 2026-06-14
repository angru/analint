from __future__ import annotations

from analint.models.flow import Assert, Emitted
from analint.models.root import Spec
from analint.models.scenario import Expect, Scenario
from analint.models.scope import Absent, instance_context_key
from analint.reporter.base import Finding, ScenarioResult, Severity
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.state_checks import check_invariants, relevant_invariants
from analint.validator.structural import _describe


def run_scenario(scenario: Scenario, spec: Spec) -> ScenarioResult:
    """Run one scenario through the shared transition kernel.

    The kernel decides the transition; this wrapper layers the scenario's own
    concerns on top: the *pre-state* must be a legal world (invariants hold),
    the *post-state* must keep holding them, and any ``then`` assertions must be
    satisfied. ``Expect.FAIL`` is honoured only for a genuine pre-execution
    block — never for a model defect.
    """
    findings: list[Finding] = []
    context = {instance_context_key(inst): inst for inst in scenario.given}
    for scope in spec.scopes:
        for ref in scope:
            context.setdefault(ref, Absent(ref))
    action = scenario.action

    relevant = relevant_invariants(spec, context)
    checks_count = len(relevant) + len(action.pre) + len(action.post)

    # The pre-state must itself be a legal world. A scenario that starts from a
    # state violating an invariant is a model defect, not a rejection — the world
    # it describes is already illegal, so Expect.FAIL cannot legitimise it.
    pre_inv_findings = check_invariants(relevant, context, "INVARIANT")
    findings.extend(pre_inv_findings)
    pre_invariant_violated = bool(pre_inv_findings)

    # The transition itself: pre/presence/terminal guards, effects, Field,
    # lifecycle and postconditions all live in the kernel now.
    result = step(spec, action, context)
    findings.extend(result.findings)

    post_defect = False
    if result.outcome is Outcome.ACCEPTED and not pre_invariant_violated:
        post = result.post_context
        assert post is not None
        post_inv_findings = check_invariants(relevant, post, "INVARIANT (post)")
        findings.extend(post_inv_findings)
        then_failed = _check_then(findings, scenario, post)
        post_defect = bool(post_inv_findings) or then_failed

    # Only a genuine pre-execution rejection (a guard) legitimises Expect.FAIL;
    # a model defect — including an illegal initial state — never does, even when
    # a precondition also happens to reject the action.
    if scenario.expected == Expect.FAIL:
        passed = result.outcome is Outcome.REJECTED and not pre_invariant_violated
        if passed:
            findings.append(
                Finding(
                    Severity.INFO,
                    f"scenario:{scenario.id}",
                    "correctly blocked — rules rejected this data as expected",
                )
            )
        else:
            message = "expected the action to be blocked, but every precondition passed"
            if result.outcome is Outcome.DEFECT or pre_invariant_violated or post_defect:
                message += " — the failures above are a model defect, not a rejection"
            findings.append(Finding(Severity.ERROR, f"scenario:{scenario.id}", message))
    else:
        passed = (
            result.outcome is Outcome.ACCEPTED and not pre_invariant_violated and not post_defect
        )

    return ScenarioResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        passed=passed,
        findings=findings,
        rules_count=checks_count,
    )


def _check_then(findings: list[Finding], scenario: Scenario, post: dict) -> bool:
    """Evaluate the scenario's ``then`` assertions over the next state."""
    emitted_names = {
        (e if isinstance(e, type) else type(e)).__name__ for e in scenario.action.emits
    }
    failed = False
    for assertion in scenario.then:
        if isinstance(assertion, Assert):
            try:
                if not evaluate(assertion.predicate, post):
                    findings.append(
                        Finding(
                            Severity.ERROR,
                            f"scenario:{scenario.id}",
                            f"then: {_describe(assertion.predicate)} — not satisfied",
                        )
                    )
                    failed = True
            except Exception as exc:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then evaluation error: {exc}",
                    )
                )
                failed = True
        elif isinstance(assertion, Emitted):
            if assertion.event_cls.__name__ not in emitted_names:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        f"scenario:{scenario.id}",
                        f"then: event '{assertion.event_cls.__name__}' not in action.emits",
                    )
                )
                failed = True
        else:
            findings.append(
                Finding(
                    Severity.ERROR,
                    f"scenario:{scenario.id}",
                    f"then entry '{assertion!r}' is not Assert(...) or Emitted(...)",
                )
            )
            failed = True
    return failed
