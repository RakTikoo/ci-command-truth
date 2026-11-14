# missing-cargo-bin — expected result

A single-crate cargo repo whose only binary is `realbin` (declared
by the `[[bin]]` section in `Cargo.toml`, backed by `src/main.rs`).
The workflow also runs `cargo run --bin ghostbin` — **no binary
named `ghostbin` exists anywhere in this repo.** That is the one
planted missing reference.

**Expected with the cargo resolver: exactly 1 finding, exit 1.**
The finding points at the `cargo run --bin ghostbin` line in
`.github/workflows/ci.yml` and names `ghostbin` as the expected
target (finding kind `missing-cargo-bin`). `cargo test` on the
same workflow produces no finding.

Registered in the `MISSING` map in `run_tests.py`: the
missing-corpus test asserts exactly one finding and exit 1, which
the cargo resolver delivers — this file was the resolver's
acceptance test, and it passes.
