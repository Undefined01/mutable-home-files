{
  description = "mutable-file Home Manager modules and runtime";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable?shallow=1";
    home-manager = {
      url = "github:nix-community/home-manager/master?shallow=1";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, home-manager }:
    let
      systems = [ "x86_64-linux" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      mkHomeManagerEvalTest =
        {
          pkgs,
          runtime,
          system,
        }:
        let
          homeManagerEvalResults = import ./modules/home-manager/tests/eval.nix {
            repoRoot = ./.;
            inherit self nixpkgs home-manager system runtime;
          };
        in
        pkgs.runCommand "home-manager-eval-tests" { } ''
          printf '%s\n' ${pkgs.lib.escapeShellArg (builtins.toJSON homeManagerEvalResults)} > results.json
          if [ "$(cat results.json)" != '[]' ]; then
            echo "home-manager eval tests failed: $(cat results.json)" >&2
            exit 1
          fi
          touch $out
        '';

      mkNamedTests =
        {
          pkgs,
          runtime,
          system,
        }:
        {
          home-manager-eval = mkHomeManagerEvalTest {
            inherit pkgs runtime system;
          };
        };
    in
    {
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);

      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          runtime = pkgs.callPackage ./runtime/package.nix { };
          namedTests = mkNamedTests {
            inherit pkgs runtime system;
          };
        in
        namedTests
        // {
          default = runtime;
          mutable-file-runtime = runtime;
        }
        // (nixpkgs.lib.mapAttrs' (name: value: {
          name = "test-${name}";
          inherit value;
        }) namedTests)
        // {
          test-all = pkgs.linkFarm "mutable-file-test-all" (
            nixpkgs.lib.mapAttrsToList (name: path: {
              inherit name path;
            }) namedTests
          );
        });

      apps = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          testTargets = builtins.filter (
            name: nixpkgs.lib.hasPrefix "test-" name && name != "test-all"
          ) (builtins.attrNames self.packages.${system});
          testsApp = pkgs.writeShellApplication {
            name = "mutable-file-tests";
            runtimeInputs = [ pkgs.nix ];
            text = ''
              set -eu

              flake_ref="path:${toString ./.}"
              tests="${builtins.concatStringsSep " " testTargets}"

              if [ "''${1-}" = "--list" ]; then
                for test_name in $tests; do
                  printf '%s\n' "$test_name"
                done
                exit 0
              fi

              if [ "$#" -gt 0 ]; then
                for test_name in "$@"; do
                  nix build "$flake_ref#$test_name"
                done
              else
                for test_name in $tests; do
                  nix build "$flake_ref#$test_name"
                done
              fi
            '';
          };
        in
        {
          default = {
            type = "app";
            program = nixpkgs.lib.getExe self.packages.${system}.mutable-file-runtime;
          };
          mutable-file-runtime = {
            type = "app";
            program = nixpkgs.lib.getExe self.packages.${system}.mutable-file-runtime;
          };
          tests = {
            type = "app";
            program = nixpkgs.lib.getExe testsApp;
          };
        });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              (python3.withPackages (ps: [ ps.pytest ps.ruamel-yaml ps.tomlkit ]))
              nixfmt-tree
            ];
          };
        });

      homeManagerModules.default = { pkgs, ... }: {
        imports = [ ./modules/home-manager/mutable-file ];
        home.mutableFileRuntime.package = self.packages.${pkgs.stdenv.hostPlatform.system}.mutable-file-runtime;
      };

      checks = forAllSystems (system:
        let
          packages = self.packages.${system};
        in
        {
          runtime-pytest = packages.test-runtime-pytest;
          home-manager-eval = packages.test-home-manager-eval;
        });

      test-runtime-pytest = forAllSystems (system: self.packages.${system}.test-runtime-pytest);
      test-home-manager-eval = forAllSystems (system: self.packages.${system}.test-home-manager-eval);
      test-all = forAllSystems (system: self.packages.${system}.test-all);
    };
}
