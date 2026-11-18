# clean-go-pinned-tools — expected result

A single-module Go repo whose workflow installs version-pinned external tools (`go install honnef.co/go/tools/cmd/staticcheck@v0.5.1`, `go install golang.org/x/vuln/cmd/govulncheck@v1.1.3`) and also runs `go build -o bin/realtool ./cmd/realtool`, `go run ./cmd/realtool` and `go test -race -count=1 ./...`. Pinned installs name remote modules, not repo-local targets, so a future Go resolver must not flag them.

**Expected with a Go resolver: 0 findings, exit 0.**

**Verified today (no Go resolver exists):** the tool reports 0
findings, exit 0, `checked` = 0, with all 5 Go segments skipped as
`external-tool`. Not registered in `run_tests.py` for that reason:
the clean-corpus test asserts `checked > 0` and the missing-corpus
test asserts exactly one finding, neither of which can hold before
a Go resolver lands.
