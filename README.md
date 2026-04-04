# mutable-file

`mutable-file` is split into two primary parts:

- `modules/home-manager/`: pure Nix code providing Home Manager modules and lightweight evaluation tests.
- `runtime/`: a Python runtime that assembles layered desired objects, computes local and declarative diffs independently, and reconciles mutable targets through format-specific editors.

The design goal is to let declarative configuration and local mutable state coexist in the same file without whole-file ownership or whole-file rewrites.

## Development

Use `nix develop` for local work. The dev shell provides the tools needed for the current implementation path:

- `python3` for runtime development and tests
- `pytest` for runtime test execution
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
- `docs/superpowers/specs/`: design specs written before major rewrites.
- `docs/superpowers/plans/`: implementation plans for larger changes.

## Home Manager model

The module exposes `home.mutableFiles` for target definitions and `home.mutableFileRuntime.package` for runtime selection.

Each target file is defined as:

- a target-relative path under `home.homeDirectory`
- a file format (`json`, `yaml`, or `toml`)
- a recursive ownership policy
- one or more ordered `layers`

Each layer declares exactly one source:

- `inline` content from Nix
- `store_path` content available at evaluation time
- `runtime_path` content resolved on the target machine at switch time

Layers also define `from` and `to` mappings, so multiple sources can contribute different subtrees to the same target file.

Ownership determines how undeclared fields behave:

- `declared`: undeclared fields are ignored and may change locally
- `sealed`: undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

## Runtime model

The runtime works in semantic phases:

1. assemble all layers into a single `current_desired` object
2. load the current local file and the previous state snapshot
3. compute `local_diff` and `desired_diff` independently
4. reject ownership-aware conflicts before writing anything
5. plan write operations only from `desired_diff`
6. apply those operations through JSON, YAML, or TOML implementations
7. verify the rendered file semantically and persist a new state snapshot

Important semantics:

- object/object overlap between layers is allowed and merged recursively
- any overlap involving arrays or scalars is rejected as a configuration error during assembly
- fields are deleted only when they existed in `previous_desired` and were removed from `current_desired`
- if a layer starts managing a field that already exists locally, identical values are accepted but differing values are conflicts
- unchanged managed fields are not rewritten just because they are managed

## Activation model

The Home Manager module uses `home.activation` DAG entries for switch-time execution on every platform.

The activation block follows current Home Manager conventions for side-effecting hooks: it runs after `writeBoundary`, uses `run --silence` so `DRY_RUN` semantics stay intact, and emits optional diagnostics through `verboseEcho`.

- Linux platform integration may later expose `systemd.user.services` when a persistent user unit is useful.
- Darwin platform integration may later expose `launchd.agents` when a persistent user agent is useful.

The switch-time reconcile path itself stays centered on `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`.

## Testing model

- Runtime verification is split by phase: task schema, assembly, diff, merge, format implementations, and end-to-end reconcile.
- Home Manager verification stays in the lightweight eval lane: direct evaluation of generated task payloads and activation blocks, not VM tests.
- YAML verification uses `ruamel.yaml` round-trip editing behavior, and TOML verification uses `tomlkit` round-trip editing behavior.

Convenience flake test outputs are exposed as:

- `.#test-runtime-pytest`
- `.#test-home-manager-eval`
- `.#test-all`

A thin convenience runner is also exposed as `nix run .#tests`.
