import json

import pytest

from mutable_file_runtime.reconcile import reconcile_document
from mutable_file_runtime.state import load_state, state_path_for
from mutable_file_runtime.task_schema import decode_task_file


def make_document(tmp_path, **overrides):
    payload = {
        "version": 4,
        "documents": [
            {
                "id": "doc-1",
                "target": ".config/app/config.json",
                "format": "json",
                "create": True,
                "mode": "0600",
                "state_dir": str(tmp_path / "state"),
                "ownership": {
                    "fallback": "declared",
                    "overrides": [],
                },
                "layers": [
                    {
                        "id": "layer-defaults",
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
    payload["documents"][0].update(overrides)
    return decode_task_file(payload).documents[0]


def test_reconcile_first_apply_writes_target_and_state(runtime_env):
    document = make_document(runtime_env["root"])

    reconcile_document(document, home_directory=runtime_env["home"])

    target = runtime_env["home"] / ".config/app/config.json"
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}

    snapshot = load_state(document)
    assert snapshot is not None
    assert snapshot.previous_applied == {"app": {"name": "demo"}}
    assert snapshot.previous_desired == {"app": {"name": "demo"}}


def test_reconcile_preserves_comments_when_only_managed_field_changes(runtime_env):
    target = runtime_env["home"] / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('# top\n[app]\nname = "old"\n\n[runtime]\nenabled = true # keep\n')

    document = make_document(
        runtime_env["root"],
        target=".config/app/config.toml",
        format="toml",
        ownership={
            "fallback": "declared",
            "overrides": [{"path": ["runtime"], "mode": "local"}],
        },
        layers=[
            {
                "id": "layer-defaults",
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"app": {"name": "new"}},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    state_path = state_path_for(document)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "document_id": document.id,
                "format": document.format,
                "ownership": {"fallback": "declared", "overrides": [{"path": ["runtime"], "mode": "local"}]},
                "previous_applied": {"app": {"name": "old"}, "runtime": {"enabled": True}},
                "previous_desired": {"app": {"name": "old"}},
            },
            indent=2,
        )
    )

    reconcile_document(document, home_directory=runtime_env["home"])

    rendered = target.read_text()
    assert '# top' in rendered
    assert '# keep' in rendered
    assert 'name = "new"' in rendered


def test_reconcile_conflicts_on_local_managed_changes(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}))
    document = make_document(runtime_env["root"])
    state_path = state_path_for(document)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "document_id": document.id,
                "format": document.format,
                "ownership": {"fallback": "declared", "overrides": []},
                "previous_applied": {"app": {"name": "demo"}},
                "previous_desired": {"app": {"name": "demo"}},
            },
            indent=2,
        )
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document, home_directory=runtime_env["home"])


def test_reconcile_treats_old_state_versions_as_absent(runtime_env):
    target = runtime_env["home"] / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "demo"}}))
    document = make_document(runtime_env["root"])
    state_path = state_path_for(document)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"version": 0, "ignored": True}))

    reconcile_document(document, home_directory=runtime_env["home"])

    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}
    snapshot = load_state(document)
    assert snapshot is not None
    assert snapshot.version == 1
