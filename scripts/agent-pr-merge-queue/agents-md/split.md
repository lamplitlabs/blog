# quota service

Go 1.24 module `example.com/quota`, standard library only. A token-budget ledger (`ledger.go`),
its HTTP front (`handler.go`), a pager (`page.go`), config loading and an upstream client.

- Keep the package name `quota`; do not add dependencies.
- Every behaviour change needs a test.
- Several agents work on this repository at the same time and their PRs merge in any order.
  Keep your change easy to merge:
  - Put new code in a new file named after your feature (`refund.go`), and its tests in a new
    test file (`refund_test.go`) with its own helpers. Do not append to existing files.
  - Edit existing code only where the ticket requires it, and keep those edits small.
  - Do not change the signature of an exported function or remove an exported name; add a new
    one beside it instead, unless the ticket explicitly requires the change.
  - New HTTP routes go through a new method on `Server`; touch `ServeHTTP` only to add a
    one-line dispatch.
- Before you finish: `gofmt -l .` prints nothing, `go vet ./...` and `go test -race ./...` pass.
