//! logstat: summarise LLM gateway access logs per (route, model).
//!
//!   logstat generate <file> <lines>        write a seeded synthetic log
//!   logstat run <v0..v4> <file> [reps]     analyse it with one of five versions
//!
//! v0 is the naive version; each later version changes one thing a profile
//! pointed at: v1 = v0 + HashSet blocklist, v2 = v1 + borrowed fields (no
//! per-line HashMap), v3 = v2 + FxHash, v4 = v2 + one byte scan per line
//! instead of str::split. All five print the same report and checksum.
use std::collections::{HashMap, HashSet};
use std::fmt::Write as _;
use std::hash::{BuildHasherDefault, Hasher};
use std::io::Write as _;
use std::time::Instant;
use std::{env, fs, hint};

// `cargo build --release --features count-alloc` counts heap allocations so the
// report can print allocations per line; the default build has no counter.
#[cfg(feature = "count-alloc")]
mod count {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::sync::atomic::{AtomicU64, Ordering::Relaxed};
    pub static ALLOCS: AtomicU64 = AtomicU64::new(0);
    pub struct Counting;
    unsafe impl GlobalAlloc for Counting {
        unsafe fn alloc(&self, l: Layout) -> *mut u8 {
            ALLOCS.fetch_add(1, Relaxed);
            unsafe { System.alloc(l) }
        }
        unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
            unsafe { System.dealloc(p, l) }
        }
        unsafe fn realloc(&self, p: *mut u8, l: Layout, n: usize) -> *mut u8 {
            ALLOCS.fetch_add(1, Relaxed);
            unsafe { System.realloc(p, l, n) }
        }
    }
    #[global_allocator]
    static A: Counting = Counting;
}

fn allocs() -> u64 {
    #[cfg(feature = "count-alloc")]
    return count::ALLOCS.load(std::sync::atomic::Ordering::Relaxed);
    #[cfg(not(feature = "count-alloc"))]
    0
}

const ROUTES: [&str; 6] = [
    "/v1/chat", "/v1/embed", "/v1/complete", "/v1/rerank", "/v1/moderate", "/v1/tokenize",
];
const MODELS: [&str; 5] = ["llama-3.1-8b", "qwen2.5-7b", "mistral-7b", "phi-3-mini", "smollm3-3b"];
const USERS: u64 = 50_000;
const BLOCKED: u64 = 1_000; // every 50th user id is on the blocklist

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        // xorshift64*
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

fn generate(path: &str, lines: usize) {
    let mut r = Rng(0x9E37_79B9_7F4A_7C15);
    let mut out = String::with_capacity(lines * 140);
    for i in 0..lines {
        let s = i as u64 * 86_400 / lines as u64;
        let level = if r.below(100) < 3 { "WARN" } else { "INFO" };
        let route = ROUTES[r.below(6) as usize];
        let model = MODELS[r.below(5) as usize];
        let user = r.below(USERS);
        let tokens = 16 + r.below(2048);
        // long-tailed latency: mostly 40-400 ms, 2% between 1 and 9 s
        let latency = if r.below(100) < 2 { 1_000 + r.below(8_000) } else { 40 + r.below(360) };
        let status = match r.below(100) { 0 => 500, 1 => 429, _ => 200 };
        writeln!(
            out,
            "ts=2026-11-03T{:02}:{:02}:{:02}Z level={level} route={route} model={model} user=u{user:05} tokens={tokens} latency_ms={latency} status={status}",
            s / 3600, s / 60 % 60, s % 60
        )
        .unwrap();
    }
    fs::write(path, out).unwrap();
}

fn blocklist() -> Vec<String> {
    (0..BLOCKED).map(|k| format!("u{:05}", k * (USERS / BLOCKED))).collect()
}

#[derive(Default)]
struct Agg {
    lat: Vec<u32>,
    tokens: u64,
}

struct Report {
    rows: Vec<(String, usize, u64, u32, u32)>,
    blocked: u64,
    errors: u64,
}

fn finish(groups: impl Iterator<Item = (String, Agg)>, blocked: u64, errors: u64) -> Report {
    let mut rows: Vec<_> = groups
        .map(|(k, mut a)| {
            a.lat.sort_unstable();
            let n = a.lat.len();
            (k, n, a.tokens, a.lat[n / 2], a.lat[n * 99 / 100])
        })
        .collect();
    rows.sort();
    Report { rows, blocked, errors }
}

// ---------------------------------------------------------------- v0: naive
#[inline(never)]
fn parse_fields_v0(line: &str) -> HashMap<String, String> {
    line.split(' ')
        .filter_map(|kv| kv.split_once('='))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

#[inline(never)]
fn is_blocked_v0(blocked: &[String], user: &str) -> bool {
    blocked.iter().any(|b| b == user)
}

#[inline(never)] // keep one frame per version in the profiles
fn run_v0(text: &str, blocked: &[String]) -> Report {
    let mut groups: HashMap<String, Agg> = HashMap::new();
    let (mut nblocked, mut errors) = (0, 0);
    for line in text.lines() {
        let f = parse_fields_v0(line);
        if is_blocked_v0(blocked, &f["user"]) {
            nblocked += 1;
            continue;
        }
        if f["status"] != "200" {
            errors += 1;
            continue;
        }
        let key = format!("{} {}", f["route"], f["model"]);
        let a = groups.entry(key).or_default();
        a.lat.push(f["latency_ms"].parse().unwrap());
        a.tokens += f["tokens"].parse::<u64>().unwrap();
    }
    finish(groups.into_iter(), nblocked, errors)
}

// ------------------------------------------------ v1: v0 + HashSet blocklist
#[inline(never)] // keep one frame per version in the profiles
fn run_v1(text: &str, blocked: &HashSet<&str>) -> Report {
    let mut groups: HashMap<String, Agg> = HashMap::new();
    let (mut nblocked, mut errors) = (0, 0);
    for line in text.lines() {
        let f = parse_fields_v0(line);
        if blocked.contains(f["user"].as_str()) {
            nblocked += 1;
            continue;
        }
        if f["status"] != "200" {
            errors += 1;
            continue;
        }
        let key = format!("{} {}", f["route"], f["model"]);
        let a = groups.entry(key).or_default();
        a.lat.push(f["latency_ms"].parse().unwrap());
        a.tokens += f["tokens"].parse::<u64>().unwrap();
    }
    finish(groups.into_iter(), nblocked, errors)
}

// ------------------------------------------- v2: v1 + borrowed fields, no per-line map
struct Line<'a> {
    route: &'a str,
    model: &'a str,
    user: &'a str,
    tokens: &'a str,
    latency: &'a str,
    status: &'a str,
}

#[inline(never)]
fn parse_fields_v2(line: &str) -> Line<'_> {
    let mut l = Line { route: "", model: "", user: "", tokens: "", latency: "", status: "" };
    for kv in line.split(' ') {
        if let Some((k, v)) = kv.split_once('=') {
            match k {
                "route" => l.route = v,
                "model" => l.model = v,
                "user" => l.user = v,
                "tokens" => l.tokens = v,
                "latency_ms" => l.latency = v,
                "status" => l.status = v,
                _ => {}
            }
        }
    }
    l
}

#[inline(never)] // keep one frame per version in the profiles
fn run_v2(text: &str, blocked: &HashSet<&str>) -> Report {
    let mut groups: HashMap<(&str, &str), Agg> = HashMap::new();
    let (mut nblocked, mut errors) = (0, 0);
    for line in text.lines() {
        let f = parse_fields_v2(line);
        if blocked.contains(f.user) {
            nblocked += 1;
            continue;
        }
        if f.status != "200" {
            errors += 1;
            continue;
        }
        let a = groups.entry((f.route, f.model)).or_default();
        a.lat.push(f.latency.parse().unwrap());
        a.tokens += f.tokens.parse::<u64>().unwrap();
    }
    finish(groups.into_iter().map(|((r, m), a)| (format!("{r} {m}"), a)), nblocked, errors)
}

// ---------------------------------- v3: v2 + FxHash instead of SipHash-1-3
#[derive(Default)]
struct FxHasher(u64);
impl Hasher for FxHasher {
    #[inline]
    fn write(&mut self, bytes: &[u8]) {
        for chunk in bytes.chunks(8) {
            let mut w = [0u8; 8];
            w[..chunk.len()].copy_from_slice(chunk);
            self.add(u64::from_le_bytes(w));
        }
    }
    #[inline]
    fn write_u8(&mut self, i: u8) {
        self.add(i as u64)
    }
    #[inline]
    fn write_usize(&mut self, i: usize) {
        self.add(i as u64)
    }
    #[inline]
    fn finish(&self) -> u64 {
        self.0
    }
}
impl FxHasher {
    #[inline]
    fn add(&mut self, w: u64) {
        self.0 = (self.0.rotate_left(5) ^ w).wrapping_mul(0x51_7c_c1_b7_27_22_0a_95);
    }
}
type Fx = BuildHasherDefault<FxHasher>;

#[inline(never)] // keep one frame per version in the profiles
fn run_v3(text: &str, blocked: &HashSet<&str, Fx>) -> Report {
    let mut groups: HashMap<(&str, &str), Agg, Fx> = HashMap::default();
    let (mut nblocked, mut errors) = (0, 0);
    for line in text.lines() {
        let f = parse_fields_v2(line);
        if blocked.contains(f.user) {
            nblocked += 1;
            continue;
        }
        if f.status != "200" {
            errors += 1;
            continue;
        }
        let a = groups.entry((f.route, f.model)).or_default();
        a.lat.push(f.latency.parse().unwrap());
        a.tokens += f.tokens.parse::<u64>().unwrap();
    }
    finish(groups.into_iter().map(|((r, m), a)| (format!("{r} {m}"), a)), nblocked, errors)
}

// ------------------------- v4: v2 + one byte scan per line instead of str::split
#[inline(never)]
fn parse_fields_v4(line: &str) -> Line<'_> {
    let mut l = Line { route: "", model: "", user: "", tokens: "", latency: "", status: "" };
    let b = line.as_bytes();
    let (mut start, mut eq) = (0, usize::MAX);
    for i in 0..=b.len() {
        let c = if i < b.len() { b[i] } else { b' ' };
        if c == b'=' && eq == usize::MAX {
            eq = i;
        } else if c == b' ' {
            if eq != usize::MAX {
                let v = &line[eq + 1..i];
                match &b[start..eq] {
                    b"route" => l.route = v,
                    b"model" => l.model = v,
                    b"user" => l.user = v,
                    b"tokens" => l.tokens = v,
                    b"latency_ms" => l.latency = v,
                    b"status" => l.status = v,
                    _ => {}
                }
            }
            start = i + 1;
            eq = usize::MAX;
        }
    }
    l
}

#[inline(never)] // keep one frame per version in the profiles
fn run_v4(text: &str, blocked: &HashSet<&str>) -> Report {
    let mut groups: HashMap<(&str, &str), Agg> = HashMap::new();
    let (mut nblocked, mut errors) = (0, 0);
    for line in text.lines() {
        let f = parse_fields_v4(line);
        if blocked.contains(f.user) {
            nblocked += 1;
            continue;
        }
        if f.status != "200" {
            errors += 1;
            continue;
        }
        let a = groups.entry((f.route, f.model)).or_default();
        a.lat.push(f.latency.parse().unwrap());
        a.tokens += f.tokens.parse::<u64>().unwrap();
    }
    finish(groups.into_iter().map(|((r, m), a)| (format!("{r} {m}"), a)), nblocked, errors)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("generate") => generate(&args[2], args[3].parse().unwrap()),
        Some("run") => {
            let text = fs::read_to_string(&args[3]).unwrap();
            let list = blocklist();
            let reps: usize = args.get(4).map_or(1, |s| s.parse().unwrap());
            let a0 = allocs();
            let t = Instant::now();
            let mut rep = None;
            for _ in 0..reps {
                rep = Some(hint::black_box(match args[2].as_str() {
                    "v0" => run_v0(&text, &list),
                    "v1" => run_v1(&text, &list.iter().map(String::as_str).collect()),
                    "v2" => run_v2(&text, &list.iter().map(String::as_str).collect()),
                    "v3" => run_v3(&text, &list.iter().map(String::as_str).collect()),
                    "v4" => run_v4(&text, &list.iter().map(String::as_str).collect()),
                    v => panic!("unknown version {v}"),
                }));
            }
            let el = t.elapsed();
            let nalloc = allocs() - a0;
            let rep = rep.unwrap();
            let mut sum: u64 = rep.blocked * 31 + rep.errors;
            let out = std::io::stdout();
            let mut out = out.lock();
            for (k, n, tok, p50, p99) in &rep.rows {
                sum = sum.wrapping_mul(1_000_003) ^ (*n as u64 + tok + *p50 as u64 * 7 + *p99 as u64 * 13 + k.len() as u64);
                if env::var_os("LOGSTAT_ROWS").is_some() {
                    writeln!(out, "{k:<26} n={n:<6} tokens={tok:<10} p50={p50}ms p99={p99}ms").unwrap();
                }
            }
            let lines = text.lines().count();
            writeln!(
                out,
                "{} lines={lines} groups={} blocked={} errors={} checksum={sum:016x} elapsed_ms={:.1} per_rep_ms={:.1} allocs_per_line={:.2}",
                args[2],
                rep.rows.len(),
                rep.blocked,
                rep.errors,
                el.as_secs_f64() * 1e3,
                el.as_secs_f64() * 1e3 / reps as f64,
                nalloc as f64 / (lines * reps) as f64
            )
            .unwrap();
        }
        _ => eprintln!("usage: logstat generate <file> <lines> | logstat run <v0|v1|v2|v3|v4> <file> [reps]"),
    }
}
