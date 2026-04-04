# Home Manager module tests

Home Manager module tests run through `modules/home-manager/tests/eval.nix` and the flake check `checks.<system>.home-manager-eval`.

The test style stays intentionally close to Home Manager's lightweight module tests: evaluate a Home Manager configuration graph and assert on generated task payloads and activation blocks, rather than booting a VM.

The flake evaluates these tests directly during normal Nix evaluation and only uses a tiny derivation as the final pass/fail carrier. It does not shell out to a nested `nix eval` inside the build.

Current coverage includes:

- option validation for layered `value`/`source`/`path` inputs
- target path relativity
- runtime path absoluteness
- requirement that each mutable file defines at least one layer
- task-file shape generation for schema v4 `documents` and ordered `layers`
- activation hook generation, including `run --silence`, `verboseEcho`, and `writeBoundary` ordering
- default and custom `xdg.stateHome`
- multi-entry ordering behavior
- flake default module wiring that injects the packaged runtime
