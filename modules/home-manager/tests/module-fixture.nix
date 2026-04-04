{ ... }:

{
  home.homeDirectory = "/home/tester";
  home.stateVersion = "24.11";

  home.mutableFiles.".config/demo/config.json" = {
    format = "json";
    preserve = [ [ "runtime" ] ];
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
