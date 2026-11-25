# quota service

Go 1.24 module `example.com/quota`, standard library only. A token-budget ledger (`ledger.go`),
its HTTP front (`handler.go`), a pager (`page.go`), config loading and an upstream client.

- Keep the package name `quota`; do not add dependencies.
- Every behaviour change needs a test in the matching `*_test.go` file.
- Before you finish: `gofmt -l .` prints nothing, `go vet ./...` and `go test -race ./...` pass.
