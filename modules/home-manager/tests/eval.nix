{
  repoRoot,
  self,
  nixpkgs,
  home-manager,
  system,
  runtime,
}:

let
  pkgs = import nixpkgs { inherit system; };
  lib = pkgs.lib;
  hmLib = home-manager.lib;

  module = repoRoot + "/modules/home-manager/mutable-file";

  evalConfig = extraModules:
    hmLib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        module
        {
          home.homeDirectory = "/home/tester";
          home.stateVersion = "24.11";
          home.mutableFileRuntime.package = runtime;
        }
      ] ++ extraModules;
    };

  evalFlakeModuleConfig = extraModules:
    hmLib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        self.homeManagerModules.default
        {
          home.homeDirectory = "/home/tester";
          home.stateVersion = "24.11";
        }
      ] ++ extraModules;
    };

  expectEvalFailure = name: modules:
    let
      result = builtins.tryEval (evalConfig modules);
    in
    lib.nameValuePair name {
      expr = result.success;
      expected = false;
    };

  expectedEntryId = target: builtins.hashString "sha256" target;
  expectedLayerId = index: name: from: to:
    builtins.hashString "sha256" "${toString index}:${name}:${builtins.toJSON from}:${builtins.toJSON to}";
in
lib.runTests {
  no_entries_do_not_emit_payload_or_activation = {
    expr =
      let
        cfg = (evalConfig [ ]).config;
      in
      {
        payload = cfg.home.mutableFilesInternal.taskPayload;
        hasActivation = builtins.hasAttr "mutableFiles" cfg.home.activation;
      };
    expected = {
      payload = { };
      hasActivation = false;
    };
  };

  payload_single_layer_defaults = {
    expr =
      (evalConfig [
        {
          home.mutableFiles.".config/demo/config.toml" = {
            format = "toml";
            ownership = {
              default = "declared";
              rules = [
                { path = [ "runtime" ]; mode = "local"; }
              ];
            };
            layers = [
              {
                name = "defaults";
                value = {
                  app = { name = "demo"; };
                  runtime = { enabled = false; };
                };
                to = [ ];
              }
            ];
          };
        }
      ]).config.home.mutableFilesInternal.taskPayload;
    expected = {
      version = 3;
      entries = [
        {
          entry_id = expectedEntryId ".config/demo/config.toml";
          target = ".config/demo/config.toml";
          format = "toml";
          create = true;
          mode = "0600";
          state_root = "/home/tester/.local/state/mutable-file";
          ownership = {
            default_mode = "declared";
            rules = [
              { path = [ "runtime" ]; mode = "local"; }
            ];
          };
          layers = [
            {
              layer_id = expectedLayerId 0 "defaults" [ ] [ ];
              name = "defaults";
              source_kind = "value";
              source_payload = {
                app = { name = "demo"; };
                runtime = { enabled = false; };
              };
              from_path = [ ];
              to_path = [ ];
              required = true;
            }
          ];
        }
      ];
    };
  };

  payload_multiple_layers_and_custom_state_home = {
    expr =
      (evalConfig [
        {
          xdg.stateHome = "/tmp/custom-state";
          home.mutableFiles.".config/demo/config.yaml" = {
            format = "yaml";
            create = false;
            mode = "0640";
            ownership = {
              default = "declared";
              rules = [
                { path = [ "credentials" ]; mode = "sealed"; }
              ];
            };
            layers = [
              {
                name = "defaults";
                source = repoRoot + "/README.md";
                from = [ ];
                to = [ "docs" ];
              }
              {
                name = "runtime-secret";
                path = "/run/secrets/runtime.json";
                from = [ "profiles" "default" ];
                to = [ "profiles" "default" ];
                required = false;
              }
            ];
          };
        }
      ]).config.home.mutableFilesInternal.taskPayload.entries;
    expected = [
      {
        entry_id = expectedEntryId ".config/demo/config.yaml";
        target = ".config/demo/config.yaml";
        format = "yaml";
        create = false;
        mode = "0640";
        state_root = "/tmp/custom-state/mutable-file";
        ownership = {
          default_mode = "declared";
          rules = [
            { path = [ "credentials" ]; mode = "sealed"; }
          ];
        };
        layers = [
          {
            layer_id = expectedLayerId 0 "defaults" [ ] [ "docs" ];
            name = "defaults";
            source_kind = "source";
            source_payload = toString (repoRoot + "/README.md");
            from_path = [ ];
            to_path = [ "docs" ];
            required = true;
          }
          {
            layer_id = expectedLayerId 1 "runtime-secret" [ "profiles" "default" ] [ "profiles" "default" ];
            name = "runtime-secret";
            source_kind = "path";
            source_payload = "/run/secrets/runtime.json";
            from_path = [ "profiles" "default" ];
            to_path = [ "profiles" "default" ];
            required = false;
          }
        ];
      }
    ];
  };

  payload_multiple_entries_sorted_by_attr_name = {
    expr =
      (evalConfig [
        {
          home.mutableFiles = {
            ".config/z-last.toml" = {
              format = "toml";
              layers = [
                {
                  name = "z";
                  value = { z = 1; };
                  to = [ ];
                }
              ];
            };
            ".config/a-first.toml" = {
              format = "toml";
              layers = [
                {
                  name = "a";
                  value = { a = 1; };
                  to = [ ];
                }
              ];
            };
          };
        }
      ]).config.home.mutableFilesInternal.taskPayload.entries;
    expected = [
      {
        entry_id = expectedEntryId ".config/a-first.toml";
        target = ".config/a-first.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_root = "/home/tester/.local/state/mutable-file";
        ownership = {
          default_mode = "declared";
          rules = [ ];
        };
        layers = [
          {
            layer_id = expectedLayerId 0 "a" [ ] [ ];
            name = "a";
            source_kind = "value";
            source_payload = { a = 1; };
            from_path = [ ];
            to_path = [ ];
            required = true;
          }
        ];
      }
      {
        entry_id = expectedEntryId ".config/z-last.toml";
        target = ".config/z-last.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_root = "/home/tester/.local/state/mutable-file";
        ownership = {
          default_mode = "declared";
          rules = [ ];
        };
        layers = [
          {
            layer_id = expectedLayerId 0 "z" [ ] [ ];
            name = "z";
            source_kind = "value";
            source_payload = { z = 1; };
            from_path = [ ];
            to_path = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  flake_module_injects_runtime_package = {
    expr =
      let
        cfg = (evalFlakeModuleConfig [
          {
            home.mutableFiles.".config/demo/config.toml" = {
              format = "toml";
              layers = [
                {
                  name = "defaults";
                  value = { app = { name = "demo"; }; };
                  to = [ ];
                }
              ];
            };
          }
        ]).config;
      in
      cfg.home.mutableFileRuntime.package.name;
    expected = runtime.name;
  };

  activation_uses_run_wrapper_and_logs = {
    expr =
      let
        cfg = (evalConfig [
          {
            home.mutableFiles.".config/demo/config.toml" = {
              format = "toml";
              layers = [
                {
                  name = "defaults";
                  value = { app = { name = "demo"; }; };
                  to = [ ];
                }
              ];
            };
          }
        ]).config;
        text = cfg.home.activation.mutableFiles.data;
      in
      {
        hasRunWrapper = builtins.match ".*run --silence '?.*mutable-file-runtime'? --task-file '?.*mutable-file-runtime-tasks.json'?.*" text != null;
        hasVerboseLog = builtins.match ".*verboseEcho \"Reconciling mutable files\".*" text != null;
      };
    expected = {
      hasRunWrapper = true;
      hasVerboseLog = true;
    };
  };

  activation_runs_after_write_boundary = {
    expr =
      let
        cfg = (evalConfig [
          {
            home.mutableFiles.".config/demo/config.toml" = {
              format = "toml";
              layers = [
                {
                  name = "defaults";
                  value = { app = { name = "demo"; }; };
                  to = [ ];
                }
              ];
            };
          }
        ]).config;
      in
      cfg.home.activation.mutableFiles.after;
    expected = [ "writeBoundary" ];
  };

  invalid_relative_target_fails = expectEvalFailure "invalid_relative_target_fails" [
    {
      home.mutableFiles."/absolute/config.toml" = {
        format = "toml";
        layers = [
          {
            name = "defaults";
            value = { app = { name = "demo"; }; };
            to = [ ];
          }
        ];
      };
    }
  ];

  invalid_multiple_sources_fail = expectEvalFailure "invalid_multiple_sources_fail" [
    {
      home.mutableFiles.".config/demo/config.toml" = {
        format = "toml";
        layers = [
          {
            name = "broken";
            value = { app = { name = "demo"; }; };
            path = "/run/secrets/config.toml";
            to = [ ];
          }
        ];
      };
    }
  ];

  invalid_relative_runtime_path_fails = expectEvalFailure "invalid_relative_runtime_path_fails" [
    {
      home.mutableFiles.".config/demo/config.toml" = {
        format = "toml";
        layers = [
          {
            name = "secret";
            path = "relative.toml";
            to = [ ];
          }
        ];
      };
    }
  ];

  missing_layers_fail = expectEvalFailure "missing_layers_fail" [
    {
      home.mutableFiles.".config/demo/config.toml" = {
        format = "toml";
      };
    }
  ];

  local_ownership_rejects_layer_target = expectEvalFailure "local_ownership_rejects_layer_target" [
    {
      home.mutableFiles.".config/demo/config.toml" = {
        format = "toml";
        ownership = {
          rules = [
            { path = [ "runtime" ]; mode = "local"; }
          ];
        };
        layers = [
          {
            name = "defaults";
            value = { enabled = true; };
            to = [ "runtime" ];
          }
        ];
      };
    }
  ];
}
