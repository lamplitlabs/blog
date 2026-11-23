//! logroute (Rust) is the Rust counterpart of scripts/go-pgo/logroute, the
//! workload of the "Rust PGO vs Go PGO" post: a small log router that parses
//! key=value access-log lines, sends each record through a rule table of
//! `dyn Matcher` trait objects (Go: Matcher interfaces), and keeps per-route
//! latency histograms behind `dyn Sink` (Go: Sink interface).
//!
//!     logroute run <api|batch> <file> <reps>
//!
//! The input file is written by the Go program (`logroute gen`), so both
//! languages read the same bytes, and `run` prints the same line as the Go
//! program: ns per line and a checksum that must equal Go's for the same
//! config and file. Nothing here is tuned for PGO: it is a line-by-line port.
use std::collections::HashMap;
use std::time::{Duration, Instant};
use std::{env, fs, process};

/// One parsed log line. Byte slices point into the file buffer.
#[derive(Default)]
struct Record<'a> {
    ts: u64,
    level: &'a [u8],
    svc: &'a [u8],
    method: &'a [u8],
    route: &'a [u8],
    status: i64,
    dur_ms: i64,
    bytes: i64,
    user: &'a [u8],
}

/// Splits `k=v k=v k="quoted v"` and stores the fields it knows.
fn scan_fields<'a>(line: &'a [u8], r: &mut Record<'a>) -> bool {
    let n = line.len();
    let mut i = 0;
    let mut seen = 0;
    while i < n {
        while i < n && line[i] == b' ' {
            i += 1;
        }
        let ks = i;
        while i < n && line[i] != b'=' && line[i] != b' ' {
            i += 1;
        }
        if i >= n || line[i] != b'=' {
            return false;
        }
        let key = &line[ks..i];
        i += 1;
        let val;
        if i < n && line[i] == b'"' {
            i += 1;
            let vs = i;
            while i < n && line[i] != b'"' {
                if line[i] == b'\\' {
                    i += 1;
                }
                i += 1;
            }
            if i >= n {
                return false;
            }
            val = &line[vs..i];
            i += 1;
        } else {
            let vs = i;
            while i < n && line[i] != b' ' {
                i += 1;
            }
            val = &line[vs..i];
        }
        if set_field(r, key, val) {
            seen += 1;
        }
    }
    seen >= 6
}

/// The per-field switch; runs ~10 times per line.
fn set_field<'a>(r: &mut Record<'a>, key: &[u8], val: &'a [u8]) -> bool {
    match key {
        b"ts" => {
            let (v, ok) = parse_uint(val);
            r.ts = v;
            return ok;
        }
        b"level" => r.level = val,
        b"svc" => r.svc = val,
        b"method" => r.method = val,
        b"route" => r.route = val,
        b"status" => {
            let (v, ok) = parse_uint(val);
            r.status = v as i64;
            return ok;
        }
        b"dur_ms" => {
            let (v, ok) = parse_uint(val);
            r.dur_ms = v as i64;
            return ok;
        }
        b"bytes" => {
            let (v, ok) = parse_uint(val);
            r.bytes = v as i64;
            return ok;
        }
        b"user" => r.user = val,
        _ => return false,
    }
    true
}

fn parse_uint(b: &[u8]) -> (u64, bool) {
    if b.is_empty() || b.len() > 19 {
        return (0, false);
    }
    let mut v: u64 = 0;
    for &c in b {
        if !c.is_ascii_digit() {
            return (0, false);
        }
        v = v.wrapping_mul(10).wrapping_add((c - b'0') as u64);
    }
    (v, true)
}

/// Decides whether a rule applies to a record.
trait Matcher {
    fn matches(&self, r: &Record) -> bool;
}

struct RoutePrefix {
    method: Vec<u8>, // empty: any
    prefix: Vec<u8>,
}

impl Matcher for RoutePrefix {
    fn matches(&self, r: &Record) -> bool {
        if !self.method.is_empty() && r.method != self.method.as_slice() {
            return false;
        }
        r.route.starts_with(&self.prefix)
    }
}

struct StatusRange {
    lo: i64,
    hi: i64,
}

impl Matcher for StatusRange {
    fn matches(&self, r: &Record) -> bool {
        r.status >= self.lo && r.status <= self.hi
    }
}

struct LevelIs {
    level: Vec<u8>,
}

impl Matcher for LevelIs {
    fn matches(&self, r: &Record) -> bool {
        r.level == self.level.as_slice()
    }
}

struct SvcIn {
    names: Vec<Vec<u8>>,
}

impl Matcher for SvcIn {
    fn matches(&self, r: &Record) -> bool {
        self.names.iter().any(|n| r.svc == n.as_slice())
    }
}

struct SlowerThan {
    ms: i64,
}

impl Matcher for SlowerThan {
    fn matches(&self, r: &Record) -> bool {
        r.dur_ms > self.ms
    }
}

/// Sends matching records to a sink; the first match wins unless `cont`.
struct Rule {
    m: Box<dyn Matcher>,
    sink: usize,
    cont: bool,
}

/// Receives routed records.
trait Sink {
    fn write(&mut self, r: &Record);
    /// Folds this sink into the checksum (Go: the type switch in checksum()).
    fn fold(&self, h: u64) -> u64;
}

#[derive(Default)]
struct RouteStats {
    count: u64,
    bytes: u64,
    errors: u64,
    buckets: [u64; 12],
}

/// Keeps a latency histogram and byte totals per route key.
struct HistSink {
    routes: HashMap<u64, Box<RouteStats>>,
    bounds: &'static [i64],
}

impl Sink for HistSink {
    // The `outline-write` feature is a measurement knob (measure.sh variant
    // rs-pgo-outline): it keeps this function out of main under PGO.
    #[cfg_attr(feature = "outline-write", inline(never))]
    fn write(&mut self, r: &Record) {
        let k = route_key(r.svc, r.route);
        let st = self.routes.entry(k).or_default();
        st.count += 1;
        st.bytes = st.bytes.wrapping_add(r.bytes as u64);
        if r.status >= 500 {
            st.errors += 1;
        }
        st.buckets[bucket_for(self.bounds, r.dur_ms)] += 1;
    }

    fn fold(&self, mut h: u64) -> u64 {
        for (k, st) in &self.routes {
            h = h.wrapping_add(k ^ st.count ^ (st.bytes << 1) ^ (st.errors << 7));
            for (i, c) in st.buckets.iter().enumerate() {
                h = h.wrapping_add(c.wrapping_mul(i as u64 + 3));
            }
        }
        h
    }
}

/// Only counts; it stands in for a forwarder.
#[derive(Default)]
struct CountSink {
    n: u64,
    bytes: u64,
}

impl Sink for CountSink {
    fn write(&mut self, r: &Record) {
        self.n += 1;
        self.bytes += r.user.len() as u64;
    }

    fn fold(&self, h: u64) -> u64 {
        h.wrapping_mul(1099511628211) ^ self.n ^ (self.bytes << 3)
    }
}

/// Hashes svc and the route with numeric path segments folded to one
/// placeholder, so /api/v1/orders/123 and /api/v1/orders/456 share a key.
fn route_key(svc: &[u8], route: &[u8]) -> u64 {
    const OFF: u64 = 14695981039346656037;
    const PRIME: u64 = 1099511628211;
    let mut h = OFF;
    for &c in svc {
        h = (h ^ c as u64).wrapping_mul(PRIME);
    }
    h = (h ^ b'|' as u64).wrapping_mul(PRIME);
    let mut digits = false;
    for &c in route {
        if c.is_ascii_digit() {
            if !digits {
                h = (h ^ b'#' as u64).wrapping_mul(PRIME);
                digits = true;
            }
            continue;
        }
        digits = false;
        h = (h ^ c as u64).wrapping_mul(PRIME);
    }
    h
}

fn bucket_for(bounds: &[i64], v: i64) -> usize {
    let (mut lo, mut hi) = (0, bounds.len());
    while lo < hi {
        let mid = (lo + hi) / 2;
        if v <= bounds[mid] {
            hi = mid;
        } else {
            lo = mid + 1;
        }
    }
    lo
}

/// Owns the rules and sinks.
struct Router {
    rules: Vec<Rule>,
    sinks: Vec<Box<dyn Sink>>,
    dropped: u64,
    bad: u64,
}

impl Router {
    fn route<'a>(&mut self, line: &'a [u8], rec: &mut Record<'a>) {
        *rec = Record::default();
        if !scan_fields(line, rec) {
            self.bad += 1;
            return;
        }
        let mut matched = false;
        for ru in &self.rules {
            if ru.m.matches(rec) {
                self.sinks[ru.sink].write(rec);
                matched = true;
                if !ru.cont {
                    break;
                }
            }
        }
        if !matched {
            self.dropped += 1;
        }
    }

    fn new(config: &str) -> Router {
        static BOUNDS: [i64; 11] = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000];
        let hist = || -> Box<dyn Sink> { Box::new(HistSink { routes: HashMap::new(), bounds: &BOUNDS }) };
        let count = || -> Box<dyn Sink> { Box::new(CountSink::default()) };
        let b = |s: &str| s.as_bytes().to_vec();
        let mut rules: Vec<Rule> = Vec::new();
        let sinks;
        match config {
            "api" => {
                // An API gateway: one rule per route family, a catch-all at the end.
                sinks = vec![hist(), hist(), hist(), count()];
                let prefixes = [
                    "/api/v1/cart", "/api/v1/orders", "/api/v1/users", "/api/v1/search", "/api/v1/catalog",
                    "/api/v2/payments", "/api/v2/shipping", "/internal/health", "/static/",
                ];
                rules.push(Rule { m: Box::new(SlowerThan { ms: 1500 }), sink: 3, cont: true });
                for (i, p) in prefixes.iter().enumerate() {
                    let method = if i % 3 == 1 { "GET" } else { "" };
                    rules.push(Rule { m: Box::new(RoutePrefix { method: b(method), prefix: b(p) }), sink: i % 3, cont: false });
                }
                rules.push(Rule { m: Box::new(StatusRange { lo: 0, hi: 999 }), sink: 2, cont: false });
            }
            "batch" => {
                // A batch pipeline: route by outcome and level, then by service.
                sinks = vec![hist(), hist(), count(), count()];
                let r = |m: Box<dyn Matcher>, sink: usize, cont: bool| Rule { m, sink, cont };
                rules = vec![
                    r(Box::new(StatusRange { lo: 500, hi: 599 }), 2, true),
                    r(Box::new(LevelIs { level: b("error") }), 2, false),
                    r(Box::new(LevelIs { level: b("warn") }), 3, false),
                    r(Box::new(StatusRange { lo: 400, hi: 499 }), 3, false),
                    r(Box::new(SvcIn { names: vec![b("billing"), b("ledger")] }), 0, false),
                    r(Box::new(StatusRange { lo: 300, hi: 399 }), 1, false),
                    r(Box::new(LevelIs { level: b("debug") }), 1, false),
                    r(Box::new(StatusRange { lo: 200, hi: 299 }), 0, false),
                ];
            }
            _ => {
                eprintln!("unknown config {config}");
                process::exit(2);
            }
        }
        Router { rules, sinks, dropped: 0, bad: 0 }
    }

    fn checksum(&self) -> u64 {
        let h = self.dropped.wrapping_mul(31).wrapping_add(self.bad);
        self.sinks.iter().fold(h, |h, s| s.fold(h))
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 5 || args[1] != "run" {
        eprintln!("usage: logroute run <api|batch> <file> <reps>");
        process::exit(2);
    }
    let config = args[2].as_str();
    let data = fs::read(&args[3]).unwrap_or_else(|e| {
        eprintln!("{e}");
        process::exit(1)
    });
    let body = data.strip_suffix(b"\n").unwrap_or(&data);
    let lines: Vec<&[u8]> = body.split(|&c| c == b'\n').collect();
    let n = lines.len();
    let mut reps: usize = args[4].parse().unwrap_or(0);
    // reps=0 loads the file and exits: its counters are the fixed cost that
    // measure.sh subtracts to get instructions per routed line.
    let mut sum = 0u64;
    let mut rec = Record::default();
    let mut best = Duration::MAX;
    let mut total = Duration::ZERO;
    for _ in 0..reps {
        let mut rt = Router::new(config);
        let t0 = Instant::now();
        for l in &lines {
            rt.route(l, &mut rec);
        }
        let d = t0.elapsed();
        total += d;
        best = best.min(d);
        sum = rt.checksum();
    }
    if reps == 0 {
        best = Duration::ZERO;
        reps = 1;
    }
    println!(
        "config={config} lines={n} reps={reps} ns_per_line_mean={:.2} ns_per_line_best={:.2} checksum={sum}",
        total.as_nanos() as f64 / (n * reps) as f64,
        best.as_nanos() as f64 / n as f64
    );
}
