import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

import tomlkit


MISSING = object()
DECLARED = "declared"
SEALED = "sealed"
LOCAL = "local"


def ensure_supported_format(format_name):
    if format_name in ("json", "yaml", "toml"):
        return
    raise ValueError(f"unsupported format: {format_name}")


def yq_bin():
    return os.environ.get("MUTABLE_FILE_YQ_BIN", "yq")


def run_process(argv, input_text=None):
    try:
        completed = subprocess.run(
            argv,
            input=input_text,
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"required command not found: {argv[0]}") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip() or "unknown error"
        raise RuntimeError(f"command failed: {' '.join(argv)}: {details}") from exc
    return completed.stdout


def load_document_from_path(format_name, path):
    ensure_supported_format(format_name)
    if format_name == "json":
        return json.loads(Path(path).read_text())
    if format_name == "yaml":
        rendered = run_process([yq_bin(), "eval", "-o=json", ".", str(path)])
        return json.loads(rendered)
    if format_name == "toml":
        return tomlkit.parse(Path(path).read_text()).unwrap()
    raise NotImplementedError(f"format adapter not implemented yet: {format_name}")


def render_document_for_format(format_name, document):
    ensure_supported_format(format_name)
    if format_name == "json":
        return json.dumps(document, indent=2, sort_keys=True)
    if format_name == "yaml":
        return run_process(
            [yq_bin(), "eval", "-p=json", "-o=yaml", ".", "-"],
            input_text=json.dumps(document, sort_keys=True),
        )
    if format_name == "toml":
        return tomlkit.dumps(document)
    raise NotImplementedError(f"format adapter not implemented yet: {format_name}")


def lookup_path(document, path):
    node = document
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return MISSING
        node = node[segment]
    return node


def ensure_mapping_path(document, path):
    cursor = document
    for segment in path[:-1]:
        next_node = cursor.get(segment)
        if not isinstance(next_node, dict):
            cursor[segment] = {}
        cursor = cursor[segment]
    return cursor


def set_path(document, path, value):
    if path == []:
        if not isinstance(value, dict):
            raise ValueError("root replacement requires a mapping value")
        document.clear()
        document.update(copy.deepcopy(value))
        return
    cursor = ensure_mapping_path(document, path)
    cursor[path[-1]] = copy.deepcopy(value)


def remove_path(document, path):
    if path == []:
        document.clear()
        return
    cursor = document
    for segment in path[:-1]:
        if not isinstance(cursor, dict) or segment not in cursor:
            return
        cursor = cursor[segment]
    if isinstance(cursor, dict):
        cursor.pop(path[-1], None)


def ensure_toml_path(document, path):
    cursor = document
    for segment in path[:-1]:
        if segment not in cursor or not hasattr(cursor[segment], "unwrap"):
            cursor[segment] = tomlkit.table()
        cursor = cursor[segment]
    return cursor


def set_toml_path(document, path, value):
    if path == []:
        raise ValueError("root replacement is not supported for in-place TOML patching")
    cursor = ensure_toml_path(document, path)
    cursor[path[-1]] = copy.deepcopy(value)


def remove_toml_path(document, path):
    if path == []:
        return
    cursor = document
    for segment in path[:-1]:
        if segment not in cursor:
            return
        cursor = cursor[segment]
    if path[-1] in cursor:
        del cursor[path[-1]]


def patch_toml_text(base_text, operations):
    document = tomlkit.parse(base_text)
    for operation in operations:
        kind = operation[0]
        path = operation[1]
        if kind == "delete":
            remove_toml_path(document, path)
        else:
            set_toml_path(document, path, operation[2])
    return tomlkit.dumps(document)


def yq_path_expr(path):
    return "." + ".".join(path)


def write_yaml_value_file(base_dir, path, value):
    suffix = "-".join(path) if path else "root"
    value_file = Path(base_dir) / f"yaml-value-{suffix}.json"
    value_file.write_text(json.dumps(value, sort_keys=True))
    return value_file


def patch_yaml_text(base_dir, base_text, operations):
    base_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base_dir) as tempdir:
        working_path = Path(tempdir) / "document.yaml"
        working_path.write_text(base_text)
        for operation in operations:
            kind = operation[0]
            path = operation[1]
            expr = yq_path_expr(path)
            if kind == "delete":
                run_process([yq_bin(), "-i", f"del({expr})", str(working_path)])
            else:
                value_file = write_yaml_value_file(tempdir, path, operation[2])
                run_process([yq_bin(), "-i", f'{expr} = load("{value_file}")', str(working_path)])
        return working_path.read_text()


def iter_paths(value, prefix=None):
    if prefix is None:
        prefix = []
    if isinstance(value, dict):
        yield prefix, value
        for key, item in value.items():
            yield from iter_paths(item, prefix + [key])
    else:
        yield prefix, value


def iter_object_paths(value, prefix=None):
    if prefix is None:
        prefix = []
    if isinstance(value, dict):
        yield prefix
        for key, item in value.items():
            yield from iter_object_paths(item, prefix + [key])


def iter_leaf_paths(value, prefix=None):
    if prefix is None:
        prefix = []
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_leaf_paths(item, prefix + [key])
    else:
        yield prefix, value


def normalize_document(value):
    if isinstance(value, dict):
        normalized = {
            key: normalize_document(item)
            for key, item in value.items()
        }
        return {
            key: item
            for key, item in normalized.items()
            if not (isinstance(item, dict) and item == {})
        }
    if isinstance(value, list):
        return [normalize_document(item) for item in value]
    return value


def scalar_or_array(value):
    return not isinstance(value, dict)


def schema_version(payload):
    return payload.get("version")


def load_task_file(path):
    payload = json.loads(Path(path).read_text())
    if schema_version(payload) != 3:
        raise ValueError("unsupported task file version")
    return payload


def ownership_mode_for_path(ownership, path):
    mode = ownership["default_mode"]
    best_length = -1
    for rule in ownership.get("rules", []):
        rule_path = rule["path"]
        if len(rule_path) <= len(path) and path[: len(rule_path)] == rule_path and len(rule_path) > best_length:
            mode = rule["mode"]
            best_length = len(rule_path)
    return mode


def ownership_local_path(ownership, path):
    return ownership_mode_for_path(ownership, path) == LOCAL


def assert_layers_do_not_target_local_paths(entry):
    for layer in entry["layers"]:
        if ownership_local_path(entry["ownership"], layer["to_path"]):
            raise RuntimeError(
                f"layer targets local ownership subtree: {layer['name']} -> {layer['to_path']}"
            )


def load_layer_document(format_name, layer):
    kind = layer["source_kind"]
    payload = layer["source_payload"]

    if kind == "value":
        return copy.deepcopy(payload)
    if kind in ("source", "path"):
        source_path = Path(payload)
        if not source_path.exists() and not layer["required"]:
            return MISSING
        return load_document_from_path(format_name, source_path)
    raise NotImplementedError(f"layer source kind not implemented yet: {kind}")


def merge_layer_value(target, path, incoming, layer_name):
    existing = lookup_path(target, path)
    if existing is MISSING:
        set_path(target, path, incoming)
        return

    if isinstance(existing, dict) and isinstance(incoming, dict):
        for key, value in incoming.items():
            merge_layer_value(target, path + [key], value, layer_name)
        return

    raise RuntimeError(f"incompatible layer overlap at {path}: {layer_name}")


def apply_layer(target, layer_doc, layer):
    if layer_doc is MISSING:
        return
    node = lookup_path(layer_doc, layer["from_path"])
    if node is MISSING:
        if layer["required"]:
            raise RuntimeError(
                f"required layer path missing: {layer['name']} from {layer['from_path']}"
            )
        return
    merge_layer_value(target, layer["to_path"], node, layer["name"])


def assemble_desired_document(entry):
    assert_layers_do_not_target_local_paths(entry)
    document = {}
    for layer in entry["layers"]:
        layer_doc = load_layer_document(entry["format"], layer)
        apply_layer(document, layer_doc, layer)
    return normalize_document(document)


def baseline_path_for(entry):
    return Path(entry["state_root"]) / entry["entry_id"] / "state.json"


def meta_path_for(entry):
    return Path(entry["state_root"]) / entry["entry_id"] / "meta.json"


def load_state(entry):
    path = baseline_path_for(entry)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_current_document(entry, target_path):
    ensure_supported_format(entry["format"])
    if target_path.exists():
        return load_document_from_path(entry["format"], target_path)
    if entry["create"]:
        return {}
    raise FileNotFoundError(f"target does not exist: {target_path}")


def managed_value_paths(document, ownership, prefix=None):
    if prefix is None:
        prefix = []

    mode = ownership_mode_for_path(ownership, prefix)
    if mode == LOCAL:
        return set()

    paths = set()
    if prefix != []:
        paths.add(tuple(prefix))

    if isinstance(document, dict):
        for key, item in document.items():
            paths |= managed_value_paths(item, ownership, prefix + [key])
    return paths


def compare_documents(current, desired, ownership, previous_managed_paths, prefix=None, result=None):
    if prefix is None:
        prefix = []
    if result is None:
        result = {
            "conflicts": [],
            "set_ops": [],
            "delete_ops": [],
            "managed_paths": set(),
        }

    mode = ownership_mode_for_path(ownership, prefix)
    current_missing = current is MISSING
    desired_missing = desired is MISSING
    path_tuple = tuple(prefix)
    previously_managed = path_tuple in previous_managed_paths

    if mode == LOCAL:
        return result

    if desired_missing:
        if previously_managed:
            if not current_missing:
                result["delete_ops"].append(prefix)
            result["managed_paths"].add(path_tuple)
        elif mode == SEALED and not current_missing:
            result["conflicts"].append((prefix, "undeclared field under sealed ownership"))
        return result

    result["managed_paths"].add(path_tuple)

    if isinstance(desired, dict):
        current_mapping = current if isinstance(current, dict) else {}
        if current is not MISSING and not isinstance(current, dict):
            result["conflicts"].append((prefix, "type mismatch during managed takeover"))
            return result

        child_keys = set(desired.keys())
        if isinstance(current_mapping, dict):
            child_keys |= set(current_mapping.keys())

        for key in sorted(child_keys):
            compare_documents(
                current_mapping.get(key, MISSING),
                desired.get(key, MISSING),
                ownership,
                previous_managed_paths,
                prefix + [key],
                result,
            )
        return result

    if current_missing:
        result["set_ops"].append((prefix, desired))
        return result

    if current == desired:
        return result

    if previously_managed:
        result["set_ops"].append((prefix, desired))
    else:
        result["conflicts"].append((prefix, "local value differs from managed takeover"))
    return result


def apply_operations_to_document(document, set_ops, delete_ops):
    result = copy.deepcopy(document)
    for path in sorted(delete_ops, key=len, reverse=True):
        remove_path(result, path)
    for path, value in sorted(set_ops, key=lambda item: len(item[0])):
        set_path(result, path, value)
    return normalize_document(result)


def patch_toml_operations(current_text, operations):
    return patch_toml_text(current_text, operations)


def patch_yaml_operations(target_path, current_text, operations):
    return patch_yaml_text(target_path.parent, current_text, operations)


def write_state(entry, desired_document, managed_paths):
    state_path = baseline_path_for(entry)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "managed_document": desired_document,
                "managed_paths": [list(path) for path in sorted(managed_paths)],
                "ownership": entry["ownership"],
            },
            indent=2,
            sort_keys=True,
        )
    )

    meta_path = meta_path_for(entry)
    meta_path.write_text(
        json.dumps(
            {
                "entry_id": entry["entry_id"],
                "target": entry["target"],
                "format": entry["format"],
                "ownership": entry["ownership"],
                "layers": [
                    {
                        "layer_id": layer["layer_id"],
                        "name": layer["name"],
                        "source_kind": layer["source_kind"],
                        "from_path": layer["from_path"],
                        "to_path": layer["to_path"],
                        "required": layer["required"],
                    }
                    for layer in entry["layers"]
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


def atomic_write(path, text, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fchmod(handle.fileno(), int(mode, 8))
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)


def render_document(entry, document):
    return render_document_for_format(entry["format"], document)


def operation_list(set_ops, delete_ops):
    return [("delete", path) for path in delete_ops] + [("set", path, value) for path, value in set_ops]


def reconcile_entry(entry, home_directory):
    target_path = Path(home_directory) / entry["target"]
    current_text = target_path.read_text() if target_path.exists() else None
    desired_doc = assemble_desired_document(entry)
    current_doc = load_current_document(entry, target_path)
    previous_state = load_state(entry)
    previous_managed_paths = set(
        tuple(path)
        for path in (previous_state["managed_paths"] if previous_state is not None else [])
    )

    comparison = compare_documents(
        current_doc,
        desired_doc,
        entry["ownership"],
        previous_managed_paths,
    )

    if comparison["conflicts"]:
        path, reason = comparison["conflicts"][0]
        raise RuntimeError(f"conflict at {path}: {reason}")

    merged = apply_operations_to_document(current_doc, comparison["set_ops"], comparison["delete_ops"])

    if current_text is not None and current_doc == merged:
        rendered = current_text
    elif entry["format"] == "toml" and current_text is not None:
        rendered = patch_toml_operations(current_text, operation_list(comparison["set_ops"], comparison["delete_ops"]))
    elif entry["format"] == "yaml" and current_text is not None:
        rendered = patch_yaml_operations(target_path, current_text, operation_list(comparison["set_ops"], comparison["delete_ops"]))
    else:
        rendered = render_document(entry, merged)

    atomic_write(target_path, rendered, entry["mode"])
    write_state(entry, desired_doc, comparison["managed_paths"])


def extract_managed_subtree(document, ownership, prefix=None):
    if prefix is None:
        prefix = []

    mode = ownership_mode_for_path(ownership, prefix)
    if mode == LOCAL:
        return MISSING

    if not isinstance(document, dict):
        return copy.deepcopy(document)

    result = {}
    for key, item in document.items():
        extracted = extract_managed_subtree(item, ownership, prefix + [key])
        if extracted is not MISSING:
            result[key] = extracted
    return normalize_document(result)


def detect_conflict(current_managed, previous_managed):
    if previous_managed is None:
        return False
    return current_managed != previous_managed


def merge_includes(current_doc, desired_doc, filter_paths):
    result = copy.deepcopy(current_doc)
    for path in filter_paths:
        node = lookup_path(desired_doc, path)
        if node is MISSING:
            remove_path(result, path)
        else:
            set_path(result, path, node)
    return normalize_document(result)


def merge_excludes(current_doc, desired_doc, filter_paths):
    result = copy.deepcopy(desired_doc)
    for path in filter_paths:
        node = lookup_path(current_doc, path)
        if node is MISSING:
            remove_path(result, path)
        else:
            set_path(result, path, node)
    return normalize_document(result)
