# Interfaces

## Home Manager module -> Runtime task file

The Home Manager module emits one aggregated task file in JSON.

Current target shape for the next iteration:

```json
{
  "version": 3,
  "entries": [
    {
      "entry_id": "<sha256(target)>",
      "target": ".config/example/config.toml",
      "format": "toml",
      "create": true,
      "mode": "0600",
      "state_root": "/home/user/.local/state/mutable-file",
      "ownership": {
        "default_mode": "declared",
        "rules": [
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
          "layer_id": "<sha256(layer)>",
          "name": "defaults",
          "source_kind": "value",
          "source_payload": {
            "app": {
              "name": "demo"
            }
          },
          "from_path": [],
          "to_path": [],
          "required": true
        },
        {
          "layer_id": "<sha256(layer)>",
          "name": "db-secret",
          "source_kind": "path",
          "source_payload": "/run/secrets/db.toml",
          "from_path": ["database"],
          "to_path": ["credentials", "database"],
          "required": true
        }
      ]
    }
  ]
}
```

## Field meanings

- `version`: task-file schema version.
- `entries`: reconciliation work items.
- `entry_id`: stable identifier used for baseline state storage.
- `target`: target file path relative to `home.homeDirectory`.
- `format`: one of `toml`, `yaml`, or `json`.
- `create`: whether missing target files may be created.
- `mode`: mode to apply to newly written files.
- `state_root`: directory used by runtime state storage.
- `ownership`: recursive ownership policy for undeclared fields and local-only subtrees.
- `ownership.default_mode`: fallback recursive policy applied when no more specific rule matches.
- `ownership.rules`: path-specific ownership overrides.
- `ownership.rules[].path`: path segment list receiving the rule.
- `ownership.rules[].mode`: one of `declared`, `sealed`, or `local`.
- `layers`: ordered source layers assembled into the desired document.
- `layer_id`: stable identifier for a normalized layer.
- `name`: human-readable layer name.
- `source_kind`: one of `value`, `source`, or `path`.
- `source_payload`: desired content or source locator.
- `from_path`: path to copy from inside the layer source.
- `to_path`: path to merge into inside the assembled desired document.
- `required`: whether the runtime must fail if the layer file or `from_path` is missing.

Current path semantics:

- each path segment is a string key
- path traversal currently supports object/table keys only
- array indexes are not part of the contract yet
- root replacement is represented by `[]`

## Home Manager module contract

The Home Manager module guarantees:

- each target is relative to `home.homeDirectory`
- each file defines at least one layer
- each layer sets exactly one of `value`, `source`, or `path`
- runtime `path` inputs are absolute
- ownership rules use valid recursive modes
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
- semantic conflict detection against baseline state and managed-field takeovers
- no platform-specific behavior in core reconciliation logic
- format adaptation through subprocess boundaries rather than ambient shell snippets

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

The runtime treats all rejected overlap as configuration errors, not runtime conflicts.

## Ownership policy contract

Ownership determines how fields not declared by layers are treated.

- `declared`: only fields declared by layers are managed. Undeclared fields are ignored and may change locally.
- `sealed`: only fields declared by layers are managed. Undeclared fields under this subtree are conflicts.
- `local`: the subtree is runtime-transparent. Layers may not write into it, and local changes are ignored.

Rules inherit recursively: a child path uses the most specific matching rule, otherwise `default_mode`.

## Deletion contract

There is no standalone unknown-field removal policy.

Fields are deleted only when:

- a field was previously managed and no longer exists in the merged desired document
- a managed subtree changes shape and previously managed descendants disappear as a result

Fields that were never declared by layers are either ignored, treated as conflicts, or left fully local depending on ownership mode.

## Managed takeover contract

When layers begin declaring a field that already exists in the current local file:

- if the current value equals the desired value, takeover succeeds without conflict
- if the current value differs, takeover is a conflict

This avoids silently overwriting previously local state while still allowing convergence when values already match.

## Format adapter model

The runtime is structured around format adapters.

Current state:

- `json`: implemented for current-file loading, layer loading, rendering, and reconcile path
- `yaml`: implemented through packaged `yq-go` (`mikefarah/yq`) conversions to and from JSON
- `toml`: implemented through Python `tomlkit`

For YAML, the runtime renders the desired base document, patches only the managed paths on a temporary working copy via `yq-go -i`, and atomically writes the final result.

For TOML, the runtime parses the current file with `tomlkit`, computes canonical managed subtrees through plain Python values, and patches only the managed TOML paths back into the original document before writing.
