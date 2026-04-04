# Interfaces

## Home Manager module -> Runtime task file

The Home Manager module emits one aggregated JSON task file.

Current schema:

```json
{
  "version": 4,
  "documents": [
    {
      "id": "<sha256(target)>",
      "target": ".config/example/config.toml",
      "format": "toml",
      "create": true,
      "mode": "0600",
      "state_dir": "/home/user/.local/state/mutable-file",
      "ownership": {
        "fallback": "declared",
        "overrides": [
          {
            "path": ["runtimeState"],
            "mode": "local"
          },
          {
            "path": ["credentials"],
            "mode": "sealed"
          }
        ]
      },
      "layers": [
        {
          "id": "<sha256(layer)>",
          "name": "defaults",
          "source": {
            "kind": "inline",
            "value": {
              "app": {
                "name": "demo"
              }
            }
          },
          "from": [],
          "to": [],
          "required": true
        },
        {
          "id": "<sha256(layer)>",
          "name": "db-secret",
          "source": {
            "kind": "runtime_path",
            "path": "/run/secrets/db.toml"
          },
          "from": ["database"],
          "to": ["credentials", "database"],
          "required": true
        }
      ]
    }
  ]
}
```

## Field meanings

- `version`: task-file schema version.
- `documents`: reconciliation work items.
- `id`: stable identifier used for state storage.
- `target`: target file path relative to `home.homeDirectory`.
- `format`: one of `toml`, `yaml`, or `json`.
- `create`: whether missing target files may be created.
- `mode`: mode to apply to newly written files.
- `state_dir`: directory used by runtime state storage.
- `ownership`: recursive ownership policy.
- `ownership.fallback`: default recursive policy when no more specific override matches.
- `ownership.overrides`: path-specific ownership overrides.
- `ownership.overrides[].path`: path segment list receiving the override.
- `ownership.overrides[].mode`: one of `declared`, `sealed`, or `local`.
- `layers`: ordered source layers assembled into the desired document.
- `layers[].id`: stable identifier for a normalized layer.
- `layers[].name`: human-readable layer name.
- `layers[].source.kind`: one of `inline`, `store_path`, or `runtime_path`.
- `layers[].source.value`: inline document for `inline` sources.
- `layers[].source.path`: file path for `store_path` and `runtime_path` sources.
- `layers[].from`: path to copy from inside the layer source.
- `layers[].to`: path to merge into inside the assembled desired document.
- `layers[].required`: whether the runtime must fail if the layer file or `from` path is missing.

Current path semantics:

- task-file `from` / `to` paths currently use string object keys only
- root replacement is represented by `[]`
- internal runtime edit-operation paths may additionally use integer array indices

## Home Manager module contract

The Home Manager module guarantees:

- each target is relative to `home.homeDirectory`
- each file defines at least one layer
- each layer sets exactly one source kind
- runtime `runtime_path` inputs are absolute
- ownership overrides use valid recursive modes
- task files are generated at activation time from declarative options
- the activation hook invokes a packaged runtime executable through `home.mutableFileRuntime.package`

The module exposes two integration modes:

- import `homeManagerModules.default` from this flake to use the flake-provided runtime package automatically
- import `modules/home-manager/mutable-file` directly and override `home.mutableFileRuntime.package` explicitly

## Runtime contract

The runtime guarantees:

- schema version checking before execution
- deterministic layer assembly for a fixed task file
- overlap validation before any local-file comparison or writes
- local-history-aware conflict detection using previous state snapshots
- write planning from `desired_diff` rather than whole-file replacement
- format adaptation behind explicit implementations rather than shell snippets in the core merge logic

## Layer merge contract

Layers are merged into a single desired document before any comparison against the current target.

Allowed overlap:

- `object` with `object` at the same path, merged recursively

Rejected overlap:

- `scalar` with any existing value
- `array` with any existing value
- `object` with existing `scalar`
- `object` with existing `array`
- identical scalar or array writes from different layers

Rejected overlap is a configuration error, not a local-file conflict.

## Ownership policy contract

Ownership determines how undeclared fields and local-only subtrees are handled.

- `declared`: fields declared by layers are managed. Undeclared fields are ignored and may change locally.
- `sealed`: fields declared by layers are managed. Undeclared fields under this subtree are conflicts.
- `local`: the subtree is runtime-transparent. Layers may not write into it, and local changes are ignored.

Rules inherit recursively: a child path uses the most specific matching override, otherwise `fallback`.

## State contract

The runtime stores one state snapshot per document.

Current state shape:

```json
{
  "version": 1,
  "document_id": "<sha256(target)>",
  "format": "toml",
  "ownership": {
    "fallback": "declared",
    "overrides": []
  },
  "previous_applied": {
    "app": { "name": "demo" }
  },
  "previous_desired": {
    "app": { "name": "demo" }
  }
}
```

The runtime treats missing or incompatible state as if no previous state existed.

## Operation contract

The semantic diff layer produces ordered operations.

Current operation kinds:

- `set(path, value)`
- `remove(path)`
- `insert(path, value)`

Semantics:

- `set` creates or replaces an object field or existing array element
- `remove` removes an object field or array element
- `insert` inserts an array element before the given index

Operation order matters. In particular, array edits must be applied in the order produced by the diff planner.

## Reconcile contract

For each document the runtime:

1. assembles `current_desired` from all layers
2. loads `current_local` from the target file
3. loads `previous_applied` and `previous_desired` from state if present
4. computes `local_diff` and `desired_diff`
5. detects ownership-aware conflicts from local changes and takeovers
6. plans writes only for paths touched by `desired_diff`
7. applies those operations through the selected format implementation
8. re-loads the rendered text and verifies its semantic value
9. atomically writes the target and persists the new snapshot
