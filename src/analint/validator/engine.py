from __future__ import annotations

from pathlib import Path
from types import ModuleType

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
            patch = _import_standalone(Path(extra).resolve())
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


def validate(
    path: Path,
    scenario_ids: list[str] | None = None,
    tags: list[str] | None = None,
    extra: Path | None = None,
) -> ValidationResult:
    spec, modules, load_errors = build_spec(path, extra=extra)

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

    result.structural_findings.extend(_unloaded_file_warnings(path, modules))
    result.structural_findings.extend(validate_structural(spec))

    has_structural_errors = any(f.severity.value == "ERROR" for f in result.structural_findings)
    if has_structural_errors:
        return result

    scenarios = spec.scenarios
    if scenario_ids:
        scenarios = [sc for sc in scenarios if sc.id in scenario_ids]
    if tags:
        scenarios = [sc for sc in scenarios if any(t in sc.tags for t in tags)]

    for scenario in scenarios:
        result.scenario_results.append(run_scenario(scenario, spec))

    if spec.queries:
        from analint.validator.explorer import run_query

        explorations: dict = {}
        for query in spec.queries:
            result.query_results.append(run_query(query, spec, explorations))
        seen_messages: set[str] = set()
        for exp in explorations.values():
            for finding in exp.findings:
                if finding.message not in seen_messages:
                    seen_messages.add(finding.message)
                    result.exploration_findings.append(finding)

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
            _extend_composed_spec(spec, collect_from_modules([patch]))
        return spec

    collected = collect_from_modules(modules)

    def _resolve(explicit: list, key: str) -> list:
        return list(explicit) if explicit else collected[key]

    return Spec(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        description=spec.description,
        imports=spec.imports,
        entities=_resolve(spec.entities, "entities"),
        scopes=_resolve(spec.scopes, "scopes"),
        actors=_resolve(spec.actors, "actors"),
        events=_resolve(spec.events, "events"),
        lifecycles=_resolve(spec.lifecycles, "lifecycles"),
        flows=_resolve(spec.flows, "flows"),
        invariants=_resolve(spec.invariants, "invariants"),
        actions=_resolve(spec.actions, "actions"),
        scenarios=_resolve(spec.scenarios, "scenarios"),
        queries=_resolve(spec.queries, "queries"),
    )


def _extend_composed_spec(spec: Spec, collected: dict) -> None:
    """Add only a what-if module's objects to an explicitly composed root."""
    from analint.models.param import expand_action

    for field_name in (
        "entities",
        "scopes",
        "actors",
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


def _deduplicate_by_identity(objects: list) -> list:
    seen: set[int] = set()
    result: list = []
    for obj in objects:
        marker = id(obj)
        if marker not in seen:
            seen.add(marker)
            result.append(obj)
    return result
