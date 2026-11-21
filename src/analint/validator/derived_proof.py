"""Speculative safety checking and concrete replay."""

from dataclasses import dataclass

from analint.models.action import Action
from analint.models.invariant import Invariant
from analint.models.query import Unreachable
from analint.models.scope import InstanceRef, is_present
from analint.reporter.base import Code, Finding, InvariantResult, QueryResult, QueryStatus, Severity
from analint.validator.derived_model import Projection, derive
from analint.validator.explorer import (
    Exploration,
    StateKey,
    _eval_reachable,
    _key_in_layout,
    _report_invariant_violations,
    _state_layout,
    _verify_one_invariant,
    explore,
    state_key,
)
from analint.validator.kernel import Outcome, step
from analint.validator.slicing import PRESENT, Slice, SliceAnalysis
from analint.validator.state_checks import InvariantPlan

Target = Invariant | Unreachable
Result = InvariantResult | QueryResult


def _evaluate(target: Target, graph: Exploration) -> Result:
    if isinstance(target, Invariant):
        return _verify_one_invariant(target, graph)
    return _eval_reachable(target, target.id, graph, False)


@dataclass
class Attempt:
    projection: Projection
    graph: Exploration
    result: Result
    budget: int
    candidate: StateKey | None
    replayed: tuple[Result, Exploration] | None
    system_id: str
    root_source: str
    roots: list[int]

    def _diagnostic_blockers(self) -> list[Finding]:
        return [
            *self.graph.findings,
            *(
                finding
                for finding in self.result.findings
                if finding.code in (Code.INVARIANT_EVALUATION_ERROR, Code.QUERY_EVALUATION_ERROR)
            ),
        ]

    @property
    def clean(self) -> bool:
        return not self.graph.excluded and not self._diagnostic_blockers()

    @property
    def proved(self) -> bool:
        return self.result.status == QueryStatus.PASS and not self.graph.capped and self.clean

    def report(
        self,
        exact: Result | None = None,
        budget: int | None = None,
        *,
        exact_graph: Exploration | None = None,
        replayed: bool = False,
    ) -> dict:
        relation = "over-approx" if exact is None else "exact"
        if replayed:
            relation = "under-approx: replayed"
        elif exact is not None and exact.status == QueryStatus.INCONCLUSIVE:
            relation = None
        blockers = self._diagnostic_blockers()
        if self.graph.capped:
            blockers.append(
                Finding(
                    Severity.WARNING,
                    "model:over-approx",
                    f"projected exploration exhausted its {self.budget}-state budget",
                    Code.BUDGET_EXHAUSTED,
                )
            )
        first = {
            "relation": "over-approx",
            "backend": "native",
            "budget": self.budget,
            "complete": not self.graph.capped and not self.graph.excluded,
            "clean": self.clean,
            "proof_blockers": [finding.to_dict() for finding in blockers],
            "status": self.result.status,
            "states_explored": self.graph.state_count,
        }
        if self.candidate is not None:
            first["candidate_trace"] = self.graph.trace_to(self.candidate)
            first["candidate_root"] = self.graph.roots[self.graph.root_of(self.candidate)]
            first["replayed"] = self.replayed is not None
        attempts = [first]
        if self.replayed is not None:
            result, graph = self.replayed
            attempts.append(
                {
                    "relation": "under-approx: replayed",
                    "backend": "native",
                    "budget": len(result.trace or ()),
                    "complete": True,
                    "status": QueryStatus.FAIL,
                    "states_explored": graph.state_count,
                    "root": next(iter(graph.roots.values())),
                }
            )
        recheck = None
        if exact is not None:
            recheck = {
                "relation": "exact",
                "backend": exact.backend or "native",
                "budget": budget,
                "complete": (
                    not exact_graph.capped and not exact_graph.excluded
                    if exact_graph is not None and exact.backend is None
                    else exact.status != QueryStatus.INCONCLUSIVE
                ),
                "status": exact.status,
                "states_explored": exact.states_explored,
            }
            attempts.append(recheck)
        return {
            "relation": relation,
            "system_id": self.system_id,
            "view_id": None,
            "proof_rule": "projection",
            "root_source": self.root_source,
            "root_numbers": self.roots,
            "retained_fields": self.projection.fields,
            "dropped": self.projection.dropped,
            "omitted_writers": [
                item["location"] for item in self.projection.dropped if item.get("writes")
            ],
            "attempts": attempts,
            "recheck": recheck,
        }


def _replay(
    target: Target,
    analysis: SliceAnalysis,
    projection: Projection,
    abstract: Exploration,
    witness: StateKey,
    initials: list[dict],
) -> tuple[Result, Exploration] | None:
    actions = {action.id: action for action in analysis.spec.actions}
    origin = abstract.root_of(witness)
    path = []
    cursor = witness
    while cursor != origin:
        parent, action_id = abstract.parents[cursor]
        path.append((actions[action_id], cursor))
        cursor = parent
    path.reverse()
    plans = {id(inv): InvariantPlan(inv) for inv in analysis.spec.invariants}
    for number, root in enumerate(initials, 1):
        projected_root = projection.context(root)
        layout = _state_layout(tuple(projected_root), projection.variables)
        if _key_in_layout(projected_root, *layout) != origin or not analysis.root_is_legal(root):
            continue
        concrete = Exploration(store_edges=False)
        ctx = root
        key = state_key(root)
        concrete.add_state(key, -1, -1)
        concrete.roots[key] = number
        concrete.multiple_roots = len(initials) > 1
        for action, expected in path:
            transition = step(analysis.spec, action, ctx, explain=False)
            post = transition.post_context
            if transition.outcome != Outcome.ACCEPTED or post is None:
                break
            if _key_in_layout(projection.context(post), *layout) != expected:
                break
            try:
                next_key = state_key(post)
            except TypeError:
                break  # the concrete explorer cannot record this state
            concrete.add_state(next_key, concrete.index[key], concrete.action_code(action.id))
            key, ctx = next_key, post
            invalid = _report_invariant_violations(analysis.spec, ctx, key, concrete, plans=plans)
            if invalid and expected != witness:
                break
        else:
            result = _evaluate(target, concrete)
            if (
                result.status == QueryStatus.FAIL
                and result.witness_key == key
                and result.findings[0].code in (Code.INVARIANT_VIOLATED, Code.REACHED_FORBIDDEN)
            ):
                return result, concrete
    return None


def attempt(
    target: Target,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    budget: int,
) -> Attempt | None:
    key = (id(target), analysis.roots_key(initials), budget)
    if key not in analysis.derived_attempts:
        analysis.derived_attempts[key] = _attempt(target, analysis, exact, initials, budget)
    return analysis.derived_attempts[key]


def _attempt(
    target: Target,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    budget: int,
) -> Attempt | None:
    predicate = target.expression if isinstance(target, Invariant) else target.predicate
    projection = derive(analysis, predicate, exact)
    if projection is None or any(not analysis.root_is_legal(ctx) for ctx in initials):
        return None
    roots = [projection.context(ctx) for ctx in initials]
    applicability = InvariantPlan(target if isinstance(target, Invariant) else Invariant(predicate))
    scoped_reads = {
        key
        for key, name in projection.variables
        if isinstance(key, InstanceRef) and name != PRESENT
    }
    if not any(
        applicability.is_applicable(root)
        and (not scoped_reads or any(is_present(root, key) for key in scoped_reads))
        for root in roots
    ):
        # Keep exact budget and applicability semantics when a content check
        # could only observe slot contents after creation, including aggregates
        # and universal predicates that can be evaluated on an empty scope.
        return None
    sub_budget = min(4096, max(1, budget // 4))
    graph = explore(
        projection.spec,
        roots,
        sub_budget,
        store_edges=False,
        projection=projection.variables,
    )
    result = _evaluate(target, graph)
    candidate = (
        result.witness_key
        if result.status == QueryStatus.FAIL
        and result.findings[0].code in (Code.INVARIANT_VIOLATED, Code.REACHED_FORBIDDEN)
        else None
    )
    replay = (
        _replay(target, analysis, projection, graph, candidate, initials)
        if candidate is not None and not graph.excluded
        else None
    )
    source = "canonical"
    if isinstance(target, Unreachable):
        if target.initial is not None:
            source = "initial"
        elif target.given_any:
            source = "given_any"
        elif target.given:
            source = "given"
    return Attempt(
        projection,
        graph,
        result,
        sub_budget,
        candidate,
        replay,
        analysis.spec.id,
        source,
        list(range(1, len(initials) + 1)),
    )


def cover_defects(
    action: Action,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    budget: int,
    *,
    canonical: bool,
) -> tuple[Projection, Exploration] | None:
    """Prove clean transition coverage with the target action intact.

    Supporting writers may be weakened. Their failures are speculative and
    force exact coverage, which owns diagnostic ordering and trace attribution.
    """
    if any(not analysis.root_is_legal(ctx) for ctx in initials):
        return None
    projection = derive(analysis, None, exact, obligation=action)
    if projection is None:
        return None
    for invariant in exact.invariants:
        if canonical and id(invariant) in analysis.trusted:
            continue
        probe = attempt(
            invariant,
            analysis,
            analysis.invariant_slice(invariant, unconstrained=True),
            initials,
            budget,
        )
        if probe is None or not probe.proved:
            return None
    graph = explore(
        projection.spec,
        [projection.context(ctx) for ctx in initials],
        min(4096, max(1, budget // 4)),
        store_edges=False,
        projection=projection.variables,
    )
    if graph.capped or graph.findings or graph.excluded:
        return None
    return projection, graph
