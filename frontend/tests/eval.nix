{
  repoRoot,
  self,
  nixpkgs,
  home-manager,
  system,
  backend,
}:

let
  pkgs = import nixpkgs { inherit system; };
  lib = pkgs.lib;
  hmLib = home-manager.lib;

  module = repoRoot + "/frontend/modules/mutable-file";

  evalConfig = extraModules:
    hmLib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        module
        {
          home.homeDirectory = "/home/tester";
          home.stateVersion = "24.11";
          home.mutableFileBackend.package = backend;
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
in
lib.runTests {
  no_entries_do_not_emit_payload_or_activation = {
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

  payload_value_includes = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/config.toml" = {
            format = "toml";
            value = {
              app = {
                name = "demo";
              };
              runtime = {
                enabled = false;
              };
            };
            includes = [ [ "app" ] ];
          };
        }
      ]).config.home.mutableFileInternal.taskPayload;
    expected = {
      version = 1;
      entries = [
        {
          entry_id = expectedEntryId ".config/demo/config.toml";
          target = ".config/demo/config.toml";
          format = "toml";
          create = true;
          mode = "0600";
          state_root = "/home/tester/.local/state/mutable-file";
          desired_source_kind = "value";
          desired_source_payload = {
            app = { name = "demo"; };
            runtime = { enabled = false; };
          };
          filter_mode = "includes";
          filter_paths = [ [ "app" ] ];
        }
      ];
    };
  };

  payload_source_excludes = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/config.yaml" = {
            format = "yaml";
            source = repoRoot + "/README.md";
            excludes = [ [ "runtime" ] [ "ephemeral" ] ];
            create = false;
            mode = "0640";
          };
        }
      ]).config.home.mutableFileInternal.taskPayload;
    expected = {
      version = 1;
      entries = [
        {
          entry_id = expectedEntryId ".config/demo/config.yaml";
          target = ".config/demo/config.yaml";
          format = "yaml";
          create = false;
          mode = "0640";
          state_root = "/home/tester/.local/state/mutable-file";
          desired_source_kind = "source";
          desired_source_payload = toString (repoRoot + "/README.md");
          filter_mode = "excludes";
          filter_paths = [ [ "runtime" ] [ "ephemeral" ] ];
        }
      ];
    };
  };

  payload_runtime_path = {
    expr =
      (evalConfig [
        {
          home.mutableFile.".config/demo/runtime.json" = {
            format = "json";
            path = "/run/secrets/runtime.json";
            includes = [ [ "profiles" "default" ] ];
          };
        }
      ]).config.home.mutableFileInternal.taskPayload;
    expected = {
      version = 1;
      entries = [
        {
          entry_id = expectedEntryId ".config/demo/runtime.json";
          target = ".config/demo/runtime.json";
          format = "json";
          create = true;
          mode = "0600";
          state_root = "/home/tester/.local/state/mutable-file";
          desired_source_kind = "path";
          desired_source_payload = "/run/secrets/runtime.json";
          filter_mode = "includes";
          filter_paths = [ [ "profiles" "default" ] ];
        }
      ];
    };
  };

  payload_honors_custom_state_home = {
    expr =
      (evalConfig [
        {
          xdg.stateHome = "/tmp/custom-state";
          home.mutableFile.".config/demo/config.toml" = {
            format = "toml";
            value = { app = { name = "demo"; }; };
            includes = [ [ "app" ] ];
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.entries;
    expected = [
      {
        entry_id = expectedEntryId ".config/demo/config.toml";
        target = ".config/demo/config.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_root = "/tmp/custom-state/mutable-file";
        desired_source_kind = "value";
        desired_source_payload = { app = { name = "demo"; }; };
        filter_mode = "includes";
        filter_paths = [ [ "app" ] ];
      }
    ];
  };

  payload_multiple_entries_sorted_by_attr_name = {
    expr =
      (evalConfig [
        {
          home.mutableFile = {
            ".config/z-last.toml" = {
              format = "toml";
              value = { z = 1; };
              includes = [ [ "z" ] ];
            };
            ".config/a-first.toml" = {
              format = "toml";
              value = { a = 1; };
              includes = [ [ "a" ] ];
            };
          };
        }
      ]).config.home.mutableFileInternal.taskPayload.entries;
    expected = [
      {
        entry_id = expectedEntryId ".config/a-first.toml";
        target = ".config/a-first.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_root = "/home/tester/.local/state/mutable-file";
        desired_source_kind = "value";
        desired_source_payload = { a = 1; };
        filter_mode = "includes";
        filter_paths = [ [ "a" ] ];
      }
      {
        entry_id = expectedEntryId ".config/z-last.toml";
        target = ".config/z-last.toml";
        format = "toml";
        create = true;
        mode = "0600";
        state_root = "/home/tester/.local/state/mutable-file";
        desired_source_kind = "value";
        desired_source_payload = { z = 1; };
        filter_mode = "includes";
        filter_paths = [ [ "z" ] ];
      }
    ];
  };

  flake_module_injects_backend_package = {
    expr =
      let
        cfg = (evalFlakeModuleConfig [
          {
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
              includes = [ [ "app" ] ];
            };
          }
        ]).config;
      in
      cfg.home.mutableFileBackend.package.name;
    expected = backend.name;
  };

  activation_uses_run_wrapper_and_logs = {
    expr =
      let
        cfg = (evalConfig [
          {
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
              includes = [ [ "app" ] ];
            };
          }
        ]).config;
        text = cfg.home.activation.mutableFile.data;
      in
      {
        hasRunWrapper = builtins.match ".*run --silence '?.*mutable-file-backend'? --task-file '?.*mutable-file-tasks.json'?.*" text != null;
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
            home.mutableFile.".config/demo/config.toml" = {
              format = "toml";
              value = { app = { name = "demo"; }; };
              includes = [ [ "app" ] ];
            };
          }
        ]).config;
      in
      cfg.home.activation.mutableFile.after;
    expected = [ "writeBoundary" ];
  };

  invalid_relative_target_fails = expectEvalFailure "invalid_relative_target_fails" [
    {
      home.mutableFile."/absolute/config.toml" = {
        format = "toml";
        value = { app = { name = "demo"; }; };
        includes = [ [ "app" ] ];
      };
    }
  ];

  invalid_multiple_sources_fail = expectEvalFailure "invalid_multiple_sources_fail" [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        value = { app = { name = "demo"; }; };
        path = "/run/secrets/config.toml";
        includes = [ [ "app" ] ];
      };
    }
  ];

  invalid_multiple_filters_fail = expectEvalFailure "invalid_multiple_filters_fail" [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        value = { app = { name = "demo"; }; };
        includes = [ [ "app" ] ];
        excludes = [ [ "state" ] ];
      };
    }
  ];

  invalid_relative_runtime_path_fails = expectEvalFailure "invalid_relative_runtime_path_fails" [
    {
      home.mutableFile.".config/demo/config.toml" = {
        format = "toml";
        path = "relative.toml";
        includes = [ [ "app" ] ];
      };
    }
  ];
}
