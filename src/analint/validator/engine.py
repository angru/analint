from __future__ import annotations
from pathlib import Path

from analint.loader.discovery import discover_files
from analint.loader.python_loader import collect_from_modules, load_all
from analint.models.root import Spec
from analint.reporter.base import ValidationResult
from analint.validator.structural import validate_structural
from analint.validator.scenario_runner import run_scenario


def validate(path: Path, scenario_ids: list[str] | None = None, tags: list[str] | None = None) -> ValidationResult:
    files = discover_files(path)
    specs, modules, load_errors = load_all(files)

    if not specs:
        result = ValidationResult(
            spec_id="__empty__",
            spec_name="(no spec found)",
            load_errors=[str(e) for e in load_errors],
        )
        return result

    if len(specs) == 1:
        spec = _auto_populate(specs[0], modules)
    else:
        spec = _merge_specs(specs)

    result = ValidationResult(
        spec_id=spec.id,
        spec_name=spec.name,
        load_errors=[str(e) for e in load_errors],
    )

    result.structural_findings = validate_structural(spec)

    has_structural_errors = any(
        f.severity.value == "ERROR" for f in result.structural_findings
    )
    if has_structural_errors:
        return result

    scenarios = spec.scenarios
    if scenario_ids:
        scenarios = [sc for sc in scenarios if sc.id in scenario_ids]
    if tags:
        scenarios = [sc for sc in scenarios if any(t in sc.tags for t in tags)]

    for scenario in scenarios:
        result.scenario_results.append(run_scenario(scenario, spec))

    return result


def _auto_populate(spec: Spec, modules: list) -> Spec:
    """Fill empty list fields from auto-discovered instances.

    If a field is explicitly set (non-empty), it is used as-is.
    If a field is empty (the default), it is populated from all loaded modules.
    This lets users write Spec(id=..., name=...) and get everything for free,
    while still allowing explicit lists when precision matters.
    """
    collected = collect_from_modules(modules)

    def _resolve(explicit: list, key: str) -> list:
        return list(explicit) if explicit else collected[key]

    return Spec(
        id=spec.id,
        name=spec.name,
        version=spec.version,
        description=spec.description,
        entities=_resolve(spec.entities, "entities"),
        actors=_resolve(spec.actors, "actors"),
        events=_resolve(spec.events, "events"),
        state_machines=_resolve(spec.state_machines, "state_machines"),
        flows=_resolve(spec.flows, "flows"),
        rules=_resolve(spec.rules, "rules"),
        use_cases=_resolve(spec.use_cases, "use_cases"),
        scenarios=_resolve(spec.scenarios, "scenarios"),
    )


def _merge_specs(specs: list[Spec]) -> Spec:
    if len(specs) == 1:
        return specs[0]

    first = specs[0]
    merged = Spec(id=first.id, name=first.name, version=first.version, description=first.description)
    seen_classes: set = set()
    seen_instances: list = []

    for s in specs:
        for cls_list, target in [
            (s.entities, merged.entities),
            (s.actors, merged.actors),
            (s.events, merged.events),
        ]:
            for c in cls_list:
                if c not in seen_classes:
                    seen_classes.add(c)
                    target.append(c)
        for inst_list, target in [
            (s.state_machines, merged.state_machines),
            (s.flows, merged.flows),
            (s.rules, merged.rules),
            (s.use_cases, merged.use_cases),
            (s.scenarios, merged.scenarios),
        ]:
            for obj in inst_list:
                if obj not in seen_instances:
                    seen_instances.append(obj)
                    target.append(obj)
    return merged
