from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from types import ModuleType
from typing import TYPE_CHECKING

from analint.loader.discovery import discover_files
from analint.loader.python_loader import (
    LoadError,
    _import_standalone,
    collect_from_modules,
    load_path,
    resolve_entry,
)
from analint.models.query import query_budget
from analint.models.root import Spec
from analint.reporter.base import Code, Finding, Severity, ValidationResult
from analint.validator.exploration_work import current_work, measure_work
from analint.validator.scenario_runner import run_scenario
from analint.validator.selection import SelectionError, select_checks
from analint.validator.structural import validate_structural

if TYPE_CHECKING:
    from analint.validator.explorer import Exploration
    from analint.validator.safety import SafetyProof


def build_spec(path: Path, extra: Path | None = None) -> tuple[Spec | None, list, list[LoadError]]:
    """Load the spec model (naming, what-if merge) without running any checks.

    `extra` is a what-if patch: a standalone .py file whose objects (scenarios,
    invariants, actions, …) are added to the model without touching the spec
    files. It is imported after the spec, so it can import the spec's modules.
    """
    specs, modules, load_errors = load_path(path)
    patch = None
    if extra is not None:
        try:
            with _spec_alias(path, modules):
                # A what-if file is an editable hypothesis, not part of the
                # stable spec import closure. Re-execute it on every validation
                # so repeated MCP checks observe edits at the same path.
                patch = _import_standalone(Path(extra).resolve(), use_cache=False)
            modules = [*modules, patch]
        except Exception as exc:
            load_errors = [*load_errors, LoadError(Path(extra), exc)]

    if not specs:
        return None, modules, load_errors
    if len(specs) == 1:
        return _complete_model(specs[0], modules, patch), modules, load_errors
    try:
        entry = resolve_entry(path)
    except LoadError as exc:
        return None, modules, [*load_errors, exc]
    error = LoadError(
        entry,
        ValueError(
            "multiple Spec objects found in the import graph; declare one root Spec "
            "and compose reusable fragments through Contract + Spec(imports=[...])"
        ),
    )
    return None, modules, [*load_errors, error]


@contextmanager
def _spec_alias(path: Path, modules: list[ModuleType]) -> Iterator[None]:
    """Temporarily expose the loaded entry module to a what-if patch.

    A what-if patch is a standalone file imported *after* the spec, so it can
    import the spec's objects. A packaged spec is importable under its real
    package name, but a single-file spec is loaded under a private synthetic name
    a patch cannot know (this is why ``--what-if`` used to fail on single-file
    examples). Expose the entry module under the fixed alias ``analint_spec`` so a
    patch can always do ``from analint_spec import X`` regardless of layout.

    The alias exists only while the patch executes. Leaving it in ``sys.modules``
    would leak one validated spec into later validations in the same MCP process.
    """
    try:
        entry = resolve_entry(path)
    except LoadError:
        yield
        return
    entry_module = next(
        (
            module
            for module in modules
            if (file_name := getattr(module, "__file__", None))
            and Path(file_name).resolve() == entry
        ),
        None,
    )
    if entry_module is None:
        yield
        return

    had_previous = "analint_spec" in sys.modules
    previous = sys.modules.get("analint_spec")
    sys.modules["analint_spec"] = entry_module
    try:
        yield
    finally:
        if not had_previous:
            sys.modules.pop("analint_spec", None)
        elif previous is not None:
            sys.modules["analint_spec"] = previous


@dataclass
class PreparedModel:
    """The loaded, structurally-checked model — shared so that validation and
    exploration always work from an identical prepared Spec."""

    spec: Spec | None
    modules: list
    load_errors: list
    structural_findings: list[Finding]

    @property
    def has_structural_errors(self) -> bool:
        return any(f.severity.value == "ERROR" for f in self.structural_findings)


def prepare_model(path: Path, *, what_if: Path | None = None) -> PreparedModel:
    """Load the spec (+ optional what-if), warn about unloaded files and run
    structural validation — the single model-preparation path for `validate` and
    the exploration service."""
    spec, modules, load_errors = build_spec(path, extra=what_if)
    structural: list[Finding] = []
    if spec is not None:
        structural.extend(_unloaded_file_warnings(path, modules))
        structural.extend(_orphan_warnings(spec, modules))
        structural.extend(validate_structural(spec))
    return PreparedModel(
        spec=spec, modules=modules, load_errors=load_errors, structural_findings=structural
    )


def validate(
    path: Path,
    scenario_ids: list[str] | None = None,
    tags: list[str] | None = None,
    extra: Path | None = None,
    max_states: int | None = None,
    sliced: bool = True,
    tlc: bool = False,
    tlc_timeout: float | None = None,
    cache: bool = False,
    checks: list[str] | None = None,
    explain_slice: bool = False,
    explain_work: bool = False,
) -> ValidationResult:
    """``checks`` selects flow/query/invariant ids (or KIND:ID). None retains
    the full check; [] or unknown/ambiguous ids raise SelectionError. Selection
    never changes model behavior. Explicit selections prove dependency-related
    canonical invariants and limit sliced action coverage to their dependencies.

    ``max_states`` overrides every exploration budget for this run — the
    spec's canonical one and each query's — without mutating the model.

    ``sliced`` checks each invariant/query on its cone of influence instead of
    the whole model (research/34 §5); ``False`` keeps the monolithic path for
    differential testing (``check --no-slice``).

    ``tlc`` hands every check analint left INCONCLUSIVE to TLC, on the same
    slice (``validator/tlc_fallback.py``, research/36 R6).

    ``cache`` memoises explorations on disk (``validator/exploration_cache.py``):
    the result is the one a fresh run gives."""
    prepared = prepare_model(path, what_if=extra)
    return _validate_prepared(
        prepared,
        scenario_ids=scenario_ids,
        tags=tags,
        checks=checks,
        max_states=max_states,
        sliced=sliced,
        tlc=tlc,
        tlc_timeout=tlc_timeout,
        cache=cache,
        explain_slice=explain_slice,
        explain_work=explain_work,
    )


def validate_spec(
    spec: Spec,
    *,
    checks: list[str] | None = None,
    scenario_ids: list[str] | None = None,
    tags: list[str] | None = None,
    max_states: int | None = None,
    sliced: bool = True,
    tlc: bool = False,
    tlc_timeout: float | None = None,
    cache: bool = False,
    explain_slice: bool = False,
    explain_work: bool = False,
) -> ValidationResult:
    """Verify a reusable Spec with invocation-only selection/settings.

    Explicit ids are required, as for other in-memory APIs. Structural checks
    run each time; no Spec is reconstructed and no declarations are mutated.
    """
    prepared = PreparedModel(spec, [], [], validate_structural(spec))
    return _validate_prepared(
        prepared,
        scenario_ids=scenario_ids,
        tags=tags,
        checks=checks,
        max_states=max_states,
        sliced=sliced,
        tlc=tlc,
        tlc_timeout=tlc_timeout,
        cache=cache,
        explain_slice=explain_slice,
        explain_work=explain_work,
    )


def _validate_prepared(
    prepared: PreparedModel,
    *,
    checks: list[str] | None = None,
    scenario_ids: list[str] | None = None,
    tags: list[str] | None = None,
    max_states: int | None = None,
    sliced: bool = True,
    tlc: bool = False,
    tlc_timeout: float | None = None,
    cache: bool = False,
    explain_slice: bool = False,
    explain_work: bool = False,
    decided: dict[str, Exploration] | None = None,
) -> ValidationResult:
    from analint.validator.exploration_cache import use_store

    if max_states is not None and (type(max_states) is not int or max_states < 1):
        raise SelectionError("max_states must be a positive integer")
    if tlc_timeout is not None and tlc_timeout <= 0:
        raise SelectionError("tlc_timeout must be positive")
    with measure_work(explain_work) as work, use_store(None) if cache else nullcontext():
        result = _run_checks(
            prepared,
            checks,
            scenario_ids,
            tags,
            max_states,
            sliced,
            tlc,
            tlc_timeout,
            cache,
            decided,
            explain_slice,
        )
        if work is not None:
            result.exploration_work = work.report(result, prepared.spec, max_states, tlc)
        return result


def _run_checks(
    prepared: PreparedModel,
    checks: list[str] | None,
    scenario_ids: list[str] | None,
    tags: list[str] | None,
    max_states: int | None,
    sliced: bool,
    tlc: bool,
    tlc_timeout: float | None,
    cache: bool,
    decided: dict[str, Exploration] | None,
    explain_slice: bool,
) -> ValidationResult:
    spec, load_errors = prepared.spec, prepared.load_errors

    if spec is None:
        result = ValidationResult(
            spec_id="__empty__",
            spec_name="(no spec found)",
            load_errors=[str(e) for e in load_errors],
        )
        return result

    result = ValidationResult(
        spec_id=spec.id,
        spec_name=spec.name,
        load_errors=[str(e) for e in load_errors],
    )

    result.structural_findings.extend(prepared.structural_findings)

    if prepared.has_structural_errors:
        return result

    work = current_work.get()
    selection = select_checks(spec, checks, scenario_ids, tags)
    safety_proofs: dict[str, SafetyProof] = {}
    probe_ms: dict[str, float] = {}
    derived_attempts = {}
    if checks is not None and sliced and selection.queries:
        from analint.validator.safety import prove_query
        from analint.validator.slicing import SliceAnalysis

        # Speculative graphs must not acquire canonical trust or contribute
        # diagnostics. Share only their own roots/budget cache across attempts.
        probe_analysis = SliceAnalysis(spec, explain_slice=explain_slice)
        probe_analysis.retain_derived_graphs = decided is not None
        for query in selection.queries:
            started = perf_counter()
            if work is not None:
                work.query_phase(query)
            proof = prove_query(
                query,
                spec,
                probe_analysis,
                max_states=max_states,
                tlc=tlc,
                tlc_timeout=tlc_timeout,
            )
            probe_ms[query.id] = (perf_counter() - started) * 1000
            if proof is not None:
                if probe_analysis.reasons is not None:
                    proof.result.slice_dependencies = probe_analysis.reasons[id(query)].report()
                if work is not None:
                    work.link(f"query:{query.id}", proof.exploration)
                safety_proofs[query.id] = proof
        derived_attempts = probe_analysis.derived_attempts
        del probe_analysis
        if decided is None:
            for proof in safety_proofs.values():
                proof.exploration.release_graph()
    verification_scope = None
    if checks is not None:
        from analint.validator.verification_scope import VerificationScope

        verification_scope = VerificationScope(
            spec,
            selection,
            sliced=sliced,
            discharged={f"query:{name}": proof.piece for name, proof in safety_proofs.items()},
        )
    result.selection = selection.scope
    if result.selection is not None:
        result.selection["options"] = {
            "max_states": max_states,
            "sliced": sliced,
            "tlc": tlc,
            "tlc_timeout": tlc_timeout,
            "cache": cache,
        }
        result.selection["budgets"] = {
            "canonical": max_states or spec.max_states,
            "queries": {
                q.id: query_budget(q, spec.max_states, max_states) for q in selection.queries
            },
        }
    for scenario in selection.scenarios:
        result.scenario_results.append(run_scenario(scenario, spec))

    if selection.flows:
        from analint.validator.flow_runner import run_flow

        for flow in selection.flows:
            result.flow_results.append(run_flow(flow, spec))

    # Findings from different explorations of the same state space overlap, so
    # deduplicate across them — but by their full identity, not message alone:
    # two actions excluded for the same reason carry the same message at
    # different locations and must both survive.
    seen_findings: set[tuple[str, str, str]] = set()

    def _merge_exploration_findings(exploration: Exploration) -> None:
        for finding in exploration.findings:
            key = (finding.severity.value, finding.location, finding.message)
            if key not in seen_findings:
                seen_findings.add(key)
                result.exploration_findings.append(finding)

    # The canonical initial is part of the model: build it once (reused below)
    # and validate that it builds even when nothing consumes it.
    from analint.validator.explorer import (
        ExplorationStorage,
        build_canonical_initials,
        resolve_query_initials,
        run_query,
    )

    canonical_initials: list | None = None
    canonical_error: str | None = None
    if spec.initial is not None or selection.invariants:
        canonical_initials, canonical_error = build_canonical_initials(spec)
    if spec.initial is not None and canonical_initials is None:
        result.exploration_findings.append(
            Finding(
                Severity.ERROR,
                f"spec:{spec.id}",
                f"canonical initial cannot be built: {canonical_error}",
                Code.CANONICAL_INITIAL_ERROR,
            )
        )

    # Shared by the canonical invariant check and the queries: a default-source
    # query with the same roots and budget reuses the canonical exploration.
    analysis = None
    if sliced and (selection.invariants or selection.queries):
        from analint.validator.slicing import SliceAnalysis

        analysis = SliceAnalysis(spec, explain_slice=explain_slice)
        analysis.retain_derived_graphs = decided is not None
        analysis.derived_attempts = derived_attempts
    explorations = ExplorationStorage(analysis)
    canonical_group = explorations.register(canonical_initials, max_states or spec.max_states)
    query_runs = []
    for query in selection.queries:
        started = perf_counter()
        initial_state = (
            (safety_proofs[query.id].initials, None)
            if query.id in safety_proofs
            else resolve_query_initials(query, spec, intern=False)
        )
        group = (
            None
            if query.id in safety_proofs
            else explorations.plan_query(
                query, initial_state[0], query_budget(query, spec.max_states, max_states)
            )
        )
        query_runs.append((query, initial_state, group, (perf_counter() - started) * 1000))

    if selection.invariants:
        from analint.validator.explorer import (
            _retain_exact_statistics,
            cover_actions,
            verify_invariants,
        )

        if work is not None:
            work.phase = "canonical_invariants_and_coverage"
            work.root_source = "canonical"
        while True:
            native_graphs = decided if decided is not None or work is None else {}
            result.invariant_results, _ = verify_invariants(
                spec,
                canonical_initials,
                build_error=canonical_error,
                invariants=selection.invariants,
                max_states=max_states or spec.max_states,
                cache=explorations,
                analysis=analysis,
                explorations=native_graphs,
                all_actions=verification_scope is None,
            )
            if work is not None and native_graphs is not None:
                for checked in result.invariant_results:
                    work.link(
                        f"invariant:{checked.invariant_id}", native_graphs.get(checked.invariant_id)
                    )
            del native_graphs
            if verification_scope is None or not verification_scope.refine(analysis):
                break
        if verification_scope is not None:
            verification_scope.register(
                canonical_initials,
                [f"invariant:{inv.id}" for inv in selection.invariants],
            )

            if analysis is not None and canonical_initials is not None:
                cover_actions(
                    analysis,
                    canonical_initials,
                    max_states or spec.max_states,
                    explorations,
                    canonical=True,
                    actions=verification_scope.actions_for(
                        f"invariant:{inv.id}" for inv in selection.invariants
                    ),
                )
                for inv, checked in zip(
                    selection.invariants, result.invariant_results, strict=True
                ):
                    if checked.model is not None and checked.model["relation"] == "over-approx":
                        _retain_exact_statistics(
                            checked,
                            analysis,
                            analysis.invariant_slice(inv, unconstrained=True),
                            canonical_initials,
                            max_states or spec.max_states,
                        )

    explorations.finish(canonical_group, decided)

    if query_runs:
        for query, initial_state, group, setup_ms in query_runs:
            if verification_scope is not None:
                initials, _ = initial_state
                verification_scope.register(
                    initials,
                    [f"query:{query.id}"],
                )
            proof = safety_proofs.get(query.id)
            if proof is not None:
                assert verification_scope is not None
                query_result = proof.result
                verification_scope.safety_coverage.extend(
                    (proof.piece, graph) for graph in (proof.exploration, *proof.projected_coverage)
                )
                if decided is not None:
                    decided[query.id] = proof.exploration
            else:
                if work is not None:
                    work.query_phase(query)
                native_graphs = decided if decided is not None or work is None else {}
                query_result = run_query(
                    query,
                    spec,
                    explorations,
                    max_states=max_states,
                    analysis=analysis,
                    explorations=native_graphs,
                    initial_state=initial_state,
                    coverage_actions=(
                        verification_scope.actions_for([f"query:{query.id}"])
                        if verification_scope is not None
                        else None
                    ),
                )
                if work is not None and native_graphs is not None:
                    work.link(f"query:{query.id}", native_graphs.get(query.id))
                del native_graphs
            query_result.elapsed_ms = (
                (query_result.elapsed_ms or 0.0) + probe_ms.get(query.id, 0.0) + setup_ms
            )
            result.query_results.append(query_result)
            explorations.finish(group, decided)

    if explain_slice:
        for prop, checked in [
            *zip(selection.invariants, result.invariant_results, strict=True),
            *zip(selection.queries, result.query_results, strict=True),
        ]:
            if checked.slice_dependencies is not None:
                continue  # selected safety proof from the isolated analysis
            reasons = (
                analysis.reasons.get(id(prop))
                if analysis and analysis.reasons is not None
                else None
            )
            if reasons is not None:
                checked.slice_dependencies = reasons.report()
            else:
                mode = "slicing_disabled" if not sliced else "no_property_closure"
                checked.slice_dependencies = {
                    "scope": "property_closure",
                    "mode": mode,
                    "inclusions": [],
                }

    if tlc:
        from analint.validator.tlc_fallback import decide_with_tlc

        decide_with_tlc(
            spec,
            result,
            analysis,
            canonical_initials,
            timeout=tlc_timeout,
            defect_actions=(
                {
                    name: {a.id for a in piece.actions}
                    for name, piece in verification_scope.pieces.items()
                }
                if verification_scope is not None
                else None
            ),
        )

    if verification_scope is not None:
        verification_scope.collect(result, explorations, analysis)
        return result

    used = analysis.explorations() if analysis is not None else []
    # Surface the transition defects every exploration found — a broken action
    # must fail the run, not hide behind a green invariant.
    for exp in [*explorations.values(), *used]:
        _merge_exploration_findings(exp)
        if result.selection is not None:
            result.selection["excluded_actions"].update(exp.excluded)

    # A backend-discovered transition defect is a hard model failure even if
    # TLC stopped before deciding the requested predicate. Explicit selections
    # already collect these through VerificationScope above.
    for check in [*result.query_results, *result.invariant_results]:
        result.exploration_findings.extend(
            f for f in check.findings if f.code == Code.TLC_TRANSITION_DEFECT
        )

    return result


def _unloaded_file_warnings(path: Path, modules: list) -> list[Finding]:
    """Warn about .py files in the spec directory not reachable from the entry point.

    The import graph of the entry point defines the spec; a file nobody imports
    is silently absent from the model — that is almost always a forgotten import.
    """
    if not path.is_dir():
        return []
    loaded = {Path(m.__file__).resolve() for m in modules if getattr(m, "__file__", None)}
    findings: list[Finding] = []
    for f in discover_files(path):
        rf = f.resolve()
        if rf not in loaded and rf.name != "__init__.py":
            findings.append(
                Finding(
                    Severity.WARNING,
                    f"loader:{f.name}",
                    f"'{f}' is not imported from the spec entry point and was ignored",
                    Code.UNLOADED_FILE,
                )
            )
    return findings


def _orphan_warnings(spec: Spec, modules: list) -> list[Finding]:
    """Warn about behaviour defined in the spec modules but absent from the model.

    Explicit membership trades silent inclusion for possible silent omission: a
    forgotten action is behaviour nobody explores, which can turn a check green.
    Surfacing it keeps the omission visible (research/35 R4).
    """
    collected = collect_from_modules(modules)
    members = {
        id(obj)
        for obj in (
            *spec._declared_actions,
            *spec.actions,
            *spec.invariants,
            *spec.scenarios,
            *spec.flows,
            *spec.queries,
        )
    }
    return [
        Finding(
            Severity.WARNING,
            f"{kind}:{obj.id}",
            f"'{obj.id}' is defined in the spec modules but is not part of the model "
            f"— list it in the Spec or a Contract, or delete it",
            Code.ORPHAN,
        )
        for kind, key in (
            ("action", "actions"),
            ("invariant", "invariants"),
            ("scenario", "scenarios"),
            ("flow", "flows"),
            ("query", "queries"),
        )
        for obj in collected[key]
        if id(obj) not in members
    ]


def _complete_model(spec: Spec, modules: list, patch: ModuleType | None = None) -> Spec:
    """Name the loaded objects and merge the what-if module (research/35 R3, R6).

    Membership is exactly what the Spec and its imported contracts list, plus
    the entities, events, scopes and lifecycles that behaviour references
    (R1, R2). Nothing is collected from module globals: a defined but unlisted
    behaviour object is reported as an orphan instead (R4).
    """
    collect_from_modules(modules)  # ids from variable names; never membership
    if patch is not None:
        # the root is cached with its import closure: merge into a copy, or
        # the hypothesis would stay in the model for every later load
        spec = spec.model_copy()
        _extend_composed_spec(spec, collect_from_modules([patch]))
    return spec


def _extend_composed_spec(spec: Spec, collected: dict) -> None:
    """Add a what-if module's objects to the model (research/35 R6)."""
    from analint.models.param import expand_action

    for field_name in (
        "entities",
        "scopes",
        "events",
        "lifecycles",
        "flows",
        "invariants",
        "scenarios",
        "queries",
    ):
        setattr(
            spec,
            field_name,
            _deduplicate_by_identity([*getattr(spec, field_name), *collected[field_name]]),
        )

    added_actions = [bound for action in collected["actions"] for bound in expand_action(action)]
    spec.actions = _deduplicate_by_identity([*spec.actions, *added_actions])
    spec._declared_actions = _deduplicate_by_identity(
        [*spec._declared_actions, *collected["actions"]]
    )
    spec.close_references()


def _deduplicate_by_identity(objects: list) -> list:
    seen: set[int] = set()
    result: list = []
    for obj in objects:
        marker = id(obj)
        if marker not in seen:
            seen.add(marker)
            result.append(obj)
    return result
