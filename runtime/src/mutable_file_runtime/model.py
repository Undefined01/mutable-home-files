from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, TypeAlias


MISSING = object()
PathSegment: TypeAlias = str | int
PathType: TypeAlias = tuple[PathSegment, ...]
DocumentValue: TypeAlias = Any
OwnershipMode: TypeAlias = str


@dataclass(frozen=True)
class OwnershipRule:
    path: PathType
    mode: OwnershipMode


@dataclass(frozen=True)
class Ownership:
    default: OwnershipMode
    rules: tuple[OwnershipRule, ...] = ()

    def mode_for(self, path: PathType) -> OwnershipMode:
        mode = self.default
        best_length = -1
        for rule in self.rules:
            if path[: len(rule.path)] == rule.path and len(rule.path) > best_length:
                mode = rule.mode
                best_length = len(rule.path)
        return mode


@dataclass(frozen=True)
class LayerSource:
    kind: str
    value: DocumentValue = None
    path: str | None = None


@dataclass(frozen=True)
class Layer:
    name: str
    source: LayerSource
    from_path: tuple[str, ...]
    to_path: tuple[str, ...]
    required: bool


@dataclass(frozen=True)
class DocumentSpec:
    target: str
    format: str
    create: bool
    mode: str
    state_dir: str
    ownership: Ownership
    layers: tuple[Layer, ...]


@dataclass(frozen=True)
class TaskFile:
    version: int
    documents: tuple[DocumentSpec, ...]


@dataclass(frozen=True)
class SetOp:
    path: PathType
    value: DocumentValue


@dataclass(frozen=True)
class RemoveOp:
    path: PathType


@dataclass(frozen=True)
class InsertOp:
    path: PathType
    value: DocumentValue


EditOp: TypeAlias = SetOp | RemoveOp | InsertOp


@dataclass(frozen=True)
class Conflict:
    path: PathType
    reason: str


@dataclass(frozen=True)
class MergeResult:
    conflicts: list[Conflict]
    final_document: DocumentValue
    planned_ops: tuple[EditOp, ...]


@dataclass(frozen=True)
class StateSnapshot:
    version: int
    target: str
    format: str
    ownership: Ownership
    previous_applied: DocumentValue
    previous_desired: DocumentValue


def clone(value: DocumentValue) -> DocumentValue:
    if value is MISSING:
        return MISSING
    return copy.deepcopy(value)


def values_equal(left: DocumentValue, right: DocumentValue) -> bool:
    if left is MISSING or right is MISSING:
        return left is right
    return left == right


def is_mapping(value: DocumentValue) -> bool:
    return isinstance(value, dict)


def is_sequence(value: DocumentValue) -> bool:
    return isinstance(value, list)


def ordered_keys(*values: DocumentValue) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if isinstance(value, dict):
            for key in value.keys():
                if key not in seen:
                    seen.add(key)
                    result.append(key)
    return tuple(result)


def lookup_path(document: DocumentValue, path: PathType) -> DocumentValue:
    cursor = document
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(cursor, list) or segment < 0 or segment >= len(cursor):
                return MISSING
            cursor = cursor[segment]
            continue
        if not isinstance(cursor, dict) or segment not in cursor:
            return MISSING
        cursor = cursor[segment]
    return cursor
