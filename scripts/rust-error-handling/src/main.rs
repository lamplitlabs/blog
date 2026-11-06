//! errbench: the same log-record parser written four ways, to measure what
//! thiserror and anyhow cost on the happy path, on the error path, and with
//! backtraces switched on.
//!
//!   errbench run <variant> <fault-permille> <count|render> [lines] [reps]
//!   errbench show                      print one bad line's error every way
//!   errbench sizes                     size_of the Result each variant returns
//!
//! Variants (the parser and the caller both differ only in error handling):
//!   typed   thiserror enum in the parser, thiserror struct adds the line number
//!   anyhow  anyhow in the parser (context/anyhow!), caller .with_context(|| ..)
//!   eager   as anyhow, but the caller writes .context(format!(..)) instead
//!   hybrid  thiserror enum in the parser, caller .with_context(|| ..) (anyhow)
//!
//! Every variant renders byte-identical error text; `run .. render` prints a
//! checksum of the rendered messages so that is checked, not assumed.
use std::fmt::Write as _;
use std::num::ParseIntError;
use std::time::Instant;
use std::{env, hint};

use anyhow::{Context as _, anyhow, bail};

// `cargo build --release --features count-alloc` counts heap allocations.
#[cfg(feature = "count-alloc")]
mod count {
    use std::alloc::{GlobalAlloc, Layout, System};
    use std::sync::atomic::{AtomicU64, Ordering::Relaxed};
    pub static ALLOCS: AtomicU64 = AtomicU64::new(0);
    pub static BYTES: AtomicU64 = AtomicU64::new(0);
    pub struct Counting;
    unsafe impl GlobalAlloc for Counting {
        unsafe fn alloc(&self, l: Layout) -> *mut u8 {
            ALLOCS.fetch_add(1, Relaxed);
            BYTES.fetch_add(l.size() as u64, Relaxed);
            unsafe { System.alloc(l) }
        }
        unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
            unsafe { System.dealloc(p, l) }
        }
        unsafe fn realloc(&self, p: *mut u8, l: Layout, n: usize) -> *mut u8 {
            ALLOCS.fetch_add(1, Relaxed);
            BYTES.fetch_add(n as u64, Relaxed);
            unsafe { System.realloc(p, l, n) }
        }
    }
    #[global_allocator]
    static A: Counting = Counting;
}

fn allocs() -> (u64, u64) {
    #[cfg(feature = "count-alloc")]
    return (
        count::ALLOCS.load(std::sync::atomic::Ordering::Relaxed),
        count::BYTES.load(std::sync::atomic::Ordering::Relaxed),
    );
    #[cfg(not(feature = "count-alloc"))]
    (0, 0)
}

// ------------------------------------------------------------------ input
const ROUTES: [&str; 4] = ["/v1/chat", "/v1/embed", "/v1/complete", "/v1/rerank"];
const MODELS: [&str; 4] = ["llama-3.1-8b", "qwen2.5-7b", "mistral-7b", "smollm3-3b"];

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

/// `lines` gateway records; `permille` of them carry one of four faults.
fn generate(lines: usize, permille: u64) -> String {
    let mut r = Rng(0x9E37_79B9_7F4A_7C15);
    let mut out = String::with_capacity(lines * 96);
    for i in 0..lines {
        let route = ROUTES[r.below(4) as usize];
        let mut model = MODELS[r.below(4) as usize];
        let tokens = (16 + r.below(2048)).to_string();
        let mut tokens = tokens.as_str();
        let latency = 40 + r.below(900);
        let mut status = [200, 200, 200, 429, 500][r.below(5) as usize];
        let mut drop_latency = false;
        if r.below(1000) < permille {
            match r.below(4) {
                0 => drop_latency = true,
                1 => tokens = "12x",
                2 => model = "gpt-9-turbo",
                _ => status = 999,
            }
        }
        write!(out, "ts={i} route={route} model={model} tokens={tokens}").unwrap();
        if !drop_latency {
            write!(out, " latency_ms={latency}").unwrap();
        }
        writeln!(out, " status={status}").unwrap();
    }
    out
}

#[derive(Debug, Clone, Copy)]
pub struct Record {
    pub model: u8,
    pub tokens: u32,
    pub latency_ms: u32,
    pub status: u16,
}

fn field<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    line.split_ascii_whitespace()
        .filter_map(|kv| kv.split_once('='))
        .find(|(k, _)| *k == key)
        .map(|(_, v)| v)
}

// ------------------------------------------------------------------ thiserror
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("missing field `{0}`")]
    Missing(&'static str),
    #[error("field `{field}` is not a number: {value:?}")]
    BadNumber {
        field: &'static str,
        value: String,
        #[source]
        source: ParseIntError,
    },
    #[error("unknown model {0:?}")]
    UnknownModel(String),
    #[error("status {0} out of range 100..=599")]
    BadStatus(u16),
}

#[derive(Debug, thiserror::Error)]
#[error("line {line}")]
pub struct AtLine {
    line: usize,
    #[source]
    source: ParseError,
}

fn num_typed<T: std::str::FromStr<Err = ParseIntError>>(line: &str, key: &'static str) -> Result<T, ParseError> {
    let v = field(line, key).ok_or(ParseError::Missing(key))?;
    v.parse().map_err(|source| ParseError::BadNumber { field: key, value: v.to_owned(), source })
}

#[inline(never)]
pub fn parse_typed(line: &str) -> Result<Record, ParseError> {
    let m = field(line, "model").ok_or(ParseError::Missing("model"))?;
    let model = MODELS.iter().position(|x| *x == m).ok_or_else(|| ParseError::UnknownModel(m.to_owned()))? as u8;
    let tokens = num_typed(line, "tokens")?;
    let latency_ms = num_typed(line, "latency_ms")?;
    let status: u16 = num_typed(line, "status")?;
    if !(100..=599).contains(&status) {
        return Err(ParseError::BadStatus(status));
    }
    Ok(Record { model, tokens, latency_ms, status })
}

// ------------------------------------------------------------------ anyhow
fn num_anyhow<T>(line: &str, key: &'static str) -> anyhow::Result<T>
where
    T: std::str::FromStr<Err = ParseIntError>,
{
    let v = field(line, key).with_context(|| format!("missing field `{key}`"))?;
    v.parse().with_context(|| format!("field `{key}` is not a number: {v:?}"))
}

#[inline(never)]
pub fn parse_anyhow(line: &str) -> anyhow::Result<Record> {
    let m = field(line, "model").context("missing field `model`")?;
    let model = MODELS.iter().position(|x| *x == m).ok_or_else(|| anyhow!("unknown model {m:?}"))? as u8;
    let tokens = num_anyhow(line, "tokens")?;
    let latency_ms = num_anyhow(line, "latency_ms")?;
    let status: u16 = num_anyhow(line, "status")?;
    if !(100..=599).contains(&status) {
        bail!("status {status} out of range 100..=599");
    }
    Ok(Record { model, tokens, latency_ms, status })
}

// ------------------------------------------------------------------ callers
#[inline(never)]
fn call_typed(n: usize, l: &str) -> Result<Record, AtLine> {
    parse_typed(l).map_err(|source| AtLine { line: n, source })
}
#[inline(never)]
fn call_anyhow(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_anyhow(l).with_context(|| format!("line {n}"))
}
#[inline(never)]
fn call_eager(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_anyhow(l).context(format!("line {n}"))
}
#[inline(never)]
fn call_hybrid(n: usize, l: &str) -> anyhow::Result<Record> {
    parse_typed(l).with_context(|| format!("line {n}"))
}

/// What a log line would show: the error and its sources joined by ": ".
/// For anyhow this is `{:#}`; for a std error we walk `source()` ourselves.
fn render_std(e: &(dyn std::error::Error + 'static), buf: &mut String) {
    write!(buf, "{e}").unwrap();
    let mut s = e.source();
    while let Some(x) = s {
        write!(buf, ": {x}").unwrap();
        s = x.source();
    }
}
fn render_anyhow(e: &anyhow::Error, buf: &mut String) {
    write!(buf, "{e:#}").unwrap();
}

fn fnv(h: &mut u64, bytes: &[u8]) {
    for b in bytes {
        *h ^= *b as u64;
        *h = h.wrapping_mul(0x100_0000_01b3);
    }
}

struct Pass {
    ok: u64,
    err: u64,
    sum: u64,
}

#[inline(never)]
fn drive<E>(text: &str, call: fn(usize, &str) -> Result<Record, E>, render: Option<fn(&E, &mut String)>) -> Pass {
    let mut p = Pass { ok: 0, err: 0, sum: 0xcbf2_9ce4_8422_2325 };
    let mut buf = String::with_capacity(256);
    for (n, l) in text.lines().enumerate() {
        match call(hint::black_box(n + 1), hint::black_box(l)) {
            Ok(r) => {
                p.ok += 1;
                p.sum = p.sum.wrapping_add(r.tokens as u64 + r.latency_ms as u64 + r.status as u64 + r.model as u64);
            }
            Err(e) => {
                p.err += 1;
                if let Some(f) = render {
                    buf.clear();
                    f(&e, &mut buf);
                    fnv(&mut p.sum, buf.as_bytes());
                }
                drop(hint::black_box(e));
            }
        }
    }
    p
}

fn one_pass(variant: &str, text: &str, render: bool) -> Pass {
    let rs = |e: &AtLine, b: &mut String| render_std(e, b);
    let ra = |e: &anyhow::Error, b: &mut String| render_anyhow(e, b);
    match variant {
        "typed" => drive(text, call_typed, render.then_some(rs as fn(&AtLine, &mut String))),
        "anyhow" => drive(text, call_anyhow, render.then_some(ra as fn(&anyhow::Error, &mut String))),
        "eager" => drive(text, call_eager, render.then_some(ra as fn(&anyhow::Error, &mut String))),
        "hybrid" => drive(text, call_hybrid, render.then_some(ra as fn(&anyhow::Error, &mut String))),
        v => panic!("unknown variant {v}"),
    }
}

fn run(args: &[String]) {
    let variant = args[0].as_str();
    let permille: u64 = args[1].parse().expect("fault permille");
    let render = match args[2].as_str() {
        "render" => true,
        "count" => false,
        m => panic!("mode is count or render, got {m}"),
    };
    let lines: usize = args.get(3).map_or(200_000, |s| s.parse().unwrap());
    let reps: usize = args.get(4).map_or(5, |s| s.parse().unwrap());
    let text = generate(lines, permille);
    one_pass(variant, &text, render); // warm-up
    let mut ns = Vec::with_capacity(reps);
    let (a0, b0) = allocs();
    let mut last = Pass { ok: 0, err: 0, sum: 0 };
    for _ in 0..reps {
        let t = Instant::now();
        last = one_pass(variant, &text, render);
        ns.push(t.elapsed().as_nanos() as f64);
    }
    let (a1, b1) = allocs();
    ns.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let med = ns[ns.len() / 2];
    let per_line = med / lines as f64;
    let rep = reps as f64;
    println!(
        "variant={variant} permille={permille} mode={} lines={lines} reps={reps} ok={} err={} ns_per_line={per_line:.2} \
         ms_per_pass={:.3} allocs_per_line={:.4} alloc_bytes_per_line={:.2} checksum={:016x}",
        args[2],
        last.ok,
        last.err,
        med / 1e6,
        (a1 - a0) as f64 / rep / lines as f64,
        (b1 - b0) as f64 / rep / lines as f64,
        last.sum
    );
}

fn show() {
    let line = "ts=17 route=/v1/chat model=qwen2.5-7b tokens=12x latency_ms=210 status=200";
    println!("input line 17: {line}\n");
    let t = call_typed(17, line).unwrap_err();
    let mut s = String::new();
    render_std(&t, &mut s);
    println!("typed (thiserror)  {{}}    -> {t}");
    println!("typed (thiserror)  chain -> {s}");
    println!("typed (thiserror)  {{:?}}  -> {t:?}");
    let a = call_anyhow(17, line).unwrap_err();
    println!("\nanyhow             {{}}    -> {a}");
    println!("anyhow             {{:#}}  -> {a:#}");
    println!("anyhow             {{:?}}  ->\n{a:?}");
    let h = call_hybrid(17, line).unwrap_err();
    let kind = match h.downcast_ref::<ParseError>() {
        Some(ParseError::BadNumber { field, .. }) => format!("BadNumber {{ field: {field:?} }}"),
        Some(other) => format!("{other:?}"),
        None => "not a ParseError".into(),
    };
    println!("\nhybrid  {{:#}} -> {h:#}");
    println!("hybrid  downcast_ref::<ParseError>() -> {kind}");
    let a_kind = a.downcast_ref::<ParseError>().map_or("None", |_| "Some");
    println!("anyhow  downcast_ref::<ParseError>() -> {a_kind}");
}

/// Cost of *printing* an anyhow error with `{:?}`: with a captured backtrace
/// that resolves symbols (slow the first time, cached after). 1 + 200 errors.
fn debugfmt() {
    let line = "ts=17 route=/v1/chat model=qwen2.5-7b tokens=12x latency_ms=210 status=200";
    let mut ns = Vec::new();
    let mut bytes = 0;
    for _ in 0..201 {
        let e = call_anyhow(17, hint::black_box(line)).unwrap_err();
        let t = Instant::now();
        let s = format!("{e:?}");
        ns.push(t.elapsed().as_nanos() as f64);
        bytes = s.len();
    }
    let first = ns[0];
    let mut rest = ns[1..].to_vec();
    rest.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!(
        "debug_first_us={:.1} debug_rest_median_us={:.1} debug_bytes={bytes}",
        first / 1e3,
        rest[rest.len() / 2] / 1e3
    );
}

fn sizes() {
    use std::mem::size_of;
    println!("Record={}", size_of::<Record>());
    println!("ParseError={}", size_of::<ParseError>());
    println!("AtLine={}", size_of::<AtLine>());
    println!("anyhow::Error={}", size_of::<anyhow::Error>());
    println!("Result<Record,ParseError>={}", size_of::<Result<Record, ParseError>>());
    println!("Result<Record,AtLine>={}", size_of::<Result<Record, AtLine>>());
    println!("anyhow::Result<Record>={}", size_of::<anyhow::Result<Record>>());
    println!("Result<Record,Box<dyn Error+Send+Sync>>={}", size_of::<Result<Record, Box<dyn std::error::Error + Send + Sync>>>());
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("run") => run(&args[1..]),
        Some("show") => show(),
        Some("sizes") => sizes(),
        Some("debugfmt") => debugfmt(),
        _ => eprintln!("usage: errbench run <typed|anyhow|eager|hybrid> <fault-permille> <count|render> [lines] [reps] | show | sizes"),
    }
}
