# clean-cargo-single — expected result

A single-crate cargo repo. The workflow runs `cargo test`,
`cargo build`, and `cargo run --bin singlecrate`; the `singlecrate`
binary exists (declared by the `[[bin]]` section in `Cargo.toml`,
backed by `src/main.rs`), and the library target is `src/lib.rs`.

**Expected once a cargo resolver exists: 0 findings, exit 0.**
Every cargo command in the workflow resolves against this repo.

**Today (no cargo resolver yet):** cargo segments are skipped with
the reason `external-tool`; the tool reports 0 findings and exit 0,
with `checked` = 0.

This fixture is deliberately **not** registered in the `CLEAN` list
in `run_tests.py` yet: the clean-corpus test asserts `checked > 0`
for every registered fixture, which only becomes true once a cargo
resolver actually checks these segments. Register it in the same
change that lands the resolver.
