from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
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
from analint.models.root import Spec
from analint.reporter.base import Finding, Severity, ValidationResult
from analint.validator.scenario_runner import run_scenario
from analint.validator.structural import validate_structural

if TYPE_CHECKING:
    from analint.validator.explorer import Exploration


def build_spec(path: Path, extra: Path | None = None) -> tuple[Spec | None, list, list[LoadError]]:
    """Load and auto-populate the spec model without running any checks.

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
        return _auto_populate(specs[0], modules, patch), modules, load_errors
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
) -> ValidationResult:
    """``max_states`` overrides every exploration budget for this run — the
    spec's canonical one and each query's — without mutating the model.

    ``sliced`` checks each invariant/query on its cone of influence instead of
    the whole model (research/34 §5); ``False`` keeps the monolithic path for
    differential testing (``check --no-slice``)."""
    prepared = prepare_model(path, what_if=extra)
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

    scenarios = spec.scenarios
    if scenario_ids:
        scenarios = [sc for sc in scenarios if sc.id in scenario_ids]
    if tags:
        scenarios = [sc for sc in scenarios if any(t in sc.tags for t in tags)]

    for scenario in scenarios:
        result.scenario_results.append(run_scenario(scenario, spec))

    if spec.flows:
        from analint.validator.flow_runner import run_flow

        for flow in spec.flows:
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
    from analint.validator.explorer import build_canonical_initials

    canonical_initials: list | None = None
    canonical_error: str | None = None
    if spec.initial is not None or spec.invariants:
        canonical_initials, canonical_error = build_canonical_initials(spec)
    if spec.initial is not None and canonical_initials is None:
        result.exploration_findings.append(
            Finding(
                Severity.ERROR,
                f"spec:{spec.id}",
                f"canonical initial cannot be built: {canonical_error}",
            )
        )

    # Shared by the canonical invariant check and the queries: a default-source
    # query with the same roots and budget reuses the canonical exploration.
    explorations: dict = {}
    analysis = None
    if sliced and (spec.invariants or spec.queries):
        from analint.validator.slicing import SliceAnalysis

        analysis = SliceAnalysis(spec)
    if spec.invariants:
        from analint.validator.explorer import verify_invariants

        result.invariant_results, _ = verify_invariants(
            spec,
            canonical_initials,
            build_error=canonical_error,
            max_states=max_states or spec.max_states,
            cache=explorations,
            analysis=analysis,
        )

    if spec.queries:
        from analint.validator.explorer import run_query

        for query in spec.queries:
            result.query_results.append(
                run_query(query, spec, explorations, max_states=max_states, analysis=analysis)
            )

    used = analysis.explorations() if analysis is not None else []
    # Surface the transition defects every exploration found — a broken action
    # must fail the run, not hide behind a green invariant.
    for exp in [*explorations.values(), *used]:
        _merge_exploration_findings(exp)

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


def _auto_populate(spec: Spec, modules: list, patch: ModuleType | None = None) -> Spec:
    """Fill empty list fields from auto-discovered instances.

    If a field is explicitly set (non-empty), it is used as-is.
    If a field is empty (the default), it is populated from all loaded modules.
    This lets users write Spec(id=..., name=...) and get everything for free,
    while still allowing explicit lists when precision matters.
    """
    # Composition is an explicit mode: importing implementation modules must
    # not make their private objects part of the root model by accident.
    if spec.imports:
        # Keep the loader's variable-name id derivation without using the
        # collected contents to populate the composed root.
        collect_from_modules(modules)
        if patch is not None:
            # the root is cached with its import closure: merge into a copy, or
            # the hypothesis would stay in the model for every later load
            spec = spec.model_copy()
            _extend_composed_spec(spec, collect_from_modules([patch]))
        return spec

    collected = collect_from_modules(modules)

    def _resolve(explicit: list, key: str) -> list:
        return list(explicit) if explicit else collected[key]

    populated = Spec(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        description=spec.description,
        imports=spec.imports,
        entities=_resolve(spec.entities, "entities"),
        scopes=_resolve(spec.scopes, "scopes"),
        events=_resolve(spec.events, "events"),
        lifecycles=_resolve(spec.lifecycles, "lifecycles"),
        flows=_resolve(spec.flows, "flows"),
        invariants=_resolve(spec.invariants, "invariants"),
        # the declarations, not their Param expansion: the rebuilt Spec expands
        # them again, and membership (orphans) is about the declaration
        actions=_resolve(spec._declared_actions, "actions"),
        scenarios=_resolve(spec.scenarios, "scenarios"),
        queries=_resolve(spec.queries, "queries"),
        initial=spec.initial,
        max_states=spec.max_states,
    )
    if patch is not None:
        # an explicit list must not drop the hypothesis (research/35 R6); an
        # auto-populated one already holds it, and the merge deduplicates
        _extend_composed_spec(populated, collect_from_modules([patch]))
    return populated


def _extend_composed_spec(spec: Spec, collected: dict) -> None:
    """Add only a what-if module's objects to an explicitly listed root."""
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
