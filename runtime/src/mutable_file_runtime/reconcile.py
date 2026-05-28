from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .assemble import assemble_document
from .diff import diff_documents, format_ops_for_error
from .errors import (
    conflict_detected,
    local_changed_since_resolve,
    multiple_state_dirs,
    render_verification_failed,
    resolve_mismatches_target_set,
    resolve_mismatches_tasks,
    resolve_worktree_merge_in_progress,
    resolved_render_mismatch,
    target_disappeared,
    target_not_found,
)
from .formats import get_format
from .git_state import GitStateRepo, INTERNAL_TASK_PATH, target_to_repo_path
from .merge import merge_documents
from .model import MISSING
from .projection import materialize_resolved, project_desired, project_local


@dataclass(frozen=True)
class DocumentRun:
    document: object
    adapter: object
    desired_managed: object
    previous_applied: object
    current_text: str | None
    current_local: object
    current_local_view: object
    merge_result: object


def _atomic_write(path: Path, text: str, mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.flush()
        os.fchmod(handle.fileno(), int(mode, 8))
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _task_payload_for_documents(documents) -> str:
    payload = {
        "version": 5,
        "documents": [
            {
                "target": document.target,
                "format": document.format,
                "create": document.create,
                "mode": document.mode,
                "state_dir": document.state_dir,
                "ownership": {
                    "default": document.ownership.default,
                    "rules": [
                        {"path": list(rule.path), "mode": rule.mode}
                        for rule in document.ownership.rules
                    ],
                },
                "layers": [
                    {
                        "name": layer.name,
                        "source": (
                            {"kind": layer.source.kind, "value": layer.source.value}
                            if layer.source.kind == "inline"
                            else {"kind": layer.source.kind, "path": layer.source.path}
                        ),
                        "from": list(layer.from_path),
                        "to": list(layer.to_path),
                        "required": layer.required,
                    }
                    for layer in document.layers
                ],
            }
            for document in documents
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _load_current_text_and_value(document, adapter, previous_live_text):
    target_path = Path(document.target)
    if target_path.exists():
        current_text = target_path.read_text()
        current_local = adapter.load_text(current_text)
        return current_text, current_local
    if previous_live_text is not None:
        raise RuntimeError(target_disappeared(target_path))
    if not document.create:
        raise FileNotFoundError(target_not_found(target_path))
    return None, {}


def _normalize_projection(value):
    if value is MISSING:
        return {}
    return value


def _current_target_paths(documents) -> set[str]:
    return {target_to_repo_path(document.target) for document in documents}


def _removed_targets(repo: GitStateRepo, documents) -> tuple[str, ...]:
    current_paths = _current_target_paths(documents)
    previous_paths = set(repo.list_paths("live")) | set(repo.list_paths("applied"))
    removed = []
    for path in sorted(previous_paths):
        if path == INTERNAL_TASK_PATH:
            continue
        if path not in current_paths:
            removed.append("/" + path)
    return tuple(removed)


def _prepare_run(document, repo: GitStateRepo) -> DocumentRun:
    adapter = get_format(document.format)
    desired = assemble_document(document)
    desired_managed = _normalize_projection(project_desired(desired, document.ownership))

    previous_applied_text = repo.read_target_text("applied", document.target)
    previous_live_text = repo.read_target_text("live", document.target)
    previous_applied = adapter.load_text(previous_applied_text) if previous_applied_text is not None else MISSING
    current_text, current_local = _load_current_text_and_value(document, adapter, previous_live_text)
    current_local_view = _normalize_projection(
        project_local(current_local, previous_applied, desired_managed, document.ownership)
    )
    merge_result = merge_documents(
        previous_applied=previous_applied,
        previous_desired=previous_applied,
        current_local=current_local,
        current_desired=desired_managed,
        ownership=document.ownership,
    )
    return DocumentRun(
        document=document,
        adapter=adapter,
        desired_managed=desired_managed,
        previous_applied=previous_applied,
        current_text=current_text,
        current_local=current_local,
        current_local_view=current_local_view,
        merge_result=merge_result,
    )


def _render_success(run: DocumentRun) -> str:
    if run.current_text is None:
        rendered = run.adapter.dump_new(run.merge_result.final_document)
    elif not run.merge_result.planned_ops:
        rendered = run.current_text
    else:
        rendered = run.adapter.apply_ops(run.current_text, run.merge_result.planned_ops)

    verified = run.adapter.load_text(rendered)
    if verified != run.merge_result.final_document:
        raise RuntimeError(render_verification_failed())
    return rendered


def _apply_resolution_run(run: DocumentRun, repo: GitStateRepo) -> str:
    resolve_text = repo.read_target_text("resolve", run.document.target)
    local_text = repo.read_target_text("local", run.document.target)
    if resolve_text is None or local_text is None:
        raise RuntimeError(
            resolve_mismatches_target_set(repo.resolve_worktree_path)
        )

    resolve_raw = run.adapter.load_text(resolve_text)
    resolve_value = _normalize_projection(
        project_local(resolve_raw, run.previous_applied, run.desired_managed, run.document.ownership)
    )
    local_view = run.adapter.load_text(local_text)
    if resolve_value != run.desired_managed:
        details = format_ops_for_error("resolve", "tasks", diff_documents(resolve_value, run.desired_managed), resolve_value, run.desired_managed)
        raise RuntimeError(
            resolve_mismatches_tasks(resolve_value, run.desired_managed, details, repo.resolve_worktree_path)
        )
    if run.current_local_view != local_view:
        raise RuntimeError(local_changed_since_resolve(repo.resolve_worktree_path))

    resolved_document = _normalize_projection(
        materialize_resolved(
            run.current_local,
            resolve_value,
            run.previous_applied,
            run.desired_managed,
            run.document.ownership,
        )
    )
    resolution_ops = diff_documents(run.current_local, resolved_document)
    if run.current_text is None:
        rendered = run.adapter.dump_new(resolved_document)
    elif not resolution_ops:
        rendered = run.current_text
    else:
        rendered = run.adapter.apply_ops(run.current_text, resolution_ops)

    verified = run.adapter.load_text(rendered)
    verified_view = _normalize_projection(
        project_local(verified, run.previous_applied, run.desired_managed, run.document.ownership)
    )
    if verified_view != resolve_value:
        raise RuntimeError(resolved_render_mismatch())
    return rendered


def reconcile_documents(documents):
    documents = tuple(documents)
    if not documents:
        return

    state_dirs = {document.state_dir for document in documents}
    if len(state_dirs) != 1:
        raise ValueError(multiple_state_dirs(state_dirs))

    repo = GitStateRepo(documents[0].state_dir)
    repo.ensure_initialized()

    if repo.worktree_merge_in_progress():
        raise RuntimeError(
            resolve_worktree_merge_in_progress(repo.resolve_worktree_path)
        )

    runs = tuple(_prepare_run(document, repo) for document in documents)
    task_text = _task_payload_for_documents(documents)
    removed_targets = _removed_targets(repo, documents)
    session_id: str | None = None

    if repo.resolve_is_merge_commit():
        resolve_paths = set(repo.list_paths("resolve"))
        local_paths = set(repo.list_paths("local"))
        current_paths = _current_target_paths(documents)
        if resolve_paths != current_paths or local_paths != current_paths:
            raise RuntimeError(
                resolve_mismatches_target_set(repo.resolve_worktree_path)
            )

        rendered_texts = {
            run.document.target: _apply_resolution_run(run, repo)
            for run in runs
        }
        for run in runs:
            _atomic_write(Path(run.document.target), rendered_texts[run.document.target], run.document.mode)
        if session_id is None:
            session_id = repo.session_id_for_ref("resolve")
        repo.persist_success(
            live_texts=rendered_texts,
            applied_texts={
                run.document.target: run.adapter.dump_new(run.desired_managed)
                for run in runs
            },
            task_text=task_text,
            removed_targets=removed_targets,
            session_id=session_id,
        )
        repo.clear_conflict_session()
        return

    first_conflict = next((run for run in runs if run.merge_result.conflicts), None)
    if first_conflict is not None:
        session_id = repo.new_session_id()
        repo.snapshot_before_reconcile(
            live_texts={
                run.document.target: run.current_text if run.current_text is not None else run.adapter.dump_new(run.current_local)
                for run in runs
            },
            removed_targets=removed_targets,
            session_id=session_id,
        )
        repo.start_conflict_session(
            desired_texts={
                run.document.target: run.adapter.dump_new(run.desired_managed)
                for run in runs
            },
            local_texts={
                run.document.target: run.adapter.dump_new(run.current_local_view)
                for run in runs
            },
            session_id=session_id,
        )
        conflict_lines: list[str] = []
        for run in runs:
            for c in run.merge_result.conflicts:
                path_str = ".".join(str(s) for s in c.path) or "<root>"
                conflict_lines.append(f"  {run.document.target}: {path_str} — {c.reason}")
        raise RuntimeError(
            conflict_detected(
                worktree=repo.resolve_worktree_path,
                state_dir=repo.state_dir,
                target=first_conflict.document.target,
                num_conflicts=sum(len(run.merge_result.conflicts) for run in runs),
                conflict_details="\n".join(conflict_lines),
            )
        )

    rendered_texts = {
        run.document.target: _render_success(run)
        for run in runs
    }
    for run in runs:
        _atomic_write(Path(run.document.target), rendered_texts[run.document.target], run.document.mode)
    repo.persist_success(
        live_texts=rendered_texts,
        applied_texts={
            run.document.target: run.adapter.dump_new(run.desired_managed)
            for run in runs
        },
        task_text=task_text,
        removed_targets=removed_targets,
        session_id=session_id,
    )
    repo.clear_conflict_session()


def reconcile_document(document):
    reconcile_documents((document,))
