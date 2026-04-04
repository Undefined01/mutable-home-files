from __future__ import annotations

from pathlib import Path
from typing import Sequence

import tomlkit

from ..model import EditOp, InsertOp, RemoveOp, SetOp



def _is_container(value):
    return isinstance(value, (dict, list)) or hasattr(value, "unwrap")



def _make_container(next_segment):
    return tomlkit.array() if isinstance(next_segment, int) else tomlkit.table()



def _ensure_parent(document, path):
    cursor = document
    for index, segment in enumerate(path[:-1]):
        next_segment = path[index + 1]
        if isinstance(segment, int):
            while len(cursor) <= segment:
                cursor.append(_make_container(next_segment))
            if not _is_container(cursor[segment]):
                cursor[segment] = _make_container(next_segment)
            cursor = cursor[segment]
            continue
        if segment not in cursor or not _is_container(cursor[segment]):
            cursor[segment] = _make_container(next_segment)
        cursor = cursor[segment]
    return cursor


class TomlFormat:
    name = "toml"

    def load_file(self, path: Path):
        return self.load_text(path.read_text())

    def load_text(self, text: str):
        if text.strip() == "":
            return {}
        return tomlkit.parse(text).unwrap()

    def dump_new(self, data):
        return tomlkit.dumps(data)

    def apply_ops(self, original_text: str, operations: Sequence[EditOp]):
        document = tomlkit.parse(original_text) if original_text.strip() else tomlkit.document()
        for operation in operations:
            path = operation.path
            if isinstance(operation, SetOp):
                if path == ():
                    if not isinstance(operation.value, dict):
                        raise ValueError("TOML document root must stay an object")
                    document = tomlkit.parse(tomlkit.dumps(operation.value))
                    continue
                parent = _ensure_parent(document, path)
                leaf = path[-1]
                if isinstance(leaf, int):
                    while len(parent) <= leaf:
                        parent.append(None)
                    parent[leaf] = operation.value
                else:
                    parent[leaf] = operation.value
                continue
            if isinstance(operation, RemoveOp):
                if path == ():
                    document = tomlkit.document()
                    continue
                parent = _ensure_parent(document, path)
                leaf = path[-1]
                if isinstance(leaf, int):
                    if 0 <= leaf < len(parent):
                        del parent[leaf]
                else:
                    if leaf in parent:
                        del parent[leaf]
                continue
            if path == ():
                raise ValueError("cannot insert at document root")
            parent = _ensure_parent(document, path)
            parent.insert(path[-1], operation.value)
        return tomlkit.dumps(document)
