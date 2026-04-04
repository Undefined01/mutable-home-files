{ lib, config, pkgs, ... }:

let
  inherit (lib)
    concatLists
    hasPrefix
    hm
    literalExpression
    mapAttrs'
    mkDefault
    mkIf
    mkMerge
    mkOption
    nameValuePair
    types
    ;

  cfg = config.home.mutableFiles;
  stateRoot = ''${config.xdg.stateHome}/mutable-file'';

  pathSegmentsType = types.listOf types.str;
  ownershipModeType = types.enum [ "declared" "sealed" "local" ];

  countSet = values: builtins.length (builtins.filter (x: x != null) values);

  ownershipRuleType = types.submodule ({ ... }: {
    options = {
      path = mkOption {
        type = pathSegmentsType;
        default = [ ];
      };

      mode = mkOption {
        type = ownershipModeType;
      };
    };
  });

  ownershipType = types.submodule ({ ... }: {
    options = {
      default = mkOption {
        type = ownershipModeType;
        default = "declared";
        description = ''
          Recursive fallback ownership mode for paths without a more specific rule.
        '';
      };

      rules = mkOption {
        type = types.listOf ownershipRuleType;
        default = [ ];
        description = ''
          Path-specific ownership overrides. The most specific matching path wins at runtime.
        '';
      };
    };
  });

  layerType = types.submodule ({ ... }: {
    options = {
      name = mkOption {
        type = types.str;
        description = "Human-readable layer name used in generated task payloads and diagnostics.";
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

      from = mkOption {
        type = pathSegmentsType;
        default = [ ];
        example = literalExpression ''[ "database" ]'';
      };

      to = mkOption {
        type = pathSegmentsType;
        default = [ ];
        example = literalExpression ''[ "credentials" "database" ]'';
      };

      required = mkOption {
        type = types.bool;
        default = true;
        description = ''
          When true, the runtime errors if the layer source cannot provide the requested `from` path.
        '';
      };
    };
  });

  fileType = types.submodule ({ ... }: {
    options = {
      format = mkOption {
        type = types.enum [ "toml" "yaml" "json" ];
      };

      create = mkOption {
        type = types.bool;
        default = true;
      };

      mode = mkOption {
        type = types.str;
        default = "0600";
      };

      ownership = mkOption {
        type = ownershipType;
        default = { };
        description = ''
          Recursive ownership policy for paths not declared by layers.
        '';
      };

      layers = mkOption {
        type = types.listOf layerType;
        default = [ ];
        description = ''
          Ordered source layers assembled into the desired document before reconciliation.
        '';
      };

      enableUserUnit = mkOption {
        type = types.bool;
        default = false;
        description = ''
          Reserved for future platform-specific persistent integration. Switch-time reconciliation still runs through home.activation.
        '';
      };
    };
  });

  layerSourceKind = layer:
    if layer.value != null then "value"
    else if layer.source != null then "source"
    else "path";

  layerSourcePayload = layer:
    if layer.value != null then layer.value
    else if layer.source != null then toString layer.source
    else layer.path;

  normalizedLayers = entry:
    builtins.genList
      (index:
        let
          layer = builtins.elemAt entry.layers index;
        in
        {
          layer_id = builtins.hashString "sha256" "${toString index}:${layer.name}:${builtins.toJSON layer.from}:${builtins.toJSON layer.to}";
          name = layer.name;
          source_kind = layerSourceKind layer;
          source_payload = layerSourcePayload layer;
          from_path = layer.from;
          to_path = layer.to;
          required = layer.required;
        })
      (builtins.length entry.layers);

  normalizedOwnership = entry: {
    default_mode = entry.ownership.default;
    rules = builtins.map (rule: {
      inherit (rule) path mode;
    }) entry.ownership.rules;
  };

  entryTask = target: entry: {
    entry_id = builtins.hashString "sha256" target;
    target = target;
    format = entry.format;
    create = entry.create;
    mode = entry.mode;
    state_root = stateRoot;
    ownership = normalizedOwnership entry;
    layers = normalizedLayers entry;
  };

  taskPayload = {
    version = 3;
    entries = builtins.attrValues (mapAttrs' (target: entry: nameValuePair target (entryTask target entry)) cfg);
  };

  taskFile = pkgs.writeText "mutable-file-runtime-tasks.json" (builtins.toJSON taskPayload);

  runtime = config.home.mutableFileRuntime.package;
  activationCommand = ''${lib.escapeShellArg (lib.getExe runtime)} --task-file ${lib.escapeShellArg taskFile}'';
  hasEntries = cfg != { };

  layerAssertionsForTarget = target:
    let
      entry = cfg.${target};
      layerCount = builtins.length entry.layers;
    in
    concatLists (
      builtins.genList
        (index:
          let
            layer = builtins.elemAt entry.layers index;
            layerRef = "home.mutableFiles.${target}.layers.${toString index}";
          in
          [
            {
              assertion = countSet [ layer.value layer.source layer.path ] == 1;
              message = "${layerRef}: exactly one of value, source, or path must be set.";
            }
            {
              assertion = layer.path == null || hasPrefix "/" layer.path;
              message = "${layerRef}: path must be absolute.";
            }
          ])
        layerCount
    );

  ownershipAssertionsForTarget = target:
    let
      entry = cfg.${target};
      ruleCount = builtins.length entry.ownership.rules;
    in
    concatLists (
      builtins.genList
        (index:
          let
            rule = builtins.elemAt entry.ownership.rules index;
            ruleRef = "home.mutableFiles.${target}.ownership.rules.${toString index}";
          in
          [
            {
              assertion = !(rule.mode == "local" && builtins.any (layer: lib.lists.hasPrefix rule.path layer.to) entry.layers);
              message = "${ruleRef}: layers may not write into a subtree marked as local ownership.";
            }
          ])
        ruleCount
    );
in
{
  options.home.mutableFilesInternal.taskPayload = mkOption {
    type = types.attrs;
    readOnly = true;
    description = ''
      Internal normalized task payload for tests and debugging.
    '';
  };

  options.home.mutableFileRuntime.package = mkOption {
    type = types.package;
    default = pkgs.callPackage ../../../runtime/package.nix { };
    defaultText = literalExpression "pkgs.callPackage ../../../runtime/package.nix { }";
    description = ''
      Runtime package used by the mutable-file activation hook. Override this when consuming the module from a flake output that already exposes the packaged runtime.
    '';
  };

  options.home.mutableFiles = mkOption {
    default = { };
    type = types.attrsOf fileType;
    description = ''
      Declarative mutable file definitions assembled from ordered runtime layers.
    '';
  };

  config = mkIf hasEntries (mkMerge [
    {
      assertions =
        builtins.map (target: {
          assertion = !(hasPrefix "/" target);
          message = "home.mutableFiles.${target}: target must be relative to home.homeDirectory.";
        }) (builtins.attrNames cfg)
        ++ builtins.map (target: {
          assertion = cfg.${target}.layers != [ ];
          message = "home.mutableFiles.${target}: at least one layer must be defined.";
        }) (builtins.attrNames cfg)
        ++ concatLists (builtins.map layerAssertionsForTarget (builtins.attrNames cfg))
        ++ concatLists (builtins.map ownershipAssertionsForTarget (builtins.attrNames cfg));

      home.packages = [ runtime ];
      home.mutableFilesInternal.taskPayload = taskPayload;
      xdg.stateHome = mkDefault "${config.home.homeDirectory}/.local/state";
      home.activation.mutableFiles = hm.dag.entryAfter [ "writeBoundary" ] ''
        verboseEcho "Reconciling mutable files"
        run --silence ${activationCommand}
      '';
    }
  ]);
}
