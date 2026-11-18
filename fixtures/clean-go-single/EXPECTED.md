# clean-go-single — expected result

A single-module Go repo (`go.mod`, one library package, one command at `cmd/realtool`). The workflow runs `go build ./...`, `go test ./...`, `go vet ./...` and `go run ./cmd/realtool`; every one of them resolves against this repo.

**Expected with a Go resolver: 0 findings, exit 0.**

**Verified today (no Go resolver exists):** the tool reports 0
findings, exit 0, `checked` = 0, with all 4 Go segments skipped as
`external-tool`. Not registered in `run_tests.py` for that reason:
the clean-corpus test asserts `checked > 0` and the missing-corpus
test asserts exactly one finding, neither of which can hold before
a Go resolver lands.
