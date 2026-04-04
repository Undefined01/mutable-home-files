{ ... }:

{
  home.homeDirectory = "/home/tester";
  home.username = "tester";
  home.stateVersion = "24.11";

  home.mutableFile.".config/demo/config.json" = {
    format = "json";
    ownership = {
      rules = [
        { path = [ "runtime" ]; mode = "local"; }
      ];
    };
    value = {
      app = {
        name = "demo";
      };
      runtime = {
        enabled = false;
      };
    };
  };
}
