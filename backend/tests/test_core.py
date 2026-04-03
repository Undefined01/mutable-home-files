import copy
import json
import os
import subprocess
from pathlib import Path
import sys
import shutil

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.src.mutable_file.core import (
    detect_conflict,
    extract_managed_subtree,
    load_desired_document,
    load_task_file,
    merge_excludes,
    merge_includes,
    meta_path_for,
    reconcile_entry,
    render_document,
    schema_version,
)
@pytest.fixture
def runtime(tmp_path):
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


def make_entry(state_root, **overrides):
    entry = {
        "entry_id": "entry-default",
        "target": ".config/app/config.json",
        "format": "json",
        "create": True,
        "mode": "0600",
        "state_root": str(state_root),
        "desired_source_kind": "value",
        "desired_source_payload": {
            "app": {"name": "demo"},
            "state": {"enabled": False},
        },
        "filter_mode": "includes",
        "filter_paths": [["app"]],
    }
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    ("document", "filter_mode", "filter_paths", "expected"),
    [
        (
            {"app": {"name": "demo", "state": {"open": True}}, "other": 1},
            "includes",
            [["app", "name"]],
            {"app": {"name": "demo"}},
        ),
        (
            {"app": {"name": "demo", "state": {"open": True}}, "other": 1},
            "excludes",
            [["app", "state"]],
            {"app": {"name": "demo"}, "other": 1},
        ),
    ],
)
def test_extract_managed_subtree(document, filter_mode, filter_paths, expected):
    assert extract_managed_subtree(document, filter_mode, filter_paths) == expected


@pytest.mark.parametrize(
    ("current", "baseline", "expected"),
    [
        ({"a": 1}, None, False),
        ({"a": 2}, {"a": 1}, True),
    ],
)
def test_detect_conflict(current, baseline, expected):
    assert detect_conflict(current, baseline) is expected


def test_load_task_file_checks_version(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"version": 1, "entries": []}))
    assert load_task_file(path)["entries"] == []


def test_schema_version_reads_version_field():
    assert schema_version({"version": 1}) == 1


def test_value_source_returns_copy():
    payload = {"app": {"name": "demo"}}
    desired = load_desired_document(
        {
            "format": "json",
            "desired_source_kind": "value",
            "desired_source_payload": payload,
        }
    )
    assert desired == payload
    assert desired is not payload


@pytest.mark.parametrize(
    ("format_name", "contents", "expected"),
    [
        ("json", '{"app": {"name": "from-source"}}', {"app": {"name": "from-source"}}),
        ("toml", '[app]\nname = "demo"\n', {"app": {"name": "demo"}}),
    ],
)
def test_load_desired_document_from_source(tmp_path, format_name, contents, expected):
    suffix = ".json" if format_name == "json" else ".toml"
    source = tmp_path / f"source{suffix}"
    source.write_text(contents)
    assert (
        load_desired_document(
            {
                "format": format_name,
                "desired_source_kind": "source",
                "desired_source_payload": str(source),
            }
        )
        == expected
    )


def test_runtime_path_input_uses_same_json_loader(tmp_path):
    source = tmp_path / "runtime.json"
    source.write_text(json.dumps({"app": {"name": "from-path"}}))
    assert (
        load_desired_document(
            {
                "format": "json",
                "desired_source_kind": "path",
                "desired_source_payload": str(source),
            }
        )
        == {"app": {"name": "from-path"}}
    )


def test_yaml_source_uses_yq_adapter(tmp_path, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    source = tmp_path / "source.yaml"
    source.write_text('app:\n  name: demo\n')
    assert (
        load_desired_document(
            {
                "format": "yaml",
                "desired_source_kind": "source",
                "desired_source_payload": str(source),
            }
        )
        == {"app": {"name": "demo"}}
    )


def test_yaml_render_uses_yq_adapter(real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    rendered = render_document({"format": "yaml"}, {"app": {"name": "demo"}})
    assert "app:" in rendered
    assert "name: demo" in rendered


def test_toml_render_uses_python_renderer_without_external_tool():
    rendered = render_document({"format": "toml"}, {"app": {"name": "demo"}})
    assert "[app]" in rendered
    assert 'name = "demo"' in rendered


@pytest.mark.parametrize(
    ("current", "desired", "filter_paths", "expected", "merge_fn"),
    [
        (
            {"app": {"name": "old"}, "state": {"enabled": True}},
            {"app": {"name": "new"}, "state": {"enabled": False}},
            [["app"]],
            {"app": {"name": "new"}, "state": {"enabled": True}},
            merge_includes,
        ),
        (
            {"app": {"name": "old"}, "state": {"enabled": True}},
            {"app": {"name": "new"}, "state": {"enabled": False}},
            [["state"]],
            {"app": {"name": "new"}, "state": {"enabled": True}},
            merge_excludes,
        ),
    ],
)
def test_merge_semantics(current, desired, filter_paths, expected, merge_fn):
    assert merge_fn(copy.deepcopy(current), copy.deepcopy(desired), filter_paths) == expected


def test_first_apply_writes_target_and_baseline(runtime):
    entry = make_entry(runtime["state_root"], entry_id="entry-a")
    reconcile_entry(entry, home_directory=runtime["home"])
    target = runtime["home"] / ".config/app/config.json"
    baseline = runtime["state_root"] / "entry-a" / "baseline_managed.json"
    meta = meta_path_for(entry)
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}
    assert json.loads(baseline.read_text()) == {"app": {"name": "demo"}}
    assert json.loads(meta.read_text())["target"] == ".config/app/config.json"


def test_unmanaged_changes_are_preserved(runtime):
    target = runtime["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "old"}, "state": {"enabled": True}}))
    entry = make_entry(runtime["state_root"], entry_id="entry-b", desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}})
    reconcile_entry(entry, home_directory=runtime["home"])
    assert json.loads(target.read_text()) == {"app": {"name": "new"}, "state": {"enabled": True}}


def test_managed_changes_conflict_against_baseline(runtime):
    target = runtime["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}, "state": {"enabled": True}}))
    baseline = runtime["state_root"] / "entry-c"
    baseline.mkdir(parents=True, exist_ok=True)
    (baseline / "baseline_managed.json").write_text(json.dumps({"app": {"name": "old"}}))
    entry = make_entry(runtime["state_root"], entry_id="entry-c", desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}})
    with pytest.raises(RuntimeError):
        reconcile_entry(entry, home_directory=runtime["home"])
    assert json.loads(target.read_text()) == {"app": {"name": "manual"}, "state": {"enabled": True}}


def test_yaml_reconcile_uses_yq_adapter(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('app:\n  name: old\nstate:\n  enabled: true\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml",
        target=".config/app/config.yaml",
        format="yaml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )
    reconcile_entry(entry, home_directory=runtime["home"])
    reloaded = load_desired_document(
        {
            "format": "yaml",
            "desired_source_kind": "source",
            "desired_source_payload": str(target),
        }
    )
    assert reloaded == {"app": {"name": "new"}, "state": {"enabled": True}}
    assert json.loads((runtime["state_root"] / "entry-yaml" / "baseline_managed.json").read_text()) == {"app": {"name": "new"}}


def test_yaml_reconcile_preserves_unmanaged_comments_with_real_yq(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# top\napp:\n  name: old\nstate:\n  enabled: true # keep\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml-comments",
        target=".config/app/config.yaml",
        format="yaml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )
    reconcile_entry(entry, home_directory=runtime["home"])
    rendered = target.read_text()
    assert "# top" in rendered
    assert "enabled: true # keep" in rendered
    reloaded = load_desired_document(
        {
            "format": "yaml",
            "desired_source_kind": "source",
            "desired_source_payload": str(target),
        }
    )
    assert reloaded["app"]["name"] == "new"


def test_toml_reconcile_preserves_unmanaged_comments_without_external_tool(runtime, monkeypatch):
    monkeypatch.delenv("MUTABLE_FILE_YQ_BIN", raising=False)
    target = runtime["home"] / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# top\n[app]\nname = "old"\n\n[state]\nenabled = true # keep\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-python-toml",
        target=".config/app/config.toml",
        format="toml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )
    reconcile_entry(entry, home_directory=runtime["home"])
    rendered = target.read_text()
    assert "# top" in rendered
    assert "enabled = true # keep" in rendered
    assert 'name = "new"' in rendered


def test_cli_reconciles_all_entries(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    task_file = tmp_path / "tasks.json"
    task_file.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "entry_id": "entry-cli",
                        "target": ".config/app/config.json",
                        "format": "json",
                        "create": True,
                        "mode": "0600",
                        "state_root": str(tmp_path / "state"),
                        "desired_source_kind": "value",
                        "desired_source_payload": {"app": {"name": "cli"}},
                        "filter_mode": "includes",
                        "filter_paths": [["app"]],
                    }
                ],
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            "backend/src/mutable_file/cli.py",
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


def test_merge_includes_replaces_managed_subtree_exactly():
    current = {"app": {"name": "old", "stale": True}, "state": {"enabled": True}}
    desired = {"app": {"name": "new"}, "state": {"enabled": False}}

    assert merge_includes(copy.deepcopy(current), copy.deepcopy(desired), [["app"]]) == {
        "app": {"name": "new"},
        "state": {"enabled": True},
    }


def test_merge_excludes_preserves_excluded_subtree_exactly():
    current = {"app": {"name": "manual"}, "state": {"enabled": True}}
    desired = {
        "app": {"name": "desired", "managed": True},
        "state": {"enabled": False},
    }

    assert merge_excludes(copy.deepcopy(current), copy.deepcopy(desired), [["app"]]) == {
        "app": {"name": "manual"},
        "state": {"enabled": False},
    }


def test_yaml_reconcile_includes_replaces_managed_subtree_exactly(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('app:\n  name: old\n  stale: true\nstate:\n  enabled: true\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml-include-exact",
        target=".config/app/config.yaml",
        format="yaml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )

    reconcile_entry(entry, home_directory=runtime["home"])

    reloaded = load_desired_document(
        {
            "format": "yaml",
            "desired_source_kind": "source",
            "desired_source_payload": str(target),
        }
    )
    assert reloaded == {"app": {"name": "new"}, "state": {"enabled": True}}


def test_yaml_reconcile_excludes_preserves_current_subtree_exactly(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('app:\n  name: manual\nstate:\n  enabled: true\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml-exclude-exact",
        target=".config/app/config.yaml",
        format="yaml",
        filter_mode="excludes",
        filter_paths=[["app"]],
        desired_source_payload={
            "app": {"name": "desired", "managed": True},
            "state": {"enabled": False},
        },
    )

    reconcile_entry(entry, home_directory=runtime["home"])

    reloaded = load_desired_document(
        {
            "format": "yaml",
            "desired_source_kind": "source",
            "desired_source_payload": str(target),
        }
    )
    assert reloaded == {"app": {"name": "manual"}, "state": {"enabled": False}}


def test_yaml_excludes_preserves_current_subtree_comments_with_real_yq(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('app:\n  # keep\n  name: manual # inline\nstate:\n  enabled: true\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml-exclude-comments",
        target=".config/app/config.yaml",
        format="yaml",
        filter_mode="excludes",
        filter_paths=[["app"]],
        desired_source_payload={
            "app": {"name": "desired", "managed": True},
            "state": {"enabled": False},
        },
    )

    reconcile_entry(entry, home_directory=runtime["home"])

    rendered = target.read_text()
    assert "# keep" in rendered
    assert "name: manual # inline" in rendered


def test_toml_excludes_preserves_current_subtree_comments(runtime, monkeypatch):
    monkeypatch.delenv("MUTABLE_FILE_YQ_BIN", raising=False)
    target = runtime["home"] / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('[app]\n# keep\nname = "manual" # inline\n\n[state]\nenabled = true\n')
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-toml-exclude-comments",
        target=".config/app/config.toml",
        format="toml",
        filter_mode="excludes",
        filter_paths=[["app"]],
        desired_source_payload={
            "app": {"name": "desired", "managed": True},
            "state": {"enabled": False},
        },
    )

    reconcile_entry(entry, home_directory=runtime["home"])

    rendered = target.read_text()
    assert "# keep" in rendered
    assert 'name = "manual" # inline' in rendered


def test_yaml_reconcile_is_stable_on_second_run(runtime, real_yq, monkeypatch):
    monkeypatch.setenv("MUTABLE_FILE_YQ_BIN", str(real_yq))
    target = runtime["home"] / ".config/app/config.yaml"
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-yaml-stable",
        target=".config/app/config.yaml",
        format="yaml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )

    reconcile_entry(entry, home_directory=runtime["home"])
    first_render = target.read_text()
    reconcile_entry(entry, home_directory=runtime["home"])
    second_render = target.read_text()

    assert second_render == first_render


def test_toml_reconcile_is_stable_on_second_run(runtime, monkeypatch):
    monkeypatch.delenv("MUTABLE_FILE_YQ_BIN", raising=False)
    target = runtime["home"] / ".config/app/config.toml"
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-toml-stable",
        target=".config/app/config.toml",
        format="toml",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )

    reconcile_entry(entry, home_directory=runtime["home"])
    first_render = target.read_text()
    reconcile_entry(entry, home_directory=runtime["home"])
    second_render = target.read_text()

    assert second_render == first_render


def test_json_reconcile_is_stable_on_second_run(runtime):
    target = runtime["home"] / ".config/app/config.json"
    entry = make_entry(
        runtime["state_root"],
        entry_id="entry-json-stable",
        target=".config/app/config.json",
        desired_source_payload={"app": {"name": "new"}, "state": {"enabled": False}},
    )

    reconcile_entry(entry, home_directory=runtime["home"])
    first_render = target.read_text()
    reconcile_entry(entry, home_directory=runtime["home"])
    second_render = target.read_text()

    assert second_render == first_render
