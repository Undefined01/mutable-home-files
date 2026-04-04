# Architecture

## Split responsibilities

### Home Manager module

The Home Manager side is pure Nix.

Responsibilities:

- define `home.mutableFiles`
- define `home.mutableFileRuntime.package`
- validate target, ownership, and layer options
- normalize file definitions into runtime task files
- register switch-time activation hooks via `home.activation`
- optionally attach Linux and Darwin specific persistent integration points later, without replacing activation
- invoke the packaged runtime binary exported by the flake or explicitly injected by callers

### Runtime

The runtime is a Python CLI with a semantic core and format-specific implementations.

Responsibilities:

- decode task files emitted by the Home Manager module
- load ordered layers from declarative values, store paths, and runtime paths
- assemble layers into one desired object while rejecting ambiguous overlap
- load current local documents and previous state snapshots
- compute local diffs and desired diffs independently
- plan writes from desired changes only
- detect ownership-aware conflicts before editing files
- apply edits through JSON, YAML, and TOML implementations
- verify semantic correctness after render
- atomically write targets and update runtime state

## Core design constraints

The system is designed around these constraints:

- layer overlap must be explicit and deterministic
- local edits and layer edits must be evaluated separately
- local state must not be silently taken over when a layer starts managing a path
- deletion must only target paths removed from previous desired state
- unchanged fields should not be rewritten just because they are managed
- YAML and TOML comments and key order should survive outside the edited write set whenever possible

## Semantic model

The runtime reasons about four semantic documents:

- `previous_applied`
- `previous_desired`
- `current_local`
- `current_desired`

Those produce two diffs:

- `local_diff = diff(previous_applied, current_local)`
- `desired_diff = diff(previous_desired, current_desired)`

This split is the key architectural change. It separates:

- what changed locally
- what changed declaratively
- what the runtime is allowed to write in this run

## Ownership model

The runtime applies one recursive ownership mode at each path.

- `declared`: only layer-declared fields are managed; undeclared fields are ignored
- `sealed`: only layer-declared fields are managed; undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

The effective mode is resolved by longest matching override, falling back to the file's `fallback` mode.

## Layer assembly model

The runtime first builds a single desired object from all layers.

Allowed merge:

- object with object, merged recursively

Rejected merge:

- scalar with scalar
- scalar with object
- scalar with array
- array with array
- array with object
- array with scalar

Rejected overlap is a configuration error, not a local-file conflict.

## Operation model

The runtime core does not patch text directly. It emits ordered semantic edit operations:

- `set`
- `remove`
- `insert`

Object changes are represented with `set` and `remove`.
Array changes additionally use `insert` so the runtime can modify only changed regions instead of rewriting whole arrays.

## Format implementation model

Each format implementation provides the same interface:

- load semantic document from file or text
- create text for a brand-new file
- apply ordered operations to existing text

Implementations:

- JSON: ordered-object editing and deterministic dump
- YAML: `ruamel.yaml` round-trip editing
- TOML: `tomlkit` round-trip editing

The format implementation is also responsible for preserving untouched ordering, comments, and layout as far as its underlying library allows.

## State model

The runtime keeps one state snapshot per target document.

That snapshot records:

- the full local semantic document after the last successful apply
- the full desired semantic document used for that apply
- the ownership policy used for that apply

Old or incompatible state is discarded instead of migrated.

## Packaging model

- `runtime/package.nix` builds the Python CLI as the `mutable-file-runtime` executable.
- The runtime depends on `tomlkit` and `ruamel.yaml`.
- `runtime/package.nix` exposes package-level `passthru.tests.pytest` so runtime verification remains buildable without changing the main package output.
- `flake.nix` exports the runtime as both `packages.<system>.mutable-file-runtime` and `packages.<system>.default`.
- `flake.nix` also exports `apps.<system>.mutable-file-runtime`, a default `devShell`, and lightweight flake checks for Home Manager evaluation plus runtime package tests.

## Testing model

- Runtime tests are organized by semantic phase: schema, assembly, diff, merge, format implementations, and end-to-end reconcile.
- Home Manager module tests remain lightweight evaluation tests that assert on generated payloads and activation hooks.
- Verification must cover both semantic correctness and round-trip preservation for YAML/TOML comments and ordering.

## Home Manager integration notes

### Generic activation

The primary switch-time integration point remains:

```nix
home.activation.mutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
  verboseEcho "Reconciling mutable files"
  run --silence ${lib.getExe runtime} --task-file ${taskFile}
'';
```

This remains the canonical location for side-effecting runtime actions.

### Linux

Linux-specific persistent integration, if needed later, uses `systemd.user.services`.

### Darwin

Darwin-specific persistent integration, if needed later, uses `launchd.agents`.
