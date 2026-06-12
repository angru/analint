from __future__ import annotations

import hashlib
import importlib
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


# Maps a resolved entry path to the names of all modules its import pulled in,
# so repeated loads in one process (tests) reuse the same closure and the same
# class identities instead of re-executing files.
_CLOSURE_CACHE: dict[Path, set[str]] = {}


def resolve_entry(path: Path) -> Path:
    """A spec is loaded through a single entry point: a .py file, or spec.py in a directory."""
    if path.is_file():
        return path.resolve()
    entry = path / "spec.py"
    if entry.is_file():
        return entry.resolve()
    raise LoadError(
        path,
        FileNotFoundError(
            "no spec.py entry point found; create spec.py that imports the rest of the spec"
        ),
    )


def _package_context(entry: Path) -> tuple[Path, str]:
    """Return (sys.path root, qualified module name) for the entry file.

    Walks up while __init__.py exists, so a packaged spec is imported under its
    real package name and sibling imports resolve to the same module objects —
    this is what prevents duplicate class identities.
    """
    parts = [entry.stem]
    d = entry.parent
    while (d / "__init__.py").is_file():
        parts.insert(0, d.name)
        d = d.parent
    return d, ".".join(parts)


def _import_packaged(qualname: str, entry: Path) -> ModuleType:
    cached = sys.modules.get(qualname)
    if cached is not None:
        cached_file = getattr(cached, "__file__", None)
        if cached_file and Path(cached_file).resolve() != entry:
            raise ImportError(
                f"module name '{qualname}' already refers to {cached_file}; "
                f"rename the spec package to avoid the collision"
            )
        return cached
    return importlib.import_module(qualname)


def _import_standalone(entry: Path) -> ModuleType:
    """Import a non-packaged entry file under a synthetic unique name.

    Nothing imports the entry module itself, so the synthetic name cannot cause
    duplicate identities; siblings the entry imports go through the standard
    import system (the entry's directory is on sys.path).
    """
    digest = hashlib.sha1(str(entry).encode()).hexdigest()[:8]
    name = f"_analint_entry_{entry.stem}_{digest}"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    file_spec = importlib.util.spec_from_file_location(name, entry)
    if file_spec is None or file_spec.loader is None:
        raise ImportError(f"cannot create import spec for {entry}")
    module = importlib.util.module_from_spec(file_spec)
    sys.modules[name] = module
    try:
        file_spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_entry(entry: Path) -> tuple[ModuleType, list[ModuleType]]:
    """Import the entry point; return (entry module, all spec modules).

    Spec modules are the modules pulled in by the entry whose files live under
    the entry's directory. Everything goes through the standard import system,
    so each file is executed exactly once per process.
    """
    entry = entry.resolve()
    root, qualname = _package_context(entry)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    before = set(sys.modules)
    if root == entry.parent:
        module = _import_standalone(entry)
    else:
        module = _import_packaged(qualname, entry)

    if entry not in _CLOSURE_CACHE:
        _CLOSURE_CACHE[entry] = (set(sys.modules) - before) | {module.__name__}
    closure = _CLOSURE_CACHE[entry]

    base = entry.parent
    modules: list[ModuleType] = []
    for name in sorted(closure):
        m = sys.modules.get(name)
        f = getattr(m, "__file__", None) if m is not None else None
        if m is not None and f and Path(f).resolve().is_relative_to(base):
            modules.append(m)
    return module, modules


def load_path(path: Path) -> tuple[list[Spec], list[ModuleType], list[LoadError]]:
    """Load a spec from a directory (with spec.py) or a single file."""
    try:
        entry = resolve_entry(path)
    except LoadError as e:
        return [], [], [e]
    try:
        _, modules = load_entry(entry)
    except Exception as exc:
        return [], [], [LoadError(entry, exc)]

    specs: list[Spec] = []
    seen: set[int] = set()
    for m in modules:
        for v in vars(m).values():
            if isinstance(v, Spec) and id(v) not in seen:
                seen.add(id(v))
                specs.append(v)
    return specs, modules, []


def load_specs_from_file(path: Path) -> list[Spec]:
    specs, _, errors = load_path(path)
    if errors:
        raise errors[0]
    return specs


def collect_from_modules(modules: list[ModuleType]) -> dict:
    """Scan modules and collect all analint instances. Deduplicates across modules.

    As a side effect, fills empty `id` fields from the module-level variable
    name the object is bound to (`archive_card = Action(...)` → id "archive_card").
    """
    from analint.models.action import Action
    from analint.models.actor import Actor
    from analint.models.entity import Entity
    from analint.models.event import Event
    from analint.models.flow import Flow
    from analint.models.invariant import Invariant
    from analint.models.lifecycle import Lifecycle
    from analint.models.query import QUERY_TYPES
    from analint.models.scenario import Scenario
    from analint.models.scope import Scope

    _BASE_CLASSES = {Entity, Actor, Event}

    seen_classes: set = set()
    # Dedup by object identity: comparing by == is unsafe here, because
    # dataclass equality on predicate fields hits the overloaded operators.
    seen_instances: set[int] = set()

    entities: list = []
    actors: list = []
    events: list = []
    invariants: list = []
    actions: list = []
    scenarios: list = []
    lifecycles: list = []
    flows: list = []
    queries: list = []
    scopes: list = []

    _INSTANCE_TYPES = (Invariant, Action, Scenario, Lifecycle, Flow, Scope, *QUERY_TYPES)

    for module in modules:
        for var_name, obj in inspect.getmembers(module):
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
            elif isinstance(obj, _INSTANCE_TYPES):
                if not obj.id:
                    obj.id = var_name
                if id(obj) in seen_instances:
                    continue
                seen_instances.add(id(obj))
                if isinstance(obj, Invariant):
                    invariants.append(obj)
                elif isinstance(obj, Action):
                    actions.append(obj)
                elif isinstance(obj, Scenario):
                    scenarios.append(obj)
                elif isinstance(obj, Lifecycle):
                    lifecycles.append(obj)
                elif isinstance(obj, Flow):
                    flows.append(obj)
                elif isinstance(obj, QUERY_TYPES):
                    queries.append(obj)
                elif isinstance(obj, Scope):
                    scopes.append(obj)

    # Lifecycles declared inline as field defaults live on the entity classes
    seen_lc = {id(lc) for lc in lifecycles}
    for cls in entities:
        for desc in getattr(cls, "_own_fields", {}).values():
            lc = desc.lifecycle
            if lc is not None and id(lc) not in seen_lc:
                seen_lc.add(id(lc))
                lifecycles.append(lc)

    return {
        "entities": entities,
        "actors": actors,
        "events": events,
        "invariants": invariants,
        "actions": actions,
        "scenarios": scenarios,
        "lifecycles": lifecycles,
        "flows": flows,
        "queries": queries,
        "scopes": scopes,
    }
