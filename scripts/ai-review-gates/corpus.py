"""Seeded agent-style patches for the "AI code review gates in CI" post.

Each entry is one pull request a coding agent might open against the base tree
in svc/. It is a list of exact (file, old, new) text replacements, applied in
order to a fresh copy of svc/; `old` must occur exactly once. `cls` is the
defect class from the earlier "reviewing AI-generated code" checklist post, or
"benign" for a correct change that every gate should let through.

The patches were written by hand to look like what agents produce (plausible,
compiling, often with a green test run). Nothing here decides which gate
catches what: run_gates.py applies each patch and runs the real tools.

The fake key in D23 is built from two halves so that a secret scanner run over
this repository does not flag the corpus itself; the gate sees it joined.
"""

FAKE_KEY = "sk-gw-" + "7Qm2Lx9VtR4pZ8nK3wY6bH1cJ5dF0sAe"

PATCHES = [
    # ---- 1. silent error fallback -------------------------------------------------
    {
        "id": "D01", "cls": "silent-error",
        "title": "DisplayName degrades to the raw id instead of returning the store error",
        "edits": [("store.go",
                   '\t\treturn "", fmt.Errorf("tenant %q: %w", id, err)\n',
                   '\t\treturn fmt.Sprintf("tenant %s", id), nil // degrade gracefully\n')],
    },
    {
        "id": "D02", "cls": "silent-error",
        "title": "bad MAX_TOKENS silently falls back to the default",
        "edits": [("config.go",
                   '\t\tif err != nil || n <= 0 {\n\t\t\treturn Config{}, fmt.Errorf("MAX_TOKENS=%q: want a positive integer", v)\n\t\t}\n\t\tc.MaxTokens = n\n',
                   '\t\tif err == nil && n > 0 {\n\t\t\tc.MaxTokens = n\n\t\t}\n')],
    },
    {
        "id": "D03", "cls": "silent-error",
        "title": "upstream decode error discarded, empty reply returned",
        "edits": [("upstream.go",
                   '\tif err := json.NewDecoder(resp.Body).Decode(&r); err != nil {\n\t\treturn nil, fmt.Errorf("upstream: decode: %w", err)\n\t}\n',
                   '\t_ = json.NewDecoder(resp.Body).Decode(&r)\n')],
    },
    {
        "id": "D04", "cls": "silent-error",
        "title": "unknown tenant is charged instead of rejected",
        "edits": [("ledger.go",
                   '\t\treturn fmt.Errorf("tenant %q: unknown", tenant)\n',
                   '\t\tl.spent[tenant] += n // new tenants get provisioned lazily\n\t\treturn nil\n')],
    },
    # ---- 2. boundary and off-by-one -----------------------------------------------
    {
        "id": "D05", "cls": "boundary",
        "title": "spend landing exactly on the limit is refused (> became >=)",
        "edits": [("ledger.go", "if l.spent[tenant]+n > lim {", "if l.spent[tenant]+n >= lim {")],
    },
    {
        "id": "D06", "cls": "boundary",
        "title": "last page drops its final item",
        "edits": [("page.go", "\tif end > len(items) {\n\t\tend = len(items)\n",
                   "\tif end >= len(items) {\n\t\tend = len(items) - 1\n")],
    },
    {
        "id": "D07", "cls": "boundary",
        "title": "page offset treats the 1-based page as 0-based",
        "edits": [("page.go", "start := (page - 1) * size", "start := page * size")],
    },
    {
        "id": "D08", "cls": "boundary",
        "title": "usage report excludes rows exactly at `since`",
        "edits": [("store.go", "ts >= $2", "ts > $2")],
    },
    # ---- 3. tests that prove nothing ----------------------------------------------
    {
        "id": "D09", "cls": "weak-tests",
        "title": "off-by-one in Spend, and the test's expected values moved to match",
        "edits": [("ledger.go", "if l.spent[tenant]+n > lim {", "if l.spent[tenant]+n >= lim {"),
                  ("ledger_test.go", '\tif err := l.Spend("acme", 40); err != nil {',
                   '\tif err := l.Spend("acme", 39); err != nil {'),
                  ("ledger_test.go", "\tif got := l.Remaining(\"acme\"); got != 0 {\n\t\tt.Fatalf(\"remaining = %d, want 0\", got)",
                   "\tif got := l.Remaining(\"acme\"); got != 1 {\n\t\tt.Fatalf(\"remaining = %d, want 1\", got)")],
    },
    {
        "id": "D10", "cls": "weak-tests",
        "title": "refused spend still charged; the balance assertion deleted",
        "edits": [("ledger.go",
                   "\tif l.spent[tenant]+n > lim {\n",
                   "\tl.spent[tenant] += n\n\tif l.spent[tenant] > lim {\n"),
                  ("ledger.go", "\tl.spent[tenant] += n\n\treturn nil\n}", "\treturn nil\n}"),
                  ("ledger_test.go",
                   '\tif got := l.Remaining("acme"); got != 100 {\n\t\tt.Fatalf("a refused spend changed the balance: remaining = %d", got)\n\t}\n',
                   "")],
    },
    {
        "id": "D11", "cls": "weak-tests",
        "title": "non-200 upstream treated as success; failing test skipped as flaky",
        "edits": [("upstream.go", "if resp.StatusCode != http.StatusOK {", "if resp.StatusCode >= 500 && false {"),
                  ("upstream_test.go", "func TestCompleteUpstreamError(t *testing.T) {\n",
                   "func TestCompleteUpstreamError(t *testing.T) {\n\tt.Skip(\"flaky on CI, see #412\")\n")],
    },
    {
        "id": "D12", "cls": "weak-tests",
        "title": "new Refund lets the balance exceed the limit; its test covers the happy path only",
        "edits": [("ledger.go", "// Remaining returns",
                   "// Refund gives n tokens back to tenant.\nfunc (l *Ledger) Refund(tenant string, n int) {\n"
                   "\tl.mu.Lock()\n\tdefer l.mu.Unlock()\n\tl.spent[tenant] -= n\n}\n\n// Remaining returns"),
                  ("ledger_test.go", "func TestSpendAll(t *testing.T) {",
                   "func TestRefund(t *testing.T) {\n\tl := NewLedger(map[string]int{\"acme\": 100})\n"
                   "\t_ = l.Spend(\"acme\", 50)\n\tl.Refund(\"acme\", 20)\n"
                   "\tif got := l.Remaining(\"acme\"); got != 70 {\n\t\tt.Fatalf(\"remaining = %d, want 70\", got)\n\t}\n}\n\n"
                   "func TestSpendAll(t *testing.T) {")],
    },
    # ---- 4. hallucinated API or wrong argument order ------------------------------
    {
        "id": "D13", "cls": "hallucinated-api",
        "title": "uses time.ParseDurationStrict, which does not exist",
        "edits": [("config.go", "d, err := time.ParseDuration(v)", "d, err := time.ParseDurationStrict(v)")],
    },
    {
        "id": "D14", "cls": "hallucinated-api",
        "title": "fmt.Errorf arguments in the wrong order",
        "edits": [("ledger.go",
                   'return fmt.Errorf("tenant %q: %w (%d + %d > %d)", tenant, ErrOverBudget, l.spent[tenant], n, lim)',
                   'return fmt.Errorf("tenant %q: %w (%d + %d > %d)", ErrOverBudget, tenant, l.spent[tenant], n, lim)')],
    },
    # ---- 5. duplicated existing helper --------------------------------------------
    {
        "id": "D15", "cls": "duplicate-helper",
        "title": "second pagination helper that errors past the end instead of returning empty",
        "edits": [("handler.go", "// ServeHTTP handles",
                   "// paginate slices xs for the admin listing.\nfunc paginate(xs []string, page, per int) ([]string, error) {\n"
                   "\tlo := (page - 1) * per\n\tif lo >= len(xs) {\n\t\treturn nil, errors.New(\"page out of range\")\n\t}\n"
                   "\thi := lo + per\n\tif hi > len(xs) {\n\t\thi = len(xs)\n\t}\n\treturn xs[lo:hi], nil\n}\n\n// ServeHTTP handles")],
    },
    # ---- 6. concurrency and resource misuse ---------------------------------------
    {
        "id": "D16", "cls": "concurrency",
        "title": "SpendAll counter incremented without its mutex",
        "edits": [("ledger.go", "\t\t\t\tmu.Lock()\n\t\t\t\tok++\n\t\t\t\tmu.Unlock()\n", "\t\t\t\tok++\n"),
                  ("ledger.go", "\tvar mu sync.Mutex\n", "")],
    },
    {
        "id": "D17", "cls": "concurrency",
        "title": "wg.Add moved inside the goroutine",
        "edits": [("ledger.go", "\t\twg.Add(1)\n\t\tgo func() {\n\t\t\tdefer wg.Done()\n",
                   "\t\tgo func() {\n\t\t\twg.Add(1)\n\t\t\tdefer wg.Done()\n")],
    },
    {
        "id": "D18", "cls": "concurrency",
        "title": "Remaining given a value receiver, copying the mutex",
        "edits": [("ledger.go", "func (l *Ledger) Remaining(", "func (l Ledger) Remaining(")],
    },
    {
        "id": "D19", "cls": "concurrency",
        "title": "context cancel func discarded",
        "edits": [("upstream.go", "\tctx, cancel := context.WithTimeout(ctx, u.Timeout)\n\tdefer cancel()\n",
                   "\tctx, _ = context.WithTimeout(ctx, u.Timeout)\n")],
    },
    {
        "id": "D20", "cls": "concurrency",
        "title": "check-then-act: lock released between the limit check and the write",
        "edits": [("ledger.go",
                   "\tl.mu.Lock()\n\tdefer l.mu.Unlock()\n\tlim, ok := l.limit[tenant]\n",
                   "\tl.mu.Lock()\n\tlim, ok := l.limit[tenant]\n\tcur := l.spent[tenant]\n\tl.mu.Unlock()\n"),
                  ("ledger.go", "\tif l.spent[tenant]+n > lim {\n\t\treturn fmt.Errorf(\"tenant %q: %w (%d + %d > %d)\", tenant, ErrOverBudget, l.spent[tenant], n, lim)\n\t}\n\tl.spent[tenant] += n\n",
                   "\tif cur+n > lim {\n\t\treturn fmt.Errorf(\"tenant %q: %w (%d + %d > %d)\", tenant, ErrOverBudget, cur, n, lim)\n\t}\n"
                   "\tl.mu.Lock()\n\tl.spent[tenant] += n\n\tl.mu.Unlock()\n")],
    },
    {
        "id": "D21", "cls": "concurrency",
        "title": "response body closed only on the success path (connection leak on errors)",
        "edits": [("upstream.go", "\tdefer resp.Body.Close()\n\tif resp.StatusCode", "\tif resp.StatusCode"),
                  ("upstream.go", "\tvar r Reply\n", "\tdefer resp.Body.Close()\n\tvar r Reply\n")],
    },
    # ---- 7. security --------------------------------------------------------------
    {
        "id": "D22", "cls": "security",
        "title": "usage query builds SQL by string concatenation",
        "edits": [("store.go",
                   '\tq := "SELECT model, SUM(tokens) FROM usage WHERE tenant = $1 AND ts >= $2 GROUP BY model ORDER BY model"\n\treturn q, []any{tenant, since}\n',
                   '\tq := "SELECT model, SUM(tokens) FROM usage WHERE tenant = \'" + tenant + "\' AND ts >= $2 GROUP BY model ORDER BY model"\n\treturn q, []any{tenant, since}\n')],
    },
    {
        "id": "D23", "cls": "security",
        "title": "hard-coded fallback API key for local runs",
        "edits": [("upstream.go", '\treq.Header.Set("Authorization", "Bearer "+u.Key)\n',
                   '\tapiKey := u.Key\n\tif apiKey == "" {\n\t\tapiKey = "' + FAKE_KEY + '" // dev key\n\t}\n'
                   '\treq.Header.Set("Authorization", "Bearer "+apiKey)\n')],
    },
    {
        "id": "D24", "cls": "security",
        "title": "Authorization header written to the log on upstream errors",
        "edits": [("upstream.go", '\t\treturn nil, fmt.Errorf("upstream: %w", err)\n',
                   '\t\tslog.Warn("upstream call failed", "url", u.URL, "auth", req.Header.Get("Authorization"), "err", err)\n'
                   '\t\treturn nil, fmt.Errorf("upstream: %w", err)\n'),
                  ("upstream.go", '\t"io"\n', '\t"io"\n\t"log/slog"\n')],
    },
    {
        "id": "D25", "cls": "security",
        "title": "TLS verification switched off to get past a self-signed staging cert",
        "edits": [("upstream.go", "// Complete sends",
                   "// NewHTTPClient returns the client used for upstream calls.\nfunc NewHTTPClient() *http.Client {\n"
                   "\treturn &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}}\n}\n\n// Complete sends"),
                  ("upstream.go", '\t"context"\n', '\t"context"\n\t"crypto/tls"\n')],
    },
    {
        "id": "D26", "cls": "security",
        "title": "request body size limit removed",
        "edits": [("handler.go", "json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16))", "json.NewDecoder(r.Body)")],
    },
    # ---- benign: correct changes every gate should pass ---------------------------
    {
        "id": "B01", "cls": "benign",
        "title": "rename a local variable and expand a doc comment",
        "edits": [("page.go", "\tstart := (page - 1) * size\n\tif start >= len(items) {\n\t\treturn []T{}, nil\n\t}\n\tend := start + size\n",
                   "\toffset := (page - 1) * size\n\tif offset >= len(items) {\n\t\treturn []T{}, nil\n\t}\n\tend := offset + size\n"),
                  ("page.go", "return items[start:end], nil", "return items[offset:end], nil"),
                  ("page.go", "// the end is empty, not an error.", "// the end is empty, not an error, so clients can stop on an empty page.")],
    },
    {
        "id": "B02", "cls": "benign",
        "title": "add a test case for a page size larger than the list",
        "edits": [("page_test.go", "\t\t{4, 3, []int{}},\n", "\t\t{4, 3, []int{}},\n\t\t{1, 10, []int{1, 2, 3, 4, 5, 6, 7}},\n")],
    },
    {
        "id": "B03", "cls": "benign",
        "title": "use the min builtin in Page",
        "edits": [("page.go", "\tend := start + size\n\tif end > len(items) {\n\t\tend = len(items)\n\t}\n",
                   "\tend := min(start+size, len(items))\n")],
    },
    {
        "id": "B04", "cls": "benign",
        "title": "add Ledger.Tenants with a test",
        "edits": [("ledger.go", "// SpendAll applies",
                   "// Tenants returns the known tenant ids, sorted.\nfunc (l *Ledger) Tenants() []string {\n"
                   "\tl.mu.Lock()\n\tdefer l.mu.Unlock()\n\tids := make([]string, 0, len(l.limit))\n"
                   "\tfor t := range l.limit {\n\t\tids = append(ids, t)\n\t}\n\tsort.Strings(ids)\n\treturn ids\n}\n\n// SpendAll applies"),
                  ("ledger.go", '\t"fmt"\n', '\t"fmt"\n\t"sort"\n'),
                  ("ledger_test.go", "func TestSpendAll(t *testing.T) {",
                   "func TestTenants(t *testing.T) {\n\tl := NewLedger(map[string]int{\"b\": 1, \"a\": 1})\n"
                   "\tif got := l.Tenants(); len(got) != 2 || got[0] != \"a\" || got[1] != \"b\" {\n\t\tt.Fatalf(\"Tenants = %v\", got)\n\t}\n}\n\n"
                   "func TestSpendAll(t *testing.T) {")],
    },
    {
        "id": "B05", "cls": "benign",
        "title": "raise the default MAX_TOKENS to 8192 and update its test (intended change)",
        "edits": [("config.go", "MaxTokens: 4096", "MaxTokens: 8192"),
                  ("config_test.go", "if c.MaxTokens != 4096 ||", "if c.MaxTokens != 8192 ||")],
    },
    {
        "id": "B06", "cls": "benign",
        "title": "fold two ledger tests into one table test (same assertions)",
        "edits": [("ledger_test.go",
                   'func TestSpendRejectsNonPositive(t *testing.T) {\n\tl := NewLedger(map[string]int{"acme": 100})\n'
                   '\tfor _, n := range []int{0, -5} {\n\t\tif err := l.Spend("acme", n); err == nil {\n'
                   '\t\t\tt.Fatalf("Spend(%d) = nil, want an error", n)\n\t\t}\n\t}\n}\n\n'
                   'func TestSpendUnknownTenant(t *testing.T) {\n\tl := NewLedger(map[string]int{"acme": 100})\n'
                   '\tif err := l.Spend("globex", 1); err == nil {\n\t\tt.Fatal("unknown tenant accepted")\n\t}\n}\n',
                   'func TestSpendRejects(t *testing.T) {\n\tl := NewLedger(map[string]int{"acme": 100})\n'
                   '\tfor _, c := range []struct {\n\t\ttenant string\n\t\tn      int\n\t}{{"acme", 0}, {"acme", -5}, {"globex", 1}} {\n'
                   '\t\tif err := l.Spend(c.tenant, c.n); err == nil {\n'
                   '\t\t\tt.Fatalf("Spend(%q, %d) = nil, want an error", c.tenant, c.n)\n\t\t}\n\t}\n}\n')],
    },
    {
        "id": "B07", "cls": "benign",
        "title": "log the remaining balance after a spend",
        "edits": [("handler.go", "\tw.Header().Set(\"Content-Type\", \"application/json\")\n\t_ = json.NewEncoder(w).Encode(spendResponse{Remaining: s.Ledger.Remaining(req.Tenant)})\n",
                   "\tleft := s.Ledger.Remaining(req.Tenant)\n\ts.Log.Info(\"spent\", \"tenant\", req.Tenant, \"remaining\", left)\n"
                   "\tw.Header().Set(\"Content-Type\", \"application/json\")\n\t_ = json.NewEncoder(w).Encode(spendResponse{Remaining: left})\n")],
    },
    {
        "id": "B08", "cls": "benign",
        "title": "errors.New where fmt.Errorf had nothing to format",
        "edits": [("config.go", 'return Config{}, fmt.Errorf("UPSTREAM_URL is required")', 'return Config{}, errors.New("UPSTREAM_URL is required")'),
                  ("config.go", 'import (\n\t"fmt"\n', 'import (\n\t"errors"\n\t"fmt"\n')],
    },
]
