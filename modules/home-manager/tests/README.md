# Home Manager module tests

Home Manager module tests run through `modules/home-manager/tests/eval.nix` and the flake check `checks.<system>.home-manager-eval`.

The test style stays intentionally close to Home Manager's lightweight module tests: evaluate a Home Manager configuration graph and assert on generated task payloads and activation blocks, rather than booting a VM.

The flake evaluates these tests directly during normal Nix evaluation and only uses a tiny derivation as the final pass/fail carrier. It does not shell out to a nested `nix eval` inside the build.

Current coverage includes:

- empty configuration behavior: no activation entry and an empty `home.mutableFileInternal.taskPayload`
- top-level shortcut normalization for `value`, runtime `source`, and store-backed `source`
- a regression test for `value = config.programs.vscode.profiles.default.userSettings`, which previously crashed while validating shortcut-derived layers
- explicit `layers` normalization, including generated fallback names, `from`, `to`, and `required`
- target normalization to absolute paths and filtering of `enable = false` entries
- entry-level exclusivity for top-level `value` / `source` / `layers`
- layer-level exclusivity for `value` / `source`, including rejection of relative runtime string sources
- ownership validation for `local` subtrees that must not also receive declarative layer writes
- activation hook generation, including `run --silence`, `verboseEcho`, and `writeBoundary` ordering
- default and custom `xdg.stateHome`
- multi-entry ordering behavior
- flake default module wiring that injects the packaged runtime

These tests are intentionally evaluation-focused. They verify module semantics, normalization, and assertion behavior without depending on runtime file I/O.
