import json
import subprocess
from pathlib import Path

import pytest

from mutable_file_runtime.formats import get_format
from mutable_file_runtime.git_state import GitStateRepo, target_to_repo_path
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


def commit_resolve(repo, target, text):
    repo_path = target_to_repo_path(target)
    file_path = repo.resolve_worktree_path / repo_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text)
    subprocess.run(["git", "-C", str(repo.resolve_worktree_path), "add", repo_path], check=True)
    subprocess.run(
        [
            "git",
            "-C", str(repo.resolve_worktree_path),
            "-c", "user.name=Test",
            "-c", "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "Resolve mutable-file conflict",
        ],
        check=True,
    )


def test_conflict_session_uses_git_merge_with_local_as_current_and_desired_as_incoming(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"app": {"name": "manual"}, "ignored": {"cache": True}}, indent=2) + "\n"
    )
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

    with pytest.raises(RuntimeError, match="resolve worktree"):
        reconcile_document(document)

    assert json.loads(repo.read_target_text("desired", document.target)) == {"app": {"name": "declared"}}
    assert json.loads(repo.read_target_text("local", document.target)) == {"app": {"name": "manual"}}
    assert repo.ref_oid("resolve") == repo.ref_oid("local")

    merge_head = subprocess.run(
        ["git", "-C", str(repo.resolve_worktree_path), "rev-parse", "MERGE_HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert merge_head == repo.ref_oid("desired")

    worktree_text = (repo.resolve_worktree_path / target_to_repo_path(document.target)).read_text()
    assert "<<<<<<< HEAD" in worktree_text
    assert "|||||||" in worktree_text
    assert ">>>>>>> desired" in worktree_text
    assert '"manual"' in worktree_text
    assert '"declared"' in worktree_text
    assert '"ignored"' not in worktree_text
    assert repo.worktree_merge_in_progress()


def test_conflict_session_local_branch_uses_projection_basis_for_sealed_paths(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "app": {"name": "manual"},
                "sealedExtra": {"cache": True},
                "projects": {"/tmp/demo": {"enabled": True}},
            },
            indent=2,
        )
        + "\n"
    )
    document = make_document(
        runtime_env["root"],
        target=str(target),
        ownership={
            "default": "sealed",
            "rules": [{"path": ["projects"], "mode": "local"}],
        },
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError, match="resolve worktree"):
        reconcile_document(document)

    assert json.loads(repo.read_target_text("local", document.target)) == {
        "app": {"name": "manual"},
        "sealedExtra": {"cache": True},
    }


def test_pending_resolution_requires_finish_or_abort(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")
    document = make_document(runtime_env["root"], target=str(target))
    seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    with pytest.raises(RuntimeError, match="abort"):
        reconcile_document(document)


def test_pending_resolution_rejects_task_mismatch_with_field_details(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")
    document = make_document(runtime_env["root"], target=str(target))
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    commit_resolve(repo, document.target, json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")

    with pytest.raises(RuntimeError, match="tasks") as excinfo:
        reconcile_document(document)

    message = str(excinfo.value)
    assert "app.name" in message
    assert 'resolve="manual"' in message
    assert 'tasks="demo"' in message


def test_pending_resolution_ignores_local_ownership_subtrees_in_resolve(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"app": {"name": "manual"}, "projects": {"/tmp/demo": {"enabled": True}}}, indent=2) + "\n"
    )
    document = make_document(
        runtime_env["root"],
        target=str(target),
        ownership={
            "default": "sealed",
            "rules": [{"path": ["projects"], "mode": "local"}],
        },
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    commit_resolve(
        repo,
        document.target,
        json.dumps({"app": {"name": "manual"}, "projects": {"/tmp/demo": {"enabled": True}}}, indent=2) + "\n",
    )

    with pytest.raises(RuntimeError, match="app.name"):
        reconcile_document(document)


def test_pending_resolution_applies_sealed_field_deletion_from_live_document(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"credentials": {"api": {"token": "x"}, "extra": True}}, indent=2) + "\n"
    )
    document = make_document(
        runtime_env["root"],
        target=str(target),
        ownership={
            "default": "declared",
            "rules": [{"path": ["credentials"], "mode": "sealed"}],
        },
        layers=[
            {
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"credentials": {"api": {"token": "x"}}},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"credentials": {"api": {"token": "x"}}}, indent=2) + "\n",
        applied_object={"credentials": {"api": {"token": "x"}}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    assert json.loads(repo.read_target_text("local", document.target)) == {
        "credentials": {"api": {"token": "x"}, "extra": True}
    }

    commit_resolve(
        repo,
        document.target,
        json.dumps({"credentials": {"api": {"token": "x"}}}, indent=2) + "\n",
    )

    reconcile_document(document)

    assert json.loads(target.read_text()) == {"credentials": {"api": {"token": "x"}}}
    assert repo.ref_oid("desired") is None
    assert repo.ref_oid("local") is None
    assert repo.ref_oid("resolve") is None


def test_pending_resolution_allows_deleted_managed_subtree(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"service": {"enabled": False}}, indent=2) + "\n")
    document = make_document(
        runtime_env["root"],
        target=str(target),
        layers=[
            {
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"service": {"enabled": True}}, indent=2) + "\n",
        applied_object={"service": {"enabled": True}},
    )

    with pytest.raises(RuntimeError, match="resolve worktree"):
        reconcile_document(document)

    commit_resolve(repo, document.target, json.dumps({}, indent=2) + "\n")

    reconcile_document(document)

    assert json.loads(target.read_text()) == {}
    assert repo.ref_oid("desired") is None
    assert repo.ref_oid("local") is None
    assert repo.ref_oid("resolve") is None


def test_pending_resolution_declared_child_masks_sealed_ancestor_descendants(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "service": {
                    "runtime": {"name": "manual", "token": "secret"},
                    "extra": {"cache": True},
                }
            },
            indent=2,
        )
        + "\n"
    )
    document = make_document(
        runtime_env["root"],
        target=str(target),
        ownership={
            "default": "declared",
            "rules": [
                {"path": ["service"], "mode": "sealed"},
                {"path": ["service", "runtime"], "mode": "declared"},
            ],
        },
        layers=[
            {
                "name": "defaults",
                "source": {
                    "kind": "inline",
                    "value": {"service": {"runtime": {"name": "declared"}}},
                },
                "from": [],
                "to": [],
                "required": True,
            }
        ],
    )
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"service": {"runtime": {"name": "demo"}}}, indent=2) + "\n",
        applied_object={"service": {"runtime": {"name": "demo"}}},
    )

    with pytest.raises(RuntimeError, match="resolve worktree"):
        reconcile_document(document)

    assert json.loads(repo.read_target_text("local", document.target)) == {
        "service": {
            "runtime": {"name": "manual"},
            "extra": {"cache": True},
        }
    }


def test_pending_resolution_applies_semantic_diff_without_overwriting_local_only_text(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('[app]\nname = "manual"\n\n[runtime]\ncache = true # keep\n')
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
        live_text='[app]\nname = "demo"\n\n[runtime]\ncache = true # keep\n',
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    commit_resolve(repo, document.target, '[app]\nname = "declared"\n')

    reconcile_document(document)

    rendered = target.read_text()
    assert 'name = "declared"' in rendered
    assert '[runtime]' in rendered
    assert '# keep' in rendered
    assert 'cache = true' in rendered


def test_pending_resolution_rejects_changed_local_projection(runtime_env):
    target = runtime_env["root"] / "target" / ".config/app/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"app": {"name": "manual"}}, indent=2) + "\n")
    document = make_document(runtime_env["root"], target=str(target))
    repo = seed_repo_success(
        document,
        live_text=json.dumps({"app": {"name": "demo"}}, indent=2) + "\n",
        applied_object={"app": {"name": "demo"}},
    )

    with pytest.raises(RuntimeError):
        reconcile_document(document)

    commit_resolve(repo, document.target, json.dumps({"app": {"name": "demo"}}, indent=2) + "\n")
    target.write_text(json.dumps({"app": {"name": "changed-again"}}, indent=2) + "\n")

    with pytest.raises(RuntimeError, match="abort"):
        reconcile_document(document)
