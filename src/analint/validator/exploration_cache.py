"""On-disk memo of explorations (``check --cache``).

``explore()`` is a pure function of the (sliced) spec it runs, its roots, root
numbers, inert roots and budget. The store keys an exploration by a canonical
digest of exactly those inputs plus the engine's own source, and keeps the
graph in a portable form: slot value tuples, not this process's interned
codes. A hit therefore returns the graph, findings and fired actions a fresh
run would build, and every check on top of it decides exactly as on a fresh
run. Anything the canonicaliser does not know makes the exploration
uncacheable; it is then explored as usual. A file that cannot be read is a
miss, never an error.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import json
import os
import sys
import zlib
from array import array
from collections.abc import Callable, Iterator
from enum import Enum
from functools import cache
from pathlib import Path
from typing import Any

import analint
from analint.models.action import Action
from analint.models.effect import Create, Delete
from analint.models.entity import _MISSING, FieldDescriptor, FieldSpec, all_fields
from analint.models.lifecycle import Lifecycle
from analint.models.quantifier import Bound, BoundField
from analint.models.root import Spec
from analint.models.scope import InstanceField, InstanceRef, Scope, context_key_label
from analint.reporter.base import Finding, Severity
from analint.validator import explorer
from analint.validator.explorer import Exploration

FORMAT = 1
MAX_BYTES = 512 * 1024 * 1024  # pruned oldest-first beyond this


class _Uncacheable(Exception):
    """A value or node the canonical form does not cover."""


def default_dir() -> Path:
    explicit = os.environ.get("ANALINT_CACHE_DIR")
    if explicit:
        return Path(explicit)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "analint" / "explorations"


@contextlib.contextmanager
def use_store(directory: Path | None) -> Iterator[None]:
    """Memoise every ``explore()`` in this block through ``directory``."""
    previous = explorer._STORE
    explorer._STORE = _Store(directory or default_dir())
    try:
        yield
    finally:
        explorer._STORE = previous


# ── canonical form ───────────────────────────────────────────────────────────


def _name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _value(value: Any, classes: dict[str, type] | None = None) -> Any:
    """A state value as JSON-safe data; the inverse is ``_Registry.value``.
    ``classes`` collects the enum and entity classes the values name."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"f": repr(value)}
    if isinstance(value, Enum):
        if classes is not None:
            classes[_name(type(value))] = type(value)
        return {"e": _name(type(value)), "n": value.name}
    if isinstance(value, InstanceRef):
        if classes is not None:
            classes[_name(value.entity_cls)] = value.entity_cls
        return {"r": _name(value.entity_cls), "k": _value(value.key, classes)}
    raise _Uncacheable(f"state value {value!r}")


def _canon(obj: Any, classes: dict[str, type]) -> Any:
    if obj is _MISSING:
        return "<missing>"
    if obj is None or isinstance(obj, (bool, int, str, float, Enum, InstanceRef)):
        return _value(obj, classes)
    if isinstance(obj, type):
        classes[_name(obj)] = obj
        return {"c": _name(obj)}
    if isinstance(obj, FieldDescriptor):
        return ["field", _canon(obj.entity_cls, classes), obj.field_name]
    if isinstance(obj, InstanceField):
        return ["ifield", _value(obj.instance, classes), obj.descriptor.field_name]
    if isinstance(obj, Bound):
        return ["bound", obj.name, _canon(obj.scope, classes)]
    if isinstance(obj, BoundField):
        return ["bfield", _canon(obj.variable, classes), obj.field_name]
    if isinstance(obj, Scope):
        keys = [_value(k, classes) for k in obj.keys]
        return ["scope", _canon(obj.entity_cls, classes), keys, obj.id]
    if isinstance(obj, Create):
        fields = sorted((k, _canon(v, classes)) for k, v in obj.fields.items())
        return ["create", _value(obj.target, classes), fields]
    if isinstance(obj, Delete):
        return ["delete", _value(obj.target, classes)]
    if isinstance(obj, Action):
        return [
            "action",
            obj.id,
            obj.name,
            *(
                [_canon(item, classes) for item in items]
                for items in (obj.pre, obj.effect, obj.post, obj.emits)
            ),
        ]
    if isinstance(obj, Lifecycle):
        return [
            "lifecycle",
            obj.id,
            _canon(obj.entity_cls, classes),
            obj.field_name,
            _value(obj.initial, classes),
            sorted(
                [_value(src, classes), [_value(d, classes) for d in dsts]]
                for src, dsts in obj.transitions.items()
            ),
            [_value(t, classes) for t in obj.terminal],
        ]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # predicate/expression/effect nodes, Invariant, FieldSpec
        return [
            _name(type(obj)),
            *(
                _canon(getattr(obj, f.name), classes)
                for f in dataclasses.fields(obj)
                if not f.name.startswith("_")
            ),
        ]
    if isinstance(obj, (list, tuple)):
        return [_canon(item, classes) for item in obj]
    if hasattr(obj, "__dict__") and hasattr(type(obj), "_own_fields"):
        # an Entity/Event instance (an emitted payload template)
        classes[_name(type(obj))] = type(obj)
        return [
            "instance",
            _name(type(obj)),
            [[k, _canon(obj.__dict__.get(k), classes)] for k in all_fields(type(obj))],
        ]
    raise _Uncacheable(f"{type(obj).__name__}")


def _class_canon(cls: type, classes: dict[str, type]) -> Any:
    if issubclass(cls, Enum):
        return ["enum", [[m.name, _value(m.value, classes)] for m in cls]]
    fields = []
    for name, desc in all_fields(cls).items():
        spec = desc.spec if isinstance(desc.spec, FieldSpec) else None
        fields.append([name, _canon(desc.default, classes), _canon(spec, classes)])
    return ["entity", fields]


def _slot_values(ctx: dict, classes: dict[str, type]) -> list:
    out = []
    for key in sorted(ctx, key=context_key_label):
        inst = ctx[key]
        classes[_name(type(inst))] = type(inst)
        present = inst.__dict__.get("_analint_present", True)
        fields = sorted(all_fields(type(inst)))
        values = [_value(inst.__dict__.get(f), classes) for f in fields] if present else []
        out.append([context_key_label(key), present, values])
    return out


def digest(
    spec: Spec,
    initials: list[dict],
    max_states: int,
    root_numbers: list[int] | None,
    inert: frozenset[int],
) -> tuple[str, dict[str, type]]:
    """The identity of one exploration's inputs, and the classes they name;
    raises ``_Uncacheable``. Every value a state can hold comes from a root,
    an effect literal or a field default, so these classes resolve it."""
    classes: dict[str, type] = {}
    body = [
        FORMAT,
        _engine(),
        sys.byteorder,
        max_states,
        root_numbers,
        sorted(inert),
        sorted(_name(e) for e in spec.entities),
        [_canon(a, classes) for a in spec.actions],
        [_canon(i, classes) for i in spec.invariants],
        [_canon(lc, classes) for lc in spec.lifecycles],
        [_canon(s, classes) for s in spec.scopes],
        [_slot_values(ctx, classes) for ctx in initials],
    ]
    done: dict[str, Any] = {}
    while len(done) < len(classes):  # class definitions may name more classes
        for name in sorted(set(classes) - set(done)):
            done[name] = _class_canon(classes[name], classes)
    body.append(sorted(done.items()))
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest(), classes


@cache
def _engine() -> str:
    """The installed engine's identity: its version and every source file."""
    root = Path(analint.__file__).parent
    h = hashlib.sha256(analint.__version__.encode())
    for path in sorted(root.rglob("*.py")):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


# ── portable graph ───────────────────────────────────────────────────────────


def _b64(values: array) -> str:
    return base64.b64encode(values.tobytes()).decode()


def _unb64(code: str, text: str) -> array:
    out = array(code)
    out.frombytes(base64.b64decode(text))
    return out


def _describe(layout: tuple) -> list:
    return [[context_key_label(key), scoped, list(fields)] for key, scoped, fields in layout]


def encode(exp: Exploration) -> dict:
    layouts: dict[int, int] = {}  # layout id → local index
    described: list = []
    tables: list[list[dict]] = []  # local layout → slot → value tuple → local code
    states = array("I")
    for key in exp.keys:
        codes = explorer._codes(key)
        layout_id = codes[0]
        local = layouts.get(layout_id)
        if local is None:
            local = layouts[layout_id] = len(described)
            described.append(_describe(explorer._LAYOUTS[layout_id]))
            tables.append([{} for _ in explorer._LAYOUTS[layout_id]])
        states.append(local)
        for slot, code in enumerate(codes[1:]):
            value = explorer._SLOT_VALUES[layout_id][slot][code]
            table = tables[local][slot]
            states.append(table.setdefault(value, len(table)))
    return {
        "layouts": described,
        "values": [
            [[[_value(v) for v in value] for value in table] for table in slots] for slots in tables
        ],
        "states": _b64(states),
        "parent": _b64(exp.parent),
        "via": _b64(exp.via),
        "edges": [_b64(exp.edge_src), _b64(exp.edge_action), _b64(exp.edge_dst)],
        "actions": exp.action_ids,
        "roots": [[exp.index[key], number] for key, number in exp.roots.items()],
        "fired": sorted(exp.fired),
        "findings": [[f.severity.value, f.location, f.message] for f in exp.findings],
        "excluded": exp.excluded,
        "capped": exp.capped,
        "growing": exp.growing,
    }


class _Registry:
    """Resolves stored values to this process's enum members and refs."""

    def __init__(self, spec: Spec, initials: list[dict], classes: dict[str, type]) -> None:
        self.enums = {name: cls for name, cls in classes.items() if issubclass(cls, Enum)}
        self.refs: dict[tuple, InstanceRef] = {}
        refs = [key for ctx in initials for key in ctx if isinstance(key, InstanceRef)]
        for scope in spec.scopes:
            refs += list(scope)
        for ref in refs:
            self.refs[(_name(ref.entity_cls), json.dumps(_value(ref.key)))] = ref

    def value(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "f" in data:
            return float(data["f"])
        if "e" in data:
            return self.enums[data["e"]][data["n"]]
        return self.refs[(data["r"], json.dumps(data["k"]))]


def decode(data: dict, spec: Spec, initials: list[dict], classes: dict[str, type]) -> Exploration:
    """Rebuild an exploration; raises on anything that does not match."""
    current = {}
    for ctx in initials:
        layout_id, layout = explorer._state_layout(tuple(ctx))
        current[json.dumps(_describe(layout))] = layout_id
    layout_ids = [current[json.dumps(described)] for described in data["layouts"]]
    registry = _Registry(spec, initials, classes)
    codes = [
        [
            [
                explorer._intern(layout_ids[local], slot, tuple(registry.value(v) for v in value))
                for value in table
            ]
            for slot, table in enumerate(slots)
        ]
        for local, slots in enumerate(data["values"])
    ]
    exp = Exploration()
    states = _unb64("I", data["states"])
    i = 0
    while i < len(states):
        local = states[i]
        width = len(codes[local])
        key = explorer._pack(
            [
                layout_ids[local],
                *(codes[local][slot][states[i + 1 + slot]] for slot in range(width)),
            ]
        )
        exp.index[key] = len(exp.keys)
        exp.keys.append(key)
        i += 1 + width
    exp.parent = _unb64("i", data["parent"])
    exp.via = _unb64("i", data["via"])
    exp.edge_src, exp.edge_action, exp.edge_dst = (_unb64("i", e) for e in data["edges"])
    for action_id in data["actions"]:
        exp.action_code(action_id)
    exp.roots = {exp.keys[index]: number for index, number in data["roots"]}
    exp.fired = set(data["fired"])
    exp.findings = [Finding(Severity(s), loc, msg) for s, loc, msg in data["findings"]]
    exp._seen = {(f.location, f.message) for f in exp.findings}
    exp.excluded = dict(data["excluded"])
    exp.capped = data["capped"]
    exp.growing = list(data["growing"])
    if len(exp.index) != len(exp.keys) or len(exp.parent) != len(exp.keys):
        raise ValueError("inconsistent stored exploration")
    return exp


# ── store ────────────────────────────────────────────────────────────────────


class _Store:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.hits = 0
        self.misses = 0

    def explore(
        self,
        run: Callable[..., Exploration],
        spec: Spec,
        initials: list[dict],
        max_states: int,
        root_numbers: list[int] | None,
        inert: frozenset[int],
    ) -> Exploration:
        try:
            key, classes = digest(spec, initials, max_states, root_numbers, inert)
        except _Uncacheable:
            return run(spec, initials, max_states, root_numbers, inert)
        path = self.directory / f"{key}.json.z"
        try:
            data = json.loads(zlib.decompress(path.read_bytes()))
            exp = decode(data, spec, initials, classes)
        except Exception:  # absent, unreadable or stale: explore instead
            exp = None
        else:
            self.hits += 1
            with contextlib.suppress(OSError):
                os.utime(path)  # recently used: pruned last
            return exp
        self.misses += 1
        exp = run(spec, initials, max_states, root_numbers, inert)
        try:
            blob = zlib.compress(json.dumps(encode(exp), separators=(",", ":")).encode(), 6)
        except _Uncacheable:
            return exp
        with contextlib.suppress(OSError):
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(blob)
            os.replace(tmp, path)
            self._prune()
        return exp

    def _prune(self) -> None:
        files = sorted(self.directory.glob("*.json.z"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= MAX_BYTES:
                break
            total -= path.stat().st_size
            path.unlink(missing_ok=True)
