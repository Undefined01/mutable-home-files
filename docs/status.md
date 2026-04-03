# Status

## Current implementation status

### Frontend

Implemented:

- `home.mutableFile` option skeleton
- `home.mutableFileBackend.package` for explicit backend package injection
- option validation for source/filter exclusivity
- aggregated JSON task-file generation
- switch-time activation hook through `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`
- activation block aligned with current Home Manager conventions through `verboseEcho` and `run --silence`
- flake-level default Home Manager module wiring that injects the packaged backend automatically
- frontend eval tests for normalized task payloads, defaults, ordering, flake-module wiring, activation-block generation, and assertion failures
- frontend eval tests imported directly during flake evaluation, with a tiny derivation used only as the pass/fail carrier
- flake test registration deduplicated so `test-*` outputs, `checks`, and `nix run .#tests` are derived from the same named test set

Not implemented yet:

- per-entry task files if needed
- richer task-file metadata
- optional persistent Linux/Darwin integrations

### Backend

Implemented:

- task-file loading
- managed-subtree extraction for `includes` and `excludes`
- baseline conflict predicate
- direct CLI task-file loading path
- first real JSON reconcile path for `desired_source_kind = value`
- JSON desired source loading for all current source kinds
- YAML desired/current document loading through packaged `yq-go`
- YAML path-based writeback through packaged `yq-go`
- YAML existing-file reconciliation on a temporary working copy before atomic replacement
- YAML comment-preserving `excludes` reconciliation for preserved subtrees
- YAML repeated-reconcile stability when semantic content is already converged
- TOML desired/current document loading through Python `tomlkit`
- TOML patch-based writeback that preserves unmanaged comments and formatting for selected-path updates
- TOML comment-preserving `excludes` reconciliation for preserved subtrees
- exact subtree replacement semantics for managed paths in JSON, YAML, and TOML merges
- repeated-reconcile stability checks for JSON, YAML, and TOML
- backend Nix package wrapper that pins the `yq-go` runtime path
- package-level `passthru.tests.pytest` following the nixpkgs package-test model
  - `value`
  - `source`
  - `path`
  - load current JSON/YAML/TOML target through adapters
  - merge managed subtree
  - detect conflict from baseline
  - atomically write target
  - persist baseline state
- pytest-based backend tests for current pure logic and reconcile behavior

Not implemented yet:

- further reduction of TOML patcher helper duplication

Environment note:

- local shell environment still may not have the correct `yq` implementation on `PATH`, but the packaged backend now provides pinned `yq-go` semantics through its wrapper
- local system Python still may not have YAML or TOML helper libraries installed, but the Nix package and dev shell now provide `tomlkit`

## Verified locally

- `nix develop path:. -c pytest backend/tests/test_core.py -q`
- `nix build path:.#checks.aarch64-darwin.backend-pytest`
- `nix build path:.#mutable-file-backend.tests.pytest`
- `nix build path:.#mutable-file-backend`
- `nix build path:.#checks.aarch64-darwin.frontend-eval`
- `nix build path:.#test-backend-pytest`
- `nix build path:.#test-frontend-eval`
- `nix build path:.#test-all`
- `nix run path:.#tests -- --list`
- `nix run path:.#tests -- test-frontend-eval`
- `nix-instantiate --parse frontend/modules/mutable-file/default.nix`
- `nix-instantiate --parse flake.nix`
- direct CLI execution from source tree against a temporary task file

Current backend test count: `31` pytest cases passing locally.

## Next step

Next step:

1. decide whether to expose a more Home Manager-native frontend test entry in flake outputs beyond the current lightweight eval check
2. add more real-tool regression cases for deletion-heavy nested structures and mixed include/exclude fixture families
3. revisit array path semantics only if a concrete consumer needs them
