package main

import (
	"go/ast"
	"go/constant"
	"go/token"
	"go/types"
	"strconv"
	"strings"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/passes/inspect"
	"golang.org/x/tools/go/ast/inspector"
)

// Policy holds four house rules, each written after an incident class that
// review kept missing. They are deliberately narrow: a rule that fires on
// correct code gets switched off within a week.
var Policy = &analysis.Analyzer{
	Name:     "policy",
	Doc:      "house rules: no InsecureSkipVerify, no SQL built by concatenation, no credentials in log calls, request bodies decoded through MaxBytesReader",
	Requires: []*analysis.Analyzer{inspect.Analyzer},
	Run:      runPolicy,
}

var sqlVerbs = []string{"SELECT ", "INSERT ", "UPDATE ", "DELETE "}

func runPolicy(pass *analysis.Pass) (any, error) {
	ins := pass.ResultOf[inspect.Analyzer].(*inspector.Inspector)
	nodes := []ast.Node{(*ast.KeyValueExpr)(nil), (*ast.BinaryExpr)(nil), (*ast.CallExpr)(nil)}
	ins.Preorder(nodes, func(n ast.Node) {
		switch n := n.(type) {
		case *ast.KeyValueExpr:
			// P1: TLS verification off.
			if id, ok := n.Key.(*ast.Ident); ok && id.Name == "InsecureSkipVerify" {
				if v, ok := n.Value.(*ast.Ident); ok && v.Name == "true" {
					pass.Reportf(n.Pos(), "policy P1: InsecureSkipVerify: true disables TLS verification")
				}
			}
		case *ast.BinaryExpr:
			// P2: a SQL string literal concatenated with a non-constant value.
			if n.Op != token.ADD || pass.TypesInfo.Types[n].Value != nil {
				return
			}
			if lit := leftmostString(n); lit != "" && isSQL(lit) && !allConst(pass, n) {
				pass.Reportf(n.Pos(), "policy P2: SQL built by string concatenation; pass values as query parameters")
			}
		case *ast.CallExpr:
			fn := calleeName(pass, n)
			// P3: credentials passed to a logger.
			if strings.HasPrefix(fn, "log/slog.") || strings.HasPrefix(fn, "log.") || strings.HasPrefix(fn, "(*log/slog.Logger).") {
				for _, a := range n.Args {
					if isCredentialRead(a) {
						pass.Reportf(a.Pos(), "policy P3: credential header passed to %s", fn)
					}
				}
			}
			// P4: request body decoded without a size limit.
			if fn == "encoding/json.NewDecoder" && len(n.Args) == 1 {
				if sel, ok := n.Args[0].(*ast.SelectorExpr); ok && sel.Sel.Name == "Body" {
					if t := pass.TypesInfo.TypeOf(sel.X); t != nil && t.String() == "*net/http.Request" {
						pass.Reportf(n.Pos(), "policy P4: request body decoded without http.MaxBytesReader")
					}
				}
			}
		}
	})
	return nil, nil
}

func leftmostString(e ast.Expr) string {
	for {
		switch x := e.(type) {
		case *ast.BinaryExpr:
			e = x.X
		case *ast.BasicLit:
			if x.Kind == token.STRING {
				s, _ := strconv.Unquote(x.Value)
				return s
			}
			return ""
		default:
			return ""
		}
	}
}

func isSQL(s string) bool {
	u := strings.ToUpper(strings.TrimSpace(s))
	for _, v := range sqlVerbs {
		if strings.HasPrefix(u, v) {
			return true
		}
	}
	return false
}

func allConst(pass *analysis.Pass, e ast.Expr) bool {
	tv, ok := pass.TypesInfo.Types[e]
	return ok && tv.Value != nil && tv.Value.Kind() == constant.String
}

func calleeName(pass *analysis.Pass, call *ast.CallExpr) string {
	var id *ast.Ident
	switch f := call.Fun.(type) {
	case *ast.Ident:
		id = f
	case *ast.SelectorExpr:
		id = f.Sel
	default:
		return ""
	}
	obj, ok := pass.TypesInfo.Uses[id].(*types.Func)
	if !ok {
		return ""
	}
	return obj.FullName()
}

// isCredentialRead matches x.Header.Get("Authorization") and friends.
func isCredentialRead(e ast.Expr) bool {
	call, ok := e.(*ast.CallExpr)
	if !ok || len(call.Args) != 1 {
		return false
	}
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != "Get" {
		return false
	}
	lit, ok := call.Args[0].(*ast.BasicLit)
	if !ok {
		return false
	}
	name, _ := strconv.Unquote(lit.Value)
	switch strings.ToLower(name) {
	case "authorization", "cookie", "x-api-key", "proxy-authorization":
		return true
	}
	return false
}
