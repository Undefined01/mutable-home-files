{ lib, config, pkgs, ... }:

let
  inherit (lib)
    hasPrefix
    hm
    literalExpression
    mkDefault
    mkIf
    mkMerge
    mkOption
    nameValuePair
    types
    mapAttrs'
    ;

  cfg = config.home.mutableFile;
  stateRoot = ''${config.xdg.stateHome}/mutable-file'';

  pathSegmentsType = types.listOf types.str;
  filterPathsType = types.listOf pathSegmentsType;

  countSet = values: builtins.length (builtins.filter (x: x != null) values);

  sourceKind = entry:
    if entry.value != null then "value"
    else if entry.source != null then "source"
    else "path";

  sourcePayload = entry:
    if entry.value != null then entry.value
    else if entry.source != null then toString entry.source
    else entry.path;

  entryTask = target: entry: {
    entry_id = builtins.hashString "sha256" target;
    target = target;
    format = entry.format;
    create = entry.create;
    mode = entry.mode;
    state_root = stateRoot;
    desired_source_kind = sourceKind entry;
    desired_source_payload = sourcePayload entry;
    filter_mode = if entry.includes != null then "includes" else "excludes";
    filter_paths = if entry.includes != null then entry.includes else entry.excludes;
  };

  taskPayload = {
    version = 1;
    entries = builtins.attrValues (mapAttrs' (target: entry: nameValuePair target (entryTask target entry)) cfg);
  };

  taskFile = pkgs.writeText "mutable-file-tasks.json" (builtins.toJSON taskPayload);

  backend = config.home.mutableFileBackend.package;

  activationCommand = ''${lib.escapeShellArg (lib.getExe backend)} --task-file ${lib.escapeShellArg taskFile}'';

  hasEntries = cfg != { };
in
{
  options.home.mutableFileInternal.taskPayload = mkOption {
    type = types.attrs;
    readOnly = true;
    description = ''
      Internal normalized task payload for tests and debugging.
    '';
  };

  options.home.mutableFileBackend.package = mkOption {
    type = types.package;
    default = pkgs.callPackage ../../../backend/package.nix { };
    defaultText = literalExpression "pkgs.callPackage ../backend/package.nix { }";
    description = ''
      Backend package used by the mutable-file activation hook. Override this when consuming the module from a flake output that already exposes the packaged backend.
    '';
  };

  options.home.mutableFile = mkOption {
    default = { };
    type = types.attrsOf (types.submodule ({ ... }: {
      options = {
        format = mkOption {
          type = types.enum [ "toml" "yaml" "json" ];
        };

        value = mkOption {
          type = types.nullOr types.anything;
          default = null;
        };

        source = mkOption {
          type = types.nullOr types.path;
          default = null;
        };

        path = mkOption {
          type = types.nullOr types.str;
          default = null;
          example = "/run/secrets/app.toml";
        };

        includes = mkOption {
          type = types.nullOr filterPathsType;
          default = null;
          example = literalExpression ''[ [ "profiles" "default" ] ]'';
        };

        excludes = mkOption {
          type = types.nullOr filterPathsType;
          default = null;
          example = literalExpression ''[ [ "state" ] ]'';
        };

        create = mkOption {
          type = types.bool;
          default = true;
        };

        mode = mkOption {
          type = types.str;
          default = "0600";
        };

        enableUserUnit = mkOption {
          type = types.bool;
          default = false;
          description = ''
            Reserved for future platform-specific persistent integration. Switch-time reconciliation still runs through home.activation.
          '';
        };
      };
    }));
  };

  config = mkIf hasEntries (mkMerge [
    {
      assertions =
        builtins.map (target: {
          assertion = !(hasPrefix "/" target);
          message = "home.mutableFile.${target}: target must be relative to home.homeDirectory.";
        }) (builtins.attrNames cfg)
        ++ builtins.map (target:
          let entry = cfg.${target};
          in {
            assertion = countSet [ entry.value entry.source entry.path ] == 1;
            message = "home.mutableFile.${target}: exactly one of value, source, or path must be set.";
          }
        ) (builtins.attrNames cfg)
        ++ builtins.map (target:
          let entry = cfg.${target};
          in {
            assertion = countSet [ entry.includes entry.excludes ] == 1;
            message = "home.mutableFile.${target}: exactly one of includes or excludes must be set.";
          }
        ) (builtins.attrNames cfg)
        ++ builtins.map (target:
          let entry = cfg.${target};
          in {
            assertion = entry.path == null || hasPrefix "/" entry.path;
            message = "home.mutableFile.${target}: path must be absolute.";
          }
        ) (builtins.attrNames cfg);

      home.packages = [ backend ];
      home.mutableFileInternal.taskPayload = taskPayload;
      xdg.stateHome = mkDefault "${config.home.homeDirectory}/.local/state";
      home.activation.mutableFile = hm.dag.entryAfter [ "writeBoundary" ] ''
        verboseEcho "Reconciling mutable files"
        run --silence ${activationCommand}
      '';
    }
  ]);
}
