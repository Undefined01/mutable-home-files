from __future__ import annotations

from pathlib import Path

from .formats import get_format
from .model import MISSING, clone


def _lookup_mapping_path(document, path):
    node = document
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return MISSING
        node = node[segment]
    return node


def _ensure_object_path(document, path):
    cursor = document
    for segment in path[:-1]:
        if segment not in cursor or not isinstance(cursor[segment], dict):
            cursor[segment] = {}
        cursor = cursor[segment]
    return cursor


def _set_object_path(document, path, value):
    if path == ():
        if not isinstance(value, dict):
            raise RuntimeError("root layer projection requires an object value")
        document.clear()
        document.update(clone(value))
        return
    cursor = _ensure_object_path(document, path)
    cursor[path[-1]] = clone(value)


def _merge_layer_value(target, path, incoming, layer_name):
    existing = _lookup_mapping_path(target, path)
    if existing is MISSING:
        _set_object_path(target, path, incoming)
        return
    if isinstance(existing, dict) and isinstance(incoming, dict):
        for key, value in incoming.items():
            _merge_layer_value(target, path + (key,), value, layer_name)
        return
    raise RuntimeError(f"incompatible layer overlap at {path}: {layer_name}")


def _load_layer_source(document, layer):
    if layer.source.kind == "inline":
        return clone(layer.source.value)
    source_path = Path(layer.source.path)
    if not source_path.exists():
        if layer.required:
            raise RuntimeError(f"required layer source is missing: {layer.name}")
        return MISSING
    adapter = get_format(document.format)
    return adapter.load_file(source_path)


def assemble_document(document):
    desired = {}
    for layer in document.layers:
        if document.ownership.mode_for(layer.to_path) == "local":
            raise RuntimeError(f"layer targets local ownership subtree: {layer.name} -> {layer.to_path}")
        layer_document = _load_layer_source(document, layer)
        if layer_document is MISSING:
            continue
        node = _lookup_mapping_path(layer_document, layer.from_path)
        if node is MISSING:
            if layer.required:
                raise RuntimeError(f"required layer path missing: {layer.name} from {layer.from_path}")
            continue
        _merge_layer_value(desired, layer.to_path, node, layer.name)
    return desired
