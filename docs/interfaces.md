# Interfaces

## Home Manager module -> Runtime task file

The Home Manager module emits one aggregated JSON task file.

Current schema:

```json
{
  "version": 5,
  "documents": [
    {
      "target": "/home/user/.config/example/config.toml",
      "format": "toml",
      "create": true,
      "mode": "0600",
      "state_dir": "/home/user/.local/state/mutable-file",
      "ownership": {
        "default": "declared",
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
- `target`: absolute target file path.
- `format`: one of `toml`, `yaml`, or `json`.
- `create`: whether missing target files may be created.
- `mode`: mode to apply to newly written files.
- `state_dir`: directory used by runtime state storage.
- `ownership`: recursive ownership policy.
- `ownership.default`: default recursive policy when no more specific rule matches.
- `ownership.rules`: path-specific ownership rules.
- `ownership.rules[].path`: path segment list receiving the rule.
- `ownership.rules[].mode`: one of `declared`, `sealed`, or `local`.
- `layers`: ordered source layers assembled into the desired document.
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

- each enabled entry normalizes to one absolute target path
- each entry defines exactly one source form: `value`, `source`, or `layers`
- top-level `value` and `source` normalize to a single default layer
- each normalized layer defines exactly one source kind
- runtime `runtime_path` inputs are absolute
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
- git-backed state storage in one bare repository per `state_dir`
- raw local history in `live` and managed declarative history in `applied`
- conflict-session branches `desired`, `local`, and `resolve`
- a fixed resolve worktree that persists across retries until completion or abort
- format adaptation behind explicit implementations rather than shell snippets in the core merge logic

## Runtime state contract

The runtime repository keeps these persistent branches:

- `live`
- `applied`

And these conflict-session branches when needed:

- `desired`
- `local`
- `resolve`

Tree layout rules:

- target files are mapped by removing the leading slash from the absolute target path
- `.mutable-file/task.json` is reserved for the task snapshot stored in `applied`

Representation rules:

- `live` stores raw target text exactly as written to disk
- `applied` stores prettified managed-view text in the file's declared format
- Git blobs are always parsed back through format implementations before semantic comparison

Missing or incompatible old JSON snapshot files are ignored.

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
- `sealed`: the whole subtree participates in the managed view. Undeclared fields under this subtree are conflicts.
- `local`: the subtree is runtime-transparent. Layers may not write into it, and local changes are ignored.

Rules inherit recursively: a child path uses the most specific matching rule, otherwise `default`.

## Conflict-session contract

When local changes conflict with the current declarative managed view, the runtime:

1. leaves `live` and `applied` unchanged
2. writes the current desired managed view into `desired`
3. writes the current local applied view into `local`
4. checks out `resolve` in the fixed resolve worktree
5. starts a Git merge so the user can inspect and resolve it manually

Later runs obey this rule:

- if `resolve` is still an in-progress merge, the runtime refuses to continue until the user finishes or aborts it
- if `resolve` already has a merge commit, the runtime reuses that merge result instead of recomputing the local conflict basis

A pending resolution is accepted only when:

- `resolve` still matches the current task-derived managed view
- the current local applied projection still matches the stored `local` branch

Pending-resolution apply is driven by `diff(local, resolve)`, which allows manual deletions, including sealed-field cleanup, to affect the real target file even when the task-derived managed view did not change.

## Reconcile contract

The runtime reconciles one `state_dir` group at a time.
For each group it:

1. assembles each document's desired object from layers
2. projects each desired object into its managed view
3. loads each current local file from the absolute target path
4. loads previous `live` / `applied` history from the state repository
5. detects ownership-aware conflicts from local changes and takeovers
6. either starts or resumes a conflict session, or computes write operations for every document in the group
7. applies those operations through the selected format implementation
8. re-loads rendered text and verifies its semantic value
9. atomically updates all target files in the group and then advances `live` / `applied`

## Edge cases

The current interface and runtime semantics intentionally define these edge cases:

- first apply with no Git state but an existing target uses takeover semantics and does not delete undeclared fields
- a missing target with existing `live` history is treated as a conflict rather than silently recreating the file
- ownership changes to `local` stop management of that subtree without deleting local content
- `sealed` rejects undeclared fields even if they predate the current run
- layer `from` / `to` paths do not yet expose array addressing even though runtime edit operations do
- targets removed from the current task file are removed from Git state on the next successful run but are not deleted locally
- old task files and old JSON snapshots are ignored rather than migrated
