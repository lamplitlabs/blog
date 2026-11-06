// gatecheck is the static-analysis gate of the AI code review post: three
// analyzers from golang.org/x/tools that `go vet` does not run by default,
// plus four policy rules of our own. Run it through go vet:
//
//	go build -o gatecheck . && go vet -vettool=$PWD/gatecheck ./...
package main

import (
	"golang.org/x/tools/go/analysis/multichecker"
	"golang.org/x/tools/go/analysis/passes/nilness"
	"golang.org/x/tools/go/analysis/passes/shadow"
	"golang.org/x/tools/go/analysis/passes/unusedwrite"
)

func main() {
	multichecker.Main(nilness.Analyzer, shadow.Analyzer, unusedwrite.Analyzer, Policy)
}
