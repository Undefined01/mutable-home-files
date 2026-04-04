from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Sequence

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from ..model import EditOp, InsertOp, RemoveOp, SetOp



def _yaml():
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml



def _plain(value):
    if isinstance(value, CommentedMap):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, CommentedSeq):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value



def _rt(value):
    if isinstance(value, dict):
        node = CommentedMap()
        for key, item in value.items():
            node[key] = _rt(item)
        return node
    if isinstance(value, list):
        node = CommentedSeq()
        for item in value:
            node.append(_rt(item))
        return node
    return value



def _make_container(next_segment):
    return CommentedSeq() if isinstance(next_segment, int) else CommentedMap()



def _ensure_parent(document, path):
    cursor = document
    for index, segment in enumerate(path[:-1]):
        next_segment = path[index + 1]
        if isinstance(segment, int):
            while len(cursor) <= segment:
                cursor.append(_make_container(next_segment))
            if not isinstance(cursor[segment], (dict, list, CommentedMap, CommentedSeq)):
                cursor[segment] = _make_container(next_segment)
            cursor = cursor[segment]
            continue
        if segment not in cursor or not isinstance(cursor[segment], (dict, list, CommentedMap, CommentedSeq)):
            cursor[segment] = _make_container(next_segment)
        cursor = cursor[segment]
    return cursor


class YamlFormat:
    name = "yaml"

    def load_file(self, path: Path):
        return self.load_text(path.read_text())

    def load_text(self, text: str):
        yaml = _yaml()
        loaded = yaml.load(text) if text.strip() else CommentedMap()
        if loaded is None:
            return {}
        return _plain(loaded)

    def dump_new(self, data):
        yaml = _yaml()
        buffer = StringIO()
        yaml.dump(_rt(data), buffer)
        return buffer.getvalue()

    def apply_ops(self, original_text: str, operations: Sequence[EditOp]):
        yaml = _yaml()
        document = yaml.load(original_text) if original_text.strip() else CommentedMap()
        if document is None:
            document = CommentedMap()
        for operation in operations:
            path = operation.path
            if isinstance(operation, SetOp):
                if path == ():
                    document = _rt(operation.value)
                    continue
                if not isinstance(document, (dict, list, CommentedMap, CommentedSeq)):
                    document = _make_container(path[0])
                parent = _ensure_parent(document, path)
                leaf = path[-1]
                if isinstance(leaf, int):
                    while len(parent) <= leaf:
                        parent.append(None)
                    parent[leaf] = _rt(operation.value)
                else:
                    parent[leaf] = _rt(operation.value)
                continue
            if isinstance(operation, RemoveOp):
                if path == ():
                    document = CommentedMap()
                    continue
                parent = _ensure_parent(document, path)
                leaf = path[-1]
                if isinstance(leaf, int):
                    if 0 <= leaf < len(parent):
                        del parent[leaf]
                else:
                    parent.pop(leaf, None)
                continue
            if path == ():
                raise ValueError("cannot insert at document root")
            parent = _ensure_parent(document, path)
            parent.insert(path[-1], _rt(operation.value))
        buffer = StringIO()
        yaml.dump(document, buffer)
        return buffer.getvalue()
