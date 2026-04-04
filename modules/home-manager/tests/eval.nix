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
          home.username = "tester";
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
          home.username = "tester";
        }
      ] ++ extraModules;
    };

  expectEvalFailure = modules:
    let
      result = builtins.tryEval (evalConfig modules);
    in
    {
      expr = result.success;
      expected = false;
    };
in
lib.runTests {
  test_no_entries_do_not_emit_payload_or_activation = {
    expr =
      let
        cfg = (evalConfig [ ]).config;
      in
      {
        payload = cfg.home.mutableFileInternal.taskPayload;
        hasActivation = builtins.hasAttr "mutableFile" cfg.home.activation;
      };
    expected = {
      payload = { };
      hasActivation = false;
    };
  };

  test_payload_top_level_value_shortcut_defaults = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/config.toml" = {
            format = "toml";
            ownership = {
              default = "declared";
              rules = [
                { path = [ "runtime" ]; mode = "local"; }
              ];
            };
            value = {
              app = { name = "demo"; };
              runtime = { enabled = false; };
            };
          };
        }
      ]).config.home.mutableFileInternal.taskPayload;
    expected = {
      version = 5;
      documents = [
        {
          target = "/home/tester/.config/demo/config.toml";
          format = "toml";
          create = true;
          mode = "0600";
          state_dir = "/home/tester/.local/state/mutable-file";
          ownership = {
            default = "declared";
            rules = [
              { path = [ "runtime" ]; mode = "local"; }
            ];
          };
          layers = [
            {
              name = "default";
              source = {
                kind = "inline";
                value = {
                  app = { name = "demo"; };
                  runtime = { enabled = false; };
                };
              };
              from = [ ];
              to = [ ];
              required = true;
            }
          ];
        }
      ];
    };
  };

  test_payload_top_level_value_shortcut_accepts_config_values = {
    expr =
      (evalConfig [
        ({ config, ... }: {
          programs.vscode.enable = true;
          programs.vscode.profiles.default.userSettings = {
            "editor.fontSize" = 14;
            "files.autoSave" = "onFocusChange";
          };

          home.mutableFile.".config/Code/User/settings.json" = {
            format = "json";
            value = config.programs.vscode.profiles.default.userSettings;
          };
        })
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/home/tester/.config/Code/User/settings.json";
        format = "json";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "inline";
              value = {
                "editor.fontSize" = 14;
                "files.autoSave" = "onFocusChange";
              };
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  test_payload_top_level_runtime_source_shortcut_and_absolute_target = {
    expr =
      (evalConfig [
        {
          xdg.stateHome = "/tmp/custom-state";
          home.mutableFile.secret = {
            target = "/etc/demo/config.yaml";
            format = "yaml";
            create = false;
            mode = "0640";
            ownership = {
              default = "declared";
              rules = [
                { path = [ "credentials" ]; mode = "sealed"; }
              ];
            };
            source = "/run/secrets/runtime.json";
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/etc/demo/config.yaml";
        format = "yaml";
        create = false;
        mode = "0640";
        state_dir = "/tmp/custom-state/mutable-file";
        ownership = {
          default = "declared";
          rules = [
            { path = [ "credentials" ]; mode = "sealed"; }
          ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "runtime_path";
              path = "/run/secrets/runtime.json";
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  test_payload_top_level_store_source_shortcut = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/from-store.yaml" = {
            format = "yaml";
            source = repoRoot + "/README.md";
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/home/tester/.config/demo/from-store.yaml";
        format = "yaml";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "store_path";
              path = toString (repoRoot + "/README.md");
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  test_payload_explicit_layers_normalize_sources_and_names = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/layers.json" = {
            format = "json";
            layers = [
              {
                value = { defaults = true; };
              }
              {
                name = "secret";
                source = "/run/secrets/app.json";
                from = [ "auth" ];
                to = [ "credentials" ];
                required = false;
              }
              {
                source = repoRoot + "/docs/interfaces.md";
                to = [ "docs" ];
              }
            ];
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/home/tester/.config/demo/layers.json";
        format = "json";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "layer0";
            source = {
              kind = "inline";
              value = { defaults = true; };
            };
            from = [ ];
            to = [ ];
            required = true;
          }
          {
            name = "secret";
            source = {
              kind = "runtime_path";
              path = "/run/secrets/app.json";
            };
            from = [ "auth" ];
            to = [ "credentials" ];
            required = false;
          }
          {
            name = "layer2";
            source = {
              kind = "store_path";
              path = toString (repoRoot + "/docs/interfaces.md");
            };
            from = [ ];
            to = [ "docs" ];
            required = true;
          }
        ];
      }
    ];
  };

  test_payload_multiple_entries_sorted_by_attr_name = {
    expr =
      (evalConfig [
        {
          home.mutableFile = {
            ".config/z-last.toml" = {
              format = "toml";
              value = { z = 1; };
            };
            ".config/a-first.toml" = {
              format = "toml";
              value = { a = 1; };
            };
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/home/tester/.config/a-first.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "inline";
              value = { a = 1; };
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
      {
        target = "/home/tester/.config/z-last.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "inline";
              value = { z = 1; };
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  test_disabled_entries_do_not_emit_documents = {
    expr =
      (evalConfig [
        {
          home.mutableFile = {
            ".config/demo/enabled.toml" = {
              format = "toml";
              value = { enabled = true; };
            };
            ".config/demo/disabled.toml" = {
              enable = false;
              format = "toml";
              value = { enabled = false; };
            };
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.documents;
    expected = [
      {
        target = "/home/tester/.config/demo/enabled.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_dir = "/home/tester/.local/state/mutable-file";
        ownership = {
          default = "declared";
          rules = [ ];
        };
        layers = [
          {
            name = "default";
            source = {
              kind = "inline";
              value = { enabled = true; };
            };
            from = [ ];
            to = [ ];
            required = true;
          }
        ];
      }
    ];
  };

  test_flake_module_injects_runtime_package = {
    expr =
      let
        cfg = (evalFlakeModuleConfig [
          {
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
            };
          }
        ]).config;
      in
      cfg.home.mutableFileRuntime.package.name;
    expected = runtime.name;
  };

  test_activation_uses_run_wrapper_and_logs = {
    expr =
      let
        cfg = (evalConfig [
          {
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
            };
          }
        ]).config;
        text = cfg.home.activation.mutableFile.data;
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

  test_activation_runs_after_write_boundary = {
    expr =
      let
        cfg = (evalConfig [
          {
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
            };
          }
        ]).config;
      in
      cfg.home.activation.mutableFile.after;
    expected = [ "writeBoundary" ];
  };

  test_duplicate_normalized_targets_fail = expectEvalFailure [
    {
      home.mutableFile = {
        one = {
          target = "/etc/demo/config.toml";
          format = "toml";
          value = { a = 1; };
        };
        two = {
          target = "/etc/demo/config.toml";
          format = "toml";
          value = { b = 2; };
        };
      };
    }
  ];

  test_invalid_value_and_source_entry_forms_fail = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        value = { app = { name = "demo"; }; };
        source = "/run/secrets/demo.toml";
      };
    }
  ];

  test_invalid_value_and_layers_entry_forms_fail = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        value = { app = { name = "demo"; }; };
        layers = [ { value = { a = 1; }; } ];
      };
    }
  ];

  test_invalid_source_and_layers_entry_forms_fail = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        source = "/run/secrets/demo.toml";
        layers = [ { value = { a = 1; }; } ];
      };
    }
  ];

  test_invalid_relative_runtime_source_fails = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        source = "relative.toml";
      };
    }
  ];

  test_missing_value_source_layers_fail = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
      };
    }
  ];

  test_layer_with_both_value_and_source_fails = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        layers = [
          {
            value = { a = 1; };
            source = "/run/secrets/demo.toml";
          }
        ];
      };
    }
  ];

  test_layer_with_neither_value_nor_source_fails = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        layers = [
          {
            to = [ "app" ];
          }
        ];
      };
    }
  ];

  test_relative_runtime_layer_source_fails = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        layers = [
          {
            source = "relative.toml";
          }
        ];
      };
    }
  ];

  test_local_ownership_rejects_layer_target = expectEvalFailure [
    {
      home.mutableFile.".config/demo/config.toml" = {
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
            to = [ "runtime" "cache" ];
          }
        ];
      };
    }
  ];
}
