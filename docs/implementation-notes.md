# Implementation Notes

## Why the current rewrite exists

The previous runtime model still had two structural limitations even after the ownership redesign:

- it compared `current_local` directly against `current_desired`
- it let the same function own task-file decoding, semantic comparison, and text patching

That model cannot cleanly answer the new questions:

- which fields changed locally since the last successful apply?
- which fields changed in layers since the last successful apply?
- which fields should be touched in this run, and which should be left byte-for-byte alone?

## New runtime boundary

The Home Manager module still does only two things:

- validate declarative inputs
- emit an aggregated JSON task file and invoke the runtime

The runtime now owns all of the following:

- task-file decoding
- state loading
- layer loading and assembly
- semantic diff generation
- ownership-aware conflict detection
- ordered write planning
- format-specific round-trip editing

## New state model

The state file is now a semantic snapshot, not a managed-path manifest.

It stores:

- `previous_applied`
- `previous_desired`
- `ownership`

This is enough to derive managed history when needed and keeps the merge logic centered on semantic documents instead of special-case path bookkeeping.

## New reconcile model

The runtime pipeline is now:

1. `decode`: load and validate the v4 task file
2. `assemble`: load layers and build `current_desired`
3. `load`: read `current_local` and prior state snapshot
4. `diff`: compute `local_diff` and `desired_diff`
5. `merge`: reject ownership conflicts and plan write operations from `desired_diff`
6. `edit`: apply ordered operations through a format implementation
7. `verify`: reload rendered text and compare to expected semantic output
8. `persist`: atomically write target and store the new snapshot

## Why write planning uses desired diff only

The runtime should not rewrite managed fields simply because they are managed. It should rewrite fields only when the declarative input changed in this run.

That means:

- local edits to managed fields become conflicts instead of silent overwrite
- unchanged managed fields remain untouched on disk
- deletions only happen when the desired state actually removed a path relative to `previous_desired`

## Operation design

The runtime uses three ordered operation kinds:

- `set`
- `remove`
- `insert`

`insert` is required because arrays need positional edits. Using only `set` and `remove` would force whole-array replacement for many common edits and would destroy unrelated ordering and comments around the array.

## Format implementation notes

### JSON

JSON does not need round-trip comment preservation, but it still needs stable field order.
The JSON implementation therefore preserves existing object key order and applies insertions at deliberate positions when possible.

### YAML

YAML now switches to `ruamel.yaml` round-trip mode.
The previous `yq-go` adaptation was acceptable for object conversion but was not a good long-term fit for comment-preserving in-place editing.

### TOML

TOML continues to use `tomlkit`, but under a dedicated implementation instead of implicit patch helpers inside the semantic core.

## Simplifications taken deliberately

- no backward compatibility with previous task-file versions
- no migration of old state snapshots
- no array addressing in layer `from` / `to` paths yet
- no history graph storage in this iteration

These keep the rewrite focused on a clean semantic core and explicit format interfaces.
