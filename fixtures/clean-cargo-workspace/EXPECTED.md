# clean-cargo-workspace — expected result

A cargo workspace with two member crates, `alpha` and `beta`
(declared in the root `Cargo.toml` `[workspace]` section, each with
its own `Cargo.toml` and `src/lib.rs`). The workflow runs
`cargo test -p alpha`, `cargo test -p beta`, and
`cargo build --workspace`; both `-p` package names are members of
the workspace.

**Expected with the cargo resolver: 0 findings, exit 0.**
Both `-p` selections resolve to workspace members.

Registered in the `CLEAN` list in `run_tests.py`: the clean-corpus
test asserts `checked > 0` for every registered fixture, which the
cargo resolver satisfies by actually checking these segments
(`checked` = 3 here).
