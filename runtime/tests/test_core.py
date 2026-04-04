import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from runtime.src.mutable_file_runtime.core import (
    LOCAL,
    SEALED,
    assemble_desired_document,
    compare_documents,
    load_layer_document,
    load_task_file,
    managed_value_paths,
    meta_path_for,
    ownership_mode_for_path,
    reconcile_entry,
    render_document,
    schema_version,
)


@pytest.fixture
def runtime_env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return {
        "root": tmp_path,
        "home": home,
        "state_root": tmp_path / "state",
    }


@pytest.fixture
def real_yq():
    path = shutil.which("yq")
    if path is None:
        pytest.skip("real yq not available")
    version = subprocess.run([path, "--version"], text=True, capture_output=True, check=True)
    if "mikefarah" not in version.stdout and "version v" not in version.stdout:
        pytest.skip(f"unexpected yq implementation: {version.stdout.strip()}")
    return path


def make_layer(name, source_kind, source_payload, **overrides):
    layer = {
        "layer_id": f"layer-{name}",
        "name": name,
        "source_kind": source_kind,
        "source_payload": source_payload,
        "from_path": [],
        "to_path": [],
        "required": True,
    }
    layer.update(overrides)
    return layer


def make_entry(state_root, **overrides):
    entry = {
        "entry_id": "entry-default",
        "target": ".config/app/config.json",
        "format": "json",
        "create": True,
        "mode": "0600",
        "state_root": str(state_root),
        "ownership": {
            "default_mode": "declared",
            "rules": [
                {"path": ["state"], "mode": LOCAL},
            ],
        },
        "layers": [
            make_layer(
                "defaults",
                "value",
                {
                    "app": {"name": "demo"},
                    "state": {"enabled": False},
                },
            )
        ],
    }
    entry.update(overrides)
    return entry


def test_load_task_file_checks_version(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"version": 3, "entries": []}))
    assert load_task_file(path)["entries"] == []


def test_schema_version_reads_version_field():
    assert schema_version({"version": 3}) == 3


def test_load_layer_document_returns_copy_for_value():
    payload = {"app": {"name": "demo"}}
    document = load_layer_document("json", make_layer("defaults", "value", payload))
    assert document == payload
    assert document is not payload


@pytest.mark.parametrize(
    ("format_name", "contents", "expected"),
    [
        ("json", '{"app": {"name": "from-source"}}', {"app": {"name": "from-source"}}),
        ("toml", '[app]\nname = "demo"\n', {"app": {"name": "demo"}}),
    ],
)
def test_load_layer_document_from_source(tmp_path, format_name, contents, expected):
    suffix = ".json" if format_name == "json" else ".toml"
    source = tmp_path / f"source{suffix}"
    source.write_text(contents)
    assert load_layer_document(
        format_name,
        make_layer("source", "source", str(source)),
    ) == expected


def test_runtime_path_input_uses_same_json_loader(tmp_path):
    source = tmp_path / "runtime.json"
    source.write_text(json.dumps({"app": {"name": "from-path"}}))
    assert load_layer_document(
        "json",
        make_layer("runtime", "path", str(source)),
    ) == {"app": {"name": "from-path"}}


def test_yaml_source_uses_yq_adapter(tmp_path, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    source = tmp_path / "source.yaml"
    source.write_text('app:\n  name: demo\n')
    assert load_layer_document(
        "yaml",
        make_layer("source", "source", str(source)),
    ) == {"app": {"name": "demo"}}


def test_assemble_desired_document_merges_object_layers(tmp_path):
    runtime_json = tmp_path / "runtime.json"
    runtime_json.write_text(json.dumps({"token": "secret-token"}))
    entry = make_entry(
        tmp_path / "state",
        ownership={"default_mode": "declared", "rules": []},
        layers=[
            make_layer(
                "defaults",
                "value",
                {
                    "app": {"name": "demo"},
                    "credentials": {"database": {"user": "demo"}},
                },
            ),
            make_layer(
                "api-secret",
                "path",
                str(runtime_json),
                from_path=["token"],
                to_path=["credentials", "api", "token"],
            ),
        ],
    )

    assert assemble_desired_document(entry) == {
        "app": {"name": "demo"},
        "credentials": {
            "database": {"user": "demo"},
            "api": {"token": "secret-token"},
        },
    }


def test_overlap_on_scalar_is_rejected(tmp_path):
    entry = make_entry(
        tmp_path / "state",
        ownership={"default_mode": "declared", "rules": []},
        layers=[
            make_layer("one", "value", {"app": {"name": "demo"}}),
            make_layer("two", "value", {"name": "other"}, to_path=["app"]),
        ],
    )

    with pytest.raises(RuntimeError):
        assemble_desired_document(entry)


def test_local_ownership_target_is_rejected(tmp_path):
    entry = make_entry(
        tmp_path / "state",
        ownership={
            "default_mode": "declared",
            "rules": [{"path": ["runtime"], "mode": LOCAL}],
        },
        layers=[
            make_layer("defaults", "value", {"enabled": True}, to_path=["runtime"]),
        ],
    )

    with pytest.raises(RuntimeError):
        assemble_desired_document(entry)


def test_optional_missing_layer_is_skipped(tmp_path):
    missing = tmp_path / "missing.json"
    entry = make_entry(
        tmp_path / "state",
        ownership={"default_mode": "declared", "rules": []},
        layers=[
            make_layer("defaults", "value", {"app": {"name": "demo"}}),
            make_layer(
                "optional-secret",
                "path",
                str(missing),
                from_path=["token"],
                to_path=["credentials", "api", "token"],
                required=False,
            ),
        ],
    )

    assert assemble_desired_document(entry) == {"app": {"name": "demo"}}


def test_ownership_mode_resolution():
    ownership = {
        "default_mode": "declared",
        "rules": [
            {"path": ["credentials"], "mode": SEALED},
            {"path": ["credentials", "runtime"], "mode": LOCAL},
        ],
    }

    assert ownership_mode_for_path(ownership, ["credentials"]) == SEALED
    assert ownership_mode_for_path(ownership, ["credentials", "runtime", "cache"]) == LOCAL
    assert ownership_mode_for_path(ownership, ["app"]) == "declared"


def test_managed_value_paths_respect_local_ownership():
    document = {
        "app": {"name": "demo"},
        "state": {"enabled": False},
    }
    ownership = {
        "default_mode": "declared",
        "rules": [{"path": ["state"], "mode": LOCAL}],
    }

    assert managed_value_paths(document, ownership) == {
        ("app",),
        ("app", "name"),
    }


def test_compare_declared_ignores_unknown_fields():
    current = {
        "app": {"name": "demo"},
        "localOnly": {"cache": True},
    }
    desired = {
        "app": {"name": "demo"},
    }
    comparison = compare_documents(current, desired, {"default_mode": "declared", "rules": []}, set())

    assert comparison["conflicts"] == []
    assert comparison["set_ops"] == []
    assert comparison["delete_ops"] == []


def test_compare_sealed_rejects_unknown_fields():
    current = {
        "credentials": {"api": {"token": "x"}, "extra": True},
    }
    desired = {
        "credentials": {"api": {"token": "x"}},
    }
    comparison = compare_documents(
        current,
        desired,
        {
            "default_mode": "declared",
            "rules": [{"path": ["credentials"], "mode": SEALED}],
        },
        set(),
    )

    assert comparison["conflicts"]


def test_takeover_equal_value_is_allowed():
    current = {"app": {"name": "demo"}}
    desired = {"app": {"name": "demo"}}
    comparison = compare_documents(current, desired, {"default_mode": "declared", "rules": []}, set())
    assert comparison["conflicts"] == []


def test_takeover_different_value_conflicts():
    current = {"app": {"name": "manual"}}
    desired = {"app": {"name": "demo"}}
    comparison = compare_documents(current, desired, {"default_mode": "declared", "rules": []}, set())
    assert comparison["conflicts"]


def test_managed_deletion_only_applies_to_previous_managed_fields():
    current = {"app": {"name": "demo"}, "old": {"value": 1}}
    desired = {"app": {"name": "demo"}}
    comparison = compare_documents(
        current,
        desired,
        {"default_mode": "declared", "rules": []},
        {("old",), ("old", "value")},
    )
    assert [tuple(path) for path in comparison["delete_ops"]] == [("old",)]


def test_yaml_render_uses_yq_adapter(real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    rendered = render_document({"format": "yaml"}, {"app": {"name": "demo"}})
    assert "app:" in rendered
    assert "name: demo" in rendered


def test_toml_render_uses_python_renderer_without_external_tool():
    rendered = render_document({"format": "toml"}, {"app": {"name": "demo"}})
    assert "[app]" in rendered
    assert 'name = "demo"' in rendered


def test_first_apply_writes_target_and_state(runtime_env):
    entry = make_entry(runtime_env["state_root"], entry_id="entry-a")
    reconcile_entry(entry, home_directory=runtime_env["home"])
    target = runtime_env["home"] / ".config/app/config.json"
    state = runtime_env["state_root"] / "entry-a" / "state.json"
    meta = meta_path_for(entry)
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}
    assert json.loads(state.read_text())["managed_document"] == {"app": {"name": "demo"}, "state": {"enabled": False}}
    assert json.loads(meta.read_text())["target"] == ".config/app/config.json"


def test_declared_unknown_fields_can_update_locally(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "demo"}, "localOnly": {"cache": True}}))
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-b",
        ownership={"default_mode": "declared", "rules": []},
        layers=[make_layer("defaults", "value", {"app": {"name": "demo"}})],
    )
    reconcile_entry(entry, home_directory=runtime_env["home"])
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}, "localOnly": {"cache": True}}


def test_sealed_unknown_fields_conflict(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"credentials": {"api": {"token": "x"}, "extra": True}}))
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-c",
        ownership={
            "default_mode": "declared",
            "rules": [{"path": ["credentials"], "mode": SEALED}],
        },
        layers=[make_layer("defaults", "value", {"credentials": {"api": {"token": "x"}}})],
    )
    with pytest.raises(RuntimeError):
        reconcile_entry(entry, home_directory=runtime_env["home"])


def test_takeover_equal_value_does_not_conflict(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "demo"}}))
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-d",
        ownership={"default_mode": "declared", "rules": []},
        layers=[make_layer("defaults", "value", {"app": {"name": "demo"}})],
    )
    reconcile_entry(entry, home_directory=runtime_env["home"])
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}


def test_takeover_different_value_conflicts(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}))
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-e",
        ownership={"default_mode": "declared", "rules": []},
        layers=[make_layer("defaults", "value", {"app": {"name": "demo"}})],
    )
    with pytest.raises(RuntimeError):
        reconcile_entry(entry, home_directory=runtime_env["home"])


def test_managed_deletion_removes_only_previous_managed_fields(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "demo"}, "old": {"value": 1}, "localOnly": {"cache": True}}))
    state_dir = runtime_env["state_root"] / "entry-f"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "managed_document": {"app": {"name": "demo"}, "old": {"value": 1}},
                "managed_paths": [["app"], ["app", "name"], ["old"], ["old", "value"]],
                "ownership": {"default_mode": "declared", "rules": []},
            }
        )
    )
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-f",
        ownership={"default_mode": "declared", "rules": []},
        layers=[make_layer("defaults", "value", {"app": {"name": "demo"}})],
    )
    reconcile_entry(entry, home_directory=runtime_env["home"])
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}, "localOnly": {"cache": True}}


def test_yaml_reconcile_preserves_comments_outside_managed_paths(runtime_env, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime_env["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# top\napp:\n  name: old\nruntime:\n  enabled: true # keep\n')
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-yaml",
        target=".config/app/config.yaml",
        format="yaml",
        ownership={
            "default_mode": "declared",
            "rules": [{"path": ["runtime"], "mode": LOCAL}],
        },
        layers=[make_layer("defaults", "value", {"app": {"name": "new"}})],
    )
    state_dir = runtime_env["state_root"] / "entry-yaml"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "managed_document": {"app": {"name": "old"}},
                "managed_paths": [["app"], ["app", "name"]],
                "ownership": entry["ownership"],
            }
        )
    )
    reconcile_entry(entry, home_directory=runtime_env["home"])
    rendered = target.read_text()
    assert "# top" in rendered
    assert "enabled: true # keep" in rendered


def test_toml_reconcile_preserves_comments_outside_managed_paths(runtime_env, monkeypatch):
    monkeypatch.delenv("MUTABLE_FILE_YQ_BIN", raising=False)
    target = runtime_env["home"] / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# top\n[app]\nname = "old"\n\n[runtime]\nenabled = true # keep\n')
    entry = make_entry(
        runtime_env["state_root"],
        entry_id="entry-toml",
        target=".config/app/config.toml",
        format="toml",
        ownership={
            "default_mode": "declared",
            "rules": [{"path": ["runtime"], "mode": LOCAL}],
        },
        layers=[make_layer("defaults", "value", {"app": {"name": "new"}})],
    )
    state_dir = runtime_env["state_root"] / "entry-toml"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "managed_document": {"app": {"name": "old"}},
                "managed_paths": [["app"], ["app", "name"]],
                "ownership": entry["ownership"],
            }
        )
    )
    reconcile_entry(entry, home_directory=runtime_env["home"])
    rendered = target.read_text()
    assert "# top" in rendered
    assert "enabled = true # keep" in rendered


def test_cli_reconciles_all_entries(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "version": 3,
                "entries": [
                    {
                        "entry_id": "entry-cli",
                        "target": ".config/app/config.json",
                        "format": "json",
                        "create": True,
                        "mode": "0600",
                        "state_root": str(tmp_path / "state"),
                        "ownership": {"default_mode": "declared", "rules": []},
                        "layers": [
                            {
                                "layer_id": "layer-cli",
                                "name": "defaults",
                                "source_kind": "value",
                                "source_payload": {"app": {"name": "cli"}},
                                "from_path": [],
                                "to_path": [],
                                "required": True,
                            }
                        ],
                    }
                ],
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            "runtime/src/mutable_file_runtime/main.py",
            "--task-file",
            str(task_file),
            "--home-directory",
            str(home),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads((home / ".config/app/config.json").read_text()) == {"app": {"name": "cli"}}
    assert json.loads(result.stdout)["entry_count"] == 1
