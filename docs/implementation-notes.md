# Implementation Notes

## Why the next change exists

The previous `layers + preserve` model was too coarse.

Problems with the old design:

- layer overlap was silently resolved by write order
- undeclared local fields were treated as managed unless they were manually listed in `preserve`
- there was no way to distinguish "ignore unknown fields" from "reject unknown fields"
- managed takeover of previously local fields was not explicit
- deletion semantics were too tied to whole-file replacement instead of managed ownership

The next iteration fixes those concerns by separating three responsibilities:

1. layer merge builds a single desired object and rejects ambiguous overlap
2. ownership decides how undeclared fields behave recursively
3. state tracks previously managed fields so deletion and takeover semantics are explicit

## Home Manager module / Runtime boundary

Current boundary remains intentionally narrow:

- the Home Manager module emits a single aggregated JSON task file
- the Home Manager module invokes one runtime executable at switch time
- the runtime owns all source loading, layer merge validation, ownership-aware comparison, and target writes

The module does not parse target files and does not shell out to `yq` directly.

## Home Manager module implementation model

- Module entry point: `modules/home-manager/mutable-file/default.nix`
- Switch-time execution path: `home.activation.mutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ...`
- Runtime selection option: `home.mutableFileRuntime.package`
- Flake default module wiring: `flake.nix` injects `self.packages.<system>.mutable-file-runtime`

The activation block stays in the current Home Manager style:

- it runs after `writeBoundary`
- it uses `verboseEcho` for optional logging
- it uses `run --silence ...` so `DRY_RUN` and activation-driver behavior remain consistent

Supported consumption paths remain:

1. import the flake's `homeManagerModules.default`
2. import the raw module and override `home.mutableFileRuntime.package`

## Runtime implementation model

- Runtime entry point: `runtime/src/mutable_file_runtime/main.py`
- Core reconcile logic: `runtime/src/mutable_file_runtime/core.py`
- State layout: `${state_root}/${entry_id}/state.json`

The runtime should now be thought of as three stages:

1. `assemble`: load layers and merge them into one desired tree with overlap validation
2. `compare`: evaluate the current file against the desired tree plus ownership rules
3. `apply`: write managed changes while preserving unmanaged comments where adapters permit

## Layer merge model

Each runtime entry is assembled from ordered layers, but order is only relevant for visiting sources. It no longer decides how conflicts resolve.

For each layer, the runtime:

- loads the layer source according to `source_kind`
- extracts the subtree at `from_path`
- merges that subtree into the desired document at `to_path`
- records the layer as the owner for newly declared paths

Overlap rules:

- object/object overlap is recursively merged
- any overlap involving scalar or array values is rejected
- identical scalar or array writes from multiple layers are still rejected because ownership is ambiguous

## Ownership model

Ownership replaces `preserve`.

Modes:

- `declared`: undeclared fields are ignored and may evolve locally
- `sealed`: undeclared fields are conflicts
- `local`: the subtree is entirely local and may not be targeted by layers

Ownership is recursive. The effective mode for a path is the most specific matching rule, otherwise `default_mode`.

This lets the schema express three distinct concerns cleanly:

- what layers declare
- where local application state may exist
- where undeclared fields are considered invalid

## Managed takeover model

When a field moves from locally-owned to layer-managed, the runtime compares the current local value to the newly declared desired value.

- equal values mean takeover without conflict
- differing values mean conflict

This keeps switch-time behavior safe for secret rollout and for gradual migration of previously mutable config into declarative management.

## Deletion model

Deletion is driven only by managed ownership.

The runtime deletes paths when:

- they were previously managed and are no longer declared
- they were previously managed and a managed ancestor changed shape so that the old descendants disappeared

The runtime does not delete fields that were never declared by layers.

## State model

The old baseline-only model is insufficient for the new semantics. The runtime now needs one state file per entry that records at least:

- the previous managed desired tree
- the previous managed path set or manifest
- the ownership configuration used for the last successful apply

This state is needed to distinguish:

- new takeover from ordinary managed updates
- managed deletion from never-managed unknown fields
- ownership-policy changes from user edits

## Format adapter status

- JSON: pure Python stdlib
- YAML: adapted via packaged `yq-go` (`mikefarah/yq`)
- TOML: adapted directly in Python with `tomlkit`

For YAML, the runtime converts target and source content through `yq-go` (`mikefarah/yq`) at the edges and then reuses the in-memory object comparison pipeline.

For YAML updates against existing files, the runtime applies managed-path mutations on a temporary working copy and only then atomically replaces the live target.

For TOML, the runtime parses the current document with `tomlkit`, uses `.unwrap()` for canonical comparison, and applies managed-path mutations back onto the original TOML document so unmanaged comments and layout survive.

## Minimum viable iteration

The minimum viable semantics for this round are:

- ownership rules with `declared`, `sealed`, and `local`
- layer overlap validation for object/scalar/array incompatibility
- managed takeover detection
- deletion only for previously managed fields
- state tracking in a single `state.json`

Deferred:

- array-addressing paths
- richer merge strategies for arrays
- history/commit graph storage
- ownership-aware partial patch minimization beyond current adapter behavior
