// Command gomut is a small mutation tester for one Go package, standard library
// only, written for the "agent-written tests, measured with mutation testing"
// post. It parses the package's non-test files with go/ast, makes one mutant per
// site and operator, and runs `go test` against each mutant through
// `go test -overlay`, so the package directory is never modified.
//
// Usage:
//
//	go run ./gomut -dir <package dir> [-j 4] [-timeout 5s] [-json out.json] [-html out.html] [-title T]
//
// Mutant states:
//
//	KILLED       go test failed (a test caught the change)
//	TIMED OUT    go test hit -timeout (counted as killed)
//	LIVED        go test passed with the mutant in place
//	NOT COVERED  the mutated line is not executed by the suite (counted as lived, not run)
//	NOT VIABLE   the mutant does not compile (excluded from the score)
//
// Mutation score = (KILLED + TIMED OUT) / (KILLED + TIMED OUT + LIVED + NOT COVERED).
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"html"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Mutant is one single-site change to one file.
type Mutant struct {
	ID       int      `json:"id"`
	File     string   `json:"file"`
	Line     int      `json:"line"`
	Col      int      `json:"col"`
	Op       string   `json:"op"`
	Orig     string   `json:"orig"`
	Repl     string   `json:"repl"`
	Snippet  string   `json:"snippet"`
	Status   string   `json:"status"`
	KilledBy []string `json:"killed_by,omitempty"`
	Millis   int64    `json:"ms"`
	start    int
	end      int
}

// Report is what -json writes.
type Report struct {
	Title       string                    `json:"title"`
	Dir         string                    `json:"dir"`
	GoVersion   string                    `json:"go_version"`
	Coverage    float64                   `json:"coverage_pct"`
	BaselineMs  int64                     `json:"baseline_ms"`
	Tests       int                       `json:"tests"`
	Counts      map[string]int            `json:"counts"`
	Score       float64                   `json:"mutation_score_pct"`
	ScoreCov    float64                   `json:"covered_mutation_score_pct"`
	ByOp        map[string]map[string]int `json:"by_op"`
	Mutants     []*Mutant                 `json:"mutants"`
	WallSeconds float64                   `json:"wall_seconds"`
}

var binSwap = map[token.Token][]struct {
	op string
	to token.Token
}{
	token.LSS:  {{"CONDITIONALS_BOUNDARY", token.LEQ}, {"CONDITIONALS_NEGATION", token.GEQ}},
	token.LEQ:  {{"CONDITIONALS_BOUNDARY", token.LSS}, {"CONDITIONALS_NEGATION", token.GTR}},
	token.GTR:  {{"CONDITIONALS_BOUNDARY", token.GEQ}, {"CONDITIONALS_NEGATION", token.LEQ}},
	token.GEQ:  {{"CONDITIONALS_BOUNDARY", token.GTR}, {"CONDITIONALS_NEGATION", token.LSS}},
	token.EQL:  {{"CONDITIONALS_NEGATION", token.NEQ}},
	token.NEQ:  {{"CONDITIONALS_NEGATION", token.EQL}},
	token.ADD:  {{"ARITHMETIC_BASE", token.SUB}},
	token.SUB:  {{"ARITHMETIC_BASE", token.ADD}},
	token.MUL:  {{"ARITHMETIC_BASE", token.QUO}},
	token.QUO:  {{"ARITHMETIC_BASE", token.MUL}},
	token.LAND: {{"LOGICAL_OPERATOR", token.LOR}},
	token.LOR:  {{"LOGICAL_OPERATOR", token.LAND}},
}

// sites returns every mutant for one parsed file.
func sites(fset *token.FileSet, f *ast.File, src []byte, name string) []*Mutant {
	var out []*Mutant
	add := func(op string, start, end int, repl string) {
		p := fset.Position(fset.File(f.Pos()).Pos(start))
		out = append(out, &Mutant{File: name, Line: p.Line, Col: p.Column, Op: op,
			Orig: string(src[start:end]), Repl: repl, start: start, end: end})
	}
	off := func(p token.Pos) int { return fset.Position(p).Offset }
	var stack []ast.Node
	ast.Inspect(f, func(n ast.Node) bool {
		if n == nil {
			stack = stack[:len(stack)-1]
			return true
		}
		stack = append(stack, n)
		switch x := n.(type) {
		case *ast.BinaryExpr:
			// string concatenation is skipped: "a" + b would not compile as "a" - b.
			if x.Op == token.ADD && (isString(x.X) || isString(x.Y)) {
				break
			}
			for _, s := range binSwap[x.Op] {
				o := off(x.OpPos)
				add(s.op, o, o+len(x.Op.String()), s.to.String())
			}
		case *ast.IncDecStmt:
			o := off(x.TokPos)
			if x.Tok == token.INC {
				add("INCREMENT_DECREMENT", o, o+2, "--")
			} else {
				add("INCREMENT_DECREMENT", o, o+2, "++")
			}
		case *ast.AssignStmt:
			o := off(x.TokPos)
			switch x.Tok {
			case token.ADD_ASSIGN:
				add("INVERT_ASSIGNMENTS", o, o+2, "-=")
			case token.SUB_ASSIGN:
				add("INVERT_ASSIGNMENTS", o, o+2, "+=")
			}
			if x.Tok != token.DEFINE && inBlock(stack) {
				add("REMOVE_STATEMENT", off(x.Pos()), off(x.End()), "")
			}
		case *ast.UnaryExpr:
			o := off(x.OpPos)
			switch x.Op {
			case token.NOT:
				add("REMOVE_NOT", o, o+1, "")
			case token.SUB:
				add("INVERT_NEGATIVES", o, o+1, "")
			}
		case *ast.ExprStmt:
			if c, ok := x.X.(*ast.CallExpr); ok && !isPanic(c) && inBlock(stack) {
				add("REMOVE_STATEMENT", off(x.Pos()), off(x.End()), "")
			}
		case *ast.DeferStmt:
			add("REMOVE_STATEMENT", off(x.Pos()), off(x.End()), "")
		case *ast.ReturnStmt:
			ft := enclosingFunc(stack)
			if ft == nil || ft.Results == nil || len(x.Results) == 0 {
				break
			}
			fl := ft.Results.List
			if id, ok := fl[len(fl)-1].Type.(*ast.Ident); !ok || id.Name != "error" {
				break
			}
			last := x.Results[len(x.Results)-1]
			if id, ok := last.(*ast.Ident); ok && id.Name == "nil" {
				break
			}
			add("RETURN_NIL_ERROR", off(last.Pos()), off(last.End()), "nil")
		}
		return true
	})
	// one line of context for the report
	lines := bytes.Split(src, []byte("\n"))
	for _, m := range out {
		m.Snippet = strings.TrimSpace(string(lines[m.Line-1]))
	}
	return out
}

func isString(e ast.Expr) bool {
	b, ok := e.(*ast.BasicLit)
	return ok && b.Kind == token.STRING
}

func isPanic(c *ast.CallExpr) bool {
	id, ok := c.Fun.(*ast.Ident)
	return ok && id.Name == "panic"
}

func inBlock(stack []ast.Node) bool {
	if len(stack) < 2 {
		return false
	}
	switch stack[len(stack)-2].(type) {
	case *ast.BlockStmt, *ast.CaseClause:
		return true
	}
	return false
}

func enclosingFunc(stack []ast.Node) *ast.FuncType {
	for i := len(stack) - 1; i >= 0; i-- {
		switch f := stack[i].(type) {
		case *ast.FuncLit:
			return f.Type
		case *ast.FuncDecl:
			return f.Type
		}
	}
	return nil
}

// coverage runs the suite once with a cover profile; it returns the covered
// line ranges per file base name, the statement coverage and the test count.
func coverage(dir string) (map[string][][2]int, float64, int, int64, error) {
	prof := filepath.Join(os.TempDir(), fmt.Sprintf("gomut-%d.cov", os.Getpid()))
	defer os.Remove(prof)
	t0 := time.Now()
	cmd := exec.Command("go", "test", "-count=1", "-vet=off", "-v", "-coverprofile="+prof, ".")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	ms := time.Since(t0).Milliseconds()
	if err != nil {
		return nil, 0, 0, 0, fmt.Errorf("baseline go test failed:\n%s", out)
	}
	tests := 0 // top-level tests only
	for _, l := range strings.Split(string(out), "\n") {
		if strings.HasPrefix(l, "=== RUN ") && !strings.Contains(l, "/") {
			tests++
		}
	}
	b, err := os.ReadFile(prof)
	if err != nil {
		return nil, 0, 0, 0, err
	}
	cov := map[string][][2]int{}
	var total, hit int
	re := regexp.MustCompile(`^(.+):(\d+)\.\d+,(\d+)\.\d+ (\d+) (\d+)$`)
	sc := bufio.NewScanner(bytes.NewReader(b))
	for sc.Scan() {
		m := re.FindStringSubmatch(sc.Text())
		if m == nil {
			continue
		}
		l0, _ := strconv.Atoi(m[2])
		l1, _ := strconv.Atoi(m[3])
		ns, _ := strconv.Atoi(m[4])
		cnt, _ := strconv.Atoi(m[5])
		total += ns
		if cnt > 0 {
			hit += ns
			base := filepath.Base(m[1])
			cov[base] = append(cov[base], [2]int{l0, l1})
		}
	}
	pct := 0.0
	if total > 0 {
		pct = 100 * float64(hit) / float64(total)
	}
	return cov, pct, tests, ms, nil
}

func covered(cov map[string][][2]int, m *Mutant) bool {
	for _, r := range cov[m.File] {
		if m.Line >= r[0] && m.Line <= r[1] {
			return true
		}
	}
	return false
}

var failRe = regexp.MustCompile(`--- FAIL: (\S+)`)

func runMutant(dir, work string, m *Mutant, src []byte, timeout time.Duration) {
	mut := append(append(append([]byte{}, src[:m.start]...), m.Repl...), src[m.end:]...)
	mf := filepath.Join(work, fmt.Sprintf("m%04d_%s", m.ID, m.File))
	if err := os.WriteFile(mf, mut, 0o644); err != nil {
		m.Status = "ERROR"
		return
	}
	abs, _ := filepath.Abs(filepath.Join(dir, m.File))
	ov := filepath.Join(work, fmt.Sprintf("m%04d.json", m.ID))
	j, _ := json.Marshal(map[string]map[string]string{"Replace": {abs: mf}})
	_ = os.WriteFile(ov, j, 0o644)
	ctx, cancel := context.WithTimeout(context.Background(), timeout+30*time.Second)
	defer cancel()
	t0 := time.Now()
	cmd := exec.CommandContext(ctx, "go", "test", "-count=1", "-vet=off",
		"-timeout", timeout.String(), "-overlay", ov, ".")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	m.Millis = time.Since(t0).Milliseconds()
	s := string(out)
	switch {
	case err == nil:
		m.Status = "LIVED"
	case strings.Contains(s, "[build failed]") || strings.Contains(s, "[setup failed]"):
		m.Status = "NOT VIABLE"
	case strings.Contains(s, "panic: test timed out") || ctx.Err() != nil:
		m.Status = "TIMED OUT"
	default:
		m.Status = "KILLED"
		seen := map[string]bool{}
		for _, f := range failRe.FindAllStringSubmatch(s, -1) {
			name := strings.SplitN(f[1], "/", 2)[0]
			if !seen[name] {
				seen[name] = true
				m.KilledBy = append(m.KilledBy, name)
			}
		}
		if len(m.KilledBy) == 0 {
			m.KilledBy = []string{"(panic or exit)"}
		}
	}
	os.Remove(mf)
	os.Remove(ov)
}

func main() {
	dir := flag.String("dir", ".", "package directory (non-test files are mutated)")
	jobs := flag.Int("j", 4, "parallel go test runs")
	timeout := flag.Duration("timeout", 5*time.Second, "go test -timeout per mutant")
	jsonOut := flag.String("json", "", "write the report as JSON")
	htmlOut := flag.String("html", "", "write an HTML report of the survivors")
	title := flag.String("title", "", "report title")
	list := flag.Bool("list", false, "only list the mutants, do not run them")
	flag.Parse()

	t0 := time.Now()
	ents, err := os.ReadDir(*dir)
	if err != nil {
		fatal(err)
	}
	fset := token.NewFileSet()
	srcs := map[string][]byte{}
	var muts []*Mutant
	var names []string
	for _, e := range ents {
		n := e.Name()
		if !strings.HasSuffix(n, ".go") || strings.HasSuffix(n, "_test.go") {
			continue
		}
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		src, err := os.ReadFile(filepath.Join(*dir, n))
		if err != nil {
			fatal(err)
		}
		f, err := parser.ParseFile(fset, n, src, parser.ParseComments)
		if err != nil {
			fatal(err)
		}
		srcs[n] = src
		ms := sites(fset, f, src, n)
		sort.SliceStable(ms, func(i, j int) bool {
			if ms[i].start != ms[j].start {
				return ms[i].start < ms[j].start
			}
			return ms[i].Op < ms[j].Op
		})
		muts = append(muts, ms...)
	}
	for i, m := range muts {
		m.ID = i + 1
	}
	if *list {
		for _, m := range muts {
			fmt.Printf("%3d %s:%d:%d %-22s %q -> %q\n", m.ID, m.File, m.Line, m.Col, m.Op, m.Orig, m.Repl)
		}
		return
	}

	cov, pct, tests, baseMs, err := coverage(*dir)
	if err != nil {
		fatal(err)
	}
	work, err := os.MkdirTemp("", "gomut-")
	if err != nil {
		fatal(err)
	}
	defer os.RemoveAll(work)

	ch := make(chan *Mutant)
	var wg sync.WaitGroup
	for w := 0; w < *jobs; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for m := range ch {
				runMutant(*dir, work, m, srcs[m.File], *timeout)
			}
		}()
	}
	for _, m := range muts {
		if !covered(cov, m) {
			m.Status = "NOT COVERED"
			continue
		}
		ch <- m
	}
	close(ch)
	wg.Wait()

	r := Report{Title: *title, Dir: modulePath(*dir), Coverage: round1(pct), BaselineMs: baseMs, Tests: tests,
		Counts: map[string]int{}, ByOp: map[string]map[string]int{}, Mutants: muts}
	if v, err := exec.Command("go", "env", "GOVERSION").Output(); err == nil {
		r.GoVersion = strings.TrimSpace(string(v))
	}
	for _, m := range muts {
		r.Counts[m.Status]++
		if r.ByOp[m.Op] == nil {
			r.ByOp[m.Op] = map[string]int{}
		}
		r.ByOp[m.Op][m.Status]++
	}
	killed := r.Counts["KILLED"] + r.Counts["TIMED OUT"]
	if d := killed + r.Counts["LIVED"] + r.Counts["NOT COVERED"]; d > 0 {
		r.Score = round1(100 * float64(killed) / float64(d))
	}
	if d := killed + r.Counts["LIVED"]; d > 0 {
		r.ScoreCov = round1(100 * float64(killed) / float64(d))
	}
	r.WallSeconds = round1(time.Since(t0).Seconds())
	fmt.Printf("%s: %d tests, coverage %.1f%%, mutants %d: killed %d, timed out %d, lived %d, not covered %d, not viable %d; mutation score %.1f%% (%.1fs)\n",
		*title, tests, pct, len(muts), r.Counts["KILLED"], r.Counts["TIMED OUT"], r.Counts["LIVED"],
		r.Counts["NOT COVERED"], r.Counts["NOT VIABLE"], r.Score, r.WallSeconds)
	if *jsonOut != "" {
		b, _ := json.MarshalIndent(r, "", "  ")
		if err := os.WriteFile(*jsonOut, append(b, '\n'), 0o644); err != nil {
			fatal(err)
		}
	}
	if *htmlOut != "" {
		if err := os.WriteFile(*htmlOut, []byte(renderHTML(r, srcs)), 0o644); err != nil {
			fatal(err)
		}
	}
}

// modulePath returns the module line of dir/go.mod, so reports name the
// package rather than a scratch directory.
func modulePath(dir string) string {
	b, err := os.ReadFile(filepath.Join(dir, "go.mod"))
	if err == nil {
		for _, l := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(l, "module ") {
				return strings.TrimSpace(strings.TrimPrefix(l, "module "))
			}
		}
	}
	return dir
}

func round1(f float64) float64 { return float64(int(f*10+0.5)) / 10 }

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "gomut:", err)
	os.Exit(1)
}

// renderHTML draws the survivors (LIVED and NOT COVERED) against their source
// lines, the way a CI job would publish them for a reviewer.
func renderHTML(r Report, srcs map[string][]byte) string {
	var b strings.Builder
	esc := html.EscapeString
	killed := r.Counts["KILLED"] + r.Counts["TIMED OUT"]
	b.WriteString(`<!doctype html><html><head><meta charset="utf-8"><title>gomut report</title><style>
body{background:#0d1117;color:#e6edf3;font:14px -apple-system,Helvetica,Arial,sans-serif;margin:24px}
h1{font-size:20px;margin:0 0 6px}.sub{color:#8b949e;margin-bottom:16px}
.cards{display:flex;gap:12px;margin-bottom:18px}.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 16px}
.card b{display:block;font-size:22px}.card span{color:#8b949e;font-size:12px}
.file{background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:14px;overflow:hidden}
.fh{padding:8px 12px;border-bottom:1px solid #30363d;font-weight:600}
pre{margin:0;font:12.5px Menlo,monospace;line-height:1.55}
.ln{color:#6e7681;display:inline-block;width:34px;text-align:right;padding-right:10px}
.l{display:block;padding:0 8px}.lived{background:rgba(248,81,73,.16)}.nc{background:rgba(210,168,70,.14)}
.tag{display:inline-block;margin-left:10px;font:11px -apple-system,Helvetica,Arial,sans-serif;padding:0 6px;border-radius:9px}
.tl{background:#5a1e1e;color:#ffb3ad}.tn{background:#4a3b12;color:#f2cc60}
.green{color:#3fb950}.red{color:#f85149}.yellow{color:#d2a846}
</style></head><body>`)
	fmt.Fprintf(&b, "<h1>%s</h1><div class=sub>gomut %s · %s · %d tests</div>", esc(r.Title), esc(r.GoVersion), esc(r.Dir), r.Tests)
	fmt.Fprintf(&b, `<div class=cards><div class=card><b>%.1f%%</b><span>statement coverage</span></div>`+
		`<div class=card><b>%.1f%%</b><span>mutation score</span></div>`+
		`<div class=card><b class=green>%d</b><span>killed</span></div>`+
		`<div class=card><b class=red>%d</b><span>lived</span></div>`+
		`<div class=card><b class=yellow>%d</b><span>not covered</span></div>`+
		`<div class=card><b>%d</b><span>not viable</span></div></div>`,
		r.Coverage, r.Score, killed, r.Counts["LIVED"], r.Counts["NOT COVERED"], r.Counts["NOT VIABLE"])
	byFileLine := map[string]map[int][]*Mutant{}
	for _, m := range r.Mutants {
		if m.Status != "LIVED" && m.Status != "NOT COVERED" {
			continue
		}
		if byFileLine[m.File] == nil {
			byFileLine[m.File] = map[int][]*Mutant{}
		}
		byFileLine[m.File][m.Line] = append(byFileLine[m.File][m.Line], m)
	}
	var files []string
	for f := range byFileLine {
		files = append(files, f)
	}
	sort.Strings(files)
	for _, f := range files {
		lines := strings.Split(string(srcs[f]), "\n")
		fmt.Fprintf(&b, "<div class=file><div class=fh>%s</div><pre>", esc(f))
		show := map[int]bool{}
		for ln := range byFileLine[f] {
			for k := ln - 1; k <= ln+1; k++ {
				show[k] = true
			}
		}
		prev := 0
		for i := range lines {
			ln := i + 1
			if !show[ln] {
				continue
			}
			if prev != 0 && ln != prev+1 {
				b.WriteString("<span class=l><span class=ln>⋮</span></span>")
			}
			prev = ln
			ms := byFileLine[f][ln]
			cls := "l"
			if len(ms) > 0 {
				cls = "l nc"
				for _, m := range ms {
					if m.Status == "LIVED" {
						cls = "l lived"
					}
				}
			}
			fmt.Fprintf(&b, "<span class=\"%s\"><span class=ln>%d</span>%s", cls, ln, esc(strings.ReplaceAll(lines[i], "\t", "    ")))
			for _, m := range ms {
				t, c := "lived", "tl"
				if m.Status == "NOT COVERED" {
					t, c = "not covered", "tn"
				}
				repl := m.Repl
				if repl == "" {
					repl = "(removed)"
				}
				orig := m.Orig
				if len(orig) > 28 {
					orig = orig[:25] + "..."
				}
				fmt.Fprintf(&b, "<span class=\"tag %s\">%s %s: %s → %s</span>", c, t, esc(strings.ToLower(m.Op)), esc(orig), esc(repl))
			}
			b.WriteString("</span>")
		}
		b.WriteString("</pre></div>")
	}
	b.WriteString("</body></html>\n")
	return b.String()
}
