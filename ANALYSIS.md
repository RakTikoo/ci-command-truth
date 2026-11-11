# CI Command Truth — Analysis

Date: 2026-11-10. Status: local build only (not pushed, per H-1B gate).

## Fixture corpus score

Corpus first, tool second. 44 fixture repositories under `fixtures/`
(after the fix pass below):

| Group | Count | Expectation | Result |
|---|---|---|---|
| Clean (`clean-*`) | 29 | 0 findings, exit 0 | **29/29 pass** |
| Planted missing (`missing-*`) | 6 | exactly 1 finding, correct kind, exit 1 | **6/6 found, 0 extra findings** |
| Edge (`edge-*`) | 8 | see below | **8/8 pass** |
| Special (`special-downgrade`) | 1 | warning-severity findings only, exit 0 | **pass** |

(Pre-fix-pass corpus was 21 fixtures: 9 clean / 6 missing / 6 edge.)

Planted misses, one per fixture: missing npm script, missing make
target, missing just recipe, missing `./script` file, missing Python
module (`python -m absentpkg.mod`), missing requirements file
(`pip install -r requirements-missing.txt`).

Edge cases: workflow with no run steps (exit 0, 0 checked), uses:-only
workflow (exit 0), empty workflow file (**listed as unscanned, exit 2 —
never a silent pass**), malformed tab-indented workflow (listed as
unscanned with the tab error, exit 2), CRLF workflow (parses clean),
workflow in a nested `.github/workflows/` subdirectory (ignored, like
GitHub itself, which only loads top-level files there), an empty
`.github/workflows/` directory (unscanned, exit 2), and a malformed
`package.json` (exit-2 error state, no findings).

Clean fixtures cover: npm/pnpm/yarn forms, make (incl. `-C` and bare
`make`), just, `./` and interpreter script paths, `python -m`, `pip -r`,
`&&`/`||`/`;`/`|` chains, env-var prefixes, `sudo`, `${{ }}`
expressions, `$VAR` script names, multi-line `|` and `>` blocks,
step `working-directory:`, and runner wrappers (`uv run make test`,
`poetry run npm run test`).

**Tests: `python3 run_tests.py` — 33 tests, all passing** (corpus
subprocess tests, edge tests, parser/tokeniser unit tests, annotation
format, fix-pass regression units, and a static-safety test asserting
the tool source contains no `subprocess`/`eval`/`exec`/`os.system`).
Plus `python3 spotcheck_fp.py` — 10 fresh-sandbox false-positive
headline cases, all passing (see Adversarial review).

### Bugs the corpus caught during the build

1. `npm run $MY_SCRIPT` was flagged as a missing script — the
   variable-argument guard only inspected the first two tokens, not the
   script name (token 3). Fixed for npm/pnpm/yarn shorthand forms; the
   clean-expressions fixture now passes with all segments skipped.
2. A first test asserted `checked > 0` for that same expressions
   fixture; correct behaviour there is *all skipped, none checked*, so
   the test was corrected, not the tool.

## Real-world run (hand-labelled)

Ran on every local tree with a `.github/workflows/` directory found
under `~/workspace/agentic-spikes/` and `~/workspace`:

| Root | Workflows | Checked | Skipped | Findings | Hand label |
|---|---|---|---|---|---|
| skillscan-src | 1 | 6 | 0 | 0 | TN — all six `python3 run_*.py` files exist |
| kicad-preflight-src | 1 | 3 | 0 | 0 | TN — all three test-runner files exist |
| stranger-suite-src | 1 | 1 | 0 | 0 | TN — `python3 tests/run_tests.py` exists |
| tmp-freshclone (SkillScan clone) | 1 | 3 | 0 | 0 | TN |
| benchmarks/tools/spector-src (NVIDIA SkillSpector) | 4 | 8 | 90 | 0 (after fix, see below) | TN — hand-verified: Makefile targets `install-dev`, `lint`, `format-check`, `test-ci` via `make` and `uv run make …`; `node --test` files and `tests/docker/smoke.sh` all exist |
| kicad corpus: upsy-desky | 2 | 0 | 15 | 0 | TN — runs are `pip install esphome` / `esphome compile` / `cp` / `mkdir` (all external) |
| kicad corpus: esp-rust-board | 1 | 0 | 0 | 0 | TN — uses:-only workflow in the wild |

**Precision on labelled findings: 1 finding was produced across these
runs and it was a false positive (see below), so post-fix precision is
vacuous (0 findings); pre-fix it was 0/1.** Recall on real-world data
cannot be measured from these trees — none of them contains a genuinely
broken `run:` reference, which is exactly why the planted corpus
carries the recall number (6/6).

### The one real-world false positive — and its fix

SkillSpector's `release.yml` runs `uv run --no-sync python -m build
--no-isolation`. The first version flagged top-level package `build` as
missing: `build` is the PyPI *pypa/build* tool, installed in the
environment, not repo-local. Fix: `python -m X` is only checked when
`X`'s top level is **not** a Python standard-library module
(`sys.stdlib_module_names`, e.g. `http.server`, `unittest`) and **not**
in a known-installed-tools list (`build`, `pytest`, `coverage`,
`twine`, …). The same run also motivated runner-wrapper unwrapping:
`uv run make lint` previously hid the inner `make` entirely (3 missed
checks in SkillSpector's CI); `uv run` / `poetry run` / `pipenv run` /
`bundle exec` / `conda run` are now unwrapped and the inner command
resolved. Both fixes are covered by fixtures/tests.

## Incumbent re-verification: actionlint

Re-checked 2026-11-10 via web search of actionlint's documented check
list (rhysd/actionlint, ~40 checks). Its `run:`-related checks are:
shellcheck integration and pyflakes integration (style/correctness of
the shell/Python *text*), script-injection detection for untrusted
`${{ }}` values, and shell-name validation. **No check in actionlint's
list resolves a `run:` command against `package.json` scripts,
Makefile targets, justfile recipes, or files on disk** — shellcheck
will happily pass `npm run nosuchscript`. Claim confirmed: actionlint
does NOT do this job. (Caveat: this is a documentation-level check of
the published checks list, not a source audit or a differential run.)

## Known limitations

- **Shell grammar subset.** No functions, no `case` bodies, no
  arithmetic; command/process substitution *contents* are replaced by
  a placeholder and not analysed; heredoc bodies are treated as data.
  Anything the subset cannot understand is counted as *skipped with a
  reason*, not flagged — the failure mode is a missed check, never a
  false alarm. `cd` tracking is pragmatic: main-level literal `cd`
  persists for the rest of the run block, subshell `cd` is scoped to
  its subshell, `cd` inside an `if`/`while` condition does not apply.
- **YAML extractor subset.** Indentation-based, with a key-path stack
  so nested keys are attributed correctly; handles single-line, `|`
  and `>` (folded, joined) block values, plain multi-line scalars,
  anchors/tags (stripped), per-job `defaults:`. No flow style and no
  multi-document files — a file mentioning `run:` that yields no
  steps is listed as unscanned, not passed.
- **`python -m` is conservative by design:** *(v0.2: submodules of a
  repo-local top-level package ARE now checked — see the v0.2 section
  below.)* Non-local modules are only checked at the top level, only
  when the top is neither stdlib (unless a local regular package
  shadows the stdlib name) nor a known installed tool and the
  workflow does not install Python packages; `src/` layout is
  recognised.
- **Monorepos (partial):** workspace-member resolution works when the
  member is identifiable — an explicit `--workspace` / `-w` /
  `--filter` / `yarn workspace` value that is an existing path or a
  member name, or a `working-directory` / `-C` pointing at the member.
  `--workspaces` (all members) and unidentifiable selectors are
  skipped with reason `workspace`. Full monorepo resolution (inferring
  the member from context with no selector) is NOT done — accepted
  limitation.
- Make parsing follows `include` (recursive, cycle-safe), pattern and
  suffix rules, and targets that exist as files on disk; it does NOT
  evaluate `$(eval …)` / variable-built target names — those remain a
  gap (accepted limitation). Case-sensitivity of path checks follows
  the host filesystem, so a Windows-only case mismatch in a path is
  not caught when scanning on Linux (accepted limitation).
- justfile parsing follows `mod` / `import`, aliases, parameter
  defaults and `@quiet` recipes.
- `npx X` / `bunx X` are not resolved (they may legitimately fetch a
  package that is not in the repo at all).

## Expansion ladder

1. More ecosystems behind the same interface: `cargo` (workspace bins),
   `go run ./cmd/...`, `task` (Taskfile), `tox`/`nox` environments,
   `composer run`, `bundle exec rake` targets, Rakefile.
2. ~~`python -m` submodule checking when the top-level package is
   repo-local~~ — **done in v0.2** (see below).
3. Full monorepo resolution beyond identifiable workspace selectors.
4. Optional `--strict-skips` mode that fails on skipped segments for
   repos that want full proof rather than best-effort.
5. ~~SARIF output for code-scanning upload~~ — **done in v0.2**.

(Done in the fix pass below, previously on this ladder: npm/pnpm/yarn
workspace selectors, Makefile `include` following, justfile
`mod`/`import` following.)

## GitHub integration story

- **Today (this build):** run it as a step —
  `run: python3 ci_command_truth.py . --github-annotations` emits
  `::error file=<workflow>,line=<n>::<message>` lines, which GitHub
  renders as PR annotations on the exact workflow line, and
  `::warning` lines for unscanned files. Exit 1 fails the job.
  `action.yml` in this repo wraps the same command as a composite
  action, so `uses: <owner>/ci-command-truth@v1` would work the day it
  is published (it is **not** published — local build only).
- **Next:** a pre-commit hook entry and a `problemMatcher` JSON for
  editor integration are trivial additions on the same output format.
- **Not planned:** a hosted service. The tool's value is that it is
  zero-dependency, offline, and deterministic.

## Adversarial review

Three independent reviews (red-team / false-positive / code-audit) ran
103 clean false-positive sandboxes, of which **60 fired** before the
fix pass, plus several silent-pass bugs. Fix pass applied 2026-11-10,
guided by: *when static resolution is genuinely uncertain, SKIP with a
named reason (counted as skipped) rather than flag.* Before/after per
item:

### Critical correctness / silent-pass fixes

1. **`read_capped` truncation — FIXED.** Before: read only 200,001
   bytes against a 1 MB cap, silently truncating files between 200 KB
   and 1 MB (both missed findings and false positives). After: reads
   up to the real 1 MB cap (binary read + decode); anything beyond
   the cap is an oversized error, never a truncated scan. Unit test
   covers 500 KB (fully read) and 1.1 MB (oversized).
2. **Empty `.github/workflows/` dir — FIXED.** Before: directory with
   no `.yml`/`.yaml` files scanned as OK. After: unscanned entry
   ("no workflow files"), exit 2. Fixture `edge-empty-workflows-dir`.
3. **Binary workflows / symlink loops — FIXED.** Before: NUL-containing
   files were scanned as text-clean; symlink-loop files were silently
   dropped by `isfile`. After: NUL check → unscanned; discovery
   includes symlinks so a loop surfaces as an unscanned entry. Unit
   tests for both.
4. **package.json failure states — FIXED.** Before: malformed JSON was
   a warning + skip; deep nesting could raise uncaught
   `RecursionError`; oversized/unreadable resolver files were treated
   as an empty script set. After: malformed (incl. `RecursionError`,
   now caught alongside `ValueError`) is an exit-2 error state listed
   like an unscanned file (fixture `edge-malformed-package-json`);
   non-string script values do not count as present; oversized or
   unreadable resolver files (package.json, Makefile, justfile)
   propagate a warning and make resolution *unknown* — dependent
   checks skip with reason `resolver-file-unknown`, never an empty set.
5. **Extractor depth bugs — FIXED.** The extractor now tracks a
   key-path stack by indent. Before: a `run:` key nested under a
   step's `with:`/`env:` was treated as the step's run; bodies of
   non-`run` block scalars (`script: |`, `text: |`) could leak into
   parsing; `strategy.matrix.include` dash items and out-of-job
   `steps:` could create phantom steps; a bare `-` dash started no
   step; a step whose first key was not a known starter was missed.
   After: only dashes whose parent path is a job-level `steps:` key
   create steps; block scalars are tracked for *any* key; bare `-`
   and any-first-key steps are recognised. Fixture `clean-nested-run`,
   `clean-matrix-steps`, plus unit tests.
6. **Per-job `working-directory` defaults — FIXED.** Before: one
   global last-wins default leaked across jobs. After: defaults are
   scoped workflow → job (job overrides for that job only, reset at
   each job boundary). Fixture `clean-per-job-defaults` (job C proves
   the reset; it failed before the fix).
7. **YAML forms — FIXED (one accepted limitation).** Folded `>`
   scalars are joined into logical lines before segment splitting;
   plain multi-line `run:` scalars are joined; block headers accept
   indent indicators and comments (`|2`, `>2-`, `|- # comment`);
   anchors/tags on `run:` (`&cmd`, `!!str`) are stripped and the
   remainder parsed. If a file contains `run:` text outside block
   bodies but yields 0 steps, it is now unscanned, not clean. **Full
   flow style stays unsupported → unscanned (accepted limitation).**
   Fixtures `clean-folded`, `clean-block-indicator`.
8. **Shell semantics — FIXED (pragmatic subset).** Trailing `#`
   comments are stripped quote-aware before splitting; `$(...)`,
   backtick and `<(...)`/`>(...)` substitution contents are replaced
   by a placeholder before splitting (their separators no longer
   split the outer command); heredoc bodies are data and skipped;
   `cd` no longer persists out of a subshell group or an
   `if`/`while` condition, `cd -- dir` works, and `cd -` returns to
   the previous directory. Fixtures `clean-trailing-comment`,
   `clean-env-subst`, `clean-heredoc`, `clean-cd-advanced`.
9. **Interpreter flags — FIXED.** Per-interpreter flag tables:
   `bash`/`sh` `-e` is a mode flag, only `-c` is inline code (before:
   `bash -e script.sh` was skipped as inline code — a silent miss);
   `python`/`node` flag-with-value skipping (`-W`, `-X`, `-r`,
   `--import`, …) finds the real file argument; `python -m` is
   recognised after leading global flags (`python -u -m`, `python -W
   ignore -m`). Fixture `clean-python-flags`.
10. **just / make parsers — FIXED.** just: parameter defaults
    (`build target='release':`), `@quiet` recipes, aliases
    (`alias t := test` makes `just t` resolve), `mod`/`import`
    following, `just -f`/`--justfile` honoured. make: `include`
    following (recursive, cycle-safe), `-f`/`--file` honoured,
    pattern rules and suffix rules count as providing a target, a
    target existing as a file/dir on disk is not missing, `#` comments
    stripped in `.PHONY`/target parsing, `define`/`endef` bodies
    skipped. Fixtures `clean-just-advanced`, `clean-make-advanced`.
11. **npm workspaces — FIXED (identifiable members).** `npm run X
    --workspace=<path|name>` / `-w` resolve against the member
    package.json when the member is identifiable (existing path, or a
    member name from the root `workspaces` globs / pnpm-workspace.yaml);
    `--workspaces` and unidentifiable selectors skip with reason
    `workspace`. `pnpm --filter` likewise; `yarn workspace <name>`
    resolves. Fixture `clean-workspaces`. Full context-inferred
    monorepo resolution remains an accepted limitation.
12. **Step context — FIXED.** `shell:` values `python`/`python3`/
    `pwsh`/`powershell`/`cmd` skip the run body with reason
    `non-shell run body`. Windows backslash paths are normalised
    (`\` → `/`) before existence checks — including protecting path
    backslashes from shlex's escape handling, which previously mangled
    `tools\check.py` into `toolscheck.py`. Fixtures
    `clean-shell-skip`, `clean-backslash`.
13. **`if:` / tolerated failure — FIXED.** Steps and whole jobs with
    literal `if: false` / `if: ${{ false }}` are skipped entirely
    (reason `if-false`). Segments joined by `||` on either side and
    steps with `continue-on-error: true` produce **warning-severity**
    findings — reported, but the exit code is unaffected (fixture
    `special-downgrade`: 2 warnings, exit 0). `$`-containing resolution
    targets (`pip -r $VAR`, `make -C $DIR`, `-f $FILE`, …) now skip
    with `variable-argument` in *all* resolver branches.
14. **Dynamic creation tracking — FIXED.** Files visibly created
    earlier in the same workflow (steps in order, segments in order)
    are tracked: `>`/`>>` redirections, `cp`, `mv`, `touch`,
    `curl -o`/`-O`, `wget -O`, `git clone <url> <dir>` (the dir and
    everything under it), and a second `actions/checkout` with
    `path:` (everything under the path). Later references skip with
    reason `created earlier in workflow`; `./node_modules/.bin/*`
    skips as `installed artifact`. `mkdir` alone deliberately does
    not create files. Fixture `clean-created`.
15. **`python -m` with an install step — FIXED.** If any step in the
    same workflow installs Python packages (`pip install`,
    `pip install -r`, `uv pip install`, `poetry install`,
    `pipenv install`), an unknown non-local module skips with reason
    `assumed installed (workflow installs packages)` instead of being
    flagged. With no install step, it is still flagged (the planted
    `missing-python-module` fixture still fires). Fixture
    `clean-install-python-m`.
16. **env prefixes / module whitelist order — FIXED.** `env -u`,
    `-C`, `--unset` (and friends) consume their values instead of
    being mistaken for the command. `KNOWN_EXTERNAL_MODULES` is now
    strictly a fallback: repo-local existence is checked FIRST and the
    whitelist only means "assumed installed" afterwards.
17. **working-directory escaping the repo — FIXED.** A step base (or
    any resolved path) outside the repo root skips path checks with
    reason `outside-repo-root`; the tool never resolves outside the
    root.

### Auditor test-gap additions

Fixtures/tests now cover: pnpm/yarn/bun forms (claims match reality —
`pnpm X` and `yarn X` shorthand are genuinely checked, `bun` only via
`bun run`), folded + plain multi-line scalars, per-job defaults,
`python -m` stdlib/known/local modules, `cd` against **different**
root vs sub Makefiles (the old `clean-chains-env` sub-Makefile was
byte-identical to the root one and proved nothing — replaced, and a
unit test asserts the pairs differ), exit-code precedence
(findings + unscanned → exit 2, with both FAIL and ERROR clauses in
the text report), empty workflows dir, malformed package.json, `|2`
headers, `with:`/`env:` nested `run:`, matrix dashes, just
defaults/`@`/alias/`mod`, make `include`/`-f`/pattern rules, heredoc,
trailing comments, `||` and `continue-on-error` downgrades,
`if: false`, workspace forms, backslash paths, created-file cases
(redirect + checkout path + clone + cp + touch), and the install-step
`python -m` skip.

### Results after the fix pass

- **Corpus:** 44 fixtures — 29/29 clean, 6/6 planted misses (no extra
  findings), 8/8 edge, 1/1 special. (Before: 21 fixtures.)
- **Tests:** `run_tests.py` 17 → **33 tests, all passing**.
- **FP spotcheck** (`spotcheck_fp.py`, fresh temp sandboxes, not the
  committed fixtures) — the hunters' headline cases: workspace npm,
  make include/`-f`/pattern, just defaults/mod/alias, per-job
  defaults, heredoc text, `if: false`, `|| true`, windows backslash,
  dynamic `gen.sh`, second-checkout path — **10/10 clean or
  skipped-with-reason, 0 error findings**.
- **Real-world re-run** on the same 7 local roots as the original
  hand-labelled run: **0 findings everywhere**, with checked counts
  identical to before (skillscan-src 6, kicad-preflight-src 3,
  stranger-suite-src 1, tmp-freshclone 3, SkillSpector 8 across 4
  workflows, upsy-desky 0, esp-rust-board 0) — no coverage was traded
  away to buy the precision.

### Remaining unfixed — documented limitations, not bugs

- Full flow-style YAML workflows → unscanned (exit 2), by design.
- Full monorepo resolution: only identifiable workspace members
  resolve; see item 11.
- Make targets built by `$(eval …)` or variable expansion are not
  resolved.
- Path case-sensitivity follows the host filesystem (a Windows-only
  case mismatch is invisible when scanning on Linux).
- Heredoc/substitution handling is a pragmatic subset (see Known
  limitations); anything unrecognised degrades to a named skip.


---

## v0.2 wave (2026-11-10) — SARIF, did-you-mean, `python -m` submodules, dogfood

Status: local build only, NOT pushed (push/tag is a separate decision).
Tool version constant is now `0.2.0`.

### What was built

1. **SARIF output (`--sarif`).** SARIF 2.1.0, mirroring the `--json`
   pattern; `--json` + `--sarif` together are a usage error (exit 2),
   and `--github-annotations` now also rejects combination with either
   machine mode (it appended lines to the document and corrupted it —
   auditor M2; it still pairs with the default text output the bundled
   Action uses). Findings → results with level error/warning by
   severity, locations at workflow file + line, a stable full rule
   table on every run, tool name/version. Unscanned files are
   error-level `toolExecutionNotifications` (never results), with
   `unscannedCount`/`exitCode` in run properties and
   `executionSuccessful: false` when any file is unscanned. Artifact
   URIs are percent-encoded repo-relative paths via
   `quote_from_bytes(os.fsencode(...))` (a non-UTF-8 filename crashed
   the naive `quote()` — red team, fixed + regression test).
2. **Did-you-mean.** `_suggest()` scores candidates with difflib
   ratios (cutoff 0.6, at most one, ties break alphabetically).
   Attached for missing npm/pnpm/yarn scripts, make targets, just
   recipes and `python -m` modules; appears in text, `--json`
   (`suggestion` field on every finding), SARIF (message +
   properties) and annotations. Never changes verdict/severity/exit.
   For submodules, similarity is judged on the differing segment only
   (red team: the shared dotted prefix inflated full-string ratios so
   unrelated siblings always "matched"). Unknown candidate sets (no
   package.json/Makefile/justfile) yield no suggestion.
3. **`python -m` submodule checking** — only when the top-level
   package is repo-local (step base or `src/` layout), per the v1
   expansion ladder. A PEP 420 resolver merges namespace portions
   across both roots at every level (a regular package / module file
   is a winner that shadows portions); parts accept `part.py`,
   `part/` dirs, and compiled modules with a genuine platform
   extension suffix (`importlib.machinery.EXTENSION_SUFFIXES`, real
   files only). A directory used as the final `-m` target must
   contain `__main__.py` — anything else is a guaranteed runtime
   failure, not an uncertainty. Packages whose `__init__.py` (AST
   check: real def/import/assignment of `__getattr__`, or real
   `sys.modules` use; comments/docstrings do not count) can invent
   submodules skip as `dynamic-module`; unparseable `__init__.py`
   also skips. Non-identifier parts skip as
   `unresolvable-module-name` when the literal top exists on disk;
   a wholly nonexistent top is a normal missing-top finding. A local
   regular package shadows a same-named stdlib module and is then
   submodule-checked (auditor M1); a namespace-only namesake does
   not shadow stdlib. Non-local behaviour is otherwise exactly v1.
4. **Dogfood + consumer-Action simulation** (below). The project's
   own `.github/workflows/tests.yml` already contained the self-check
   step (`python3 ci_command_truth.py . --github-annotations`); it was
   verified present and the own-tree run stays clean (2 checked, 0
   findings). A real `uses: RakTikoo/ci-command-truth@v...` run on
   GitHub still only happens after a push/tag decision.

### Corpus before/after (explicit changes, never silent)

- Fixtures 44 → **47**: clean 29 → **31** (new
  `clean-python-submodule` — incl. `src/` layout; new
  `clean-python-namespace`), planted missing 6 → **7** (new
  `missing-python-submodule`: `pkg.modd` beside real `pkg.mod`,
  exactly 1 finding, suggestion `pkg.mod`), edge 8, special 1.
- **Fixture corrections forced by the submodule check:** the v1
  fixtures `clean-python-known`, `clean-python-flags` and
  `clean-install-python-m` all reference `python -m pkg.mod` but
  contained only `pkg/__init__.py` — v1 never actually resolved
  `mod`. Each gained the `pkg/mod.py` its workflow always claimed,
  and `clean-python-submodule`'s `pkg/nested/` gained the
  `__main__.py` its `python -m pkg.nested` run requires. Without
  these, the new check would (correctly) have flagged them.
- Score after: **31/31 clean, 7/7 planted (0 extra findings), 8/8
  edge, 1/1 special.**
- Tests: `run_tests.py` 33 → **70 tests, all passing** (suggestion
  unit tests incl. no-suggestion/determinism/tie-break; submodule,
  namespace-split, dynamic, stdlib-shadow and `__main__` tests; SARIF
  structure/rule-crossref/level/unscanned/escaping/mutual-exclusion/
  exit-code tests; review regression tests). `spotcheck_fp.py`
  10 → **14/14** (adds namespace, src-layout, dynamic-module and
  split-namespace cases).

### Dogfood (v0.2 tool, hand-labelled)

| Root | Workflows | Checked | Skipped | Findings | Hand label |
|---|---|---|---|---|---|
| skillscan-src | 1 | 6 | 0 | 0 | TN |
| kicad-preflight-src | 1 | 3 | 0 | 0 | TN |
| stranger-suite-src | 1 | 1 | 0 | 0 | TN |
| round3-trio/expiry-radar | 1 | 3 | 2 (shell-builtin) | 0 | TN |
| round3-trio/phantomdep-pr-gate | 0 | 0 | 0 | 0 (1 unscanned: no `.github/workflows/` dir, exit 2) | Expected — this product intentionally has no tests workflow of its own (its Action runs in consumer repos); not a finding |
| ci-command-truth (own tree) | 1 | 2 | 0 | 0 | TN |
| benchmarks/tools/spector-src (regression extra) | 4 | 8 | 89 | 0 | TN — checked/findings identical to v1 |

Consumer-Action simulation (scratch repo outside the product tree,
`~/workspace/agentic-spikes/scratch/cct-consumer-sim/`, log in
`simulation.log` there): a consumer repo using the bundled composite
action (local-path `uses:` form) with the action's run block executed
exactly as written in `action.yml` — (a) clean consumer: exit 0,
3 checked, 0 findings; (b) planted `npm run nosuchscript`: exit 1
with `::error file=.github/workflows/ci.yml,line=7::…` annotation.
Re-run with the final post-review build: identical results.

### Adversarial review (3 independent reviewers) and fix pass

- **False-positive hunter:** 48 fresh sandboxes + 3 SARIF repos, 40
  runtime-verified clean with real CPython. **1 HIGH root cause:**
  namespace packages split across root/`src/` portions were falsely
  flagged (5 sandboxes, incl. a misleading suggestion). Root cause:
  the walk committed to the first root. Fixed with the PEP 420
  multi-portion resolver above + 4 unit tests + 1 spotcheck case;
  hunter's case 04a re-run clean. 2 LOWs (top-level `.so` message
  wording; SARIF `results: []` on unscanned repos — mitigated by
  design via notifications + properties) recorded; the first is
  accepted (the verdict matches real `python -m` behaviour), the
  second is the documented design.
- **Code auditor:** 0 Critical, **1 High, 3 Medium, 7 Low**.
  H1 `make -f`/`just -f` escaped the repo root (outside files read,
  outside paths leaked into `looked_in`/SARIF) — fixed with
  `_within_root` guards on both file arguments (this was a v1 bug;
  SARIF/`looked_in` made the leak visible). M1 stdlib-named local
  packages never submodule-checked — fixed (shadowing rule above).
  M2 `--json`/`--sarif` + `--github-annotations` corrupted stdout —
  fixed (combination rejected, exit 2). M3 annotation `file=`
  properties and unscanned lines unescaped — fixed with GitHub
  property escaping (`% \r \n : ,`) + hostile-filename test. Lows
  fixed: dead `defaultConfiguration` ternary removed, SARIF rule
  table stabilised, `executionSuccessful` reflects unscanned files,
  bad root emits a machine-readable document in `--json`/`--sarif`
  modes, `_dir_child` gives a package dir precedence over a
  same-named module file (CPython order). L6 (`informationUri`)
  assessed not-a-defect: the repo is live, the URI is correct.
  Clean areas confirmed by the auditor: determinism across
  PYTHONHASHSEED values in all modes, the full exit-code matrix
  (36/36), stdlib-only imports, static-safety (no
  subprocess/eval/exec/os.system strings), and finding-shape
  consistency across all fixtures.
- **Red team:** 3 High, 8 Medium, 2 Low (several Mediums duplicated
  auditor items already fixed in the parallel pass: `-f` escape,
  annotation injection, `executionSuccessful`). New fixes:
  SARIF crash on non-UTF-8 filenames (bytes quoting); `python -m`
  was the only checker without an outside-root guard for a `cd`'d
  base (fixed + test); final-directory `-m` targets require
  `__main__.py`; dynamic-package detection moved from substring to
  AST (comment-planted bypass closed); compiled-module acceptance
  tightened to genuine platform suffixes + real files;
  non-identifier module names no longer suppress the missing-top
  check when nothing exists on disk; submodule suggestions judged
  on the differing segment; suggestion tie-break and top-level
  candidate hygiene (package-like dirs only).
  **Accepted, not fixed (documented):** the unconditional `src/`
  fallback and untracked `env -C`/`pushd` directory changes — both
  are the pre-existing v1 model (the v0.2 spec retains `src/` "per
  existing logic"; shell tracking is the documented pragmatic
  subset), and changing them is a separate slice, not this wave.

### Remaining limitations (v0.2 additions)

- `python -m` resolution models `sys.path` as (step base, `src/`)
  only — PYTHONPATH entries, editable-install `.pth` targets beyond
  `src/`, and venv site-packages are not modelled; anything they
  would resolve that is not repo-local stays skipped or top-level
  only, per the design rule.
- A final-directory `-m` target is judged on `__main__.py` presence
  in the merged portions; a `__main__.py` that itself imports missing
  modules is out of scope (existence, not execution).
- Did-you-mean uses plain string ratios: it can suggest a
  semantically unrelated but textually close name; it remains
  advisory-only for exactly that reason.
- SARIF validation is structural (schema-shape, rule cross-refs,
  level values) — no official SARIF validator was run locally.
- Top-level compiled modules (bare `name.so`) are still reported as
  a missing top-level package: the verdict matches real `python -m`
  (which cannot execute an extension module), but the wording does
  not distinguish "exists as compiled module" (FP hunter LOW,
  accepted).
