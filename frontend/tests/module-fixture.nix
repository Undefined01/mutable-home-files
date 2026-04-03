{ ... }:

{
  home.homeDirectory = "/home/tester";
  home.stateVersion = "24.11";

  home.mutableFile.".config/demo/config.json" = {
    format = "json";
    value = {
      app = {
        name = "demo";
      };
      runtime = {
        enabled = false;
      };
    };
    excludes = [ [ "runtime" ] ];
  };
}
