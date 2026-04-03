# Architecture

## Split responsibilities

### Frontend

The frontend is pure Nix.

Responsibilities:

- define `home.mutableFile`
- define `home.mutableFileBackend.package`
- validate user options
- normalize entries into task files
- register switch-time activation hooks via `home.activation`
- optionally attach Linux and Darwin specific persistent integration points later, without replacing activation
- invoke the packaged backend binary exported by the flake or explicitly injected by callers

### Backend

The backend is a Python tool.

Responsibilities:

- load task files emitted by the frontend
- use packaged helper tools such as `yq-go` where Python stdlib is insufficient
- compute managed subtrees
- compare current state against baseline
- reconcile managed content into target files while preserving unmanaged TOML and YAML content where the adapter model allows it
- replace managed subtrees exactly rather than deep-merging stale keys back in
- atomically write targets and update baseline state

## Packaging model

- `backend/package.nix` builds the Python CLI as the `mutable-file-backend` executable.
- The wrapper sets `MUTABLE_FILE_YQ_BIN` to the packaged `yq-go` binary, so runtime format adaptation does not depend on ambient `PATH` state.
- `backend/package.nix` also exports package-level `passthru.tests.pytest`, following the nixpkgs pattern of keeping package tests buildable without changing the main output.
- `flake.nix` exports the backend as both `packages.<system>.mutable-file-backend` and `packages.<system>.default`.
- `flake.nix` also exports `apps.<system>.mutable-file-backend` for direct execution, a default `devShell` with `python3`, `pytest`, `yq-go`, and `nixfmt-tree`, and lightweight flake checks for frontend evaluation plus backend package tests.

## Testing model

- Backend package tests follow the nixpkgs `passthru.tests` style: the package exposes a separate pytest derivation so package verification is buildable without changing the main package output.
- Frontend module tests follow the Home Manager style more closely: they are lightweight evaluation/golden-style checks over generated task payloads and activation blocks, not VM tests.
- Full NixOS-style VM integration tests are still deferred because the current module primarily generates user configuration and switch-time tasks rather than system services.

## Home Manager integration notes

### Generic activation

The primary switch-time integration point is:

```nix
home.activation.<name> = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
  verboseEcho "Reconciling mutable files"
  run --silence ${lib.getExe backend} --task-file ${taskFile}
'';
```

This is the canonical location for side-effecting runtime actions. The block should respect Home Manager's activation driver semantics by using helpers such as `run`, `verboseEcho`, and the `writeBoundary` ordering constraint.

### Linux

Linux-specific persistent integration, if needed in the future, uses `systemd.user.services`.

### Darwin

Darwin-specific persistent integration, if needed in the future, uses `launchd.agents`.

Home Manager manages launch agents through activation logic in its launchd module, so Darwin-specific behavior must not assume Linux-style `systemd` semantics.
