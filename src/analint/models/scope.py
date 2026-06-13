"""Bounded multiplicity: stable references to a finite set of entity instances."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, TypeGuard

from analint.models.entity import Entity, FieldDescriptor, all_fields

if TYPE_CHECKING:
    from analint.models.predicate import Predicate


class Scope:
    """A fixed finite universe of instances of one entity type.

    Each key produces a stable ``InstanceRef``. References address fields in
    predicates/effects and create identified snapshots for ``given``:

        accounts = Scope(Account, keys=["alice", "bob"])
        alice = accounts["alice"]

        alice.balance >= 0
        given=[alice(balance=3), accounts["bob"](balance=0)]
    """

    def __init__(self, entity_cls: type[Entity], *, keys: list[Any], id: str = "") -> None:
        if not isinstance(entity_cls, type) or not issubclass(entity_cls, Entity):
            raise TypeError("Scope entity_cls must be an Entity subclass")
        if not keys:
            raise TypeError("Scope needs at least one key")
        for key in keys:
            try:
                hash(key)
            except TypeError as exc:
                raise TypeError(f"Scope key {key!r} is not hashable") from exc
        if len(set(keys)) != len(keys):
            raise TypeError("Scope keys must be unique")
        self.entity_cls = entity_cls
        self.id = id
        self._refs = {key: InstanceRef(self, key) for key in keys}

    @property
    def keys(self) -> tuple[Any, ...]:
        return tuple(self._refs)

    def __getitem__(self, key: Any) -> InstanceRef:
        try:
            return self._refs[key]
        except KeyError as exc:
            raise KeyError(f"{self.entity_cls.__name__} scope has no key {key!r}") from exc

    def __iter__(self) -> Iterator[InstanceRef]:
        return iter(self._refs.values())

    def __len__(self) -> int:
        return len(self._refs)

    def __repr__(self) -> str:
        return f"Scope({self.entity_cls.__name__}, keys={list(self.keys)!r})"


class InstanceRef:
    """Stable identity of one entity instance inside a bounded ``Scope``."""

    def __init__(self, scope: Scope, key: Any) -> None:
        self.scope = scope
        self.key = key

    @property
    def entity_cls(self) -> type[Entity]:
        return self.scope.entity_cls

    def __getattr__(self, field_name: str) -> InstanceField:
        if field_name.startswith("_"):
            raise AttributeError(field_name)
        descriptor = all_fields(self.entity_cls).get(field_name)
        if descriptor is None:
            raise AttributeError(f"{self.entity_cls.__name__} has no field '{field_name}'")
        return InstanceField(self, descriptor)

    def __call__(self, **fields: Any) -> Entity:
        """Create an entity snapshot carrying this instance identity."""
        instance = self.entity_cls(**fields)
        instance.__dict__["_analint_instance_ref"] = self
        instance.__dict__["_analint_present"] = True
        return instance

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return f"{self.entity_cls.__name__}[{self.key!r}]"


class InstanceField:
    """A field addressed through a concrete ``InstanceRef``."""

    def __init__(self, instance: InstanceRef, descriptor: FieldDescriptor) -> None:
        self.instance = instance
        self.descriptor = descriptor

    @property
    def entity_cls(self) -> type[Entity]:
        return self.instance.entity_cls

    @property
    def field_name(self) -> str:
        return self.descriptor.field_name

    @property
    def spec(self) -> Any:
        return self.descriptor.spec

    @property
    def lifecycle(self) -> Any:
        return self.descriptor.lifecycle

    def __eq__(self, other: Any) -> Predicate:  # type: ignore[override]
        from analint.models.predicate import _Eq

        return _Eq(left=self, right=other)

    def __ne__(self, other: Any) -> Predicate:  # type: ignore[override]
        from analint.models.predicate import _Ne

        return _Ne(left=self, right=other)

    def __gt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gt

        return _Gt(left=self, right=other)

    def __ge__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Gte

        return _Gte(left=self, right=other)

    def __lt__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lt

        return _Lt(left=self, right=other)

    def __le__(self, other: Any) -> Predicate:
        from analint.models.predicate import _Lte

        return _Lte(left=self, right=other)

    def __add__(self, other: Any) -> Any:
        from analint.models.expr import _AddExpr

        return _AddExpr(self, other)

    def __radd__(self, other: Any) -> Any:
        from analint.models.expr import _AddExpr

        return _AddExpr(other, self)

    def __sub__(self, other: Any) -> Any:
        from analint.models.expr import _SubExpr

        return _SubExpr(self, other)

    def __rsub__(self, other: Any) -> Any:
        from analint.models.expr import _SubExpr

        return _SubExpr(other, self)

    def __mul__(self, other: Any) -> Any:
        from analint.models.expr import _MulExpr

        return _MulExpr(self, other)

    def __rmul__(self, other: Any) -> Any:
        from analint.models.expr import _MulExpr

        return _MulExpr(other, self)

    def __hash__(self) -> int:
        return hash((id(self.instance), self.field_name))

    def __repr__(self) -> str:
        return f"{self.instance!r}.{self.field_name}"


FieldRef = FieldDescriptor | InstanceField
ContextKey = type | InstanceRef


def is_field_ref(value: Any) -> TypeGuard[FieldRef]:
    return isinstance(value, (FieldDescriptor, InstanceField))


def field_context_key(field: FieldRef) -> ContextKey:
    if isinstance(field, InstanceField):
        return field.instance
    return field.entity_cls


def instance_context_key(instance: Any) -> ContextKey:
    return instance.__dict__.get("_analint_instance_ref", type(instance))


def Absent(instance: InstanceRef) -> Entity:
    """Create an absent snapshot for one slot in a bounded Scope."""
    if not isinstance(instance, InstanceRef):
        raise TypeError("Absent needs an InstanceRef from a Scope")
    snapshot = object.__new__(instance.entity_cls)
    for field_name in all_fields(instance.entity_cls):
        snapshot.__dict__[field_name] = None
    snapshot.__dict__["_analint_instance_ref"] = instance
    snapshot.__dict__["_analint_present"] = False
    return snapshot


def is_present(context: dict[Any, Any], key: ContextKey) -> bool:
    entity = context.get(key)
    if entity is None:
        return False
    if isinstance(key, InstanceRef):
        return entity.__dict__.get("_analint_present", True)
    return True


def present_instances(scope: Scope, context: dict[Any, Any]) -> list[InstanceRef]:
    return [instance for instance in scope if is_present(context, instance)]


def context_key_label(key: ContextKey) -> str:
    if isinstance(key, InstanceRef):
        return repr(key)
    return key.__name__
