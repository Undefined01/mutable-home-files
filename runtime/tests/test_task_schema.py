import json

import pytest

from mutable_file_runtime.task_schema import load_task_file


def make_payload():
    return {
        "version": 5,
        "documents": [
            {
                "target": "/home/tester/.config/app/config.json",
                "format": "json",
                "create": True,
                "mode": "0600",
                "state_dir": "/tmp/state",
                "ownership": {
                    "default": "declared",
                    "rules": [
                        {"path": ["runtime"], "mode": "local"},
                    ],
                },
                "layers": [
                    {
                        "name": "defaults",
                        "source": {
                            "kind": "inline",
                            "value": {"app": {"name": "demo"}},
                        },
                        "from": [],
                        "to": [],
                        "required": True,
                    }
                ],
            }
        ],
    }


def test_load_task_file_accepts_v5_schema_without_explicit_ids(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(make_payload()))

    task_file = load_task_file(path)

    assert task_file.version == 5
    assert len(task_file.documents) == 1
    document = task_file.documents[0]
    assert document.target == "/home/tester/.config/app/config.json"
    assert document.ownership.default == "declared"
    assert document.ownership.mode_for(("runtime", "cache")) == "local"
    assert document.layers[0].name == "defaults"
    assert document.layers[0].source.kind == "inline"


def test_load_task_file_rejects_old_versions(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"version": 4, "documents": []}))

    with pytest.raises(ValueError):
        load_task_file(path)


def test_load_task_file_rejects_relative_runtime_paths(tmp_path):
    payload = make_payload()
    payload["documents"][0]["layers"][0]["source"] = {
        "kind": "runtime_path",
        "path": "relative.json",
    }
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError):
        load_task_file(path)
