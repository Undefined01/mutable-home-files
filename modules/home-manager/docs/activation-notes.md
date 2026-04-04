# Activation Notes

## Generic switch-time hook

Use Home Manager activation DAG entries after `writeBoundary` for any side-effecting action:

```nix
home.activation.mutableFiles = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
  verboseEcho "Reconciling mutable files"
  run --silence ${lib.getExe runtime} --task-file ${taskFile}
'';
```

This keeps the hook compatible with Home Manager's activation-driver expectations:

- `writeBoundary` marks the point after which writes are allowed
- `run` makes `DRY_RUN` behavior consistent with the rest of the activation script
- `verboseEcho` makes the block visible when `VERBOSE=1` without adding unconditional output

## Linux integration

Persistent Linux user integration can be expressed with `systemd.user.services`, but it is not the default execution path for `mutable-file`.

The default switch-time reconcile path is `home.activation` only. Add a Linux user unit later only if the runtime grows a persistent or on-demand daemon mode.

## Darwin integration

Persistent Darwin user integration can be expressed with `launchd.agents`, but it is not the default execution path for `mutable-file`.

The default switch-time reconcile path is `home.activation` only. Add a Darwin launch agent later only if the runtime grows a persistent or on-demand daemon mode.

Home Manager's Darwin launch agent installation behavior is itself implemented in activation logic, so module code must treat it as a platform-specific transport rather than a replacement for activation.
