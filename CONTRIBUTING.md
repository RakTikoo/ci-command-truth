# Contributing to CI Command Truth

Thanks for your interest. This project has a small surface and a
strict quality bar — the rules below are the whole game.

## The ground rules

1. **Zero dependencies.** Python standard library only. A pull request
   that adds a dependency will not be merged.
2. **Static only, ever.** The tool never executes the code it scans
   (a test asserts the source contains no `subprocess` / `eval` /
   `exec` / `os.system`). No network access, deterministic output.
3. **Uncertain means skip, never flag.** When static resolution is
   genuinely ambiguous, the segment is counted as *skipped* with a
   named reason. A false positive is the worst bug this tool can
   have — it is why people uninstall checkers.
4. **Fixture-first.** New behaviour starts as fixtures, not code.

## Development

You need Python 3 (standard library only — nothing to install):

```console
$ python3 run_tests.py       # the full suite — must pass
$ python3 spotcheck_fp.py    # false-positive headline cases — must pass
$ python3 ci_command_truth.py .   # the tool, run on its own repo
```

## Adding fixtures

Fixtures live in `fixtures/`, one small repo per case:

- `clean-*` — must produce **zero** findings and exit 0
- `missing-*` — exactly one planted missing reference, exactly one
  finding, exit 1
- `edge-*` — unusual shapes (empty files, malformed inputs, CRLF…)
  with an explicitly documented expectation
- `special-*` — warning-severity cases that must not change the exit
  code

If your change alters a corpus count, update the tests, the README
fixture summary and `ANALYSIS.md` in the same change — counts are
never changed silently.

## Adding or extending a resolver

Keep it a small, controlled slice:

1. Fixture corpus first (clean + planted-missing cases).
2. Resolver change, following the existing resolvers' shape.
3. Regression tests for every behaviour you touch, including the
   skip-with-reason path for the ambiguous cases.
4. Document the limits honestly in `README.md` and `ANALYSIS.md` —
   what the resolver does *not* model is part of the feature.

Good starter slices are listed in the issues labelled
**good first issue** — fixture packs for ecosystems on the expansion
ladder (for example `cargo` or Taskfile shapes) are a natural fit,
because they land the corpus before any checker code has to change.

## Pull request checklist

- [ ] `run_tests.py` and `spotcheck_fp.py` both pass
- [ ] New behaviour has fixtures in both directions (must-flag and
      must-not-flag)
- [ ] No new dependencies, no network, no execution of scanned code
- [ ] Output is deterministic (stable ordering everywhere)
- [ ] README / ANALYSIS / CHANGELOG updated where they describe the
      changed behaviour

## Reporting problems

Bugs: open an issue with a minimal repo (or fixture) that reproduces
it — a false-positive report with a small clean repo that gets
flagged is the most valuable kind.
Security issues: please use private vulnerability reporting, as
described in `SECURITY.md` — not a public issue.
