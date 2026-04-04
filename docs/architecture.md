# Architecture

## Split responsibilities

### Home Manager module

The Home Manager side is pure Nix.

Responsibilities:

- define `home.mutableFiles`
- define `home.mutableFileRuntime.package`
- define recursive ownership policy inputs
- validate target, ownership, and layer options
- normalize file definitions into runtime task files
- register switch-time activation hooks via `home.activation`
- optionally attach Linux and Darwin specific persistent integration points later, without replacing activation
- invoke the packaged runtime binary exported by the flake or explicitly injected by callers

### Runtime

The runtime is a Python CLI.

Responsibilities:

- load task files emitted by the Home Manager module
- load ordered layers from declarative values, store paths, and runtime paths
- merge layers into one desired object while rejecting ambiguous overlap
- evaluate local files through recursive ownership policy
- compare managed state against recorded runtime state
- reconcile managed content into target files while preserving unmanaged TOML and YAML content where the adapter model allows it
- atomically write targets and update runtime state

## Core design constraints

The system is designed around these constraints:

- layer overlap must be explicit and deterministic
- undeclared fields need different handling in different subtrees
- local state must not be silently taken over when a layer starts managing a path
- deletion must only target paths that were previously managed
- YAML and TOML comments should survive outside the managed write set whenever possible

## Ownership model

The runtime applies one recursive ownership mode at each path.

- `declared`: only layer-declared fields are managed; undeclared fields are ignored
- `sealed`: only layer-declared fields are managed; undeclared fields are conflicts
- `local`: the subtree is entirely local and runtime-transparent

The effective mode is resolved by longest matching rule, falling back to the file's default ownership mode.

## Layer merge model

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

## State model

The runtime keeps one state record per target entry.

That state must be rich enough to answer:

- which paths were previously managed
- what values those paths last converged to
- which ownership policy was active during the last successful apply

Without that information, the runtime cannot distinguish managed deletion from never-managed unknown fields or safe takeover from destructive overwrite.

## Packaging model

- `runtime/package.nix` builds the Python CLI as the `mutable-file-runtime` executable.
- The wrapper sets `MUTABLE_FILE_YQ_BIN` to the packaged `yq-go` binary, so runtime format adaptation does not depend on ambient `PATH` state.
- `runtime/package.nix` also exports package-level `passthru.tests.pytest`, following the nixpkgs pattern of keeping package tests buildable without changing the main output.
- `flake.nix` exports the runtime as both `packages.<system>.mutable-file-runtime` and `packages.<system>.default`.
- `flake.nix` also exports `apps.<system>.mutable-file-runtime` for direct execution, a default `devShell` with `python3`, `pytest`, `yq-go`, and `nixfmt-tree`, and lightweight flake checks for Home Manager evaluation plus runtime package tests.

## Testing model

- Runtime package tests follow the nixpkgs `passthru.tests` style: the package exposes a separate pytest derivation so package verification is buildable without changing the main package output.
- Home Manager module tests stay in the lightweight evaluation lane: they assert on generated task payloads and activation blocks rather than booting a VM.
- Full NixOS-style VM integration tests are still deferred because the current module primarily generates user configuration and switch-time tasks rather than long-running services.

## Home Manager integration notes

### Generic activation

The primary switch-time integration point is:

```nix
home.activation.mutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
  verboseEcho "Reconciling mutable files"
  run --silence ${lib.getExe runtime} --task-file ${taskFile}
'';
```

This is the canonical location for side-effecting runtime actions. The block should respect Home Manager's activation driver semantics by using helpers such as `run`, `verboseEcho`, and the `writeBoundary` ordering constraint.

### Linux

Linux-specific persistent integration, if needed in the future, uses `systemd.user.services`.

### Darwin

Darwin-specific persistent integration, if needed in the future, uses `launchd.agents`.

Home Manager manages launch agents through activation logic in its launchd module, so Darwin-specific behavior must not assume Linux-style `systemd` semantics.
