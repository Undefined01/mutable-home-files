# Frontend tests

Frontend module tests now run through `frontend/tests/eval.nix` and the flake check `checks.<system>.frontend-eval`.

The test style is intentionally close to Home Manager's lightweight module tests: evaluate a Home Manager configuration graph and assert on generated payloads and activation blocks, rather than booting a VM.

The flake now evaluates these tests directly during normal Nix evaluation and only uses a tiny derivation as the final pass/fail carrier. It no longer shells out to a nested `nix eval` inside the build.

Current coverage includes:

- option validation for `value/source/path`
- option validation for `includes/excludes`
- target path relativity
- runtime path absoluteness
- task-file shape generation
- activation hook generation, including `run --silence`, `verboseEcho`, and `writeBoundary` ordering
- default and custom `xdg.stateHome`
- multi-entry ordering behavior
- flake default module wiring that injects the packaged backend
