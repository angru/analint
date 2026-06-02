from __future__ import annotations
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

from analint.models.root import Spec


class LoadError(Exception):
    def __init__(self, path: Path, cause: Exception) -> None:
        super().__init__(f"{path}: {cause}")
        self.path = path
        self.cause = cause


def load_module(path: Path) -> tuple[ModuleType | None, LoadError | None]:
    # Ensure the working directory is importable so user packages resolve correctly
    cwd = str(Path.cwd().resolve())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    file_spec = importlib.util.spec_from_file_location(f"_analint_{path.stem}", path)
    if file_spec is None or file_spec.loader is None:
        return None, None

    module = importlib.util.module_from_spec(file_spec)
    module_name = f"_analint_{path.stem}_{id(path)}"
    sys.modules[module_name] = module
    try:
        file_spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module, None
    except Exception as exc:
        sys.modules.pop(module_name, None)
        return None, LoadError(path, exc)


def load_specs_from_file(path: Path) -> list[Spec]:
    module, error = load_module(path)
    if error:
        raise error
    if module is None:
        return []
    return [v for v in vars(module).values() if isinstance(v, Spec)]


def load_all(files: list[Path]) -> tuple[list[Spec], list[ModuleType], list[LoadError]]:
    """Load all files. Returns (specs, modules, errors)."""
    specs: list[Spec] = []
    modules: list[ModuleType] = []
    errors: list[LoadError] = []
    for f in files:
        module, error = load_module(f)
        if error:
            errors.append(error)
            continue
        if module is None:
            continue
        modules.append(module)
        specs.extend(v for v in vars(module).values() if isinstance(v, Spec))
    return specs, modules, errors


def collect_from_modules(modules: list[ModuleType]) -> dict:
    """Scan modules and collect all analint instances. Deduplicates across modules."""
    from analint.models.entity import Entity
    from analint.models.actor import Actor
    from analint.models.event import Event
    from analint.models.business import BusinessRule, UseCase
    from analint.models.scenario import Scenario
    from analint.models.statemachine import StateMachine
    from analint.models.flow import Flow

    _BASE_CLASSES = {Entity, Actor, Event}

    seen_classes: set = set()
    seen_instances: list = []

    entities: list = []
    actors: list = []
    events: list = []
    rules: list = []
    use_cases: list = []
    scenarios: list = []
    state_machines: list = []
    flows: list = []

    for module in modules:
        for _, obj in inspect.getmembers(module):
            if isinstance(obj, type):
                if obj in seen_classes or obj in _BASE_CLASSES:
                    continue
                seen_classes.add(obj)
                if issubclass(obj, Entity):
                    entities.append(obj)
                elif issubclass(obj, Actor):
                    actors.append(obj)
                elif issubclass(obj, Event):
                    events.append(obj)
            elif isinstance(obj, (BusinessRule, UseCase, Scenario, StateMachine, Flow)):
                if obj in seen_instances:
                    continue
                seen_instances.append(obj)
                if isinstance(obj, BusinessRule):
                    rules.append(obj)
                elif isinstance(obj, UseCase):
                    use_cases.append(obj)
                elif isinstance(obj, Scenario):
                    scenarios.append(obj)
                elif isinstance(obj, StateMachine):
                    state_machines.append(obj)
                elif isinstance(obj, Flow):
                    flows.append(obj)

    return {
        "entities": entities,
        "actors": actors,
        "events": events,
        "rules": rules,
        "use_cases": use_cases,
        "scenarios": scenarios,
        "state_machines": state_machines,
        "flows": flows,
    }
