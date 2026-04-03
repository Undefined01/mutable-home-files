# Interfaces

## Frontend -> Backend task file

The frontend emits one aggregated task file in JSON.

Current shape:

```json
{
  "version": 1,
  "entries": [
    {
      "entry_id": "<sha256(target)>",
      "target": ".config/example/config.toml",
      "format": "toml",
      "create": true,
      "mode": "0600",
      "state_root": "/home/user/.local/state/mutable-file",
      "desired_source_kind": "value",
      "desired_source_payload": {
        "app": {
          "name": "demo"
        }
      },
      "filter_mode": "includes",
      "filter_paths": [["app"]]
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
- `state_root`: directory used by backend baseline storage.
- `desired_source_kind`: one of `value`, `source`, or `path`.
- `desired_source_payload`: desired content or source locator.
- `filter_mode`: one of `includes` or `excludes`.
- `filter_paths`: list of managed path segment lists.

Current path semantics:

- each path segment is a string key
- path traversal currently supports object/table keys only
- array indexes are not part of the contract yet

## Frontend contract

The frontend guarantees:

- exactly one desired source is set
- exactly one filter mode is set
- `target` is relative
- runtime `path` inputs are absolute
- task files are generated at activation time from declarative options
- the activation hook invokes a packaged backend executable through `home.mutableFileBackend.package`

The frontend exposes two integration modes:

- import `homeManagerModules.default` from this flake to use the flake-provided backend package automatically
- import `frontend/modules/mutable-file` directly and override `home.mutableFileBackend.package` explicitly

## Backend contract

The backend guarantees:

- schema version checking before execution
- deterministic managed-subtree extraction
- semantic conflict detection against baseline state
- no platform-specific behavior in core reconciliation logic
- format adaptation through subprocess boundaries rather than ambient shell snippets
- exact managed-path replacement semantics for both `includes` and `excludes`

## Format adapter model

The backend is structured around format adapters.

Current state:

- `json`: implemented for current-file loading, desired loading, rendering, and reconcile path
- `yaml`: implemented through packaged `yq-go` (`mikefarah/yq`) conversions to and from JSON
- `toml`: implemented through Python `tomlkit`

For YAML, the backend renders the desired base document, patches only the selected paths on a temporary working copy via `yq-go -i`, and atomically writes the final result.

For TOML, the backend parses the current file with `tomlkit`, computes canonical managed subtrees through plain Python values, and patches only the selected TOML paths back into the original document before writing.

Managed-path semantics are exact subtree semantics:

- `includes`: selected paths in the target must match the desired document exactly, including removal of stale keys under managed subtrees
- `excludes`: selected paths are preserved from the current target exactly, while the rest of the document is reconciled to the desired state

## Desired source model

Current state:

- `value`: implemented for JSON
- `source`: implemented for JSON, YAML, and TOML through adapters
- `path`: implemented for JSON, YAML, and TOML through adapters

For YAML, source loading is delegated to packaged `yq-go` (`mikefarah/yq`). For TOML, source loading is delegated to Python `tomlkit`.
