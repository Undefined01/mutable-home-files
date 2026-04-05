{
  git,
  python3Packages,
}:

python3Packages.buildPythonApplication rec {
  pname = "mutable-file-runtime";
  version = "0.1.0";
  pyproject = true;

  src = builtins.path {
    path = ./.;
    name = "runtime";
  };
  build-system = [ python3Packages.uv-build ];
  dependencies = [
    python3Packages.ruamel-yaml
    python3Packages.tomlkit
  ];
  propagatedBuildInputs = [ git ];

  nativeCheckInputs = [
    git
    python3Packages.pytestCheckHook
  ];

  pytestFlags = [ "-s" ];

  meta.mainProgram = "mutable-file-runtime";
}
