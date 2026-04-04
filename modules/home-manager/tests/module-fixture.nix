{ ... }:

{
  home.homeDirectory = "/home/tester";
  home.stateVersion = "24.11";

  home.mutableFiles.".config/demo/config.json" = {
    format = "json";
    ownership = {
      rules = [
        { path = [ "runtime" ]; mode = "local"; }
      ];
    };
    layers = [
      {
        name = "defaults";
        value = {
          app = {
            name = "demo";
          };
          runtime = {
            enabled = false;
          };
        };
        to = [ ];
      }
    ];
  };
}
