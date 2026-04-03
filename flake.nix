{
  description = "mutable-file frontend/backend split repository";

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
      mkFrontendEvalTest =
        {
          pkgs,
          backend,
          system,
        }:
        let
          frontendEvalResults = import ./frontend/tests/eval.nix {
            repoRoot = ./.;
            inherit self nixpkgs home-manager system backend;
          };
        in
        pkgs.runCommand "frontend-eval-tests" { } ''
          printf '%s\n' ${pkgs.lib.escapeShellArg (builtins.toJSON frontendEvalResults)} > results.json
          if [ "$(cat results.json)" != '[]' ]; then
            echo "frontend eval tests failed: $(cat results.json)" >&2
            exit 1
          fi
          touch $out
        '';
      mkNamedTests =
        {
          pkgs,
          backend,
          system,
        }:
        {
          backend-pytest = backend.tests.pytest;
          frontend-eval = mkFrontendEvalTest {
            inherit pkgs backend system;
          };
        };
    in
    {
      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);

      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          backend = pkgs.callPackage ./backend/package.nix { };
          namedTests = mkNamedTests {
            inherit pkgs backend system;
          };
        in
        namedTests
        // {
          default = backend;
          mutable-file-backend = backend;
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
            program = nixpkgs.lib.getExe self.packages.${system}.mutable-file-backend;
          };
          mutable-file-backend = {
            type = "app";
            program = nixpkgs.lib.getExe self.packages.${system}.mutable-file-backend;
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
              (python3.withPackages (ps: [ ps.pytest ps.tomlkit ]))
              yq-go
              nixfmt-tree
            ];
          };
        });

      homeManagerModules.default = { pkgs, ... }: {
        imports = [ ./frontend/modules/mutable-file ];
        home.mutableFileBackend.package = self.packages.${pkgs.stdenv.hostPlatform.system}.mutable-file-backend;
      };

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          packages = self.packages.${system};
        in
        {
          backend-pytest = packages.test-backend-pytest;
          frontend-eval = packages.test-frontend-eval;
        });

      test-backend-pytest = forAllSystems (system: self.packages.${system}.test-backend-pytest);
      test-frontend-eval = forAllSystems (system: self.packages.${system}.test-frontend-eval);
      test-all = forAllSystems (system: self.packages.${system}.test-all);
    };
}
