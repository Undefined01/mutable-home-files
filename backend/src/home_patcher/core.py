import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

import tomlkit


MISSING = object()


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


def load_document_from_text(format_name, text):
    ensure_supported_format(format_name)
    if format_name == "json":
        return json.loads(text)
    if format_name == "yaml":
        rendered = run_process([yq_bin(), "eval", "-o=json", ".", "-"], input_text=text)
        return json.loads(rendered)
    if format_name == "toml":
        return tomlkit.parse(text).unwrap()
    raise NotImplementedError(f"format adapter not implemented yet: {format_name}")


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
    cursor = ensure_mapping_path(document, path)
    cursor[path[-1]] = copy.deepcopy(value)


def ensure_toml_path(document, path):
    cursor = document
    for segment in path[:-1]:
        if segment not in cursor or not hasattr(cursor[segment], "unwrap"):
            cursor[segment] = tomlkit.table()
        cursor = cursor[segment]
    return cursor


def set_toml_path(document, path, value):
    cursor = ensure_toml_path(document, path)
    cursor[path[-1]] = copy.deepcopy(value)


def remove_toml_path(document, path):
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


def patch_toml_includes(current_text, desired_doc, filter_paths):
    return patch_toml_text(current_text, include_operations(desired_doc, filter_paths))


def patch_toml_excludes(current_text, current_doc, desired_doc, filter_paths):
    return patch_toml_text(current_text, exclude_operations(current_doc, desired_doc, filter_paths))


def yq_path_expr(path):
    return "." + ".".join(path)


def path_has_prefix(path, prefix):
    return len(path) >= len(prefix) and path[: len(prefix)] == prefix


def is_under_any(path, prefixes):
    return any(path_has_prefix(path, prefix) for prefix in prefixes)


def iter_leaf_paths(value, prefix=None):
    if prefix is None:
        prefix = []
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_leaf_paths(item, prefix + [key])
    else:
        yield prefix, value


def iter_container_paths(value, prefix=None):
    if prefix is None:
        prefix = []
    if isinstance(value, dict):
        if prefix:
            yield prefix
        for key, item in value.items():
            yield from iter_container_paths(item, prefix + [key])


def include_operations(source_doc, filter_paths):
    operations = []
    for path in filter_paths:
        operations.append(("delete", path))
        node = lookup_path(source_doc, path)
        if node is MISSING:
            continue
        if isinstance(node, dict):
            for leaf_path, leaf_value in iter_leaf_paths(node, path):
                operations.append(("set", leaf_path, leaf_value))
        else:
            operations.append(("set", path, node))
    return operations


def exclude_operations(current_doc, desired_doc, filter_paths):
    target_doc = merge_excludes(current_doc, desired_doc, filter_paths)
    current_leafs = {
        tuple(path): value
        for path, value in iter_leaf_paths(current_doc)
        if not is_under_any(path, filter_paths)
    }
    target_leafs = {
        tuple(path): value
        for path, value in iter_leaf_paths(target_doc)
        if not is_under_any(path, filter_paths)
    }

    operations = []

    stale_leafs = sorted(
        [list(path) for path in current_leafs if path not in target_leafs],
        key=len,
        reverse=True,
    )
    for path in stale_leafs:
        operations.append(("delete", path))

    for path_tuple, value in sorted(target_leafs.items(), key=lambda item: (len(item[0]), item[0])):
        if current_leafs.get(path_tuple, MISSING) != value:
            operations.append(("set", list(path_tuple), value))

    stale_containers = sorted(
        {
            tuple(path)
            for path in iter_container_paths(current_doc)
            if not is_under_any(path, filter_paths) and lookup_path(target_doc, path) is MISSING
        },
        key=len,
        reverse=True,
    )
    for path in stale_containers:
        operations.append(("delete", list(path)))

    return operations


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


def patch_yaml_file_includes(target_path, current_text, desired_doc, filter_paths):
    return patch_yaml_text(target_path.parent, current_text, include_operations(desired_doc, filter_paths))


def patch_yaml_file_excludes(target_path, current_text, current_doc, desired_doc, filter_paths):
    return patch_yaml_text(target_path.parent, current_text, exclude_operations(current_doc, desired_doc, filter_paths))


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


def schema_version(payload):
    return payload.get("version")


def copy_path(source, destination, path):
    node = lookup_path(source, path)
    if node is MISSING:
        return
    set_path(destination, path, node)


def remove_path(document, path):
    cursor = document
    for segment in path[:-1]:
        if not isinstance(cursor, dict) or segment not in cursor:
            return
        cursor = cursor[segment]

    if isinstance(cursor, dict):
        cursor.pop(path[-1], None)


def prune_empty_containers(value):
    if isinstance(value, dict):
        items = {key: prune_empty_containers(item) for key, item in value.items()}
        return {
            key: item
            for key, item in items.items()
            if not (isinstance(item, dict) and item == {})
        }
    if isinstance(value, list):
        return [prune_empty_containers(item) for item in value]
    return value


def extract_managed_subtree(document, filter_mode, filter_paths):
    if filter_mode == "includes":
        result = {}
        for path in filter_paths:
            copy_path(document, result, path)
        return prune_empty_containers(result)
    if filter_mode == "excludes":
        result = copy.deepcopy(document)
        for path in filter_paths:
            remove_path(result, path)
        return prune_empty_containers(result)
    raise ValueError(f"unsupported filter mode: {filter_mode}")


def detect_conflict(current_managed, baseline_managed):
    if baseline_managed is None:
        return False
    return current_managed != baseline_managed


def replace_paths(base_doc, source_doc, filter_paths):
    result = copy.deepcopy(base_doc)
    for path in filter_paths:
        node = lookup_path(source_doc, path)
        if node is MISSING:
            remove_path(result, path)
        else:
            set_path(result, path, node)
    return prune_empty_containers(result)


def merge_includes(current_doc, desired_doc, filter_paths):
    return replace_paths(current_doc, desired_doc, filter_paths)


def merge_excludes(current_doc, desired_doc, filter_paths):
    return replace_paths(desired_doc, current_doc, filter_paths)


def load_task_file(path):
    payload = json.loads(Path(path).read_text())
    if schema_version(payload) != 1:
        raise ValueError("unsupported task file version")
    return payload


def baseline_path_for(entry):
    return Path(entry["state_root"]) / entry["entry_id"] / "baseline_managed.json"


def meta_path_for(entry):
    return Path(entry["state_root"]) / entry["entry_id"] / "meta.json"


def load_baseline(entry):
    path = baseline_path_for(entry)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_desired_document(entry):
    kind = entry["desired_source_kind"]
    payload = entry["desired_source_payload"]
    ensure_supported_format(entry["format"])

    if kind == "value":
        return copy.deepcopy(payload)
    if kind in ("source", "path"):
        return load_document_from_path(entry["format"], payload)
    raise NotImplementedError(f"desired source kind not implemented yet: {kind}")


def load_current_document(entry, target_path):
    ensure_supported_format(entry["format"])
    if target_path.exists():
        return load_document_from_path(entry["format"], target_path)
    if entry["create"]:
        return {}
    raise FileNotFoundError(f"target does not exist: {target_path}")


def render_document(entry, document):
    return render_document_for_format(entry["format"], document)


def write_baseline(entry, desired_managed):
    baseline_path = baseline_path_for(entry)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(desired_managed, indent=2, sort_keys=True))

    meta_path = meta_path_for(entry)
    meta_path.write_text(
        json.dumps(
            {
                "entry_id": entry["entry_id"],
                "target": entry["target"],
                "format": entry["format"],
                "filter_mode": entry["filter_mode"],
                "filter_paths": entry["filter_paths"],
                "desired_source_kind": entry["desired_source_kind"],
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


def reconcile_entry(entry, home_directory):
    target_path = Path(home_directory) / entry["target"]
    current_text = target_path.read_text() if target_path.exists() else None
    desired_doc = load_desired_document(entry)
    current_doc = load_current_document(entry, target_path)

    baseline_managed = load_baseline(entry)
    current_managed = extract_managed_subtree(current_doc, entry["filter_mode"], entry["filter_paths"])
    desired_managed = extract_managed_subtree(desired_doc, entry["filter_mode"], entry["filter_paths"])

    if detect_conflict(current_managed, baseline_managed):
        raise RuntimeError(f"managed subtree changed since last successful switch: {entry['target']}")

    if entry["filter_mode"] == "includes":
        merged = merge_includes(current_doc, desired_doc, entry["filter_paths"])
    else:
        merged = merge_excludes(current_doc, desired_doc, entry["filter_paths"])

    if current_text is not None and current_doc == merged:
        rendered = current_text
    elif entry["format"] == "toml" and current_text is not None:
        if entry["filter_mode"] == "includes":
            rendered = patch_toml_includes(current_text, desired_doc, entry["filter_paths"])
        else:
            rendered = patch_toml_excludes(current_text, current_doc, desired_doc, entry["filter_paths"])
    elif entry["format"] == "yaml" and current_text is not None:
        if entry["filter_mode"] == "includes":
            rendered = patch_yaml_file_includes(target_path, current_text, desired_doc, entry["filter_paths"])
        else:
            rendered = patch_yaml_file_excludes(target_path, current_text, current_doc, desired_doc, entry["filter_paths"])
    else:
        rendered = render_document(entry, merged)

    atomic_write(target_path, rendered, entry["mode"])

    write_baseline(entry, desired_managed)
