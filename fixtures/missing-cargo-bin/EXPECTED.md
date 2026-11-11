# missing-cargo-bin — expected result

A single-crate cargo repo whose only binary is `realbin` (declared
by the `[[bin]]` section in `Cargo.toml`, backed by `src/main.rs`).
The workflow also runs `cargo run --bin ghostbin` — **no binary
named `ghostbin` exists anywhere in this repo.** That is the one
planted missing reference.

**Expected once a cargo resolver exists: exactly 1 finding,
exit 1.** The finding must point at the `cargo run --bin ghostbin`
line in `.github/workflows/ci.yml` and name `ghostbin` as the
expected target (the finding `kind` string is the resolver's to
define, e.g. `missing-cargo-bin`). `cargo test` on the same
workflow must produce no finding.

**Today (no cargo resolver yet):** cargo segments are skipped with
the reason `external-tool`; the tool reports 0 findings and exit 0.
This file is the future resolver's acceptance test — the planted
miss above is what it must catch.

This fixture is deliberately **not** registered in the `MISSING`
map in `run_tests.py` yet: the missing-corpus test asserts exactly
one finding and exit 1, which only becomes true once a cargo
resolver exists. Register it in the same change that lands the
resolver.
