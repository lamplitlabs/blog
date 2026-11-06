//! tokiobench: five Tokio performance pitfalls, each measured next to its fix.
//!
//!   tokiobench blocking <variant> <secs> <burst>  variant: none | inline | spawn_blocking | block_in_place
//!   tokiobench mutex <variant>             variant: std | parking_lot | tokio
//!   tokiobench held <variant> <tasks>      variant: across_await | scoped
//!   tokiobench spawn <variant> <items> <work>  variant: per_item | joinset | chunked | inline
//!   tokiobench fs <variant> <dir> <files>  variant: tokio_seq | tokio_join | std_inline | one_blocking
//!
//! Every command prints one line of key=value pairs.
//! The runtime always has 4 worker threads so results do not depend on the core count.

use std::collections::HashMap;
use std::hint::black_box;
use std::sync::Arc;
use std::time::{Duration, Instant};

const WORKERS: usize = 4;

fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(WORKERS)
        .enable_all()
        .build()
        .expect("runtime")
}

/// Deterministic CPU work: `iters` rounds of xorshift. About 1.5-1.9 ns per round on an M2 Pro.
#[inline(never)]
fn burn(iters: u64, seed: u64) -> u64 {
    let mut x = seed | 1;
    for _ in 0..iters {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
    }
    black_box(x)
}

fn pct(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return f64::NAN;
    }
    let i = ((sorted.len() as f64 - 1.0) * p).round() as usize;
    sorted[i]
}

fn arg(args: &[String], i: usize, what: &str) -> String {
    args.get(i).cloned().unwrap_or_else(|| {
        eprintln!("missing argument: {what}");
        std::process::exit(2)
    })
}

// ------------------------------------------------------------------ 1. blocking
//
// An open-loop load generator (a plain OS thread, like a network client that does
// not care how the server is doing) spawns 4,000 light requests per second, each
// about 40 us of CPU. Twenty times a second it also spawns a heavy job: about
// 30-37 ms of CPU (think: hashing an upload, a big serde parse, a regex compile).
// Heavy jobs arrive in bursts of `burst` at once (20/burst bursts a second), so the
// heavy CPU per second is the same for every burst size.
// The latency of a light request is measured from its scheduled arrival, so a
// stalled runtime cannot hide its queueing delay (no coordinated omission).
const LIGHT_PER_SEC: u64 = 4000;
const HEAVY_PER_SEC: u64 = 20;
const LIGHT_ITERS: u64 = 25_000;
const HEAVY_ITERS: u64 = 20_000_000;

fn blocking(variant: &str, secs: u64, burst: u64) {
    let rt = runtime();
    let handle = rt.handle().clone();
    let lat = Arc::new(std::sync::Mutex::new(Vec::<f64>::with_capacity(
        (LIGHT_PER_SEC * secs) as usize,
    )));
    let heavy_ms = Arc::new(std::sync::Mutex::new(Vec::<f64>::new()));
    let heavy_every = LIGHT_PER_SEC * burst / HEAVY_PER_SEC;
    let total = LIGHT_PER_SEC * secs;
    let start = Instant::now() + Duration::from_millis(50);
    let mut joins = Vec::with_capacity(total as usize);
    let mut heavy_joins = Vec::new();
    for i in 0..total {
        let due = start + Duration::from_nanos(i * 1_000_000_000 / LIGHT_PER_SEC);
        // Pure spin: on a busy laptop OS sleeps overshoot by milliseconds, which would
        // turn the generator itself into the source of the tail.
        while Instant::now() < due {
            std::hint::spin_loop();
        }
        for b in 0..burst {
            if variant == "none" || i % heavy_every != heavy_every / 2 {
                break;
            }
            let i = i * 8 + b;
            let hm = heavy_ms.clone();
            let v = variant.to_string();
            heavy_joins.push(handle.spawn(async move {
                let t0 = Instant::now();
                let x = match v.as_str() {
                    "inline" => burn(HEAVY_ITERS, i),
                    "spawn_blocking" => tokio::task::spawn_blocking(move || burn(HEAVY_ITERS, i))
                        .await
                        .unwrap(),
                    "block_in_place" => tokio::task::block_in_place(|| burn(HEAVY_ITERS, i)),
                    other => panic!("unknown variant {other}"),
                };
                hm.lock().unwrap().push(t0.elapsed().as_secs_f64() * 1e3);
                x
            }));
        }
        let lat = lat.clone();
        joins.push(handle.spawn(async move {
            let x = burn(LIGHT_ITERS, i);
            let us = due.elapsed().as_secs_f64() * 1e6;
            lat.lock().unwrap().push(us);
            x
        }));
    }
    rt.block_on(async {
        for j in joins.into_iter().chain(heavy_joins) {
            j.await.unwrap();
        }
    });
    let mut l = lat.lock().unwrap().clone();
    l.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let h = heavy_ms.lock().unwrap().clone();
    let heavy_mean = if h.is_empty() { 0.0 } else { h.iter().sum::<f64>() / h.len() as f64 };
    let over_10ms = l.iter().filter(|&&x| x > 10_000.0).count() as f64 / l.len() as f64;
    println!(
        "experiment=blocking variant={variant} burst={burst} requests={} p50_us={:.1} p90_us={:.1} p99_us={:.1} p999_us={:.1} max_us={:.1} over_10ms_pct={:.3} heavy_jobs={} heavy_mean_ms={:.2}",
        l.len(),
        pct(&l, 0.50),
        pct(&l, 0.90),
        pct(&l, 0.99),
        pct(&l, 0.999),
        l[l.len() - 1],
        over_10ms * 100.0,
        h.len(),
        heavy_mean
    );
}

// --------------------------------------------------------------------- 2. mutex
//
// 64 tasks on 4 workers each do 20,000 updates of a shared HashMap<u64, u64>.
// The critical section is a few hundred nanoseconds and never awaits, which is
// exactly the case the Tokio docs say a blocking mutex is fine for.
const MUTEX_TASKS: u64 = 64;
const MUTEX_OPS: u64 = 20_000;

fn mutex(variant: &str) {
    let rt = runtime();
    let t0 = Instant::now();
    let sum = rt.block_on(async {
        let mut js = Vec::new();
        match variant {
            "std" => {
                let m = Arc::new(std::sync::Mutex::new(HashMap::<u64, u64>::new()));
                for t in 0..MUTEX_TASKS {
                    let m = m.clone();
                    js.push(tokio::spawn(async move {
                        for i in 0..MUTEX_OPS {
                            *m.lock().unwrap().entry((t * 31 + i) % 1024).or_default() += 1;
                            if i % 64 == 0 {
                                tokio::task::yield_now().await;
                            }
                        }
                    }));
                }
                for j in js {
                    j.await.unwrap();
                }
                let s: u64 = m.lock().unwrap().values().sum();
                s
            }
            "parking_lot" => {
                let m = Arc::new(parking_lot::Mutex::new(HashMap::<u64, u64>::new()));
                for t in 0..MUTEX_TASKS {
                    let m = m.clone();
                    js.push(tokio::spawn(async move {
                        for i in 0..MUTEX_OPS {
                            *m.lock().entry((t * 31 + i) % 1024).or_default() += 1;
                            if i % 64 == 0 {
                                tokio::task::yield_now().await;
                            }
                        }
                    }));
                }
                for j in js {
                    j.await.unwrap();
                }
                let s: u64 = m.lock().values().sum();
                s
            }
            "tokio" => {
                let m = Arc::new(tokio::sync::Mutex::new(HashMap::<u64, u64>::new()));
                for t in 0..MUTEX_TASKS {
                    let m = m.clone();
                    js.push(tokio::spawn(async move {
                        for i in 0..MUTEX_OPS {
                            *m.lock().await.entry((t * 31 + i) % 1024).or_default() += 1;
                            if i % 64 == 0 {
                                tokio::task::yield_now().await;
                            }
                        }
                    }));
                }
                for j in js {
                    j.await.unwrap();
                }
                let s: u64 = m.lock().await.values().sum();
                s
            }
            other => panic!("unknown variant {other}"),
        }
    });
    let ns = t0.elapsed().as_secs_f64() * 1e9 / (MUTEX_TASKS * MUTEX_OPS) as f64;
    assert_eq!(sum, MUTEX_TASKS * MUTEX_OPS);
    println!("experiment=mutex variant={variant} ops={} ns_per_op={ns:.1}", MUTEX_TASKS * MUTEX_OPS);
}

// ------------------------------------------------------------------ fake network
//
// A dedicated OS thread that completes "network calls" after an exact delay by
// spinning on a deadline list. tokio::time::sleep would do, except that this host
// coalesces timers by several milliseconds and that would swamp the 2 ms we model.
struct FakeNet {
    tx: std::sync::mpsc::Sender<(Instant, tokio::sync::oneshot::Sender<()>)>,
}

impl FakeNet {
    fn start() -> FakeNet {
        let (tx, rx) = std::sync::mpsc::channel::<(Instant, tokio::sync::oneshot::Sender<()>)>();
        std::thread::spawn(move || {
            let mut pending: Vec<(Instant, tokio::sync::oneshot::Sender<()>)> = Vec::new();
            loop {
                loop {
                    match rx.try_recv() {
                        Ok(p) => pending.push(p),
                        Err(std::sync::mpsc::TryRecvError::Empty) => break,
                        Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                            if pending.is_empty() {
                                return;
                            }
                            break;
                        }
                    }
                }
                let now = Instant::now();
                let mut i = 0;
                while i < pending.len() {
                    if pending[i].0 <= now {
                        let (_, done) = pending.swap_remove(i);
                        let _ = done.send(());
                    } else {
                        i += 1;
                    }
                }
                std::hint::spin_loop();
            }
        });
        FakeNet { tx }
    }

    async fn call(&self, d: Duration) {
        let (done, wait) = tokio::sync::oneshot::channel();
        self.tx.send((Instant::now() + d, done)).unwrap();
        wait.await.unwrap();
    }
}

// ---------------------------------------------------------------------- 3. held
//
// Each task updates a shared cache entry and then does a 2 ms "upstream call"
// (FakeNet standing in for a network round trip). The pitfall holds
// the tokio::sync::Mutex guard across that await; the fix drops it first.
fn held(variant: &str, tasks: u64) {
    let rt = runtime();
    let t0 = Instant::now();
    let net = Arc::new(FakeNet::start());
    let lat = rt.block_on(async {
        let m = Arc::new(tokio::sync::Mutex::new(HashMap::<u64, u64>::new()));
        let mut js = Vec::new();
        for t in 0..tasks {
            let m = m.clone();
            let net = net.clone();
            let v = variant.to_string();
            js.push(tokio::spawn(async move {
                let s = Instant::now();
                match v.as_str() {
                    "across_await" => {
                        let mut g = m.lock().await;
                        *g.entry(t % 16).or_default() += 1;
                        net.call(Duration::from_millis(2)).await; // guard still alive
                    }
                    "scoped" => {
                        {
                            let mut g = m.lock().await;
                            *g.entry(t % 16).or_default() += 1;
                        } // guard dropped here
                        net.call(Duration::from_millis(2)).await;
                    }
                    other => panic!("unknown variant {other}"),
                }
                s.elapsed().as_secs_f64() * 1e3
            }));
        }
        let mut l = Vec::new();
        for j in js {
            l.push(j.await.unwrap());
        }
        l
    });
    let wall = t0.elapsed().as_secs_f64() * 1e3;
    let mut l = lat;
    l.sort_by(|a, b| a.partial_cmp(b).unwrap());
    println!(
        "experiment=held variant={variant} tasks={tasks} wall_ms={wall:.1} p50_ms={:.2} p99_ms={:.2} per_sec={:.0}",
        pct(&l, 0.5),
        pct(&l, 0.99),
        tasks as f64 / (wall / 1e3)
    );
}

// --------------------------------------------------------------------- 4. spawn
//
// Process `items` independent items of `work` xorshift rounds each.
fn spawn(variant: &str, items: u64, work: u64) {
    let rt = runtime();
    let t0 = Instant::now();
    let acc = rt.block_on(async {
        match variant {
            "per_item" => {
                let mut js = Vec::with_capacity(items as usize);
                for i in 0..items {
                    js.push(tokio::spawn(async move { burn(work, i) }));
                }
                let mut a = 0u64;
                for j in js {
                    a ^= j.await.unwrap();
                }
                a
            }
            "joinset" => {
                let mut set = tokio::task::JoinSet::new();
                for i in 0..items {
                    set.spawn(async move { burn(work, i) });
                }
                let mut a = 0u64;
                while let Some(r) = set.join_next().await {
                    a ^= r.unwrap();
                }
                a
            }
            "chunked" => {
                // One task per chunk, 4x as many chunks as workers.
                let chunks = (WORKERS as u64) * 4;
                let per = items.div_ceil(chunks);
                let mut js = Vec::new();
                for c in 0..chunks {
                    let lo = c * per;
                    let hi = ((c + 1) * per).min(items);
                    js.push(tokio::spawn(async move {
                        let mut a = 0u64;
                        for i in lo..hi {
                            a ^= burn(work, i);
                        }
                        a
                    }));
                }
                let mut a = 0u64;
                for j in js {
                    a ^= j.await.unwrap();
                }
                a
            }
            "inline" => {
                let mut a = 0u64;
                for i in 0..items {
                    a ^= burn(work, i);
                }
                a
            }
            other => panic!("unknown variant {other}"),
        }
    });
    let el = t0.elapsed().as_secs_f64();
    black_box(acc);
    println!(
        "experiment=spawn variant={variant} items={items} work={work} total_ms={:.2} ns_per_item={:.1}",
        el * 1e3,
        el * 1e9 / items as f64
    );
}

// ------------------------------------------------------------------------ 5. fs
//
// Read `files` small files (4 KiB, already in the page cache).
fn fs(variant: &str, dir: &str, files: usize) {
    let dir = std::path::PathBuf::from(dir);
    std::fs::create_dir_all(&dir).unwrap();
    let names: Vec<_> = (0..files).map(|i| dir.join(format!("f{i:05}.json"))).collect();
    for (i, n) in names.iter().enumerate() {
        if !n.exists() {
            std::fs::write(n, vec![b'a' + (i % 26) as u8; 4096]).unwrap();
        }
    }
    // warm the page cache
    let warm: usize = names.iter().map(|n| std::fs::read(n).unwrap().len()).sum();
    let rt = runtime();
    let names = Arc::new(names);
    let t0 = Instant::now();
    let bytes = rt.block_on(async {
        match variant {
            "tokio_seq" => {
                let mut b = 0usize;
                for n in names.iter() {
                    b += tokio::fs::read(n).await.unwrap().len();
                }
                b
            }
            "tokio_join" => {
                let mut js = Vec::new();
                for i in 0..names.len() {
                    let names = names.clone();
                    js.push(tokio::spawn(async move { tokio::fs::read(&names[i]).await.unwrap().len() }));
                }
                let mut b = 0usize;
                for j in js {
                    b += j.await.unwrap();
                }
                b
            }
            "std_inline" => names.iter().map(|n| std::fs::read(n).unwrap().len()).sum(),
            "one_blocking" => {
                let names = names.clone();
                tokio::task::spawn_blocking(move || {
                    names.iter().map(|n| std::fs::read(n).unwrap().len()).sum()
                })
                .await
                .unwrap()
            }
            other => panic!("unknown variant {other}"),
        }
    });
    let el = t0.elapsed().as_secs_f64();
    assert_eq!(bytes, warm);
    println!(
        "experiment=fs variant={variant} files={files} total_ms={:.2} us_per_file={:.2} ",
        el * 1e3,
        el * 1e6 / files as f64
    );
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match arg(&args, 1, "command").as_str() {
        "blocking" => blocking(
            &arg(&args, 2, "variant"),
            arg(&args, 3, "secs").parse().unwrap(),
            arg(&args, 4, "burst").parse().unwrap(),
        ),
        "mutex" => mutex(&arg(&args, 2, "variant")),
        "held" => held(&arg(&args, 2, "variant"), arg(&args, 3, "tasks").parse().unwrap()),
        "spawn" => spawn(
            &arg(&args, 2, "variant"),
            arg(&args, 3, "items").parse().unwrap(),
            arg(&args, 4, "work").parse().unwrap(),
        ),
        "fs" => fs(&arg(&args, 2, "variant"), &arg(&args, 3, "dir"), arg(&args, 4, "files").parse().unwrap()),
        other => {
            eprintln!("unknown command {other}");
            std::process::exit(2)
        }
    }
}
