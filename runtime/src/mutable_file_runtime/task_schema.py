from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .model import DocumentSpec, Layer, LayerSource, Ownership, OwnershipOverride, TaskFile


SUPPORTED_FORMATS = {"json", "yaml", "toml"}
SUPPORTED_OWNERSHIP = {"declared", "sealed", "local"}
SUPPORTED_SOURCES = {"inline", "store_path", "runtime_path"}



def _decode_path(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(segment, str) for segment in value):
        raise ValueError(f"{field_name} must be a list of string path segments")
    return tuple(value)



def _decode_ownership(payload: Any) -> Ownership:
    if not isinstance(payload, dict):
        raise ValueError("ownership must be an object")
    fallback = payload.get("fallback", "declared")
    if fallback not in SUPPORTED_OWNERSHIP:
        raise ValueError(f"unsupported ownership mode: {fallback}")

    overrides = []
    for item in payload.get("overrides", []):
        if not isinstance(item, dict):
            raise ValueError("ownership override must be an object")
        path = _decode_path(item.get("path", []), "ownership.overrides[].path")
        mode = item.get("mode")
        if mode not in SUPPORTED_OWNERSHIP:
            raise ValueError(f"unsupported ownership mode: {mode}")
        overrides.append(OwnershipOverride(path=path, mode=mode))
    return Ownership(fallback=fallback, overrides=tuple(overrides))



def _decode_source(payload: Any) -> LayerSource:
    if not isinstance(payload, dict):
        raise ValueError("layer source must be an object")
    kind = payload.get("kind")
    if kind not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported source kind: {kind}")

    if kind == "inline":
        if "value" not in payload:
            raise ValueError("inline layer source must define value")
        return LayerSource(kind=kind, value=copy.deepcopy(payload["value"]))

    path = payload.get("path")
    if not isinstance(path, str):
        raise ValueError("path-based layer source must define a string path")
    if kind == "runtime_path" and not path.startswith("/"):
        raise ValueError("runtime_path sources must be absolute")
    return LayerSource(kind=kind, path=path)



def _decode_layer(payload: Any) -> Layer:
    if not isinstance(payload, dict):
        raise ValueError("layer must be an object")
    return Layer(
        id=payload["id"],
        name=payload["name"],
        source=_decode_source(payload["source"]),
        from_path=_decode_path(payload.get("from", []), "layer.from"),
        to_path=_decode_path(payload.get("to", []), "layer.to"),
        required=bool(payload.get("required", True)),
    )



def _decode_document(payload: Any) -> DocumentSpec:
    if not isinstance(payload, dict):
        raise ValueError("document must be an object")
    format_name = payload.get("format")
    if format_name not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported format: {format_name}")
    layers = tuple(_decode_layer(layer) for layer in payload.get("layers", []))
    if not layers:
        raise ValueError("document must define at least one layer")
    target = payload.get("target")
    if not isinstance(target, str):
        raise ValueError("target must be a string")
    state_dir = payload.get("state_dir")
    if not isinstance(state_dir, str):
        raise ValueError("state_dir must be a string")
    return DocumentSpec(
        id=payload["id"],
        target=target,
        format=format_name,
        create=bool(payload.get("create", True)),
        mode=payload.get("mode", "0600"),
        state_dir=state_dir,
        ownership=_decode_ownership(payload.get("ownership", {})),
        layers=layers,
    )



def decode_task_file(payload: Any) -> TaskFile:
    if not isinstance(payload, dict):
        raise ValueError("task file must be an object")
    version = payload.get("version")
    if version != 4:
        raise ValueError("unsupported task file version")
    documents_payload = payload.get("documents")
    if not isinstance(documents_payload, list):
        raise ValueError("documents must be a list")
    documents = tuple(_decode_document(item) for item in documents_payload)
    return TaskFile(version=version, documents=documents)



def load_task_file(path: str | Path) -> TaskFile:
    payload = json.loads(Path(path).read_text())
    return decode_task_file(payload)
