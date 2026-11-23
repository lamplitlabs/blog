//! `guardbench serve <rules.json> <naive|hardened> <port>`: the guardrail service with the
//! Rust `regex` crate. std only: one thread per connection, HTTP/1.1 keep-alive, POST
//! /check with a Content-Length body. Reply: {"flagged": [rule names], "ms": guard time}.
use regex::{Regex, RegexBuilder};
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;
use std::time::Instant;

struct Rule {
    name: String,
    replace: bool,
    rx: Regex,
}

fn check(rules: &[Rule], body: &str) -> Vec<String> {
    let mut text = std::borrow::Cow::Borrowed(body);
    let mut flagged = Vec::new();
    for r in rules {
        if r.replace {
            let next = r.rx.replace_all(&text, "#").into_owned();
            if next != *text {
                flagged.push(r.name.clone());
                text = std::borrow::Cow::Owned(next);
            }
        } else if r.rx.is_match(&text) {
            flagged.push(r.name.clone());
        }
    }
    flagged
}

fn handle(stream: TcpStream, rules: Arc<Vec<Rule>>) -> std::io::Result<()> {
    stream.set_nodelay(true)?;
    let mut out = stream.try_clone()?;
    let mut rd = BufReader::new(stream);
    loop {
        let mut line = String::new();
        if rd.read_line(&mut line)? == 0 {
            return Ok(());
        }
        let mut len = 0usize;
        loop {
            let mut h = String::new();
            if rd.read_line(&mut h)? == 0 {
                return Ok(());
            }
            let h = h.trim_end();
            if h.is_empty() {
                break;
            }
            if let Some((k, v)) = h.split_once(':') {
                if k.eq_ignore_ascii_case("content-length") {
                    len = v.trim().parse().unwrap_or(0);
                }
            }
        }
        let mut body = vec![0u8; len];
        rd.read_exact(&mut body)?;
        let text = String::from_utf8_lossy(&body);
        let t = Instant::now();
        let flagged = check(&rules, &text);
        let ms = t.elapsed().as_nanos() as f64 / 1e6;
        let resp = serde_json::json!({ "flagged": flagged, "ms": ms }).to_string();
        write!(
            out,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            resp.len(),
            resp
        )?;
        out.flush()?;
    }
}

pub fn serve(rules_path: &str, variant: &str, port: &str) {
    let cfg: Value = serde_json::from_str(&std::fs::read_to_string(rules_path).unwrap()).unwrap();
    let rules: Vec<Rule> = cfg["rules"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Rule {
            name: r["name"].as_str().unwrap().to_string(),
            replace: r["mode"] == "replace",
            rx: RegexBuilder::new(r[variant].as_str().unwrap())
                .case_insensitive(r["flags"].as_str().unwrap().contains('i'))
                .build()
                .unwrap(),
        })
        .collect();
    let rules = Arc::new(rules);
    let l = TcpListener::bind(format!("127.0.0.1:{port}")).unwrap();
    println!("rust guard ({variant}) on :{port}");
    for s in l.incoming().flatten() {
        let rules = rules.clone();
        std::thread::spawn(move || {
            let _ = handle(s, rules);
        });
    }
}
