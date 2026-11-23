//! Time the guardrail rules in rules.json with the Rust `regex` crate (finite automata,
//! no backtracking: O(m * n) per search).
//!
//!   guardbench bench <rules.json> <benign.txt> [budget_ms]
//!   guardbench compile <rules.json>
//!   guardbench serve <rules.json> <naive|hardened> <port>   (see serve.rs)
//!
//! `bench` prints the same tab-separated columns as bench.py, bench.mjs and gobench:
//!   kind engine rule variant n bytes ms matched
//! `compile` builds every pattern with the default size limit and prints
//!   compile engine rule variant ok|error micros message
//! because "it compiles in Python" does not mean it compiles here.
use regex::{Regex, RegexBuilder};
use serde_json::Value;
use std::time::Instant;

mod serve;

fn s(v: &Value, k: &str) -> String {
    v[k].as_str().unwrap_or_default().to_string()
}

fn build(rule: &Value, variant: &str) -> Result<Regex, regex::Error> {
    RegexBuilder::new(&s(rule, variant))
        .case_insensitive(s(rule, "flags").contains('i'))
        .build()
}

fn run(rx: &Regex, mode: &str, h: &str) -> bool {
    if mode == "search" {
        rx.is_match(h)
    } else {
        rx.replace_all(h, "#") != h
    }
}

fn timed(rx: &Regex, mode: &str, h: &str) -> (f64, bool) {
    let t = Instant::now();
    let m = run(rx, mode, h);
    (t.elapsed().as_nanos() as f64 / 1e6, m)
}

fn median(mut xs: Vec<f64>) -> f64 {
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let k = xs.len() / 2;
    if xs.len() % 2 == 1 { xs[k] } else { (xs[k - 1] + xs[k]) / 2.0 }
}

fn tf(b: bool) -> &'static str {
    if b { "True" } else { "False" }
}

const ENGINE: &str = "rust-regex-1.13";

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args[1] == "serve" {
        serve::serve(&args[2], &args[3], &args[4]);
        return;
    }
    let cfg: Value = serde_json::from_str(&std::fs::read_to_string(&args[2]).unwrap()).unwrap();
    let rules = cfg["rules"].as_array().unwrap();
    if args[1] == "compile" {
        for rule in rules {
            for variant in ["naive", "hardened"] {
                let t = Instant::now();
                let r = build(rule, variant);
                let us = t.elapsed().as_micros();
                match r {
                    Ok(_) => println!("compile\t{ENGINE}\t{}\t{variant}\tok\t{us}\t-", s(rule, "name")),
                    Err(e) => {
                        let msg = e.to_string().lines().last().unwrap_or("").trim().to_string();
                        println!("compile\t{ENGINE}\t{}\t{variant}\terror\t{us}\t{msg}", s(rule, "name"))
                    }
                }
            }
        }
        for p in cfg["compile_probes"].as_array().into_iter().flatten() {
            let t = Instant::now();
            let r = RegexBuilder::new(&s(p, "pattern")).case_insensitive(s(p, "flags").contains('i')).build();
            let us = t.elapsed().as_micros();
            let (ok, msg) = match r {
                Ok(_) => ("ok", "-".to_string()),
                Err(e) => ("error", e.to_string().lines().last().unwrap_or("").trim().to_string()),
            };
            println!("compile\t{ENGINE}\t{}\t{}\t{ok}\t{us}\t{msg}", s(p, "name"), s(p, "variant"));
        }
        return;
    }
    let budget: f64 = args.get(4).map(|b| b.parse().unwrap()).unwrap_or(cfg["budget_ms"].as_f64().unwrap());
    let text = std::fs::read_to_string(&args[3]).unwrap();
    let benign: Vec<&str> = text.lines().collect();
    let nbytes: usize = benign.iter().map(|l| l.len() + 1).sum();
    let ladder: Vec<usize> = cfg["ladder"].as_array().unwrap().iter().map(|n| n.as_u64().unwrap() as usize).collect();
    for rule in rules {
        let name = s(rule, "name");
        let mode = s(rule, "mode");
        for variant in ["naive", "hardened"] {
            let rx = match build(rule, variant) {
                Ok(rx) => rx,
                Err(_) => {
                    println!("pos\t{ENGINE}\t{name}\t{variant}\t0\t0\t0\tcompile-error");
                    continue;
                }
            };
            let pos = rule["positives"].as_array().unwrap();
            let hits = pos.iter().filter(|p| run(&rx, &mode, p.as_str().unwrap())).count();
            println!("pos\t{ENGINE}\t{name}\t{variant}\t{hits}\t{}\t0\t{}", pos.len(), tf(hits == pos.len()));
            let a = &rule["attack"];
            for &n in &ladder {
                let h = format!("{}{}{}", s(a, "prefix"), s(a, "unit").repeat(n), s(a, "suffix"));
                let (first, m) = timed(&rx, &mode, &h);
                let reps = if first < 50.0 { 5 } else if first < 300.0 { 3 } else { 1 };
                let mut samples = vec![first];
                for _ in 1..reps {
                    samples.push(timed(&rx, &mode, &h).0);
                }
                let ms = median(samples);
                println!("attack\t{ENGINE}\t{name}\t{variant}\t{n}\t{}\t{ms:.4}\t{}", h.len(), tf(m));
                if ms > budget {
                    break;
                }
            }
            let nat = &rule["natural"];
            let words: Vec<&str> = nat["words"].as_array().unwrap().iter().map(|w| w.as_str().unwrap()).collect();
            for k in 1..=words.len() {
                let h = format!("{}{}{}", s(nat, "prefix"), words[..k].join(&s(nat, "sep")), s(nat, "suffix"));
                let (first, m) = timed(&rx, &mode, &h);
                let mut samples = vec![first];
                if first < 50.0 {
                    for _ in 0..4 {
                        samples.push(timed(&rx, &mode, &h).0);
                    }
                }
                let ms = median(samples);
                println!("natural\t{ENGINE}\t{name}\t{variant}\t{k}\t{}\t{ms:.4}\t{}", h.len(), tf(m));
                if ms > budget {
                    break;
                }
            }
            let mut samples = Vec::new();
            let mut hits = 0;
            for _ in 0..5 {
                hits = 0;
                let t = Instant::now();
                for l in &benign {
                    if run(&rx, &mode, l) {
                        hits += 1;
                    }
                }
                samples.push(t.elapsed().as_nanos() as f64 / 1e6);
            }
            println!("benign\t{ENGINE}\t{name}\t{variant}\t{}\t{nbytes}\t{:.4}\t{hits}", benign.len(), median(samples));
        }
    }
}
