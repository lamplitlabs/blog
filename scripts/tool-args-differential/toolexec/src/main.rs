//! toolexec: the Rust side of the tool-call argument differential bench.
//!
//! A `read_file` tool server receives the model's `arguments` string (raw JSON
//! text, as OpenAI-style tool calls deliver it) and reads the named file under
//! a sandbox root. Each executor variant below is a common way to write that
//! handler with serde. The bench runs every variant over the same payloads
//! that the policy gates judged, and really opens the file.
//!
//!   toolexec exec <variant> <root> <payloads.b64>   one JSON line per payload
//!   toolexec gate rust-value <payloads.b64>          serde_json::Value gate
//!   toolexec bench <iterations>                      parse cost per variant
//!
//! Payload files hold one base64-encoded argument string per line.
use serde::Deserialize;
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

/// Variant `typed`: the usual derive. Unknown keys are ignored; a duplicate
/// `path` key is a "duplicate field" error.
#[derive(Deserialize)]
struct ReadFile {
    path: String,
}

/// Variant `typed-deny`: the same struct with `deny_unknown_fields`, and the
/// one optional field the tool schema declares.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadFileStrict {
    path: String,
    #[allow(dead_code)]
    #[serde(default)]
    reason: Option<String>,
}

/// Variant `alias`: accepts the spellings models often emit for the same field.
#[derive(Deserialize)]
struct ReadFileAlias {
    #[serde(alias = "file_path", alias = "filepath", alias = "filename")]
    path: String,
}

fn b64decode(s: &str) -> Vec<u8> {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut lut = [255u8; 256];
    for (i, c) in T.iter().enumerate() {
        lut[*c as usize] = i as u8;
    }
    let mut out = Vec::new();
    let (mut acc, mut bits) = (0u32, 0);
    for &c in s.trim().as_bytes() {
        if c == b'=' {
            break;
        }
        acc = (acc << 6) | lut[c as usize] as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
        }
    }
    out
}

fn read_payloads(file: &str) -> Vec<Vec<u8>> {
    let f = std::fs::File::open(file).expect("payload file");
    std::io::BufReader::new(f)
        .lines()
        .map(|l| b64decode(&l.unwrap()))
        .collect()
}

/// Pull `path` out of the raw argument bytes the way each variant does.
fn extract(variant: &str, raw: &[u8]) -> Result<String, String> {
    let e = |e: serde_json::Error| e.to_string();
    match variant {
        "typed" | "typed-checked" => serde_json::from_slice::<ReadFile>(raw).map(|a| a.path).map_err(e),
        "typed-deny" | "typed-deny-checked" => serde_json::from_slice::<ReadFileStrict>(raw).map(|a| a.path).map_err(e),
        "alias" => serde_json::from_slice::<ReadFileAlias>(raw).map(|a| a.path).map_err(e),
        "value" => {
            let v: serde_json::Value = serde_json::from_slice(raw).map_err(e)?;
            v.get("path").and_then(|p| p.as_str()).map(str::to_owned).ok_or_else(|| "no string path".into())
        }
        _ => panic!("unknown variant {variant}"),
    }
}

/// Executor-side containment: resolve symlinks and `..`, then require the
/// result to sit under <root>/workspace.
fn checked(root: &Path, p: &str) -> Result<PathBuf, String> {
    let ws = root.join("workspace").canonicalize().map_err(|e| e.to_string())?;
    let full = ws.parent().unwrap().join(p).canonicalize().map_err(|e| e.to_string())?;
    if full.starts_with(&ws) { Ok(full) } else { Err(format!("outside workspace: {}", full.display())) }
}

fn esc(s: &str) -> String {
    serde_json::to_string(s).unwrap()
}

fn exec(variant: &str, root: &str, file: &str) {
    let root = Path::new(root);
    let out = std::io::stdout();
    let mut out = out.lock();
    for (i, raw) in read_payloads(file).iter().enumerate() {
        let line = match extract(variant, raw) {
            Err(err) => format!(r#"{{"i":{i},"status":"reject","err":{}}}"#, esc(&err)),
            Ok(p) => {
                let target = if variant.ends_with("-checked") { checked(root, &p) } else { Ok(root.join(&p)) };
                match target.and_then(|t| std::fs::read_to_string(&t).map_err(|e| e.to_string())) {
                    Ok(body) => format!(
                        r#"{{"i":{i},"status":"read","path":{},"bytes":{},"sha_head":{}}}"#,
                        esc(&p),
                        body.len(),
                        esc(body.lines().next().unwrap_or(""))
                    ),
                    Err(err) => format!(r#"{{"i":{i},"status":"error","path":{},"err":{}}}"#, esc(&p), esc(&err)),
                }
            }
        };
        writeln!(out, "{line}").unwrap();
    }
}

/// A gate written in Rust over `serde_json::Value` (last duplicate wins).
fn gate_value(file: &str) {
    for raw in read_payloads(file) {
        let path = serde_json::from_slice::<serde_json::Value>(&raw)
            .ok()
            .and_then(|v| v.get("path").and_then(|p| p.as_str()).map(str::to_owned));
        let allow = path.as_deref().map(policy_ok).unwrap_or(false);
        println!(r#"{{"allow":{allow},"path":{}}}"#, path.as_deref().map(esc).unwrap_or("null".into()));
    }
}

/// The policy every gate applies: a relative path under workspace/ with no `..` part.
fn policy_ok(p: &str) -> bool {
    p.starts_with("workspace/") && !p.split('/').any(|c| c == "..")
}

fn bench(iters: usize) {
    let plain: &[u8] = br#"{"path": "workspace/src/handlers/billing/invoice_export.rs"}"#;
    let reason: &[u8] = br#"{"path": "workspace/src/handlers/billing/invoice_export.rs", "reason": "read the export handler before editing the CSV header order"}"#;
    let variants = ["typed", "typed-deny", "alias", "value"];
    let mut sink = 0usize;
    println!("variant\tpayload\tns_per_call");
    for (v, pname, raw) in variants.iter().flat_map(|v| [(*v, "plain", plain), (*v, "with-reason", reason)]) {
        // warm up
        for _ in 0..iters / 10 {
            sink += extract(v, raw).map(|p| p.len()).unwrap_or(0);
        }
        let t = Instant::now();
        for _ in 0..iters {
            sink += extract(v, std::hint::black_box(raw)).map(|p| p.len()).unwrap_or(0);
        }
        println!("{v}\t{pname}\t{:.1}", t.elapsed().as_nanos() as f64 / iters as f64);
    }
    // canonical re-serialisation: what a gate pays to forward the bytes it judged
    let t = Instant::now();
    for _ in 0..iters {
        let a: ReadFileStrict = serde_json::from_slice(std::hint::black_box(reason)).unwrap();
        sink += serde_json::to_vec(&serde_json::json!({ "path": a.path })).unwrap().len();
    }
    println!("parse+reserialise\twith-reason\t{:.1}", t.elapsed().as_nanos() as f64 / iters as f64);
    let root = std::env::temp_dir();
    let _ = std::fs::create_dir_all(root.join("workspace/src"));
    let _ = std::fs::write(root.join("workspace/src/x.rs"), "x");
    let t = Instant::now();
    let n = iters / 100;
    for _ in 0..n {
        sink += checked(&root, "workspace/src/x.rs").map(|p| p.as_os_str().len()).unwrap_or(0);
    }
    println!("canonicalize-check\tplain\t{:.1}", t.elapsed().as_nanos() as f64 / n as f64);
    eprintln!("sink {sink}");
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    match a.get(1).map(String::as_str) {
        Some("exec") => exec(&a[2], &a[3], &a[4]),
        Some("gate") => gate_value(&a[3]),
        Some("bench") => bench(a[2].parse().unwrap()),
        _ => {
            eprintln!("usage: toolexec exec <variant> <root> <payloads> | gate rust-value <payloads> | bench <n>");
            std::process::exit(2)
        }
    }
}
