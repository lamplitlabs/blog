// logroute is the workload of the "Go PGO in practice" post: a small log
// router that parses key=value access-log lines, sends each record through a
// rule table of Matcher interfaces, and keeps per-route latency histograms.
//
//	logroute gen <config> <lines> <file>          write seeded lines to file
//	logroute run <config> <file> <reps> [cpuprofile-path]
//
// <config> is "api" (rules are mostly route-prefix matchers, as on an API
// gateway) or "batch" (rules are mostly status and level matchers, as on a
// batch-job log pipeline). Lines come from a seeded generator and are written
// once to a file, so every build reads the same bytes; run prints ns per line
// and a checksum that must match across builds.
package main

import (
	"bytes"
	"fmt"
	"math/rand/v2"
	"os"
	"runtime/pprof"
	"strconv"
	"time"
)

// Record is one parsed log line. Byte slices point into the line buffer.
type Record struct {
	TS     uint64
	Level  []byte
	Svc    []byte
	Method []byte
	Route  []byte
	Status int
	DurMS  int
	Bytes  int
	User   []byte
}

func (r *Record) reset() { *r = Record{} }

// scanFields splits `k=v k=v k="quoted v"` and stores the fields it knows.
func scanFields(line []byte, r *Record) bool {
	i := 0
	n := len(line)
	seen := 0
	for i < n {
		for i < n && line[i] == ' ' {
			i++
		}
		ks := i
		for i < n && line[i] != '=' && line[i] != ' ' {
			i++
		}
		if i >= n || line[i] != '=' {
			return false
		}
		key := line[ks:i]
		i++
		var val []byte
		if i < n && line[i] == '"' {
			i++
			vs := i
			for i < n && line[i] != '"' {
				if line[i] == '\\' {
					i++
				}
				i++
			}
			if i >= n {
				return false
			}
			val = line[vs:i]
			i++
		} else {
			vs := i
			for i < n && line[i] != ' ' {
				i++
			}
			val = line[vs:i]
		}
		if setField(r, key, val) {
			seen++
		}
	}
	return seen >= 6
}

// setField is the per-field switch. It is too big for the default inline
// budget (80 nodes), and it runs ~10 times per line.
func setField(r *Record, key, val []byte) bool {
	switch string(key) {
	case "ts":
		v, ok := parseUint(val)
		r.TS = v
		return ok
	case "level":
		r.Level = val
	case "svc":
		r.Svc = val
	case "method":
		r.Method = val
	case "route":
		r.Route = val
	case "status":
		v, ok := parseUint(val)
		r.Status = int(v)
		return ok
	case "dur_ms":
		v, ok := parseUint(val)
		r.DurMS = int(v)
		return ok
	case "bytes":
		v, ok := parseUint(val)
		r.Bytes = int(v)
		return ok
	case "user":
		r.User = val
	default:
		return false
	}
	return true
}

func parseUint(b []byte) (uint64, bool) {
	if len(b) == 0 || len(b) > 19 {
		return 0, false
	}
	var v uint64
	for _, c := range b {
		if c < '0' || c > '9' {
			return 0, false
		}
		v = v*10 + uint64(c-'0')
	}
	return v, true
}

// Matcher decides whether a rule applies to a record.
type Matcher interface {
	Match(r *Record) bool
}

type routePrefix struct {
	method []byte // empty: any
	prefix []byte
}

func (m *routePrefix) Match(r *Record) bool {
	if len(m.method) > 0 && !bytes.Equal(r.Method, m.method) {
		return false
	}
	return bytes.HasPrefix(r.Route, m.prefix)
}

type statusRange struct{ lo, hi int }

func (m *statusRange) Match(r *Record) bool { return r.Status >= m.lo && r.Status <= m.hi }

type levelIs struct{ level []byte }

func (m *levelIs) Match(r *Record) bool { return bytes.Equal(r.Level, m.level) }

type svcIn struct{ names [][]byte }

func (m *svcIn) Match(r *Record) bool {
	for _, n := range m.names {
		if bytes.Equal(r.Svc, n) {
			return true
		}
	}
	return false
}

type slowerThan struct{ ms int }

func (m *slowerThan) Match(r *Record) bool { return r.DurMS > m.ms }

// Rule sends matching records to a sink; the first match wins unless Continue.
type Rule struct {
	M        Matcher
	Sink     int
	Continue bool
}

// Sink receives routed records.
type Sink interface {
	Write(r *Record)
}

// histSink keeps a latency histogram and byte totals per route key.
type histSink struct {
	routes map[uint64]*routeStats
	bounds []int
}

type routeStats struct {
	count   uint64
	bytes   uint64
	errors  uint64
	buckets [12]uint64
}

func (s *histSink) Write(r *Record) {
	k := routeKey(r.Svc, r.Route)
	st := s.routes[k]
	if st == nil {
		st = &routeStats{}
		s.routes[k] = st
	}
	st.count++
	st.bytes += uint64(r.Bytes)
	if r.Status >= 500 {
		st.errors++
	}
	st.buckets[bucketFor(s.bounds, r.DurMS)]++
}

// countSink only counts; it stands in for a forwarder.
type countSink struct{ n, bytes uint64 }

func (s *countSink) Write(r *Record) { s.n++; s.bytes += uint64(len(r.User)) }

// routeKey hashes svc and the route with numeric path segments folded to one
// placeholder, so /api/v1/orders/123 and /api/v1/orders/456 share a key.
func routeKey(svc, route []byte) uint64 {
	const off, prime = 14695981039346656037, 1099511628211
	h := uint64(off)
	for _, c := range svc {
		h = (h ^ uint64(c)) * prime
	}
	h = (h ^ '|') * prime
	digits := false
	for _, c := range route {
		if c >= '0' && c <= '9' {
			if !digits {
				h = (h ^ '#') * prime
				digits = true
			}
			continue
		}
		digits = false
		h = (h ^ uint64(c)) * prime
	}
	return h
}

func bucketFor(bounds []int, v int) int {
	lo, hi := 0, len(bounds)
	for lo < hi {
		mid := (lo + hi) / 2
		if v <= bounds[mid] {
			hi = mid
		} else {
			lo = mid + 1
		}
	}
	return lo
}

// Router owns the rules and sinks.
type Router struct {
	rules   []Rule
	sinks   []Sink
	dropped uint64
	bad     uint64
}

func (rt *Router) Route(line []byte, rec *Record) {
	rec.reset()
	if !scanFields(line, rec) {
		rt.bad++
		return
	}
	matched := false
	for i := range rt.rules {
		ru := &rt.rules[i]
		if ru.M.Match(rec) {
			rt.sinks[ru.Sink].Write(rec)
			matched = true
			if !ru.Continue {
				break
			}
		}
	}
	if !matched {
		rt.dropped++
	}
}

func newRouter(config string) *Router {
	bounds := []int{1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000}
	hist := func() *histSink { return &histSink{routes: map[uint64]*routeStats{}, bounds: bounds} }
	b := func(s string) []byte { return []byte(s) }
	rt := &Router{}
	switch config {
	case "api":
		// An API gateway: one rule per route family, a catch-all at the end.
		rt.sinks = []Sink{hist(), hist(), hist(), &countSink{}}
		prefixes := []string{"/api/v1/cart", "/api/v1/orders", "/api/v1/users", "/api/v1/search",
			"/api/v1/catalog", "/api/v2/payments", "/api/v2/shipping", "/internal/health", "/static/"}
		rt.rules = append(rt.rules, Rule{M: &slowerThan{ms: 1500}, Sink: 3, Continue: true})
		for i, p := range prefixes {
			method := ""
			if i%3 == 1 {
				method = "GET"
			}
			rt.rules = append(rt.rules, Rule{M: &routePrefix{method: b(method), prefix: b(p)}, Sink: i % 3})
		}
		rt.rules = append(rt.rules, Rule{M: &statusRange{lo: 0, hi: 999}, Sink: 2})
	case "batch":
		// A batch pipeline: route by outcome and level, then by service.
		rt.sinks = []Sink{hist(), hist(), &countSink{}, &countSink{}}
		rt.rules = []Rule{
			{M: &statusRange{lo: 500, hi: 599}, Sink: 2, Continue: true},
			{M: &levelIs{level: b("error")}, Sink: 2},
			{M: &levelIs{level: b("warn")}, Sink: 3},
			{M: &statusRange{lo: 400, hi: 499}, Sink: 3},
			{M: &svcIn{names: [][]byte{b("billing"), b("ledger")}}, Sink: 0},
			{M: &statusRange{lo: 300, hi: 399}, Sink: 1},
			{M: &levelIs{level: b("debug")}, Sink: 1},
			{M: &statusRange{lo: 200, hi: 299}, Sink: 0},
		}
	default:
		fmt.Fprintln(os.Stderr, "unknown config", config)
		os.Exit(2)
	}
	return rt
}

func (rt *Router) checksum() uint64 {
	h := rt.dropped*31 + rt.bad
	for _, s := range rt.sinks {
		switch s := s.(type) {
		case *histSink:
			for k, st := range s.routes {
				h += k ^ st.count ^ (st.bytes << 1) ^ (st.errors << 7)
				for i, c := range st.buckets {
					h += c * uint64(i+3)
				}
			}
		case *countSink:
			h = h*1099511628211 ^ s.n ^ (s.bytes << 3)
		}
	}
	return h
}

// generate builds n seeded access-log lines in one buffer.
func generate(config string, n int) [][]byte {
	rng := rand.New(rand.NewPCG(42, uint64(len(config))))
	svcs := []string{"checkout", "catalog", "users", "search", "billing", "ledger", "edge"}
	routes := []string{"/api/v1/cart/items", "/api/v1/orders/%d", "/api/v1/users/%d/profile", "/api/v1/search",
		"/api/v1/catalog/sku/%d", "/api/v2/payments/%d/capture", "/api/v2/shipping/quote", "/internal/health",
		"/static/app.%d.js", "/api/v1/cart/%d/coupon", "/api/v3/beta/%d"}
	methods := []string{"GET", "GET", "GET", "POST", "PUT", "DELETE"}
	levels := []string{"info", "info", "info", "info", "debug", "warn", "error"}
	statuses := []int{200, 200, 200, 200, 200, 201, 204, 301, 304, 400, 404, 404, 429, 500, 503}
	buf := make([]byte, 0, n*170)
	lines := make([][]byte, 0, n)
	ts := uint64(1762819200000)
	for i := 0; i < n; i++ {
		ts += uint64(rng.IntN(40))
		route := routes[rng.IntN(len(routes))]
		if bytes.Contains([]byte(route), []byte("%d")) {
			route = fmt.Sprintf(route, rng.IntN(90000)+100)
		}
		dur := int(rng.ExpFloat64()*35) + 1
		if rng.IntN(200) == 0 {
			dur += 1500
		}
		start := len(buf)
		buf = fmt.Appendf(buf, `ts=%d level=%s svc=%s method=%s route=%s status=%d dur_ms=%d bytes=%d user=u%d msg="%s"`,
			ts, levels[rng.IntN(len(levels))], svcs[rng.IntN(len(svcs))], methods[rng.IntN(len(methods))], route,
			statuses[rng.IntN(len(statuses))], dur, rng.IntN(64000)+120, rng.IntN(50000),
			[]string{"ok", "served from cache", "upstream \\\"slow\\\"", "retry 1 of 3"}[rng.IntN(4)])
		lines = append(lines, buf[start:len(buf):len(buf)])
	}
	return lines
}

func main() {
	if len(os.Args) < 5 {
		fmt.Fprintln(os.Stderr, "usage: logroute gen <api|batch> <lines> <file> | logroute run <api|batch> <file> <reps> [cpuprofile]")
		os.Exit(2)
	}
	config := os.Args[2]
	switch os.Args[1] {
	case "gen":
		n, _ := strconv.Atoi(os.Args[3])
		var out []byte
		for _, l := range generate(config, n) {
			out = append(append(out, l...), '\n')
		}
		if err := os.WriteFile(os.Args[4], out, 0o644); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	case "run":
	default:
		os.Exit(2)
	}
	data, err := os.ReadFile(os.Args[3])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	lines := bytes.Split(bytes.TrimSuffix(data, []byte{'\n'}), []byte{'\n'})
	n := len(lines)
	reps, _ := strconv.Atoi(os.Args[4])
	if len(os.Args) > 5 {
		f, err := os.Create(os.Args[5])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		if err := pprof.StartCPUProfile(f); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer f.Close()
		defer pprof.StopCPUProfile()
	}
	// reps=0 loads the file and exits: its counters are the fixed cost that
	// measure.sh subtracts to get instructions per routed line.
	var sum uint64
	var rec Record
	best := time.Duration(1 << 62)
	var total time.Duration
	for rep := 0; rep < reps; rep++ {
		rt := newRouter(config)
		t0 := time.Now()
		for _, l := range lines {
			rt.Route(l, &rec)
		}
		d := time.Since(t0)
		total += d
		best = min(best, d)
		sum = rt.checksum()
	}
	if reps == 0 {
		best = 0
		reps = 1
	}
	fmt.Printf("config=%s lines=%d reps=%d ns_per_line_mean=%.2f ns_per_line_best=%.2f checksum=%d\n",
		config, n, reps, float64(total.Nanoseconds())/float64(n*reps), float64(best.Nanoseconds())/float64(n), sum)
}
