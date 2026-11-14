# CI Command Truth

**Prove every `run:` command in your GitHub workflows actually exists — before CI finds out it doesn't.**

A workflow that says `npm run test:unit` when `package.json` has no
`test:unit` script, `make deploy` when the Makefile has no `deploy`
target, or `./scripts/release.sh` when that file was renamed fails only
*after* you push, wait for a runner, and read the log. CI Command Truth
checks those references statically, in milliseconds, with zero
dependencies.

## Demo

A two-file demo repo: `package.json` defines the scripts `test` and
`test:units` — but the workflow asks for `test:unit` (no trailing "s"):

```yaml
# .github/workflows/ci.yml — the last step
      - run: npm run test:unit
```

```console
$ python3 ci_command_truth.py .
CI Command Truth — root: .
Workflows scanned: 1
  scanned: .github/workflows/ci.yml
Segments checked: 1
Segments skipped: 0
Findings: 1
  .github/workflows/ci.yml:8: `npm run test:unit` — missing-npm-script: expected script 'test:unit' (looked in: package.json) — did you mean 'test:units'?
FAIL — missing commands/targets/files found.
$ echo $?
1
```

Real captured output from the shipped v0.2 tool (only the root path is
shortened). The phantom command is caught in milliseconds — locally, or
as a PR annotation with `--github-annotations` — instead of after a
push, a runner, and a log dive.

## What it resolves

| Workflow says | Checked against |
|---|---|
| `npm run X`, `npm test/start/...`, `pnpm run X`, `pnpm X`, `yarn X`, `bun run X` | `scripts` in `package.json` (repo root, or the step's `working-directory`) |
| `npm run X --workspace=<path\|name>` / `-w`, `pnpm --filter …`, `yarn workspace <name> …` | the workspace member's `package.json` when the member is identifiable; otherwise the segment is *skipped* with reason `workspace` |
| `make X`, `make -C dir X`, `make -f file X`, bare `make` | targets in the `Makefile` / `makefile` / `GNUmakefile`, following `include` files; a target matching a pattern/suffix rule, or existing as a file/dir on disk, counts as present |
| `just X`, `just -f file X`, bare `just` | recipes in `justfile` / `Justfile` / `.justfile`, following `mod` / `import` files; recipes with parameter defaults (`build target='release':`), `@quiet` recipes and `alias` names all count |
| `./scripts/x.sh`, `bash x.sh`, `sh ./x.sh`, `python x.py`, `python3 ./x.py`, `node x.js` | the file existing on disk (per-interpreter flag tables: `bash -e` is a mode flag, only `-c` is inline code; `python -W ignore -m pkg` finds the module) |
| `python -m pkg.mod` | the full dotted path, **when the top-level package is repo-local** (`pkg/`, `pkg.py`, or under `src/`): every submodule part must resolve (`pkg/mod.py`, `pkg/mod/` regular or namespace package — namespace portions merged across the root and `src/` trees, PEP 420 style — or a compiled module with a genuine platform extension suffix), and a package used as the final target must contain `__main__.py`. Conservative otherwise: repo-local existence is checked first (a local regular package even shadows a stdlib name); stdlib modules (`http.server`, `unittest`, …) and known installed tools (`build`, `pytest`, `coverage`, …) are assumed installed; if the workflow itself installs Python packages (`pip install`, `poetry install`, …), unknown modules are skipped as *assumed installed*; a package whose `__init__.py` really defines/imports `__getattr__` or uses `sys.modules` can invent submodules at runtime, so its submodules are skipped as `dynamic-module` |
| `pip install -r req.txt` / `-c constraints.txt` | the file existing on disk |

It also unwraps runner prefixes (`uv run make lint`, `poetry run …`,
`bundle exec …`), follows a leading `cd dir` inside a run block
(subshell-scoped `cd` does not leak out; `cd -- dir` and `cd -` work),
splits `&&` / `||` / `;` / `|` chains and checks each segment, strips
env-var prefixes (`FOO=bar cmd`), `sudo`, and `env -u/-C` flags,
skips heredoc bodies and `$(...)` / backtick / `<(...)` substitution
contents, and strips trailing `#` comments (quote-aware). Windows
backslash paths (`.\scripts\run.sh`, `python tools\check.py`) are
normalised before checking. Files a workflow visibly creates earlier
in the same run (`> gen.sh`, `cp`, `touch`, `curl -o`, `git clone`,
a second `actions/checkout` with `path:`) are not flagged when later
steps use them, and `./node_modules/.bin/*` counts as an installed
artifact.

## What it deliberately does NOT flag

False positives are the bug this tool refuses to have:

- shell builtins (`echo`, `cd`, `export`, `[`, `source`, …)
- external/system tools (`docker`, `curl`, `git`, `jq`, `sed`, …) — plus a
  general rule: **a bare command with no repo-local resolution target is
  never checked**
- any segment containing a `${{ }}` GitHub expression or a `$VAR` that
  makes resolution impossible — those are counted as *skipped*, with a
  reason, never guessed at
- steps whose `working-directory:` contains an expression — all path
  checks for that step are skipped, not guessed
- steps (or whole jobs) with a literal `if: false` / `if: ${{ false }}`
- `run:` bodies for non-shell `shell:` values (`python`, `pwsh`,
  `powershell`, `cmd`) — the body is not shell, so it is skipped with
  reason `non-shell run body`
- segments whose failure is tolerated — joined by `||`, or in a step
  with `continue-on-error: true` — are reported as **warnings**, not
  findings; they never affect the exit code
- a resolver file (`package.json` / Makefile / justfile) that exists
  but is too large or unreadable makes its checks *skipped* (reason
  `resolver-file-unknown`, plus a warning), never treated as empty.
  A **malformed** `package.json` is stronger: an error state (exit 2),
  listed explicitly like an unscanned file

## Usage

```console
$ python3 ci_command_truth.py [ROOT]          # ROOT defaults to .
$ python3 ci_command_truth.py . --json        # machine-readable report
$ python3 ci_command_truth.py . --sarif       # SARIF 2.1.0 report (for GitHub code-scanning upload)
$ python3 ci_command_truth.py . --github-annotations   # ::error file=…,line=… lines for PR annotations
```

`--json` and `--sarif` are mutually exclusive, and `--github-annotations`
pairs with the default text output only (appending annotation lines to a
JSON/SARIF document would corrupt it, so the combination is rejected with
exit 2). In SARIF output, findings are results (error findings → `error`,
warning-severity findings → `warning`) located at the workflow file and
line; files that could not be scanned are **not** results — they appear as
error-level tool-execution notifications, with the unscanned count in the
run properties, mirroring exit code 2. Artifact locations are
percent-encoded repo-relative URIs; no absolute paths are emitted.

When a referenced script, target, recipe or module is missing and a close
match exists, every output adds a **did-you-mean** suggestion (e.g.
``did you mean 'test:units'?``) computed with stdlib `difflib` —
deterministic, at most one suggestion, judged on the differing name
segment only. A suggestion is advisory: it never changes a verdict,
severity or exit code, and unrelated names get no suggestion.

Every report states: workflows scanned, segments **checked**, segments
**skipped (by reason)**, every finding as `file:line`, the offending
segment, what was expected and where it was looked for — and every
workflow file that could **not** be scanned (empty, tab-indented,
oversized), listed explicitly. Nothing ever passes silently.

Exit codes: `0` everything checked resolved · `1` something missing ·
`2` usage/parse error (including any unscanned workflow file).

## Use it in GitHub Actions (3 lines)

```yaml
      - uses: actions/checkout@v4
      - name: CI Command Truth
        run: python3 ci_command_truth.py . --github-annotations
```

Or as a (local) action via the bundled `action.yml`; see
`examples/example-workflow.yml`.

## NOT in v1

- No `uses:` action validation (that's actionlint's job — and it does
  it well)
- No GitLab CI / Jenkins / other CI systems
- No `${{ }}` expression evaluation, no matrix expansion
- No shell grammar beyond the documented subset (see ANALYSIS.md)
- No execution of anything, ever: **static parsing only**

## The YAML parser, honestly

PyYAML is not in the Python standard library, and this tool ships with
zero dependencies, so workflow extraction uses a small
indentation-based parser written for this project. It supports
single-line `run:` values, `|` / `>` block scalars (including indent
indicators like `|2` and header comments; folded `>` scalars are
joined into logical lines), plain multi-line scalars, anchors/tags on
`run:` (stripped and parsed), `- run:` inline steps and bare `-`
steps, and step-level plus defaults `working-directory:` — with
defaults scoped **per job** (a job's `defaults:` overrides the
workflow defaults for that job only). Nested `run:` keys under
`with:` / `env:` and the bodies of non-`run` block scalars are never
mistaken for steps, and only dashes inside a job-level `steps:` list
create steps (`strategy.matrix.include` items do not). It does **not**
support flow style or multi-document files; a file that mentions
`run:` but yields no extractable steps is reported as unscanned
(exit 2), never silently passed — as are empty workflow files, binary
files, symlink loops, and an empty `.github/workflows/` directory.
See ANALYSIS.md for the full limitation list.

## Safety

Static only: the tool never executes a scanned repository's code,
scripts, or workflow commands (a test asserts the source contains no
`subprocess`/`eval`/`exec`/`os.system`). File reads are size-capped
(1 MB per file). No network, no LLM, deterministic output.

## Tests

```console
$ python3 run_tests.py     # 70 tests, zero dependencies
$ python3 spotcheck_fp.py  # 14 false-positive headline cases, fresh sandboxes
```

Fixture corpus in `fixtures/`: 31 clean repos that must produce zero
findings, 7 repos with exactly one planted missing reference each, 8
edge-case repos (no-run, uses-only, empty, malformed, CRLF, nested
workflow subdirectory, empty workflows dir, malformed package.json),
and 1 downgrade repo (warning-severity findings, exit 0). A further
3 cargo repos (2 clean, 1 planted-missing) sit alongside them with
documented expectations in their `EXPECTED.md` files; they join the
registered corpus when a cargo resolver lands, since cargo segments
are currently skipped as external tools. See
ANALYSIS.md for the score, including the v0.2 section.

## License

MIT — see `LICENSE`.


---

**More from this workshop:** [SkillScan](https://github.com/RakTikoo/skillscan) · [KiCad Preflight](https://github.com/RakTikoo/kicad-preflight) · [Expiry Radar](https://github.com/RakTikoo/expiry-radar) · [PhantomDep PR Gate](https://github.com/RakTikoo/phantomdep-pr-gate) · [Stranger Suite](https://github.com/RakTikoo/stranger-suite) · [Living Contract Diff](https://github.com/RakTikoo/living-contract-diff) · [Handoff Reconciler](https://github.com/RakTikoo/handoff-reconciler)
