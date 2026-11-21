"""Speculative safety checking and concrete replay."""

from copy import copy
from dataclasses import dataclass, field
from math import isqrt

from analint.models.action import Action
from analint.models.invariant import Invariant
from analint.models.predicate import Predicate
from analint.models.query import Reachable, Unreachable
from analint.models.root import Query
from analint.models.scope import InstanceRef, is_present
from analint.reporter.base import Code, Finding, InvariantResult, QueryResult, QueryStatus, Severity
from analint.validator.derived_model import Projection, derive
from analint.validator.explorer import (
    Exploration,
    StateKey,
    _eval_reachable,
    _key_in_layout,
    _report_invariant_violations,
    _scan_states,
    _state_layout,
    _verify_one_invariant,
    decode_state,
    explore,
    state_key,
)
from analint.validator.kernel import Outcome, step
from analint.validator.rule_checker import evaluate
from analint.validator.slicing import PRESENT, Slice, SliceAnalysis, Var
from analint.validator.state_checks import InvariantPlan

Target = Invariant | Unreachable
Result = InvariantResult | QueryResult
_MAX_REFINEMENTS = 3
_MAX_WITNESS_REPLAYS = 32


def _witness_budget(budget: int) -> int:
    # Coverage may run for every expanded action. Limit duplicate speculative
    # work at large budgets while giving bigger checks room beyond 4096 states.
    return max(1, min(budget // 4, 32 * isqrt(budget)))


def _refine(
    analysis: SliceAnalysis,
    predicate: Predicate | None,
    exact: Slice,
    projection: Projection,
    graph: Exploration,
    witness: StateKey | None = None,
    *,
    obligation: Action | None = None,
    replay_reads: set[Var] | None = None,
) -> Projection | None:
    faulting_actions = {
        graph.findings[index].location.removeprefix("action:") for index in graph.finding_states
    }
    reads = set(replay_reads or ())
    if not reads:
        reads.update(
            var
            for action in faulting_actions
            for _, term_reads in projection.dropped_guards.get(action, ())
            for var in term_reads
        )
    if not reads:
        origins = {origin for states in graph.finding_states.values() for origin in states}
        paths = [graph._trace(origin) for origin in sorted(origins)]
        if witness is not None:
            paths.append(graph.trace_to(witness))
        # Prefer the guard closest to each failed step. Earlier guards can
        # bring in unrelated state, so reconsider them only on a later round.
        for path in paths:
            for action in reversed(path):
                if action in projection.dropped_guards:
                    reads.update(
                        var
                        for _, term_reads in projection.dropped_guards[action]
                        for var in term_reads
                    )
                    break
    if not reads:
        return None
    return derive(
        analysis, predicate, exact, obligation=obligation, retain=projection.variables | reads
    )


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
    previous_rounds: list[dict] = field(default_factory=list)
    widened_fields: list[str] = field(default_factory=list)
    compact_report: dict | None = None

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

    def blocked_actions(self, piece: Slice) -> tuple[Action, ...]:
        """Find transition-only blockers that independent coverage can clear."""
        if self.graph.capped or self.graph.excluded or self.result.status != QueryStatus.PASS:
            return ()
        blockers = self._diagnostic_blockers()
        locations = {f"action:{action.id}": action for action in piece.actions}
        if not blockers or any(
            finding.location not in locations or not finding.code.value.startswith("transition.")
            for finding in blockers
        ):
            return ()
        names = {finding.location for finding in blockers}
        return tuple(action for name, action in locations.items() if name in names)

    def covered_by(self, actions: tuple[Action, ...], coverage: dict[int, Exploration]) -> bool:
        return bool(actions) and all(
            (graph := coverage.get(id(action))) is not None
            and not graph.capped
            and not graph.excluded
            and not graph.findings
            for action in actions
        )

    def release_graph(self) -> None:
        self.compact_report = self.round_report()
        self.graph.release_graph()

    def round_report(self) -> dict:
        if self.compact_report is not None:
            return self.compact_report.copy()
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
            "retained_fields": self.projection.fields,
            "widened_fields": self.widened_fields,
        }
        if self.candidate is not None:
            first["candidate_trace"] = self.graph.trace_to(self.candidate)
            first["candidate_root"] = self.graph.roots[self.graph.root_of(self.candidate)]
            first["replayed"] = self.replayed is not None
        return first

    def report(
        self,
        exact: Result | None = None,
        budget: int | None = None,
        *,
        exact_graph: Exploration | None = None,
        replayed: bool = False,
        covered: tuple[Action, ...] = (),
    ) -> dict:
        relation = "over-approx" if exact is None else "exact"
        if replayed:
            relation = "under-approx: replayed"
        elif exact is not None and exact.status == QueryStatus.INCONCLUSIVE:
            relation = None
        current: dict = self.round_report()
        if covered:
            current["covered_transition_actions"] = [action.id for action in covered]
        attempts = [*self.previous_rounds, current]
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


def _replay_path(
    analysis: SliceAnalysis,
    projection: Projection,
    abstract: Exploration,
    witness: StateKey,
    root: dict,
    number: int,
    multiple_roots: bool,
    *,
    exact: Slice | None = None,
    replay_reads: set[Var] | None = None,
) -> tuple[Exploration, StateKey] | None:
    origin = abstract.root_of(witness)
    projected_root = projection.context(root)
    layout = _state_layout(tuple(projected_root), projection.variables)
    if _key_in_layout(projected_root, *layout) != origin or not analysis.root_is_legal(root):
        return None
    actions = {action.id: action for action in (exact.actions if exact else analysis.spec.actions)}
    path = []
    cursor = witness
    while cursor != origin:
        parent, action_id = abstract.parents[cursor]
        action = actions.get(action_id)
        if action is None:
            return None
        path.append((action, cursor))
        cursor = parent

    plans = {id(inv): InvariantPlan(inv) for inv in analysis.spec.invariants}
    concrete = Exploration(store_edges=False)
    ctx = root
    key = state_key(root)
    concrete.add_state(key, -1, -1)
    concrete.roots[key] = number
    concrete.multiple_roots = multiple_roots
    for action, expected in reversed(path):
        transition = step(analysis.spec, action, ctx, explain=False)
        post = transition.post_context
        if transition.outcome != Outcome.ACCEPTED or post is None:
            if replay_reads is not None:
                for term, reads in projection.dropped_guards.get(action.id, ()):
                    try:
                        blocked = not evaluate(term, ctx)
                    except Exception:
                        blocked = True
                    if blocked:
                        replay_reads.update(reads)
                        break
            return None
        if _key_in_layout(projection.context(post), *layout) != expected:
            return None
        try:
            next_key = state_key(post)
        except TypeError:
            return None  # the concrete explorer cannot record this state
        if next_key in concrete.index:
            return None  # the concrete state key collapses this projected step
        concrete.add_state(next_key, concrete.index[key], concrete.action_code(action.id))
        key, ctx = next_key, post
        invalid = _report_invariant_violations(analysis.spec, ctx, key, concrete, plans=plans)
        if invalid and (expected != witness or exact is not None):
            return None
    return concrete, key


def _replay(
    target: Target,
    analysis: SliceAnalysis,
    projection: Projection,
    abstract: Exploration,
    witness: StateKey,
    initials: list[dict],
    exact: Slice,
) -> tuple[Result, Exploration] | None:
    roots, numbers, _ = analysis.project_roots(exact, initials)
    for number, root in zip(numbers, roots, strict=True):
        replay = _replay_path(analysis, projection, abstract, witness, root, number, len(roots) > 1)
        if replay is None:
            continue
        concrete, key = replay
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
    key = (id(target), analysis.roots_key(initials), budget, exact.key)
    if key not in analysis.derived_attempts:
        probe = _attempt(target, analysis, exact, initials, budget)
        if probe is not None and not analysis.retain_derived_graphs:
            probe.release_graph()
        analysis.derived_attempts[key] = probe
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
    sub_budget = _witness_budget(budget)
    previous_rounds: list[dict] = []
    widened_fields: list[str] = []
    for refinement in range(_MAX_REFINEMENTS + 1):
        graph = explore(
            projection.spec,
            [projection.context(ctx) for ctx in initials],
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
            _replay(target, analysis, projection, graph, candidate, initials, exact)
            if candidate is not None and not graph.excluded
            else None
        )
        current = Attempt(
            projection,
            graph,
            result,
            sub_budget,
            candidate,
            replay,
            analysis.spec.id,
            root_source(target) if isinstance(target, Unreachable) else "canonical",
            list(range(1, len(initials) + 1)),
        )
        current.previous_rounds = previous_rounds
        current.widened_fields = widened_fields
        if (
            current.proved
            or replay is not None
            or graph.capped
            or graph.excluded
            or refinement == _MAX_REFINEMENTS
        ):
            return current
        widened = _refine(analysis, predicate, exact, projection, graph, candidate)
        if widened is None:
            return current
        previous_rounds.append(current.round_report())
        widened_fields = widened.widened_fields(projection.variables)
        projection = widened
    raise AssertionError("refinement loop must return")


def cover_defects(
    action: Action,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    budget: int,
    *,
    canonical: bool,
    work: list[int] | None = None,
) -> tuple[Projection, Exploration] | None:
    """Prove clean transition coverage with the target action intact.

    Supporting writers may be weakened. Their rejected edges cannot remove
    a concrete accepted edge. Their defects are assessed by their own coverage
    obligations, so they cannot block this action's certificate.
    """
    if (work is not None and work[0] <= 0) or any(
        not analysis.root_is_legal(ctx) for ctx in initials
    ):
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
    for refinement in range(_MAX_REFINEMENTS + 1):
        limit = _witness_budget(budget)
        if work is not None:
            if work[0] <= 0:
                return None
            limit = min(limit, work[0])
        graph = explore(
            projection.spec,
            [projection.context(ctx) for ctx in initials],
            limit,
            store_edges=False,
            projection=projection.variables,
        )
        if work is not None:
            work[0] -= graph.state_count
        supporting_locations = {
            f"action:{writer.id}" for writer in projection.spec.actions if writer.id != action.id
        }
        if (
            not graph.capped
            and not graph.excluded
            and all(
                finding.location in supporting_locations
                and finding.code.value.startswith("transition.")
                for finding in graph.findings
            )
        ):
            if graph.findings:
                # The certificate enters coverage bookkeeping. Keep speculative
                # supporting diagnostics and their provenance out of it.
                graph = copy(graph)
                graph.findings = []
                graph.finding_states = {}
                graph._seen = {}
            return projection, graph
        if refinement == _MAX_REFINEMENTS or graph.capped or graph.excluded:
            return None
        widened = _refine(analysis, None, exact, projection, graph, obligation=action)
        if widened is None:
            return None
        projection = widened
    return None


def root_source(query: Query) -> str:
    if query.initial is not None:
        return "initial"
    if query.given_any:
        return "given_any"
    return "given" if query.given else "canonical"


@dataclass
class ReachProbe:
    model: dict
    witness: tuple[QueryResult, Exploration] | None = None

    def record_exact(self, result: QueryResult, graph: Exploration, budget: int) -> None:
        self.model["relation"] = "exact" if result.status != QueryStatus.INCONCLUSIVE else None
        recheck = {
            "relation": "exact",
            "backend": "native",
            "budget": budget,
            "complete": not graph.capped and not graph.excluded,
            "status": result.status,
            "states_explored": graph.state_count,
        }
        self.model["recheck"] = recheck
        self.model["attempts"].append(recheck)
        result.model = self.model


def reach_witness(
    query: Reachable,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    budget: int,
) -> ReachProbe | None:
    projection = derive(analysis, query.predicate, exact)
    if projection is None or any(not analysis.root_is_legal(ctx) for ctx in initials):
        return None
    exact_roots, _, _ = analysis.project_roots(exact, initials)
    # Per-root exploration preserves obligations even when abstract roots merge.
    # A complete scan is required because evaluation errors outrank a witness.
    attempts: list[dict] = []
    probe = ReachProbe(
        {
            "relation": "under-approx: replayed",
            "system_id": analysis.spec.id,
            "view_id": None,
            "proof_rule": "projection",
            "root_source": root_source(query),
            "root_numbers": list(range(1, len(initials) + 1)),
            "retained_fields": projection.fields,
            "dropped": projection.dropped,
            "omitted_writers": [
                item["location"] for item in projection.dropped if item.get("writes")
            ],
            "attempts": attempts,
            "recheck": None,
        }
    )
    best = None
    states = 0
    sub_budget = _witness_budget(budget)
    for number, root in enumerate(initials, 1):
        widened_fields: list[str] = []
        for refinement in range(_MAX_REFINEMENTS + 1):
            graph = explore(
                projection.spec,
                [projection.context(root)],
                sub_budget,
                store_edges=False,
                projection=projection.variables,
            )
            complete = not graph.capped and not graph.excluded
            abstract = {
                "relation": "over-approx",
                "backend": "native",
                "budget": sub_budget,
                "complete": complete,
                "root": number,
                "states_explored": graph.state_count,
                "status": QueryStatus.INCONCLUSIVE,
                "proof_blockers": [finding.to_dict() for finding in graph.findings],
                "retained_fields": projection.fields,
                "widened_fields": widened_fields,
            }
            attempts.append(abstract)
            if not complete:
                return probe
            witness = None
            replay_reads: set[Var] = set()
            if not graph.findings:
                scan = _scan_states(graph, query.predicate, collect_matches=True)
                witness = scan.first_match
                if scan.errors or witness is None:
                    abstract["status"] = QueryStatus.FAIL
                    abstract["evaluation_errors"] = scan.errors
                    return probe
                abstract["status"] = QueryStatus.PASS
                replay = None
                # An invented shortest path can coexist with a real witness
                # elsewhere on the same covering graph. Refine only if none
                # of the bounded replay candidates works.
                for index, match in enumerate(scan.matches[:_MAX_WITNESS_REPLAYS]):
                    candidate = graph.keys[match]
                    replay = _replay_path(
                        analysis,
                        projection,
                        graph,
                        candidate,
                        root,
                        number,
                        len(exact_roots) > 1,
                        exact=exact,
                        replay_reads=replay_reads if index == 0 else None,
                    )
                    if replay is not None:
                        witness = candidate
                        break
                abstract["candidate_trace"] = graph.trace_to(witness)
                abstract["replayed"] = replay is not None
                if replay is not None:
                    break
            if refinement == _MAX_REFINEMENTS:
                return probe
            widened = _refine(
                analysis,
                query.predicate,
                exact,
                projection,
                graph,
                witness,
                replay_reads=replay_reads,
            )
            if widened is None:
                return probe
            widened_fields = widened.widened_fields(projection.variables)
            projection = widened
            probe.model["retained_fields"] = projection.fields
            probe.model["dropped"] = projection.dropped
            probe.model["omitted_writers"] = [
                item["location"] for item in projection.dropped if item.get("writes")
            ]
        else:
            raise AssertionError("refinement loop must decide whether to replay")
        concrete, _ = replay
        result = _eval_reachable(query, query.id or "Reachable", concrete, True)
        if result.status != QueryStatus.PASS:
            return probe
        if best is None or concrete.state_count < best[1].state_count:
            best = result, concrete
        states += graph.state_count
        attempts.append(
            {
                "relation": "under-approx: replayed",
                "backend": "native",
                "complete": True,
                "status": QueryStatus.PASS,
                "root": number,
                "states_explored": concrete.state_count,
                "trace": result.trace,
            }
        )
    if best is not None:
        result, _ = best
        result.states_explored = states
        result.model = probe.model
        probe.witness = best
    return probe


def firing_witness(
    action: Action,
    analysis: SliceAnalysis,
    exact: Slice,
    initials: list[dict],
    proof: tuple[Projection, Exploration],
) -> dict | None:
    projection, graph = proof
    if action.id not in graph.fired:
        return None
    projected = next(
        candidate for candidate in projection.spec.actions if candidate.id == action.id
    )
    witness = next(
        (
            key
            for key in graph.order
            if step(projection.spec, projected, decode_state(key), explain=False).entered
        ),
        None,
    )
    if witness is None:
        return None
    roots, numbers, _ = analysis.project_roots(exact, initials)
    for number, root in zip(numbers, roots, strict=True):
        replay = _replay_path(
            analysis, projection, graph, witness, root, number, len(roots) > 1, exact=exact
        )
        if replay is None:
            continue
        concrete, key = replay
        if step(analysis.spec, action, decode_state(key), explain=False).entered:
            return {
                "relation": "under-approx: replayed",
                "backend": "native",
                "complete": True,
                "status": QueryStatus.PASS,
                "root": number,
                "action": action.id,
                "trace": [*concrete.trace_to(key), action.id],
                "states_explored": concrete.state_count,
                "retained_fields": projection.fields,
            }
    return None
