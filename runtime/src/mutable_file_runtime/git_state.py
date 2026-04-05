from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path


INTERNAL_TASK_PATH = ".mutable-file/task.json"
_COMMIT_NAME = "mutable-file-runtime"
_COMMIT_EMAIL = "mutable-file-runtime@localhost"
_CONFLICT_BRANCHES = ("desired", "local", "resolve")


class GitStateRepo:
    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.repo_dir = self.state_dir / "repo.git"
        self.resolve_worktree_path = self.state_dir / "resolve"

    def ensure_initialized(self) -> None:
        if self.repo_dir.exists():
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init", "--bare", str(self.repo_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        empty_tree = self._write_tree({})
        initial_commit = self._commit_tree(empty_tree, None, "Initialize mutable-file runtime state")
        self._update_ref("live", initial_commit)
        self._update_ref("applied", initial_commit)

    def ref_oid(self, name: str) -> str | None:
        result = self._git(["rev-parse", "--verify", f"refs/heads/{name}"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def list_paths(self, name: str) -> tuple[str, ...]:
        result = self._git(["ls-tree", "-r", "--name-only", f"refs/heads/{name}"], check=False)
        if result.returncode != 0:
            return ()
        return tuple(line for line in result.stdout.splitlines() if line)

    def read_target_text(self, name: str, target: str) -> str | None:
        return self._read_path(name, target_to_repo_path(target))

    def read_internal_text(self, name: str, path: str) -> str | None:
        return self._read_path(name, path)

    def persist_success(
        self,
        *,
        live_texts: dict[str, str],
        applied_texts: dict[str, str],
        task_text: str,
        removed_targets: tuple[str, ...] = (),
        session_id: str | None = None,
    ) -> tuple[str, str]:
        self.ensure_initialized()

        live_tree = self._tree_texts("live")
        applied_tree = self._tree_texts("applied")

        for target in removed_targets:
            repo_path = target_to_repo_path(target)
            live_tree.pop(repo_path, None)
            applied_tree.pop(repo_path, None)

        for target, text in live_texts.items():
            live_tree[target_to_repo_path(target)] = text
        for target, text in applied_texts.items():
            applied_tree[target_to_repo_path(target)] = text
        applied_tree[INTERNAL_TASK_PATH] = task_text

        live_message = f"Update live {session_id}" if session_id is not None else "Update live state"
        applied_message = f"Update applied {session_id}" if session_id is not None else "Update applied state"
        live_commit = self._commit_from_texts(live_message, live_tree, self.ref_oid("live"))
        applied_commit = self._commit_from_texts(applied_message, applied_tree, self.ref_oid("applied"))
        self._update_ref("live", live_commit)
        self._update_ref("applied", applied_commit)
        return live_commit, applied_commit

    def snapshot_before_reconcile(
        self,
        *,
        live_texts: dict[str, str],
        removed_targets: tuple[str, ...] = (),
        session_id: str,
    ) -> str:
        self.ensure_initialized()

        live_tree = self._tree_texts("live")
        for target in removed_targets:
            live_tree.pop(target_to_repo_path(target), None)
        for target, text in live_texts.items():
            live_tree[target_to_repo_path(target)] = text

        commit = self._commit_from_texts(f"Before reconcile {session_id}", live_tree, self.ref_oid("live"))
        self._update_ref("live", commit)
        return commit

    def start_conflict_session(self, *, desired_texts: dict[str, str], local_texts: dict[str, str], session_id: str | None = None) -> None:
        self.ensure_initialized()
        self.clear_conflict_session()

        base = self.ref_oid("applied")
        desired_tree = {target_to_repo_path(target): text for target, text in desired_texts.items()}
        local_tree = {target_to_repo_path(target): text for target, text in local_texts.items()}
        desired_message = f"Desired view {session_id}" if session_id is not None else "Create desired conflict view"
        local_message = f"Local view {session_id}" if session_id is not None else "Create local conflict view"
        desired_commit = self._commit_from_texts(desired_message, desired_tree, base)
        local_commit = self._commit_from_texts(local_message, local_tree, base)
        self._update_ref("desired", desired_commit)
        self._update_ref("local", local_commit)
        self._update_ref("resolve", local_commit)

        self.resolve_worktree_path.parent.mkdir(parents=True, exist_ok=True)
        self._git(["worktree", "add", "--force", str(self.resolve_worktree_path), "resolve"])
        merge = self._git_in_worktree(["-c", "merge.conflictstyle=diff3", "merge", "--no-commit", "desired"], check=False)
        if merge.returncode not in (0, 1):
            raise RuntimeError(merge.stderr.strip() or "failed to create resolve worktree merge state")

    def clear_conflict_session(self) -> None:
        self.ensure_initialized()
        if self.resolve_worktree_path.exists():
            self._git(["worktree", "remove", "--force", str(self.resolve_worktree_path)], check=False)
        if self.resolve_worktree_path.exists():
            shutil.rmtree(self.resolve_worktree_path, ignore_errors=True)
        for branch in _CONFLICT_BRANCHES:
            self._git(["update-ref", "-d", f"refs/heads/{branch}"], check=False)

    def worktree_merge_in_progress(self) -> bool:
        if not self.resolve_worktree_path.exists():
            return False
        result = self._git_in_worktree(["rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False)
        return result.returncode == 0

    def resolve_is_merge_commit(self) -> bool:
        oid = self.ref_oid("resolve")
        if oid is None:
            return False
        line = self._git_stdout(["rev-list", "--parents", "-n", "1", oid]).strip()
        return len(line.split()) >= 3

    def new_session_id(self) -> str:
        return secrets.token_hex(4)

    def commit_subject(self, revision: str) -> str:
        return self._git_stdout(["log", "-1", "--format=%s", revision]).strip()

    def session_id_for_ref(self, name: str) -> str | None:
        oid = self.ref_oid(name)
        if oid is None:
            return None
        return _extract_session_id(self.commit_subject(oid))

    def _tree_texts(self, name: str) -> dict[str, str]:
        texts: dict[str, str] = {}
        for path in self.list_paths(name):
            content = self._read_path(name, path)
            if content is not None:
                texts[path] = content
        return texts

    def _read_path(self, name: str, path: str) -> str | None:
        result = self._git(["show", f"refs/heads/{name}:{path}"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout

    def _commit_from_texts(self, message: str, texts: dict[str, str], parent: str | None) -> str:
        tree = self._write_tree(texts)
        return self._commit_tree(tree, parent, message)

    def _write_tree(self, texts: dict[str, str]) -> str:
        if not texts:
            return self._git_stdout(["mktree"], input_text="").strip()

        fd, index_path = tempfile.mkstemp(dir=self.state_dir)
        os.close(fd)
        os.unlink(index_path)
        try:
            index_env = {"GIT_INDEX_FILE": index_path}
            update_lines: list[str] = []
            for path, text in sorted(texts.items()):
                blob = self._git_stdout(["hash-object", "-w", "--stdin"], input_text=text).strip()
                update_lines.append(f"100644 {blob} 0\t{path}\n")
            self._git(["update-index", "--index-info"], input_text="".join(update_lines), extra_env=index_env)
            return self._git_stdout(["write-tree"], extra_env=index_env).strip()
        finally:
            if os.path.exists(index_path):
                os.unlink(index_path)

    def _commit_tree(self, tree: str, parent: str | None, message: str) -> str:
        args = ["commit-tree", tree]
        if parent is not None:
            args.extend(["-p", parent])
        args.extend(["-m", message])
        return self._git_stdout(args).strip()

    def _update_ref(self, name: str, commit: str) -> None:
        self._git(["update-ref", f"refs/heads/{name}", commit])

    def _git_stdout(
        self,
        args: list[str],
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> str:
        return self._git(args, input_text=input_text, extra_env=extra_env).stdout

    def _git(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_DIR": str(self.repo_dir),
                "GIT_AUTHOR_NAME": _COMMIT_NAME,
                "GIT_AUTHOR_EMAIL": _COMMIT_EMAIL,
                "GIT_COMMITTER_NAME": _COMMIT_NAME,
                "GIT_COMMITTER_EMAIL": _COMMIT_EMAIL,
            }
        )
        if extra_env is not None:
            env.update(extra_env)
        return subprocess.run(
            ["git", *args],
            check=check,
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
        )

    def _git_in_worktree(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": _COMMIT_NAME,
                "GIT_AUTHOR_EMAIL": _COMMIT_EMAIL,
                "GIT_COMMITTER_NAME": _COMMIT_NAME,
                "GIT_COMMITTER_EMAIL": _COMMIT_EMAIL,
            }
        )
        return subprocess.run(
            ["git", "-C", str(self.resolve_worktree_path), *args],
            check=check,
            capture_output=True,
            text=True,
            env=env,
        )


def _extract_session_id(message: str) -> str | None:
    match = re.search(r"([0-9a-f]{8})$", message)
    if match is None:
        return None
    return match.group(1)


def target_to_repo_path(target: str) -> str:
    if not target.startswith("/"):
        raise ValueError(f"target must be absolute: {target}")
    repo_path = target[1:]
    if repo_path == "" or repo_path.startswith(".mutable-file/") or repo_path == ".mutable-file":
        raise ValueError(f"target path is reserved for runtime state: {target}")
    return repo_path
