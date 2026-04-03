# mutable-file

`mutable-file` is split into two independent parts:

- `frontend/`: pure Nix code providing Home Manager modules for Linux and Darwin.
- `backend/`: a Python tool that consumes task files emitted by the frontend and performs reconciliation.

The design goal is to manage only selected parts of mutable config files while preserving unmanaged application state.

## Development

Use `nix develop` for local work. The dev shell provides the tools needed for the current implementation path:

- `python3` for backend development and tests
- `pytest` for backend test execution
- `yq-go` for YAML format adaptation in the backend
- `nixfmt-tree` for Nix formatting

The backend is packaged as a Nix package and exposed from the flake as both `packages.<system>.mutable-file-backend` and the default package. The frontend module consumes that package when imported from this flake's `homeManagerModules.default` output.

Current adapter status:

- JSON: native Python path
- YAML: packaged `yq-go` (`mikefarah/yq` CLI)
- TOML: Python `tomlkit` path with in-place patching over the current document

## Repository layout

- `frontend/modules/`: Home Manager module implementation.
- `frontend/docs/`: frontend-specific notes about activation hooks and platform integration.
- `backend/src/mutable_file/`: Python runtime implementation.
- `backend/tests/`: backend unit tests.
- `docs/`: cross-cutting architecture and task schema.

## Activation model

The frontend uses Home Manager's `home.activation` DAG for switch-time execution on every platform.

The activation block follows current Home Manager conventions for side-effecting hooks: it runs after `writeBoundary`, uses `run --silence` so `DRY_RUN` semantics stay intact, and emits optional diagnostics through `verboseEcho`.

- Linux platform integration may later expose `systemd.user.services` when a persistent user unit is useful.
- Darwin platform integration may later expose `launchd.agents` when a persistent user agent is useful.

The switch-time reconcile path itself stays centered on `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`.

## Testing model

- Backend verification follows the nixpkgs package-test pattern through `mutable-file-backend.tests.pytest` and the matching flake check.
- Frontend verification stays in the Home Manager-style lightweight lane: direct evaluation of generated task payloads and activation blocks, not VM tests.
- YAML tests use real `yq-go`, and TOML tests use real `tomlkit` patching behavior.

Convenience flake test outputs are also exposed:

- `.#test-backend-pytest`
- `.#test-frontend-eval`
- `.#test-all`

A thin convenience runner is also exposed as `nix run .#tests`:

- `nix run .#tests -- --list` lists the current flake test outputs
- `nix run .#tests -- test-frontend-eval` runs a selected test output
- `nix run .#tests` runs the full aggregate test set

The runner discovers `test-*` outputs from the current flake package set, so the list stays in sync with the exported test targets instead of being maintained separately.
