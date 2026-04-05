# mutable-file

`mutable-file` is split into two primary parts:

- `modules/home-manager/`: pure Nix code providing Home Manager modules and lightweight evaluation tests.
- `runtime/`: a Python runtime that assembles layered desired objects, tracks git-backed runtime state, and reconciles mutable targets through format-specific editors.

The design goal is to let declarative configuration and local mutable state coexist in the same file without whole-file ownership or whole-file rewrites.

## Development

Use `nix develop` for local work. The dev shell provides the tools needed for the current implementation path:

- `python3` for runtime development and tests
- `pytest` for runtime test execution
- `git` for the runtime state repository and conflict worktrees
- `tomlkit` for TOML round-trip editing
- `ruamel.yaml` for YAML round-trip editing
- `nixfmt-tree` for Nix formatting

The runtime is packaged as a Nix package and exposed from the flake as both `packages.<system>.mutable-file-runtime` and the default package. The Home Manager module consumes that package automatically when imported from this flake's `homeManagerModules.default` output.

## Repository layout

- `modules/home-manager/mutable-file/`: Home Manager module implementation.
- `modules/home-manager/docs/`: module-specific notes about activation hooks and platform integration.
- `modules/home-manager/tests/`: Home Manager eval tests for generated task payloads and activation blocks.
- `runtime/src/mutable_file_runtime/`: Python runtime implementation.
- `runtime/tests/`: runtime unit tests.
- `docs/`: cross-cutting architecture, interface, and implementation notes.

## Why this exists

`mutable-file` exists because two common configuration models are both too coarse on their own.

- Whole-file declarative ownership is too rigid when an application needs to write local runtime state into the same file.
- Whole-file local ownership is too weak when most of the file should still come from declarative configuration.

The project therefore splits the problem into three independent concerns:

- layers declare desired data from one or more sources
- ownership controls how undeclared fields behave at each subtree
- git-backed runtime state separates raw local history from managed declarative history across runs

This lets declarative defaults, runtime secrets, and local application state coexist without silently overwriting one another.

## Home Manager model

The module exposes `home.mutableFile` for mutable target definitions and `home.mutableFileRuntime.package` for runtime selection.

Each mutable file entry is defined by:

- `target`, defaulting to the attribute name and normalized to an absolute path
- a file format (`json`, `yaml`, or `toml`)
- a recursive ownership policy using `default` and `rules`
- exactly one source form: top-level `value`, top-level `source`, or explicit ordered `layers`

Top-level `value` and `source` are shortcuts for a single default layer with `from = [ ]`, `to = [ ]`, and `required = true`.

Layer sources support three normalized runtime kinds:

- `inline` content from Nix values
- `store_path` content available at evaluation time
- `runtime_path` content resolved on the target machine at activation time

Ownership determines how undeclared fields behave:

- `declared`: undeclared fields are ignored and may change locally
- `sealed`: undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

## Runtime model

The runtime consumes a schema v5 task file with absolute targets and no explicit document or layer ids.

Current runtime state is git-backed:

- one bare repository per `state_dir`
- `live` stores raw target text from the last successful apply
- `applied` stores prettified managed views plus `.mutable-file/task.json`
- `desired`, `local`, and `resolve` drive conflict sessions in a fixed resolve worktree

Normal successful runs work in semantic phases:

1. assemble all layers into a single desired object
2. project that object through ownership into the managed view
3. load current local files and the previous `live` / `applied` history
4. detect ownership-aware conflicts before writing anything
5. plan write operations only for the semantic changes that should happen now
6. apply those operations through JSON, YAML, or TOML implementations
7. verify the rendered file semantically and update `live` / `applied`

When local changes conflict with current declarative intent, the runtime creates a conflict session:

- `desired` contains the current managed target view
- `local` contains the current local applied view
- `resolve` is checked out in a fixed worktree and merged against `local`
- later runs reuse a merge commit on `resolve` until the user aborts or the session is accepted

Important semantics:

- object/object overlap between layers is allowed and merged recursively
- any overlap involving arrays or scalars is rejected as a configuration error during assembly
- unchanged managed fields are not rewritten just because they are managed
- pending-resolution apply uses `diff(local, resolve)` so sealed-field cleanup can be carried back into the real file
- targets that disappear from the task file are removed from Git state on the next successful run but are not deleted locally

## Edge cases and safety rules

The current implementation intentionally handles several edge cases explicitly:

- first apply with no previous Git state but an existing target uses takeover semantics and does not delete undeclared fields
- a missing target with existing `live` history is treated as a destructive local change and fails
- ownership changes to `local` stop management of that subtree without deleting local content
- `sealed` rejects undeclared fields even if they were already present before the current run
- pending-resolution sessions are reused across runs instead of silently recomputing the conflict basis
- stale local files are rejected before an existing `resolve` merge commit is applied
- declarative layer `from` / `to` paths still support only object keys; array indices are currently runtime-internal only
- old task files and old JSON snapshots are ignored rather than migrated

## Activation model

The Home Manager module uses `home.activation` DAG entries for switch-time execution on every platform.

The activation block follows current Home Manager conventions for side-effecting hooks: it runs after `writeBoundary`, uses `run --silence` so `DRY_RUN` semantics stay intact, and emits optional diagnostics through `verboseEcho`.

## Testing model

- Runtime verification is split by phase: task schema, assembly, diff, merge, git-backed state, format implementations, conflict sessions, and end-to-end reconcile.
- Home Manager verification stays in the lightweight eval lane: direct evaluation of generated task payloads and activation blocks, not VM tests.
- YAML verification uses `ruamel.yaml` round-trip editing behavior, and TOML verification uses `tomlkit` round-trip editing behavior.
- Full aggregate checks are exposed through flake outputs and `nix run .#tests`.

Convenience flake test outputs are exposed as:

- `.#test-runtime-pytest`
- `.#test-home-manager-eval`
- `.#test-all`

A thin convenience runner is also exposed as `nix run .#tests`.

## Further reading

- [docs/git-backed-runtime-state.md](docs/git-backed-runtime-state.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/interfaces.md](docs/interfaces.md)
- [docs/status.md](docs/status.md)
