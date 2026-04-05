# Git-Backed Runtime State Design

## Scope

This document defines the next runtime-state model for `mutable-file`.
It replaces the per-target JSON snapshot with a dedicated bare Git repository.

This is a design document, not a statement that the behavior is already implemented.
The current implementation still uses JSON snapshots.

## Goals

The new state model must satisfy all of the following:

- keep a full history of what the runtime last saw on disk
- keep a separate history of the managed view derived from ownership and layers
- allow users to inspect and resolve local/declarative conflicts with normal Git tools
- preserve target-file formatting, key order, comments, and unrelated layout whenever possible
- keep declarative inputs as the only long-term source of truth
- support a conflict workflow that can pause across runs and resume later
- allow conflict resolution to express deletions, including sealed-path extra fields that should disappear

## Terms

The design uses the following precise terms.

### `live`

A branch whose tree stores the raw text of each managed target file as it existed after the last successful apply.

- text is stored byte-for-byte in the target format
- comments, ordering, whitespace, and tool-specific formatting are preserved exactly
- `live` is updated only after a successful runtime apply

### `applied`

A branch whose tree stores the managed view of each target file after the last successful apply.

- each file is rendered in its declared format
- the rendering is prettified and deterministic
- only the ownership-visible managed view is stored here
- `applied` is updated only after a successful runtime apply

### `live-candidate`

A temporary commit created for the current run from the latest on-disk target files.

- it is built before conflict checking
- it does not move `live`
- its tree stores raw file text, just like `live`

### `applied-candidate`

A temporary commit created for the current run from the current tasks.

Construction:

1. load all layer sources
2. assemble each target's full semantic object
3. project that object through ownership into the managed view
4. render the managed view with deterministic pretty formatting in the target format

`applied-candidate` is what the runtime would like `applied` to become if the run succeeds.

### `local applied view`

The ownership-projected semantic view of the current local file.

It is derived from the parsed current local file using the same projection basis as conflict detection:

- paths declared by `previous_applied ∪ current_desired`
- the current ownership rules

This view is used for conflict comparison.
It is not stored in `live`.

### `pending resolution`

A runtime state in which a conflict session already exists and the user has not either:

- aborted it, or
- completed it and then rerun with matching tasks

Pending resolution is represented by the presence of a merge commit on `resolve`.
Once that merge commit exists, the runtime no longer recomputes the logical conflict result from the current local file on later runs. It reuses `resolve` until the user aborts or successfully completes the session.

## Repository Layout

Each runtime state directory contains one dedicated bare repository.

Example:

- `state_dir/repo.git`

This repository is used only by `mutable-file-runtime`.
No extra namespace prefix is needed in branch names.

Persistent branches:

- `live`
- `applied`

Conflict-session branches:

- `desired`
- `local`
- `resolve`

Reserved internal path in the `applied` tree:

- `.mutable-file/task.json`

That file stores the exact task file used to construct the current `applied` commit.
It is for diagnosis and historical inspection only. It does not participate in per-file semantic diffing.

Target files are mapped into Git paths by removing the leading slash from the absolute target path.

Examples:

- `/home/han/.config/app/config.toml` -> `home/han/.config/app/config.toml`
- `/etc/cloudflare/config.yaml` -> `etc/cloudflare/config.yaml`

The `.mutable-file/` namespace is reserved. Targets that would collide with it are invalid.

## Initial Repository State

On first use the runtime initializes the bare repository and creates one empty commit.
Both `live` and `applied` point at that same empty commit.

Properties:

- the commit tree contains no target files
- `.mutable-file/task.json` is absent in the initial commit
- there is no active conflict session

## Stored Representation

### `live` representation

`live` stores raw file text.

Why:

- it preserves exact user/application formatting history
- it makes Git history reflect what actually existed on disk
- it keeps future text-oriented diagnostics possible

### `applied` representation

`applied` stores prettified managed-view text in the file's own format.

Why:

- users can inspect the managed view in the same syntax as the target file
- Git diffs are easier to read than a JSON-encoded semantic state
- conflict worktrees can use the same representation as `applied`

### Semantic comparison rule

Git blobs are not compared directly for runtime semantics.
The runtime always parses text back through the file-format implementation before:

- ownership projection
- semantic diff generation
- compatibility checks
- operation planning

This keeps Git as a persistence and inspection layer rather than the semantic source of truth.

## Projection Model

For each target file the runtime reasons about three semantic objects.

### Full local object

This is the parsed target file as it exists on disk right now.

### Full desired object

This is the object assembled from all layers before ownership filtering.

### Managed view

This is the ownership-projected object used in `applied`, conflict branches, and semantic comparisons.

Projection rules:

- `local`: the subtree is omitted from the managed view entirely
- `declared`: only paths declared by `previous_applied ∪ current_desired` are visible
- `sealed`: the whole subtree is visible

The use of `previous_applied ∪ current_desired` is intentional.
It preserves visibility for paths that were previously managed but are now being deleted.
Without that union, deletion conflicts and takeover edges would lose context.

## Normal Successful Run

When there is no active pending resolution, the runtime performs the following steps.

1. Acquire the state lock for the repository.
2. Load and validate the task file.
3. Fail immediately if the task file is internally invalid.
   Examples:
   - required runtime sources are missing
   - layer overlap is incompatible
   - task-level ownership rules contradict layer targets
4. Read `live` and `applied` heads.
5. Build `live-candidate` from the current on-disk files for all task targets.
6. Build `applied-candidate` from the current tasks.
7. For each target, parse and compare:
   - previous applied view from `applied`
   - current local file from disk
   - current local applied view
   - current desired managed view from `applied-candidate`
8. Detect conflicts using ownership-aware semantics.
9. If there are no conflicts, plan format-specific edit operations against the current raw local text.
10. Verify the rendered output semantically.
11. Atomically write all targets.
12. Re-read the written targets and build the new successful `live` tree.
13. Build the new successful `applied` tree from the same semantic results and write `.mutable-file/task.json`.
14. Advance `live` and `applied`.
15. Clear any stale conflict branches or worktree.

`live` and `applied` must move only after every target has been written and verified successfully.
There is no partial ref update.

## Creating a Conflict Session

If the task file is valid but local semantic conflicts remain, the runtime creates one conflict session.

The repository contains only one active conflict session at a time.
A new session is not created while an old one is still active.

The session is built like this:

1. `applied` remains unchanged and acts as the merge base.
2. `desired` is created as a commit whose parent is `applied` and whose tree is the current `applied-candidate`.
3. `local` is created as a commit whose parent is `applied` and whose tree is the current local applied view.
4. `resolve` is checked out in a linked worktree rooted at a fixed path such as `state_dir/resolve`, starting from `local`.
5. The worktree merges `desired` while setting `merge.conflictstyle=diff3` so Git itself produces standard conflict markers with the `applied` base context.

The result is a normal Git merge state that users can inspect with standard commands.

Useful commands in the worktree:

- `git status`
- `git diff`
- `git diff --ours`
- `git diff --theirs`
- `git add`
- `git commit`
- `git merge --abort`

The worktree contains the full tree for all current task targets, not only conflicting files.
This preserves history and context.

## Meaning of `resolve`

`resolve` starts as the merge target branch for the conflict worktree.
Once the user creates a merge commit on `resolve`, the runtime interprets that merge commit as:

- the user-reviewed resolution for this conflict session
- the frozen logical replacement for the earlier local conflict result
- a pending declarative state that still must be matched by tasks before apply may continue

This is the key rule:

When `resolve` contains a merge commit, later runtime invocations do not recompute the logical conflict result from the current local file and do not regenerate a new merge worktree automatically.
They treat the existing `resolve` result as the user's chosen managed outcome until the session is aborted or completed.

## Running Again While a Conflict Session Exists

The runtime has three modes when conflict branches exist.

### 1. Merge still in progress

If the worktree is in an unresolved merge state, the runtime exits and tells the user to either:

- finish the merge and create a merge commit, or
- run `git merge --abort`

### 2. `resolve` merge commit exists

This means the user already resolved the conflict once.
The runtime must now validate that the environment still matches that resolution.

The second run proceeds as follows.

1. Load the current task file and rebuild `applied-candidate`.
2. Read the semantic result from `resolve`.
3. Require `resolve == applied-candidate` semantically for every target.
   If this fails, the runtime does not apply anything.
   It tells the user that the declarative inputs still do not describe the chosen resolution.
4. Re-read the current on-disk target files and compute a fresh current local applied projection.
5. Compare that fresh projection with the stored `local` branch semantically.
   This is the compatibility check.
6. If compatible, apply the stored resolution.
7. If not compatible, the local file changed since the conflict session was created.
   The runtime tells the user to abort the session and rerun, which creates a new merge worktree.

Compatibility is projection-based, not raw-text-based.
That means formatting-only changes or unrelated changes in ownership-ignored regions do not invalidate the session.

### 3. User aborted the merge

If the user aborts the merge and there is no pending `resolve` merge commit anymore, the runtime may create a fresh conflict session on the next run.

## How Apply Works After `resolve`

When a pending resolution is accepted, the runtime does not treat it as a new permanent source of truth.
Instead it uses it as a one-time, user-approved managed result that must already match current tasks.

The apply sequence is:

1. compute `resolution_diff` from the stored `local` managed view to the `resolve` managed view
2. apply that diff to the current raw local text using the normal format editor
3. preserve unrelated text structure as much as the format editor allows
4. verify that the resulting local file projects back to the `resolve` managed view
5. update `live` from the actual final file text
6. update `applied` from the resolved managed view and current task file
7. remove `desired`, `local`, and `resolve`, then clean the worktree

This design intentionally allows a resolution to produce file edits even when the current tasks are semantically equal to the previous `applied` state.
That case matters for sealed-path cleanup.

### Sealed extra-field deletion example

A sealed subtree may reject an extra local field that is not present in tasks.
A user may resolve that conflict by deleting the extra field in the merge worktree.

In that scenario:

- the resolved managed view may be semantically equal to the current tasks
- `desired_diff(previous_applied, current_desired)` may be empty
- the runtime must still modify the real local file to delete the unwanted field

That is why pending-resolution apply is driven by:

- `diff(local, resolve)`

not only by:

- `diff(previous_applied, current_desired)`

Without this rule, manual conflict resolution could never remove a sealed extra field unless tasks also changed.

## Why `resolve` Does Not Immediately Rewrite Files

The design deliberately avoids writing target files as soon as the user commits `resolve`.

Reasons:

- declarative inputs remain the only durable source of truth
- the user can inspect and amend tasks before the next apply
- the runtime can reject stale sessions when the underlying local file has evolved further
- it avoids silently accepting a manual merge result that the task file still does not express

The result is similar to Git conflict resolution, but with an extra declarative-consistency gate before the real files are changed.

## Branch Lifecycle

### On success with no conflict

- move `live`
- move `applied`
- delete `desired`
- delete `local`
- delete `resolve`
- remove any existing resolve worktree

### On newly detected conflict

- keep `live` unchanged
- keep `applied` unchanged
- recreate `desired`
- recreate `local`
- recreate or reset the resolve worktree on `resolve`

### On aborted conflict

- keep `live` unchanged
- keep `applied` unchanged
- delete `desired`
- delete `local`
- delete `resolve`
- remove the resolve worktree

### On accepted pending resolution

- write real files
- move `live`
- move `applied`
- delete `desired`
- delete `local`
- delete `resolve`
- remove the resolve worktree

## File-Set Changes

If a target disappears from the current task file:

- the runtime does not modify the local file on disk
- the path disappears from the next successful `live` tree
- the path disappears from the next successful `applied` tree
- historical commits still preserve the old state

If a target set change occurs while a conflict session is pending, the session is considered stale unless the `resolve` tree still matches the rebuilt `applied-candidate` exactly.
In practice this usually means the user should abort and regenerate the session.

## Ownership Semantics During Conflict Handling

### `declared`

- only declared paths participate in the managed view
- undeclared sibling fields may change locally without blocking apply
- compatibility checks ignore undeclared fields outside the projection

### `sealed`

- the full subtree participates in the managed view
- extra local fields appear in `local`
- the user may delete those fields in `resolve`
- a later successful apply must carry those deletions back into the real file

### `local`

- the subtree is omitted from `applied`, `desired`, `local`, and `resolve`
- conflict handling never asks the user to resolve changes inside it
- changes under `local` do not invalidate a conflict session unless they leak into the projected managed view through a configuration mistake

## Parsing and Formatting Failures

The runtime must fail before conflict construction or apply if:

- the target file cannot be parsed in its declared format
- a layer source cannot be parsed in the target format
- a rendered result cannot be parsed back to the expected semantic object

These are runtime or input errors, not merge conflicts.
They do not create a conflict session.

## Locking and Concurrency

The repository is guarded by one lock per `state_dir`.
Only one runtime process may manipulate the repository or resolve worktree at a time.

The lock covers:

- branch inspection
- candidate commit creation
- conflict-session setup
- apply
- branch advancement
- conflict cleanup

Without this lock, refs and the fixed resolve worktree could diverge.

## Invariants

The design relies on these invariants.

- `live` always reflects the raw file text from the last successful apply.
- `applied` always reflects the managed view from the last successful apply.
- `desired`, `local`, and `resolve` belong to at most one active conflict session.
- once `resolve` has a merge commit, it becomes the authoritative pending resolution for that session
- a pending resolution never writes files until it matches current tasks
- pending-resolution apply uses `diff(local, resolve)` so manual deletions and other conflict resolutions can take effect
- the runtime never treats Git text blobs themselves as semantic truth without parsing them through the format implementation
- tasks disappearing remove paths from Git state on the next successful run but do not delete local files

## Non-Goals

This design does not attempt to solve:

- multi-user collaborative editing inside the resolve worktree
- multiple simultaneous active conflict sessions in one state repository
- migration of old JSON snapshot state into the Git repository
- treating manual merge commits as a new declarative source of truth

## Why This Design Is Sufficient

Within the intended scope, this design covers the critical edge cases that motivated the rewrite:

- exact historical raw text is preserved in `live`
- readable managed history is preserved in `applied`
- users can resolve conflicts with standard Git tools in a persistent worktree
- later runs reuse `resolve` rather than silently changing the conflict basis
- stale local changes are detected before accepting an old resolution
- sealed extra fields can be manually deleted and then applied even when tasks themselves did not change
- declarative inputs remain the gate for successful apply

That combination gives the runtime a durable state model, an inspectable conflict workflow, and a clear boundary between user-assisted conflict resolution and declarative truth.
