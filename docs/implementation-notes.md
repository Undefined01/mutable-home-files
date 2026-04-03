# Implementation Notes

## Frontend / Backend boundary

Current boundary is intentionally narrow:

- frontend emits a single aggregated JSON task file
- frontend invokes one backend executable at Home Manager switch time
- backend owns all runtime reads, conflict detection, merges, and target writes

The frontend does not parse target files and does not shell out to `yq` directly.

## Frontend implementation model

- Home Manager module entry point: `frontend/modules/mutable-file/default.nix`
- Switch-time execution path: `home.activation.mutableFile = lib.hm.dag.entryAfter [ "writeBoundary" ] ...`
- Backend selection option: `home.mutableFileBackend.package`
- Flake default module wiring: `flake.nix` injects `self.packages.<system>.mutable-file-backend`

The activation block is written in the current Home Manager style:

- it runs after `writeBoundary`
- it uses `verboseEcho` for optional logging
- it uses `run --silence ...` so `DRY_RUN` and activation-driver behavior remain consistent

This gives two supported consumption paths:

1. import the flake's `homeManagerModules.default`
2. import the raw module and override `home.mutableFileBackend.package`

## Backend implementation model

- Runtime entry point: `backend/src/mutable_file/cli.py`
- Core reconcile logic: `backend/src/mutable_file/core.py`
- State layout: `${state_root}/${entry_id}/baseline_managed.json` and `${state_root}/${entry_id}/meta.json`

The backend currently uses a hybrid strategy:

- Python stdlib owns task parsing, path filtering, conflict detection, merge logic, and atomic writes
- external helpers are only used as format adapters

## Format adapter status

- JSON: pure Python stdlib
- YAML: adapted via packaged `yq-go` (`mikefarah/yq`)
- TOML: adapted directly in Python with `tomlkit`

For YAML, the backend converts target/source content through `yq-go` (`mikefarah/yq`) at the edges and then reuses the in-memory JSON-like merge pipeline.

For YAML updates against existing files, the backend now applies selected-path mutations on a temporary working copy and only then atomically replaces the live target. This keeps the write path aligned with the generic atomic-write contract instead of mutating the live file in-place during reconciliation.

For TOML, the backend parses the current document with `tomlkit`, uses `.unwrap()` for canonical subtree comparison, and applies selected-path mutations back onto the original TOML document so unmanaged comments and layout survive.

## Packaging model

- Nix package definition: `backend/package.nix`
- Executable name: `mutable-file-backend`
- Wrapper environment: `MUTABLE_FILE_YQ_BIN` is set to the packaged `yq-go` binary
- Development shell: `nix develop` provides `python3`, `pytest`, `yq-go`, `nixfmt-tree`

## Current follow-up scope

- keep the same frontend/backend task-file interface
- continue reducing helper duplication between JSON/YAML/TOML path operations where it simplifies the code rather than hiding format-specific details
- reconsider `yq-go` TOML round-trip only after confidence is high enough
- path filters still operate on string key segments only; array addressing is explicitly out of scope for now
