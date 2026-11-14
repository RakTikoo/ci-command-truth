# Changelog

Brief, factual entries for the shipped versions, newest first.

## v0.3.0 — 2026-11-14

- **Taskfile (`task`) target resolution** — workflow `task X` calls
  now resolve against the tasks defined in `Taskfile.yml` /
  `Taskfile.yaml` / `taskfile.yml` (the v3 `tasks:` mapping, read
  line-wise — stdlib only, no YAML parser), following `includes:`
  namespaces (`task ci:verify`) and `flatten:` includes. Task
  `aliases:` names and `*` wildcard task names count; `internal:`
  tasks do not. Bare `task` requires a `default` task; `task
  --list` only requires the file. New finding kinds:
  `missing-taskfile` and `missing-task-target` (with did-you-mean
  suggestions). A Taskfile whose tasks cannot be enumerated
  statically (v2 layout, flow-style or anchor-built mappings,
  remote includes) is treated as unknown — its checks are skipped,
  never flagged. Fixtures: `clean-taskfile`,
  `missing-taskfile-target` and `missing-taskfile` join the
  registered corpus (32 clean / 9 planted-missing); tests 71 → 77,
  spotcheck 14 → 15 cases.
- Fixtures: added a cargo fixture pack (`clean-cargo-single`,
  `clean-cargo-workspace`, `missing-cargo-bin`) with documented
  expectations in each fixture's `EXPECTED.md`, ahead of any cargo
  resolver — corpus first, no tool code changes. The fixtures are
  not yet registered in `run_tests.py`; registration lands with
  the resolver.
- Documentation: corrected stale status lines in `ANALYSIS.md`
  (cross-repo staleness audit, 2026-11-11); added this changelog, a
  `CONTRIBUTING.md`, and the README demo above.


## v0.2.1 — 2026-11-12

- **Fixed the published action manifest** — the `description:` in
  `action.yml` contained an unquoted colon ("Prove every run:
  command ..."), which is invalid YAML, so GitHub could not load
  the action at all: every consumer run failed at "Set up job".
  The description is now quoted. Found by the first real
  cross-repo consumer run; the v0.2 tag is left in place but its
  manifest is unloadable — pin `@v0.2.1`.
- **Regression test** — the suite now strictly parses `action.yml`
  (PyYAML where available, plus a stdlib scan for the same defect
  class), so an unloadable manifest fails tests instead of
  consumers. Tests 70 → 71.

## v0.2 — 2026-11-10

Tagged `v0.2` at commit `1d9cbaa`; CI run #115 success (70 tests).

- **SARIF output** — `--sarif` emits a SARIF 2.1.0 report for GitHub
  code-scanning upload; unscanned files are reported as notifications,
  never as a clean pass.
- **Did-you-mean suggestions** — a missing script, make target, just
  recipe or Python module now suggests the closest existing name
  (e.g. `test:unit` → `test:units`) in the text, `--json`, SARIF and
  annotation outputs. Suggestions never change a verdict or exit code.
- **`python -m` submodule checking** — when the top-level package is
  repo-local (including `src/` layouts and PEP 420 namespace
  packages), every part of the dotted path must now resolve; dynamic
  packages are skipped with a named reason.
- **Dogfood** — run against the author's other project trees and in a
  simulated consumer repo using the bundled composite action (clean
  run passes; a planted phantom command is annotated at the exact
  workflow line).
- Tests 33 → 70; fixture corpus 44 → 47 (31 clean / 7 planted-missing /
  8 edge / 1 special); false-positive spotcheck 10 → 14 cases.
- Fixes from the adversarial review rounds include: split root/`src`
  namespace packages no longer falsely flagged, `make -f` / `just -f`
  can no longer read files outside the repo root, and SARIF output is
  byte-stable across runs.

## v0.1 — 2026-11-10 (initial release)

Shipped at commit `62098a7`; CI run #102 success (33 tests). (This
release was not given a git tag at the time — the first tagged release
is `v0.2`.)

- Static resolution of workflow `run:` commands against `package.json`
  scripts (npm / pnpm / yarn / bun, including identifiable workspace
  members), Makefile targets, justfile recipes, script files on disk,
  `python -m` top-level packages, and `pip install -r` files.
- Output modes: human text, `--json`, and `--github-annotations` (PR
  annotations at the exact workflow line). Exit codes 0 / 1 / 2 —
  an unscanned workflow file is always reported, never silently passed.
- Composite GitHub Action (`action.yml`) wrapping the same command.
- Design rule, from the start: when static resolution is genuinely
  uncertain, the segment is *skipped with a named reason* — never
  flagged. Fixture corpus 44 repos (29 clean / 6 planted-missing /
  8 edge / 1 special); planted misses 6/6 with no extra findings.
- Zero dependencies (Python standard library only), fully static —
  the tool never executes the code it scans.
