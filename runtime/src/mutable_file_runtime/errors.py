from __future__ import annotations

import textwrap
from pathlib import Path


def _dedent(text: str) -> str:
    return textwrap.dedent(text).strip()


def resolve_worktree_merge_in_progress(worktree: str | Path) -> str:
    return _dedent(f"""
        The resolve worktree is still in an unresolved Git merge state.

        Why: a previous conflict session was started but the merge has not been
        completed or aborted yet. The runtime cannot proceed until the merge
        state is resolved.

        How to fix (choose one):

        Option A — finish the merge and commit the resolution:
          cd {worktree}
          # edit the conflicting files until you are satisfied
          git add .
          git commit -m "Resolve mutable-file conflict"

        Option B — abort the merge and start fresh:
          cd {worktree}
          git merge --abort

        Then rerun the mutable-file-runtime command.
    """)


def conflict_detected(
    worktree: str | Path,
    state_dir: str | Path,
    target: str,
    num_conflicts: int,
    conflict_details: str,
) -> str:
    return _dedent(f"""
        Conflict detected: {num_conflicts} semantic conflict(s) in {target}.

        A conflict worktree has been created so you can inspect and resolve
        the differences with standard Git tools.

        Why: the current on-disk file differs from both the previous applied
        state and the desired declarative state in ways that cannot be
        automatically reconciled.

        Conflict details:
        {conflict_details}

        How to resolve:
          cd {worktree}

        Useful commands in the worktree:
          git diff                          # see all changes
          git diff --ours                   # what changed on the local side
          git diff --theirs                 # what changed on the desired side
          git diff --base                   # diff against the merge base (applied)
          git show :2:<path>                # view the local version (stage 2)
          git show :3:<path>                # view the desired version (stage 3)
          git mergetool                     # launch visual 3-way merge tool

        After resolving all conflicts:
          git add .
          git commit -m "Resolve mutable-file conflict"

        Then rerun the runtime. If your resolved state matches the current task
        file, it will be applied to the real file on disk.

        To abort this conflict session:
          cd {state_dir}
          # the next run will create a fresh session if conflicts remain

        Repository: {state_dir}/repo.git
    """)


def resolve_mismatches_tasks(resolve_value, desired_managed, details: str, worktree: str | Path) -> str:
    return _dedent(f"""
        The resolve commit does not match the current task file.

        Why: the resolution you committed in the worktree describes a managed
        view that differs from what the current declarative tasks produce.
        The runtime requires resolve == applied-candidate before it will
        write the resolution to real files.

        Differences:
        {details}

        How to fix (choose one):

        Option A — update your task file so its output matches your resolution:
          1. edit the task file to produce the desired managed view
          2. rerun the runtime

        Option B — update the resolve commit to match the current tasks:
          cd {worktree}
          git checkout desired -- <file>    # accept the desired version
          # or manually edit the file
          git add .
          git commit --amend -m "Resolve mutable-file conflict"

        Option C — abort the session and start over:
          cd {worktree}
          git merge --abort
    """)


def resolve_mismatches_target_set(worktree: str | Path) -> str:
    return _dedent(f"""
        The resolve session's target set does not match the current task file.

        Why: targets were added or removed in the task file since the conflict
        session was created. The file set in resolve/local branches no longer
        matches the current declarative targets.

        How to fix:
          cd {worktree}
          git merge --abort

        Then rerun the runtime to create a fresh conflict session.
    """)


def local_changed_since_resolve(worktree: str | Path) -> str:
    return _dedent(f"""
        The local file has changed since the resolve session was created.

        Why: the on-disk target file was modified after you committed the
        conflict resolution. The staged resolution may no longer be valid
        against the new local state.

        How to fix:
          cd {worktree}
          git merge --abort

        Then rerun the runtime. If conflicts still exist, a fresh worktree
        will be created with the current local state.
    """)


def target_disappeared(target_path: str | Path) -> str:
    return _dedent(f"""
        Target file disappeared since the last successful apply.

        Why: {target_path} existed during the previous run but is now missing
        from disk. The runtime needs the previous file content to compute
        a safe diff.

        How to fix:
          1. restore the file from backup or from the live branch:
             git -C <state_dir>/repo.git show live:<repo-path> > {target_path}
          2. or remove the target from the task file and rerun
    """)


def target_not_found(target_path: str | Path) -> str:
    return _dedent(f"""
        Target file does not exist and create is disabled.

        Why: {target_path} does not exist on disk and the task does not
        have create=true set. The runtime cannot create a new file without
        explicit permission.

        How to fix (choose one):
          1. set "create": true in the task file for this target
          2. create the file manually: touch {target_path}
    """)


def render_verification_failed() -> str:
    return _dedent(f"""
        Rendered output did not match the planned semantic result.

        Why: the format adapter produced text that, when parsed back, differs
        from the expected semantic object. This is likely a bug in the format
        implementation (e.g. type coercion, key reordering, or value
        serialization that does not round-trip).

        How to fix:
          this is an internal runtime error — please report it with the
          task file and target file that triggered the failure
    """)


def resolved_render_mismatch() -> str:
    return _dedent(f"""
        Resolved render did not match the resolve branch semantic output.

        Why: after applying the resolution diff to the real file and projecting
        through ownership, the result differs from what the resolve branch
        stores. This usually indicates a projection inconsistency —
        the resolve branch may contain ownership-local data that should not
        participate, or the format adapter lost information during the edit.

        How to fix:
          this is an internal runtime error — please report it with the
          task file, target file, and resolve branch state
    """)


def multiple_state_dirs(got: set[str]) -> str:
    return _dedent(f"""
        Documents span multiple state directories.

        Why: all documents passed to reconcile_documents must share exactly
        one state_dir, because the Git state repository is per-state_dir.
        Got state_dirs: {sorted(got)}

        How to fix:
          group documents by state_dir and call reconcile_documents
          separately for each group
    """)


def root_not_object() -> str:
    return _dedent(f"""
        Root layer projection requires an object value.

        Why: a layer targets the document root (to=[]) with a non-object
        value. The document root must always be a mapping (dict/object).

        How to fix:
          ensure the layer source value at the projected path is an object,
          not a scalar or array
    """)


def layer_overlap(path: tuple[str, ...], layer_name: str) -> str:
    return _dedent(f"""
        Incompatible layer overlap.

        Why: two or more layers contribute non-object values to the same path.
        At path {'.'.join(path) or '<root>'}, layer '{layer_name}' tried to
        merge a value that conflicts with an existing non-object value.
        Only objects (dicts/mappings) can be deeply merged across layers.

        How to fix:
          ensure layers that target overlapping paths all contribute object
          values at the overlapping keys, or adjust layer to/from paths so
          they do not overlap at non-object leaves
    """)


def required_layer_source_missing(layer_name: str, source_path: str) -> str:
    return _dedent(f"""
        Required layer source file is missing.

        Why: layer '{layer_name}' has required=true but its source file
        does not exist at {source_path}.

        How to fix (choose one):
          1. create the missing source file
          2. set "required": false in the task file if this layer is optional
    """)


def layer_targets_local(layer_name: str, to_path: tuple[str, ...]) -> str:
    return _dedent(f"""
        Layer targets a local-ownership subtree.

        Why: layer '{layer_name}' projects to {list(to_path)}, which is
        covered by a local ownership rule. local subtrees are excluded
        from the managed view, so no layer may target them.

        How to fix (choose one):
          1. change the layer's "to" path to target a non-local subtree
          2. change the ownership rule to declared or sealed
    """)


def required_layer_path_missing(layer_name: str, from_path: tuple[str, ...]) -> str:
    return _dedent(f"""
        Required layer path missing in source.

        Why: layer '{layer_name}' has required=true but the path
        {list(from_path)} does not exist in its source document.

        How to fix (choose one):
          1. add the expected path to the source file
          2. adjust the layer's "from" path
          3. set "required": false in the task file if this layer is optional
    """)


def cannot_insert_at_root() -> str:
    return _dedent(f"""
        Cannot insert at the document root.

        Why: a diff operation attempted to insert a value at path ()
        (the document root). Insert operations require an array index
        because they insert into a list.

        How to fix:
          this is an internal runtime error — the diff algorithm should
          never produce a root-level insert. Please report this bug.
    """)


def insert_requires_array_index(path: tuple[...]) -> str:
    return _dedent(f"""
        Insert operation requires an array index.

        Why: an InsertOp was generated with path {list(path)}, but the
        last segment is not an integer. Insert can only add elements
        into arrays (lists), which requires a numeric index.

        How to fix:
          this is an internal runtime error — the diff algorithm should
          only produce InsertOp with integer-indexed paths. Please report
          this bug.
    """)