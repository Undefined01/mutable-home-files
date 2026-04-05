# Status

## Current implementation status

### Home Manager module

Implemented:

- `home.mutableFile` option surface for layered mutable-file definitions
- `home.mutableFileRuntime.package` for explicit runtime package injection
- top-level `value` and `source` shortcuts that normalize to a single default layer
- option validation for file-level `value` / `source` / `layers` exclusivity
- normalized absolute target generation with target defaulting to the attribute name
- aggregated JSON task-file generation for schema version `5`
- task payload shape with `documents`, nested `source`, absolute `target`, and ownership `default` / `rules`
- ordered `layers` support with `from` -> `to` mappings
- switch-time activation hook through `home.activation = lib.hm.dag.entryAfter [ "writeBoundary" ]`
- activation block aligned with current Home Manager conventions through `verboseEcho` and `run --silence`
- flake-level default Home Manager module wiring that injects the packaged runtime automatically
- Home Manager eval tests for normalized task payloads, defaults, ordering, flake-module wiring, activation-block generation, and assertion failures
- flake test registration deduplicated so `test-*` outputs, `checks`, and `nix run .#tests` are derived from the same named test set

Not implemented yet:

- optional persistent Linux or Darwin integrations
- array-addressing support in declarative `from` / `to` paths

### Runtime

Implemented:

- task-file loading for schema version `5`
- interface-oriented runtime split across schema, assembly, diff, merge, projection, reconcile, and format implementations
- ordered layer loading from `inline`, `store_path`, and `runtime_path` sources
- overlap-validated layer assembly before any local comparison
- absolute-target reconciliation without `--home-directory`
- git-backed runtime state in one bare repository per `state_dir`
- persistent `live` and `applied` branches
- raw target text history in `live`
- prettified managed-view history in `applied`
- `.mutable-file/task.json` snapshots in `applied`
- ownership-aware projections for desired and local applied views
- ownership-aware merge planning with `declared`, `sealed`, and `local`
- takeover detection for newly managed fields
- ordered semantic operations: `set`, `remove`, and `insert`
- JSON format implementation for semantic load and operation-based rewrite
- YAML format implementation through `ruamel.yaml` round-trip editing
- TOML format implementation through `tomlkit` round-trip editing
- semantic verification after render before atomic write
- fixed conflict-session branches: `desired`, `local`, and `resolve`
- fixed resolve worktree under the runtime state directory
- reuse of an existing `resolve` merge commit on later runs
- pending-resolution apply driven by `diff(local, resolve)` so sealed-field cleanup can take effect
- repo-level reconciliation per `state_dir` so one run can update multiple targets atomically
- runtime Nix package and package-level `passthru.tests.pytest`
- runtime unit coverage for schema, assembly, diff, merge, git-backed state, format implementations, conflict sessions, and end-to-end reconcile

Not implemented yet:

- multiple simultaneous conflict sessions in one state repository
- old JSON snapshot migration into the Git state repository
- richer locking than the current single-process assumption
- declarative array path support in layer projection
- advanced merge strategies beyond strict object/object layer overlap

Environment note:

- the dev shell and packaged runtime provide `git`, `ruamel.yaml`, and `tomlkit`
- old runtime JSON snapshots are ignored rather than migrated

## Verification targets

- `nix develop path:. -c python -m pytest runtime/tests -q`
- `nix build path:.#test-runtime-pytest`
- `nix build path:.#test-home-manager-eval`
- `nix build path:.#test-all`
- `nix run path:.#tests -- --list`
- `nix run path:.#tests`

## Next step

1. harden locking around the shared state repository and resolve worktree lifecycle
2. decide whether array-addressing should be exposed in Home Manager `from` / `to`
3. refine conflict-session UX and diagnostics around abort/resume flows
