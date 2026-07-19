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

  cfg = lib.filterAttrs (_: entry: entry.enable) config.home.mutableFile;
  stateDir = ''${config.xdg.stateHome}/mutable-file'';
  homeDirectory = config.home.homeDirectory;

  pathSegmentsType = types.listOf types.str;
  ownershipModeType = types.enum [ "declared" "sealed" "local" ];

  countSet = values: builtins.length (builtins.filter (x: x != null) values);

  normalizeTarget = target:
    if hasPrefix "/" target then target else "${homeDirectory}/${target}";

  normalizedSource = source:
    if lib.isPath source then {
      kind = "store_path";
      path = pkgs.writeText "mutable-file-tasks-deps-${lib.baseNameOf source}" (lib.readFile source);
    } else {
      kind = "runtime_path";
      path = source;
    };

  layerDescriptorFromValue = name: value: {
    inherit name;
    source = {
      kind = "inline";
      inherit value;
    };
    from = [ ];
    to = [ ];
    required = true;
  };

  layerDescriptorFromSource = name: source: {
    inherit name;
    source = normalizedSource source;
    from = [ ];
    to = [ ];
    required = true;
  };

  shortcutLayersForEntry = entry:
    if entry.value != null then
      [ (layerDescriptorFromValue "default" entry.value) ]
    else
      [ (layerDescriptorFromSource "default" entry.source) ];

  normalizeLayer = index: layer:
    let
      resolvedName = if layer.name != null then layer.name else "layer" + toString index;
      source = if layer.value != null then {
        kind = "inline";
        value = layer.value;
      } else normalizedSource layer.source;
    in
    {
      name = resolvedName;
      inherit source;
      from = layer.from;
      to = layer.to;
      required = layer.required;
    };

  normalizedLayersForEntry = entry:
    if entry.layers != [ ] then
      builtins.genList
        (index: normalizeLayer index (builtins.elemAt entry.layers index))
        (builtins.length entry.layers)
    else
      shortcutLayersForEntry entry;

  layerSourceOptionType = types.either types.path types.str;

  ownershipRuleType = types.submodule ({ ... }: {
    options = {
      path = mkOption {
        type = pathSegmentsType;
        default = [ ];
        example = [ "runtime" "cache" ];
        description = ''
          Path inside the managed document where this ownership rule starts to apply.
        '';
      };

      mode = mkOption {
        type = ownershipModeType;
        example = "local";
        description = ''
          Ownership mode applied at this path and all descendants unless a more specific rule overrides it.
        '';
      };
    };
  });

  ownershipType = types.submodule ({ ... }: {
    options = {
      default = mkOption {
        type = ownershipModeType;
        default = "declared";
        example = "declared";
        description = ''
          Default ownership mode used for paths not matched by a more specific rule.
        '';
      };

      rules = mkOption {
        type = types.listOf ownershipRuleType;
        default = [ ];
        example = literalExpression ''[
          { path = [ "credentials" ]; mode = "sealed"; }
          { path = [ "runtimeState" ]; mode = "local"; }
        ]'';
        description = ''
          Path-specific ownership rules. The most specific matching path wins at runtime.
        '';
      };
    };
  });

  layerType = types.submodule ({ ... }: {
    options = {
      name = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "defaults";
        description = ''
          Human-readable layer name used in diagnostics and generated task payloads.
        '';
      };

      value = mkOption {
        type = types.nullOr types.anything;
        default = null;
        example = literalExpression ''{
          app = { name = "demo"; };
        }'';
        description = ''
          Inline layer content embedded directly into the generated task payload.
          Set exactly one of `value` or `source` for each layer.
        '';
      };

      source = mkOption {
        type = types.nullOr layerSourceOptionType;
        default = null;
        example = literalExpression ''./defaults.toml'';
        description = ''
          File source for this layer.

          If set to a Nix path then the source is normalized to a store-backed source.
          If set to an absolute string path then the source is normalized to a runtime path read during activation.

          Set exactly one of `value` or `source` for each layer.
        '';
      };

      from = mkOption {
        type = pathSegmentsType;
        default = [ ];
        example = literalExpression ''[ "database" ]'';
        description = ''
          Path extracted from the layer source before merging it into the target document.
        '';
      };

      to = mkOption {
        type = pathSegmentsType;
        default = [ ];
        example = literalExpression ''[ "credentials" "database" ]'';
        description = ''
          Path inside the final target document where the extracted layer content is merged.
        '';
      };

      required = mkOption {
        type = types.bool;
        default = true;
        example = false;
        description = ''
          Whether activation should fail when the layer source or requested `from` path is missing.
        '';
      };
    };
  });

  fileType = types.submodule ({ name, config, ... }: {
    options = {
      enable = mkOption {
        type = types.bool;
        default = true;
        example = false;
        description = ''
          Whether this mutable file entry should be generated.
        '';
      };

      target = mkOption {
        type = types.str;
        default = name;
        defaultText = literalExpression "name";
        apply = normalizeTarget;
        example = "/etc/demo/config.toml";
        description = ''
          Absolute target path for the managed file.

          If a relative path is given then it is interpreted relative to `home.homeDirectory`.
        '';
      };

      format = mkOption {
        type = types.enum [ "toml" "yaml" "json" ];
        example = "toml";
        description = ''
          Serialization format used for reading, diffing, and updating the target file.
        '';
      };

      create = mkOption {
        type = types.bool;
        default = true;
        example = false;
        description = ''
          Whether the runtime may create the target file if it does not already exist.
        '';
      };

      mode = mkOption {
        type = types.str;
        default = "0600";
        example = "0640";
        description = ''
          File mode applied when the runtime writes the target file.
        '';
      };

      ownership = mkOption {
        type = ownershipType;
        default = { };
        description = ''
          Recursive ownership policy describing which undeclared fields are allowed, rejected, or treated as fully local.
        '';
      };

      value = mkOption {
        type = types.nullOr types.anything;
        default = null;
        example = literalExpression ''{
          app = { name = "demo"; };
        }'';
        description = ''
          Inline content shortcut for a single default layer.

          This is equivalent to defining one layer with `from = [ ]`, `to = [ ]`, and `required = true`.
          Set exactly one of `value`, `source`, or `layers` at the file level.
        '';
      };

      source = mkOption {
        type = types.nullOr layerSourceOptionType;
        default = null;
        example = literalExpression ''/run/secrets/app.toml'';
        description = ''
          File source shortcut for a single default layer.

          This is equivalent to defining one layer with `from = [ ]`, `to = [ ]`, and `required = true`.
          Nix paths become store-backed sources, while absolute string paths become runtime sources.

          Set exactly one of `value`, `source`, or `layers` at the file level.
        '';
      };

      layers = mkOption {
        type = types.listOf layerType;
        default = [ ];
        example = literalExpression ''[
          {
            name = "defaults";
            source = ./defaults.toml;
            to = [ ];
          }
          {
            name = "secret";
            source = "/run/secrets/app.toml";
            from = [ "credentials" ];
            to = [ "credentials" ];
          }
        ]'';
        description = ''
          Ordered source layers assembled into the target document before reconciliation.

          Set exactly one of `value`, `source`, or `layers` at the file level.
        '';
      };
    };
  });

  normalizedOwnership = entry: {
    default = entry.ownership.default;
    rules = builtins.map (rule: {
      inherit (rule) path mode;
    }) entry.ownership.rules;
  };

  documentTask = target: entry: {
    target = entry.target;
    format = entry.format;
    create = entry.create;
    mode = entry.mode;
    state_dir = stateDir;
    ownership = normalizedOwnership entry;
    layers = normalizedLayersForEntry entry;
  };

  taskPayload = {
    version = 5;
    documents = builtins.attrValues (mapAttrs' (target: entry: nameValuePair target (documentTask target entry)) cfg);
  };

  taskFile = pkgs.writeText "mutable-file-runtime-tasks.json" (builtins.toJSON taskPayload);

  runtime = config.home.mutableFileRuntime.package;
  activationCommand = ''${lib.escapeShellArg (lib.getExe runtime)} --task-file ${lib.escapeShellArg taskFile}'';
  hasEntries = cfg != { };

  duplicateTargets =
    let
      counts = lib.foldAttrs (acc: value: acc + value) 0 (
        lib.mapAttrsToList (_: entry: { "${entry.target}" = 1; }) cfg
      );
    in
    lib.attrNames (lib.filterAttrs (_: value: value > 1) counts);

  entryAssertionsForTarget = target:
    let
      entry = cfg.${target};
      sourceFormCount = countSet [ entry.value entry.source ] + (if entry.layers == [ ] then 0 else 1);
      normalizedLayers = normalizedLayersForEntry entry;
      layerCount = builtins.length entry.layers;
    in
    [
      {
        assertion = sourceFormCount == 1;
        message = "home.mutableFile.${target}: exactly one of value, source, or layers must be set.";
      }
      {
        assertion = lib.isPath entry.source || entry.source == null || hasPrefix "/" entry.source;
        message = "home.mutableFile.${target}.source: runtime string sources must be absolute.";
      }
    ]
    ++ concatLists (
      builtins.genList
        (index:
          let
            layer = builtins.elemAt entry.layers index;
            layerRef = "home.mutableFile.${target}.layers.${toString index}";
          in
          [
            {
              assertion = countSet [ layer.value layer.source ] == 1;
              message = "${layerRef}: exactly one of value or source must be set.";
            }
            {
              assertion = lib.isPath layer.source || layer.source == null || hasPrefix "/" layer.source;
              message = "${layerRef}.source: runtime string sources must be absolute.";
            }
          ])
        layerCount
    )
    ++ concatLists (
      builtins.genList
        (index:
          let
            rule = builtins.elemAt entry.ownership.rules index;
            ruleRef = "home.mutableFile.${target}.ownership.rules.${toString index}";
          in
          [
            {
              assertion = !(rule.mode == "local" && builtins.any (layer: lib.lists.hasPrefix rule.path layer.to) normalizedLayers);
              message = "${ruleRef}: layers may not write into a subtree marked as local ownership.";
            }
          ])
        (builtins.length entry.ownership.rules)
    );
in
{
  options.home.mutableFileInternal.taskPayload = mkOption {
    type = types.attrs;
    readOnly = true;
    description = ''
      Internal normalized task payload generated for the mutable file runtime.
    '';
  };

  options.home.mutableFileRuntime.package = mkOption {
    type = types.package;
    default = pkgs.callPackage ../../../runtime/package.nix { };
    defaultText = literalExpression "pkgs.callPackage ../../../runtime/package.nix { }";
    description = ''
      Runtime package used by the mutable file activation hook.
    '';
  };

  options.home.mutableFile = mkOption {
    default = { };
    type = types.attrsOf fileType;
    description = ''
      Declarative mutable file definitions reconciled in place by the mutable file runtime.
    '';
  };

  config = mkMerge [
    {
      home.mutableFileInternal.taskPayload = if hasEntries then taskPayload else { };
      xdg.stateHome = mkDefault "${config.home.homeDirectory}/.local/state";
    }
    (mkIf hasEntries {
      assertions = [
        {
          assertion = duplicateTargets == [ ];
          message = ''
            Conflicting managed target files: ${lib.concatStringsSep ", " duplicateTargets}
          '';
        }
      ]
      ++ concatLists (builtins.map entryAssertionsForTarget (builtins.attrNames cfg));

      home.packages = [ runtime ];
      home.activation.mutableFile = hm.dag.entryAfter [ "writeBoundary" ] ''
        ${activationCommand}
      '';
    })
  ];
}
