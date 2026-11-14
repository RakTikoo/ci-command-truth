# clean-cargo-single — expected result

A single-crate cargo repo. The workflow runs `cargo test`,
`cargo build`, and `cargo run --bin singlecrate`; the `singlecrate`
binary exists (declared by the `[[bin]]` section in `Cargo.toml`,
backed by `src/main.rs`), and the library target is `src/lib.rs`.

**Expected with the cargo resolver: 0 findings, exit 0.**
Every cargo command in the workflow resolves against this repo.

Registered in the `CLEAN` list in `run_tests.py`: the clean-corpus
test asserts `checked > 0` for every registered fixture, which the
cargo resolver satisfies by actually checking these segments
(`checked` = 3 here).
