import json

from mutable_file_runtime.git_state import GitStateRepo, INTERNAL_TASK_PATH


def test_repo_initializes_live_and_applied_heads(runtime_env):
    repo = GitStateRepo(runtime_env["state_dir"])

    repo.ensure_initialized()

    live_head = repo.ref_oid("live")
    applied_head = repo.ref_oid("applied")
    assert live_head is not None
    assert applied_head == live_head
    assert repo.list_paths("live") == ()
    assert repo.list_paths("applied") == ()


def test_repo_persists_live_and_applied_trees(runtime_env):
    repo = GitStateRepo(runtime_env["state_dir"])
    target = "/home/tester/.config/app/config.json"
    raw_text = '{"app":{"name":"demo"}}\n'
    applied_text = json.dumps({"app": {"name": "demo"}}, indent=2) + "\n"
    task_text = json.dumps({"version": 5, "documents": []}, indent=2) + "\n"

    repo.ensure_initialized()
    live_commit, applied_commit = repo.persist_success(
        live_texts={target: raw_text},
        applied_texts={target: applied_text},
        task_text=task_text,
    )

    assert repo.ref_oid("live") == live_commit
    assert repo.ref_oid("applied") == applied_commit
    assert repo.read_target_text("live", target) == raw_text
    assert repo.read_target_text("applied", target) == applied_text
    assert repo.read_internal_text("applied", INTERNAL_TASK_PATH) == task_text
    assert repo.list_paths("live") == ("home/tester/.config/app/config.json",)
    assert repo.list_paths("applied") == (
        ".mutable-file/task.json",
        "home/tester/.config/app/config.json",
    )



def test_conflict_session_commits_share_one_short_session_id(runtime_env):
    repo = GitStateRepo(runtime_env["state_dir"])
    target = "/home/tester/.config/app/config.json"
    raw_text = '{"app":{"name":"manual"}}\n'
    applied_text = json.dumps({"app": {"name": "demo"}}, indent=2) + "\n"
    task_text = json.dumps({"version": 5, "documents": []}, indent=2) + "\n"

    repo.ensure_initialized()
    repo.persist_success(
        live_texts={target: raw_text},
        applied_texts={target: applied_text},
        task_text=task_text,
    )
    before_live = repo.ref_oid("live")
    before_applied = repo.ref_oid("applied")

    session_id = repo.new_session_id()
    before_commit = repo.snapshot_before_reconcile(
        live_texts={target: raw_text},
        removed_targets=(),
        session_id=session_id,
    )
    repo.start_conflict_session(
        desired_texts={target: json.dumps({"app": {"name": "declared"}}, indent=2) + "\n"},
        local_texts={target: json.dumps({"app": {"name": "manual"}}, indent=2) + "\n"},
        session_id=session_id,
    )
    repo.persist_success(
        live_texts={target: json.dumps({"app": {"name": "declared"}}, indent=2) + "\n"},
        applied_texts={target: json.dumps({"app": {"name": "declared"}}, indent=2) + "\n"},
        task_text=task_text,
        removed_targets=(),
        session_id=session_id,
    )

    before_message = repo._git_stdout(["log", "-1", "--format=%s", before_commit]).strip()
    desired_message = repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("desired")]).strip()
    local_message = repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("local")]).strip()
    live_message = repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("live")]).strip()
    applied_message = repo._git_stdout(["log", "-1", "--format=%s", repo.ref_oid("applied")]).strip()

    assert before_message == f"Before reconcile {session_id}"
    assert desired_message == f"Desired view {session_id}"
    assert local_message == f"Local view {session_id}"
    assert live_message == f"Update live {session_id}"
    assert applied_message == f"Update applied {session_id}"
    assert before_live != repo.ref_oid("live")
    assert before_applied != repo.ref_oid("applied")
