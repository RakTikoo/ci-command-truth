# clean-cargo-workspace — expected result

A cargo workspace with two member crates, `alpha` and `beta`
(declared in the root `Cargo.toml` `[workspace]` section, each with
its own `Cargo.toml` and `src/lib.rs`). The workflow runs
`cargo test -p alpha`, `cargo test -p beta`, and
`cargo build --workspace`; both `-p` package names are members of
the workspace.

**Expected once a cargo resolver exists: 0 findings, exit 0.**
Both `-p` selections resolve to workspace members.

**Today (no cargo resolver yet):** cargo segments are skipped with
the reason `external-tool`; the tool reports 0 findings and exit 0,
with `checked` = 0.

This fixture is deliberately **not** registered in the `CLEAN` list
in `run_tests.py` yet: the clean-corpus test asserts `checked > 0`
for every registered fixture, which only becomes true once a cargo
resolver actually checks these segments. Register it in the same
change that lands the resolver.
