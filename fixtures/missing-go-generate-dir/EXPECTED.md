# missing-go-generate-dir — expected result

A single-module Go repo. The workflow runs `go build ./...` and `go generate ./internal/ghostschema`; **no `internal/ghostschema` directory exists in this repo.** That is the one planted missing reference.

**Expected with a Go resolver: exactly 1 finding, exit 1,** pointing at the planted line in `.github/workflows/ci.yml`. The other command on the workflow produces no finding.

**Verified today (no Go resolver exists):** the tool reports 0
findings, exit 0, `checked` = 0, with all 2 Go segments skipped as
`external-tool`. Not registered in `run_tests.py` for that reason:
the clean-corpus test asserts `checked > 0` and the missing-corpus
test asserts exactly one finding, neither of which can hold before
a Go resolver lands.
