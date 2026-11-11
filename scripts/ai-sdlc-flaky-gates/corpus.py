"""Agent-style pull requests whose test verdict depends on luck.

Companion to scripts/ai-review-gates/: the base tree is the same Go token-budget
service (scripts/ai-review-gates/svc), and two patches (D16, D17) are reused
from that corpus as they are. The others are new and written by hand to look
like what a coding agent opens: each compiles, and each passes `go test` at
least some of the time. Nothing here says which run fails; measure.py runs the
real test binaries over and over and counts.

`kind` is one of:
  control      the unpatched base tree
  correct      a correct change whose tests are deterministic
  test-flake   the product code is correct, the new test is nondeterministic
  defect       the product code is wrong, and the tests only notice sometimes
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "gate_corpus", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai-review-gates", "corpus.py"))
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)
_G = {p["id"]: p for p in _gate.PATCHES}

# A stress test the issue asked for: 50 concurrent spends of 10 against a limit
# of 250 must admit exactly 25. On the base tree it always passes.
STRESS_TEST = (
    "func TestSpendAllNeverOverAdmits(t *testing.T) {\n"
    "\tl := NewLedger(map[string]int{\"acme\": 250})\n"
    "\tspends := make([]int, 50)\n\tfor i := range spends {\n\t\tspends[i] = 10\n\t}\n"
    "\tif got := l.SpendAll(\"acme\", spends); got != 25 {\n\t\tt.Fatalf(\"SpendAll admitted %d spends, want 25\", got)\n\t}\n"
    "\tif got := l.Remaining(\"acme\"); got != 0 {\n\t\tt.Fatalf(\"remaining = %d, want 0\", got)\n\t}\n}\n\n"
)

TENANTS_FN = (
    "// Tenants returns the known tenant ids{doc}.\nfunc (l *Ledger) Tenants() []string {{\n"
    "\tl.mu.Lock()\n\tdefer l.mu.Unlock()\n\tids := make([]string, 0, len(l.limit))\n"
    "\tfor t := range l.limit {{\n\t\tids = append(ids, t)\n\t}}\n{sort}\treturn ids\n}}\n\n// SpendAll applies"
)
TENANTS_TEST = (
    "func TestTenants(t *testing.T) {\n\tl := NewLedger(map[string]int{\"b\": 1, \"a\": 1})\n"
    "\tif got := l.Tenants(); len(got) != 2 || got[0] != \"a\" || got[1] != \"b\" {\n\t\tt.Fatalf(\"Tenants = %v\", got)\n\t}\n}\n\n"
    "func TestSpendAll(t *testing.T) {"
)

CASES = [
    {"id": "BASE", "kind": "control", "title": "unpatched base tree", "edits": []},
    {
        "id": "C1", "kind": "correct",
        "title": "add Ledger.Tenants (sorted) with a test",
        "edits": [("ledger.go", "// SpendAll applies", TENANTS_FN.format(doc=", sorted", sort="\tsort.Strings(ids)\n")),
                  ("ledger.go", '\t"fmt"\n', '\t"fmt"\n\t"sort"\n'),
                  ("ledger_test.go", "func TestSpendAll(t *testing.T) {", TENANTS_TEST)],
    },
    {
        "id": "C2", "kind": "correct",
        "title": "add the over-admission stress test the issue asked for",
        "edits": [("ledger_test.go", "func TestSpendAll(t *testing.T) {", STRESS_TEST + "func TestSpendAll(t *testing.T) {")],
    },
    {
        "id": "T1", "kind": "test-flake",
        "title": "handler tests share one Server to save setup; a new test needs the old ones to run first",
        "edits": [("handler_test.go",
                   "func newServer() *Server {\n\treturn &Server{\n\t\tLedger: NewLedger(map[string]int{\"acme\": 100}),\n"
                   "\t\tLog:    slog.New(slog.NewTextHandler(io.Discard, nil)),\n\t}\n}\n",
                   "// one server for all handler tests; building a ledger per test is wasteful\n"
                   "var shared = &Server{\n\tLedger: NewLedger(map[string]int{\"acme\": 100}),\n"
                   "\tLog:    slog.New(slog.NewTextHandler(io.Discard, nil)),\n}\n\n"
                   "func newServer() *Server {\n\treturn shared\n}\n"),
                  ("handler_test.go", "func TestHandlerBadBody(t *testing.T) {",
                   "func TestHandlerSpendRest(t *testing.T) {\n"
                   "\tw := post(newServer(), `{\"tenant\":\"acme\",\"tokens\":70}`)\n"
                   "\tif w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `\"remaining\":0`) {\n"
                   "\t\tt.Fatalf(\"got %d %s\", w.Code, w.Body)\n\t}\n}\n\n"
                   "func TestHandlerBadBody(t *testing.T) {")],
    },
    {
        "id": "T2", "kind": "test-flake",
        "title": "timeout test with a 10 ms margin between server sleep and client deadline",
        "edits": [("upstream_test.go", "func TestCompleteUpstreamError(t *testing.T) {",
                   "func TestCompleteSlowUpstream(t *testing.T) {\n"
                   "\tts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {\n"
                   "\t\ttime.Sleep(40 * time.Millisecond)\n\t\tw.Write([]byte(`{\"text\":\"hi\",\"tokens\":3}`))\n\t}))\n"
                   "\tdefer ts.Close()\n"
                   "\tu := &Upstream{URL: ts.URL, HTTP: ts.Client(), Timeout: 50 * time.Millisecond}\n"
                   "\tif _, err := u.Complete(context.Background(), \"hello\"); err != nil {\n\t\tt.Fatal(err)\n\t}\n}\n\n"
                   "func TestCompleteUpstreamError(t *testing.T) {")],
    },
    {
        "id": "F1", "kind": "defect",
        "title": "Ledger.Tenants returns map order; the test expects sorted ids",
        "edits": [("ledger.go", "// SpendAll applies", TENANTS_FN.format(doc="", sort="")),
                  ("ledger_test.go", "func TestSpendAll(t *testing.T) {", TENANTS_TEST)],
    },
    dict(_G["D16"], id="F2", kind="defect", src="D16"),
    dict(_G["D17"], id="F3", kind="defect", src="D17"),
    {
        "id": "F4", "kind": "defect",
        "title": "lock released between the limit check and the write (\"shorter critical section\"), with the stress test",
        "edits": list(_G["D20"]["edits"]) + [
            ("ledger_test.go", "func TestSpendAll(t *testing.T) {", STRESS_TEST + "func TestSpendAll(t *testing.T) {")],
        "src": "D20",
    },
]
for c in CASES:
    c.pop("cls", None)
