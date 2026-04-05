import json
from pathlib import Path

import pytest

from mutable_file_runtime.formats import get_format
from mutable_file_runtime.git_state import GitStateRepo, INTERNAL_TASK_PATH
from mutable_file_runtime.reconcile import reconcile_document
from mutable_file_runtime.task_schema import decode_task_file


def make_document(tmp_path, target=None, **overrides):
    if target is None:
        target = str(tmp_path / "target" / ".config/app/config.json")
    payload = {
        "version": 5,
        "documents": [
            {
                "target": target,
                "format": "json",
                "create": True,
                "mode": "0600",
                "state_dir": str(tmp_path / "state"),
                "ownership": {
                    "default": "declared",
                    "rules": [],
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
    payload["documents"][0].update(overrides)
    return decode_task_file(payload).documents[0]


def seed_repo_success(document, *, live_text, applied_object, task_text='{"version":5,"documents":[]}\n'):
    repo = GitStateRepo(Path(document.state_dir))
    repo.ensure_initialized()
    repo.persist_success(
        live_texts={document.target: live_text},
        applied_texts={document.target: get_format(document.format).dump_new(applied_object)},
        task_text=task_text,
    )
    return repo


def test_reconcile_first_apply_writes_target_and_git_state(runtime_env):
    document = make_document(runtime_env["root"])

    reconcile_document(document)

    target = Path(document.target)
    repo = GitStateRepo(Path(document.state_dir))
    assert json.loads(target.read_text()) == {"app": {"name": "demo"}}
    assert repo.read_target_text("live", document.target) == target.read_text()
    assert json.loads(repo.read_target_text("applied", document.target)) == {"app": {"name": "demo"}}
    assert json.loads(repo.read_internal_text("applied", INTERNAL_TASK_PATH))["version"] == 5


def test_reconcile_preserves_comments_when_only_managed_field_changes(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_text = '# top\n[app]\nname = "old"\n\n[runtime]\nenabled = true # keep\n'
    target.write_text(original_text)

    document = make_document(
        runtime_env["root"],
        target=str(target),
        format="toml",
        ownership={
            "default": "declared",
            "rules": [{"path": ["runtime"], "mode": "local"}],
        },
        layers=[
            {
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
    seed_repo_success(
        document,
        live_text=original_text,
        applied_object={"app": {"name": "old"}},
    )

    reconcile_document(document)

    rendered = target.read_text()
    assert '# top' in rendered
    assert '# keep' in rendered
    assert 'name = "new"' in rendered


def test_reconcile_conflicts_on_local_managed_changes(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}))
    document = make_document(runtime_env["root"], target=str(target))
    seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)


def test_reconcile_ignores_old_json_snapshot_files(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "demo"}}))
    document = make_document(runtime_env["root"], target=str(target))
    legacy_state = Path(document.state_dir) / "legacy-state.json"
    legacy_state.parent.mkdir(parents=True, exist_ok=True)
    legacy_state.write_text(json.dumps({"version": 0, "ignored": True}))

    reconcile_document(document)

    repo = GitStateRepo(Path(document.state_dir))
    assert json.loads(repo.read_target_text("applied", document.target)) == {"app": {"name": "demo"}}


def test_reconcile_documents_is_atomic_with_shared_state_dir(runtime_env):
    first = make_document(runtime_env["root"], target=str(runtime_env["root"] / "target" / ".config/app/first.json"))
    second = make_document(runtime_env["root"], target=str(runtime_env["root"] / "target" / ".config/app/second.json"))

    Path(first.target).parent.mkdir(parents=True, exist_ok=True)
    Path(first.target).write_text(json.dumps({"app": {"name": "demo"}}, indent=2) + "\n")
    Path(second.target).parent.mkdir(parents=True, exist_ok=True)
    Path(second.target).write_text(json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")

    repo = GitStateRepo(Path(first.state_dir))
    repo.ensure_initialized()
    repo.persist_success(
        live_texts={
            first.target: json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
            second.target: json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        },
        applied_texts={
            first.target: json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
            second.target: json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        },
        task_text=json.dumps({"version": 5, "documents": []}, indent=2) + "\n",
    )
    live_before = repo.ref_oid("live")
    applied_before = repo.ref_oid("applied")

    from mutable_file_runtime.reconcile import reconcile_documents

    with pytest.raises(RuntimeError, match="resolve"):
        reconcile_documents((first, second))

    assert repo.ref_oid("live") != live_before
    assert repo.ref_oid("applied") == applied_before
    assert repo.commit_subject(repo.ref_oid("live")).startswith("Before reconcile ")
    assert json.loads(repo.read_target_text("desired", first.target)) == {"app": {"name": "demo"}}
    assert json.loads(repo.read_target_text("local", second.target)) == {"app": {"name": "manual"}}



def test_reconcile_conflict_session_creates_before_reconcile_commit(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")
    document = make_document(
        runtime_env["root"],
        target=str(target),
        layers=[
            {
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"app": {"name": "declared"}},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError, match="resolve"):
        reconcile_document(document)

    live_head = repo.ref_oid("live")
    session_id = repo.session_id_for_ref("live")
    assert repo.commit_subject(live_head) == f"Before reconcile {session_id}"
    assert repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("desired")]).strip() == f"Desired view {session_id}"
    assert repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("local")]).strip() == f"Local view {session_id}"


def test_reconcile_sealed_visible_subtree_preserves_new_yaml_fields(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'service:\n'
        '  declared:\n'
        '    enabled: true\n'
        '    extra: keep\n'
        '  runtime:\n'
        '    token: secret\n'
    )
    document = make_document(
        runtime_env["root"],
        target=str(target),
        format="yaml",
        ownership={
            "default": "declared",
            "rules": [
                {"path": ["service"], "mode": "sealed"},
                {"path": ["service", "runtime"], "mode": "local"},
            ],
        },
        layers=[
            {
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"service": {"declared": {"enabled": False}}},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    seed_repo_success(
        document,
        live_text='service:\n  declared:\n    enabled: false\n',
        applied_object={"service": {"declared": {"enabled": False}}},
    )

    with pytest.raises(RuntimeError, match="resolve"):
        reconcile_document(document)

    repo = GitStateRepo(Path(document.state_dir))
    assert get_format("yaml").load_text(repo.read_target_text("local", document.target)) == {
        "service": {"declared": {"enabled": True, "extra": "keep"}}
    }
