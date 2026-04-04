{ python3, python3Packages, yq-go }:

python3Packages.buildPythonApplication rec {
  pname = "mutable-file-runtime";
  version = "0.1.0";
  pyproject = true;

  src = ./.;
  build-system = [ python3Packages.uv-build ];
  dependencies = [ python3Packages.tomlkit python3Packages.uv-build ];

  passthru.tests = {
    pytest = python3Packages.stdenv.mkDerivation {
      name = "${pname}-pytest";
      src = ../.;
      nativeBuildInputs = [ (python3.withPackages (ps: [ ps.pytest ps.tomlkit ])) yq-go ];
      buildPhase = ''
        export HOME="$TMPDIR/home"
        export XDG_CACHE_HOME="$TMPDIR/cache"
        export XDG_STATE_HOME="$TMPDIR/state"
        mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME"
        export PYTHONPATH="$src"
        pytest -p no:cacheprovider $src/runtime/tests/test_core.py -q
      '';
      installPhase = ''
        touch $out
      '';
    };
  };

  meta.mainProgram = "mutable-file-runtime";
}
