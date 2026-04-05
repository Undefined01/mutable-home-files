from __future__ import annotations

import copy
import difflib
import json
from typing import Iterable

from .model import EditOp, InsertOp, PathType, RemoveOp, SetOp, clone, is_mapping, is_sequence



def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))



def _diff_list(old, new, path: PathType, ops: list[EditOp]) -> None:
    matcher = difflib.SequenceMatcher(
        a=[_canonical(item) for item in old],
        b=[_canonical(item) for item in new],
        autojunk=False,
    )
    net_offset = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        cursor = i1 + net_offset
        if tag == "equal":
            continue
        if tag == "delete":
            for _ in range(i1, i2):
                ops.append(RemoveOp(path=path + (cursor,)))
                net_offset -= 1
            continue
        if tag == "insert":
            for value in new[j1:j2]:
                ops.append(InsertOp(path=path + (cursor,), value=clone(value)))
                cursor += 1
                net_offset += 1
            continue

        shared = min(i2 - i1, j2 - j1)
        for offset in range(shared):
            _diff_node(old[i1 + offset], new[j1 + offset], path + (cursor + offset,), ops)
        cursor += shared
        if (i2 - i1) > shared:
            for _ in range(shared, i2 - i1):
                ops.append(RemoveOp(path=path + (cursor,)))
                net_offset -= 1
        if (j2 - j1) > shared:
            for value in new[j1 + shared:j2]:
                ops.append(InsertOp(path=path + (cursor,), value=clone(value)))
                cursor += 1
                net_offset += 1



def _diff_node(old, new, path: PathType, ops: list[EditOp]) -> None:
    if is_mapping(old) and is_mapping(new):
        for key in old.keys():
            if key not in new:
                ops.append(RemoveOp(path=path + (key,)))
        for key in new.keys():
            if key in old:
                _diff_node(old[key], new[key], path + (key,), ops)
            else:
                ops.append(SetOp(path=path + (key,), value=clone(new[key])))
        return

    if is_sequence(old) and is_sequence(new):
        _diff_list(old, new, path, ops)
        return

    if old != new:
        ops.append(SetOp(path=path, value=clone(new)))



def diff_documents(old, new) -> tuple[EditOp, ...]:
    ops: list[EditOp] = []
    _diff_node(old, new, (), ops)
    return tuple(ops)



def format_ops_for_error(left_name: str, right_name: str, ops: Iterable[EditOp], left, right) -> str:
    lines: list[str] = []
    for operation in ops:
        path = ".".join(str(segment) for segment in operation.path) or "<root>"
        if isinstance(operation, RemoveOp):
            lines.append(f"{path}: {left_name}={json.dumps(_lookup_value(left, operation.path), sort_keys=True)} {right_name}=<missing>")
            continue
        lines.append(
            f"{path}: {left_name}={json.dumps(_lookup_value(left, operation.path), sort_keys=True)} "
            f"{right_name}={json.dumps(getattr(operation, 'value', _lookup_value(right, operation.path)), sort_keys=True)}"
        )
    return "; ".join(lines)



def _lookup_value(document, path: PathType):
    cursor = document
    for segment in path:
        if isinstance(segment, int):
            if not isinstance(cursor, list) or segment < 0 or segment >= len(cursor):
                return None
            cursor = cursor[segment]
            continue
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor



def _empty_container(next_segment):
    return [] if isinstance(next_segment, int) else {}



def _ensure_parent(root, path: PathType):
    cursor = root
    for index, segment in enumerate(path[:-1]):
        next_segment = path[index + 1]
        if isinstance(segment, int):
            while len(cursor) <= segment:
                cursor.append(_empty_container(next_segment))
            if not isinstance(cursor[segment], (dict, list)):
                cursor[segment] = _empty_container(next_segment)
            cursor = cursor[segment]
            continue
        if segment not in cursor or not isinstance(cursor[segment], (dict, list)):
            cursor[segment] = _empty_container(next_segment)
        cursor = cursor[segment]
    return cursor



def apply_ops(document, operations: Iterable[EditOp]):
    result = copy.deepcopy(document)
    for operation in operations:
        path = operation.path
        if isinstance(operation, SetOp):
            if path == ():
                result = clone(operation.value)
                continue
            if not isinstance(result, (dict, list)):
                result = _empty_container(path[0])
            parent = _ensure_parent(result, path)
            leaf = path[-1]
            if isinstance(leaf, int):
                while len(parent) <= leaf:
                    parent.append(None)
                parent[leaf] = clone(operation.value)
            else:
                parent[leaf] = clone(operation.value)
            continue

        if isinstance(operation, RemoveOp):
            if path == ():
                result = {}
                continue
            parent = _ensure_parent(result, path)
            leaf = path[-1]
            if isinstance(leaf, int):
                if 0 <= leaf < len(parent):
                    del parent[leaf]
            else:
                parent.pop(leaf, None)
            continue

        if path == ():
            raise ValueError("cannot insert at document root")
        if not isinstance(result, (dict, list)):
            result = _empty_container(path[0])
        parent = _ensure_parent(result, path)
        index = path[-1]
        if not isinstance(index, int):
            raise ValueError("insert operations require an array index")
        parent.insert(index, clone(operation.value))
    return result
