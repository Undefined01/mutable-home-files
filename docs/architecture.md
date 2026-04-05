# Architecture

## Split responsibilities

### Home Manager module

The Home Manager side remains pure Nix.

Responsibilities:

- define `home.mutableFile`
- define `home.mutableFileRuntime.package`
- validate target, ownership, and layer options
- normalize file definitions into runtime task files
- normalize top-level `value` and `source` into default layers
- register switch-time activation hooks via `home.activation`
- invoke the packaged runtime binary exported by the flake or explicitly injected by callers

### Runtime

The runtime is a Python CLI with a semantic core, git-backed state, and format-specific editors.

Responsibilities:

- decode task files emitted by the Home Manager module
- load ordered layers from inline values, store paths, and runtime paths
- assemble layers into one desired object while rejecting ambiguous overlap
- project desired and local data through ownership into managed views
- load current local files and previous `live` / `applied` state from a bare Git repository
- detect ownership-aware conflicts before editing files
- create and reuse conflict-session branches and the fixed resolve worktree
- apply edits through JSON, YAML, and TOML implementations
- verify semantic correctness after render
- atomically write targets and advance runtime state

## Core design constraints

The system is designed around these constraints:

- layer overlap must be explicit and deterministic
- local edits and layer edits must be evaluated separately
- local state must not be silently taken over when a layer starts managing a path
- unchanged managed fields should not be rewritten just because they are managed
- YAML and TOML comments and key order should survive outside the edited write set whenever possible
- runtime state should preserve both raw local history and managed declarative history
- conflict resolution should be inspectable with ordinary Git tools

## Runtime state model

The runtime keeps one dedicated bare repository per `state_dir`.

Persistent branches:

- `live`: raw target text from the last successful apply
- `applied`: prettified managed-view text from the last successful apply

Conflict-session branches:

- `desired`: managed view requested by the current task file
- `local`: current local applied view at the time the conflict session was created
- `resolve`: fixed merge branch used in the resolve worktree

The `applied` tree also stores `.mutable-file/task.json` so the task input that produced the current `applied` state remains inspectable.

## Semantic model

For each target the runtime reasons about these semantic values:

- `previous_applied`: parsed managed view from `applied`
- `current_local`: parsed current file on disk
- `current_desired`: assembled desired object from layers
- `desired_managed`: ownership-projected managed view of `current_desired`
- `current_local_view`: ownership-projected managed view of `current_local`

This split lets the runtime answer two independent questions:

- what the declarative input wants now
- what the local file contributes now inside the managed projection

## Ownership model

The runtime applies one recursive ownership mode at each path.

- `declared`: only layer-declared fields are managed; undeclared fields are ignored
- `sealed`: the whole subtree participates in conflict detection; undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

The effective mode is resolved by longest matching rule, falling back to the file's `default` mode.

## Layer assembly model

The runtime first builds a single desired object from all layers.

Allowed merge:

- object with object, merged recursively

Rejected merge:

- scalar with scalar
- scalar with object
- scalar with array
- array with array
- array with object
- array with scalar

Rejected overlap is a configuration error, not a local-file conflict.

## Conflict model

When the current local file conflicts with the current declarative managed view, the runtime does not overwrite anything immediately.
Instead it creates one conflict session in the state repository.

That session:

- records the desired managed view in `desired`
- records the current local applied view in `local`
- checks out `resolve` in a fixed worktree
- starts a Git merge so the user can inspect and resolve the conflict with standard Git commands

If the user creates a merge commit on `resolve`, later runs reuse that merge result instead of silently recomputing the conflict basis.
The runtime only applies that pending resolution when:

- `resolve` still matches the current task-derived managed view
- the current local applied projection still matches the stored `local` branch

Pending-resolution apply uses `diff(local, resolve)` so manual cleanup, including sealed-field deletion, can be carried back into the real target file even when the task-derived managed view itself did not change.

## Operation model

The runtime core does not patch text directly. It emits ordered semantic edit operations:

- `set`
- `remove`
- `insert`

Object changes are represented with `set` and `remove`.
Array changes additionally use `insert` so the runtime can modify only changed regions instead of rewriting whole arrays.

## Format implementation model

Each format implementation provides the same interface:

- load semantic document from file or text
- create text for a brand-new file
- apply ordered operations to existing text

Implementations:

- JSON: ordered-object editing and deterministic dump
- YAML: `ruamel.yaml` round-trip editing
- TOML: `tomlkit` round-trip editing

The format implementation is responsible for preserving untouched ordering, comments, and layout as far as its underlying library allows.

## Packaging model

- `runtime/package.nix` builds the Python CLI as the `mutable-file-runtime` executable.
- The runtime depends on `git`, `tomlkit`, and `ruamel.yaml`.
- `runtime/package.nix` exposes package-level `passthru.tests.pytest` so runtime verification remains buildable without changing the main package output.
- `flake.nix` exports the runtime as both `packages.<system>.mutable-file-runtime` and `packages.<system>.default`.
- `flake.nix` also exports `apps.<system>.mutable-file-runtime`, a default `devShell`, and lightweight flake checks for Home Manager evaluation plus runtime package tests.

## Testing model

- Runtime tests are organized by semantic phase: schema, assembly, diff, merge, git-backed state, conflict sessions, format implementations, and end-to-end reconcile.
- Home Manager module tests remain lightweight evaluation tests that assert on generated payloads and activation hooks.
- Verification covers both semantic correctness and round-trip preservation for YAML/TOML comments and ordering.
- Aggregate verification is exposed through `nix run .#tests` so package tests and Home Manager eval tests stay in one place.

## Home Manager integration notes

The primary switch-time integration point remains:

```nix
home.activation.mutableFile = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
  verboseEcho "Reconciling mutable files"
  run --silence ${lib.getExe runtime} --task-file ${taskFile}
'';
```

This remains the canonical location for side-effecting runtime actions.
