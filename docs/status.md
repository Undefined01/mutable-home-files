# Status

## Current implementation status

### Home Manager module

Implemented:

- `home.mutableFiles` option skeleton
- `home.mutableFileRuntime.package` for explicit runtime package injection
- option validation for layered `value`/`source`/`path` exclusivity
- aggregated JSON task-file generation for schema version `2`
- ordered `layers` support with `from` -> `to` mappings
- switch-time activation hook through `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`
- activation block aligned with current Home Manager conventions through `verboseEcho` and `run --silence`
- flake-level default Home Manager module wiring that injects the packaged runtime automatically
- Home Manager eval tests for normalized task payloads, defaults, ordering, flake-module wiring, activation-block generation, and assertion failures
- flake test registration deduplicated so `test-*` outputs, `checks`, and `nix run .#tests` are derived from the same named test set

In progress for the next iteration:

- replace `preserve` with recursive `ownership`
- emit schema version `3`
- validate ownership rules and incompatible layer targets earlier

Not implemented yet:

- optional persistent Linux/Darwin integrations

### Runtime

Implemented:

- task-file loading for schema version `2`
- ordered layer loading
- baseline conflict predicate
- direct CLI task-file loading path
- JSON layer loading for all current source kinds
- YAML layer/current document loading through packaged `yq-go`
- YAML existing-file reconciliation on a temporary working copy before atomic replacement
- YAML comment-preserving reconciliation for preserved subtrees
- TOML layer/current document loading through Python `tomlkit`
- TOML patch-based writeback that preserves unmanaged comments and formatting for preserved-path updates
- runtime Nix package wrapper that pins the `yq-go` runtime path
- package-level `passthru.tests.pytest` following the nixpkgs package-test model

In progress for the next iteration:

- overlap-validated layer merge
- ownership-aware compare/apply with `declared`, `sealed`, and `local`
- managed takeover detection
- deletion driven only by previously managed fields
- state tracking in a unified `state.json`

Not implemented yet:

- array path semantics
- richer merge strategies for arrays
- history/commit graph storage

Environment note:

- local shell environment still may not have the correct `yq` implementation on `PATH`, but the packaged runtime provides pinned `yq-go` semantics through its wrapper
- local system Python still may not have YAML or TOML helper libraries installed, but the Nix package and dev shell provide `tomlkit`

## Verification targets

- `nix build path:.#checks.aarch64-darwin.runtime-pytest`
- `nix build path:.#checks.aarch64-darwin.home-manager-eval`
- `nix build path:.#mutable-file-runtime.tests.pytest`
- `nix build path:.#mutable-file-runtime`
- `nix build path:.#test-runtime-pytest`
- `nix build path:.#test-home-manager-eval`
- `nix build path:.#test-all`
- `nix run path:.#tests -- --list`
- `nix-instantiate --parse modules/home-manager/mutable-file/default.nix`
- `nix-instantiate --parse flake.nix`

## Next step

1. switch task payloads to schema version `3`
2. implement overlap validation and recursive ownership in runtime
3. add tests for takeover, undeclared-field handling, and incompatible layer overlap
