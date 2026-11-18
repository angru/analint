"""Dependency closure and diagnostic ownership for explicit check selections.

A clean unconstrained safety PASS discharges pruning support. Other canonical
queries request the proofs their unconstrained cone needs.
Successful unconstrained invariant proofs need no further support; other proofs
and constrained queries grow the dependency set until it is closed. Whole-model
execution uses a conservative constrained closure. No analysis removes model
constraints or grants trust to an unchecked invariant.
"""

from __future__ import annotations

from analint.models.query import AlwaysHolds, Reachable, Unreachable
from analint.models.root import Spec
from analint.reporter.base import Code, Finding, ValidationResult
from analint.validator.explorer import Exploration, state_key
from analint.validator.selection import Selection
from analint.validator.slicing import Slice, SliceAnalysis
from analint.validator.state_checks import check_invariants


def _locations(piece: Slice) -> set[str]:
    return {f"action:{a.id}" for a in piece.actions} | {
        f"invariant:{i.id}" for i in piece.invariants
    }


def _root_key(initials: list[dict]) -> tuple:
    return tuple(dict.fromkeys(state_key(ctx) for ctx in initials))


class VerificationScope:
    def __init__(
        self,
        spec: Spec,
        selection: Selection,
        *,
        sliced: bool,
        discharged: dict[str, Slice] | None = None,
    ) -> None:
        self.spec = spec
        self.sliced = sliced
        self.selection = selection
        self.discharged = discharged or {}
        planner = SliceAnalysis(spec)
        self.pieces: dict[str, Slice] = {}
        targets = {id(inv) for inv in selection.invariants}
        for query in selection.queries:
            name = f"query:{query.id}"
            if name in self.discharged:
                self.pieces[name] = self.discharged[name]
                continue
            # Recoverability is global under invariant pruning: an unrelated
            # violation can strand a full-model state. DeadActions asks about
            # every action. Neither may hide defects behind a local predicate.
            piece = (
                planner.whole
                if not isinstance(query, (AlwaysHolds, Reachable, Unreachable))
                else planner.predicate_slice(
                    query.predicate,
                    canonical=False,
                    unconstrained=sliced
                    and not (query.given or query.given_any or query.initial is not None),
                )
            )
            self.pieces[f"query:{query.id}"] = piece
            if not (query.given or query.given_any or query.initial is not None):
                targets.update(id(inv) for inv in planner.supporting_invariants(piece))
        # Proofs may themselves depend on further invariant constraints.
        pending = list(selection.invariants) + [
            inv for inv in spec.invariants if id(inv) in targets
        ]
        while pending:
            inv = pending.pop()
            name = f"invariant:{inv.id}"
            if name in self.pieces:
                continue
            piece = planner.invariant_slice(inv, unconstrained=sliced)
            self.pieces[name] = piece
            for dependency in piece.invariants if not sliced else ():
                if id(dependency) not in targets:
                    targets.add(id(dependency))
                    pending.append(dependency)
        selection.invariants = [inv for inv in spec.invariants if id(inv) in targets]
        self._metadata()
        self.known = {f"action:{a.id}" for a in spec.actions} | {
            f"invariant:{inv.id}" for inv in spec.invariants
        }
        self.routes: dict[tuple, set[str]] = {}
        self.root_findings: list[Finding] = []
        self.root_defects: set[tuple] = set()
        self.checked_roots: set[tuple] = set()

    def _metadata(self) -> None:
        selection = self.selection
        scope = selection.scope
        assert scope is not None
        scope["supporting"] = [
            f"invariant:{inv.id}"
            for inv in selection.invariants
            if f"invariant:{inv.id}" not in scope["requested"]
        ]
        scope["not_selected"] = [
            name for name in scope["not_selected"] if name not in scope["supporting"]
        ]
        scope["dependencies"] = {
            name: {
                "actions": [a.id for a in piece.actions],
                "invariants": [i.id for i in piece.invariants],
                "whole_model": piece.vars is None,
            }
            for name, piece in self.pieces.items()
        }

    def refine(self, analysis: SliceAnalysis | None) -> bool:
        """Add only dependencies consulted by the actual proof strategy.

        Each non-final pass adds an invariant; the loop is bounded by model size.
        Results/explorations are reused by the existing per-run caches.
        """
        if not self.sliced or analysis is None:
            return False
        targets = {id(inv) for inv in self.selection.invariants}
        needed = set(targets)
        for inv in self.selection.invariants:
            trusted = id(inv) in analysis.trusted
            piece = analysis.invariant_slice(inv, unconstrained=trusted)
            self.pieces[f"invariant:{inv.id}"] = piece
            if not trusted:
                needed.update(id(dep) for dep in analysis.supporting_invariants(piece))
        for query in self.selection.queries:
            if f"query:{query.id}" in self.discharged:
                continue
            canonical = not (query.given or query.given_any or query.initial is not None)
            piece = (
                analysis.whole
                if not isinstance(query, (AlwaysHolds, Reachable, Unreachable))
                else analysis.predicate_slice(query.predicate, canonical=canonical)
            )
            self.pieces[f"query:{query.id}"] = piece
            if canonical:
                needed.update(id(inv) for inv in analysis.supporting_invariants(piece))
        self.selection.invariants = [inv for inv in self.spec.invariants if id(inv) in needed]
        self._metadata()
        return needed != targets

    def register(self, initials: list[dict] | None, checks: list[str]) -> None:
        if initials is None:
            return
        root_key = _root_key(initials)
        # Budgets limit search, not behavior. A real defect found at the same
        # roots also belongs to a selected check with a smaller search budget.
        allowed = self.routes.setdefault(root_key, set())
        for name in checks:
            allowed.add(name)
            allowed.update(_locations(self.pieces[name]))
        if root_key not in self.checked_roots:
            self.checked_roots.add(root_key)
            # Every invariant participates in root legality, even outside a
            # slice. A bad root is a dependency, not an unrelated diagnostic.
            for index, ctx in enumerate(initials, 1):
                findings = check_invariants(self.spec, ctx, f"initial #{index}")
                self.root_findings.extend(findings)
                self.root_defects.update(
                    (f.code, f.severity, f.location, state_key(ctx)) for f in findings
                )

    def collect(
        self, result: ValidationResult, cache: dict, analysis: SliceAnalysis | None
    ) -> None:
        runs = [(key, exp) for key, exp in cache.items()]
        if analysis is not None:
            runs += [
                ((tuple(dict.fromkeys(roots)), budget), exp)
                for (roots, budget), entries in analysis.explored.items()
                for piece, exp in entries
                if analysis.is_exact(piece)
            ]
        scoped: dict[tuple, Finding] = {}
        model: dict[tuple, Finding] = {}
        seen: dict[int, Exploration] = {}
        excluded: dict[str, str] = {}
        selected_excluded: dict[str, str] = {}
        for key, exp in runs:
            seen[id(exp)] = exp
            allowed = self.routes.get(key[0])
            for index, finding in enumerate(exp.findings):
                identity = (finding.code, finding.severity, finding.location, finding.message)
                # Unknown ownership stays blocking; never parse diagnostic prose.
                target = (
                    model
                    if allowed is not None
                    and finding.location in self.known
                    and finding.location not in allowed
                    else scoped
                )
                states = exp.finding_states.get(index)
                if (
                    target is model
                    and states
                    and all(
                        exp.parent[state] < 0
                        and (finding.code, finding.severity, finding.location, exp.keys[state])
                        in self.root_defects
                        for state in states
                    )
                ):
                    # Root legality already owns this exact failure. A later
                    # state or missing provenance must retain the diagnostic.
                    continue
                target[identity] = finding
            excluded.update(exp.excluded)
            selected_excluded.update(
                {
                    aid: why
                    for aid, why in exp.excluded.items()
                    if allowed is None or f"action:{aid}" in allowed
                }
            )
        for finding in self.root_findings:
            scoped[(finding.code, finding.severity, finding.location, finding.message)] = finding
        # TLC only asserts defects in this check's dependency actions. A found
        # defect blocks the selected run even if TLC could not decide its target.
        for check in [*result.query_results, *result.invariant_results]:
            for finding in check.findings:
                if finding.code == Code.TLC_TRANSITION_DEFECT:
                    scoped[(finding.code, finding.severity, finding.location, finding.message)] = (
                        finding
                    )
        result.exploration_findings.extend(scoped.values())
        result.model_findings = [f for key, f in model.items() if key not in scoped]
        result.model_coverage = {
            "scope": "actions_from_verification_roots",
            "root_sets": len(self.routes),
            "explorations": len(seen),
            "states_explored": sum(len(exp.states) for exp in seen.values()),
            "capped_explorations": sum(exp.capped for exp in seen.values()),
            "excluded_actions": excluded,
            "invariant_proofs": "selected_and_supporting_only",
        }
        assert result.selection is not None
        result.selection["excluded_actions"] = selected_excluded
