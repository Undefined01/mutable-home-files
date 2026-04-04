# mutable-file

`mutable-file` is split into two primary parts:

- `modules/home-manager/`: pure Nix code providing Home Manager modules and lightweight evaluation tests.
- `runtime/`: a Python runtime that assembles layered desired objects from task files, validates overlap, and reconciles them against mutable targets.

The design goal is to let declarative configuration and local mutable state coexist in the same file without relying on whole-file ownership.

## Development

Use `nix develop` for local work. The dev shell provides the tools needed for the current implementation path:

- `python3` for runtime development and tests
- `pytest` for runtime test execution
- `yq-go` for YAML format adaptation in the runtime
- `nixfmt-tree` for Nix formatting

The runtime is packaged as a Nix package and exposed from the flake as both `packages.<system>.mutable-file-runtime` and the default package. The Home Manager module consumes that package automatically when imported from this flake's `homeManagerModules.default` output.

## Repository layout

- `modules/home-manager/mutable-file/`: Home Manager module implementation.
- `modules/home-manager/docs/`: module-specific notes about activation hooks and platform integration.
- `modules/home-manager/tests/`: Home Manager eval tests for generated task payloads and activation blocks.
- `runtime/src/mutable_file_runtime/`: Python runtime implementation.
- `runtime/tests/`: runtime unit tests.
- `docs/`: cross-cutting architecture, interface, and implementation notes.

## Home Manager model

The module exposes `home.mutableFiles` for target definitions and `home.mutableFileRuntime.package` for runtime selection.

Each target file is defined as:

- a target-relative path under `home.homeDirectory`
- a file format (`json`, `yaml`, or `toml`)
- a recursive ownership policy
- one or more ordered `layers`

Each layer declares exactly one source:

- `value` for declarative Nix content
- `source` for a store path known at evaluation time
- `path` for a runtime path such as a secret file

Layers also define `from` and `to` mappings, so multiple sources can contribute different subtrees to the same target file.

Ownership determines how undeclared fields behave:

- `declared`: undeclared fields are ignored and may change locally
- `sealed`: undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

## Runtime model

The runtime works in three stages:

1. load and merge all layers into a single desired object
2. reject incompatible overlap before touching local files
3. compare and apply changes according to recursive ownership policy

Important semantics:

- object/object overlap is allowed and merged recursively
- any overlap involving arrays or scalars is rejected as a configuration error
- fields are deleted only when they were previously managed and are no longer declared
- if a layer starts managing a field that already exists locally, identical values are accepted but differing values are conflicts

## Activation model

The Home Manager module uses `home.activation` DAG entries for switch-time execution on every platform.

The activation block follows current Home Manager conventions for side-effecting hooks: it runs after `writeBoundary`, uses `run --silence` so `DRY_RUN` semantics stay intact, and emits optional diagnostics through `verboseEcho`.

- Linux platform integration may later expose `systemd.user.services` when a persistent user unit is useful.
- Darwin platform integration may later expose `launchd.agents` when a persistent user agent is useful.

The switch-time reconcile path itself stays centered on `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`.

## Testing model

- Runtime verification follows the nixpkgs package-test pattern through `mutable-file-runtime.tests.pytest` and the matching flake check.
- Home Manager verification stays in the lightweight eval lane: direct evaluation of generated task payloads and activation blocks, not VM tests.
- YAML tests use real `yq-go`, and TOML tests use real `tomlkit` patching behavior.

Convenience flake test outputs are also exposed:

- `.#test-runtime-pytest`
- `.#test-home-manager-eval`
- `.#test-all`

A thin convenience runner is also exposed as `nix run .#tests`:

- `nix run .#tests -- --list` lists the current flake test outputs
- `nix run .#tests -- test-home-manager-eval` runs a selected test output
- `nix run .#tests` runs the full aggregate test set

The runner discovers `test-*` outputs from the current flake package set, so the list stays in sync with the exported test targets instead of being maintained separately.
