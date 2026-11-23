// Time the guardrail rules in rules.json with V8's Irregexp (Node), a backtracking engine.
//
//   node bench.mjs <rules.json> <benign.txt> [budget_ms]
//   node --enable-experimental-regexp-engine-on-excessive-backtracks bench.mjs ...
//
// Same output columns as bench.py: kind engine rule variant n bytes ms matched.
// The engine name says whether V8's linear-time fallback flag was on (V8 flags are
// process-wide, so the worker threads run with it too). Each (rule, variant) runs in a worker thread; a watchdog
// terminates it when one timing passes cfg.cap_s, and that row reports ms = cap and
// matched = capped, the same as bench.py. The benign corpus is timed first so a capped
// ladder cannot lose it.
import { readFileSync } from "node:fs";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";

const median = (xs) => { const s = [...xs].sort((a, b) => a - b); const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
const bytes = (s) => Buffer.byteLength(s, "utf8");

if (!isMainThread) {
  const { rule, variant, ladder, budget, benign } = workerData;
  const row = (...c) => parentPort.postMessage({ row: c.join("\t") });
  const run = (rx, mode, s) => {
    if (mode === "search") { rx.lastIndex = 0; return rx.test(s); }
    return s.replace(rx, "#") !== s;
  };
  const timed = (rx, mode, s, kind, n, len) => {
    parentPort.postMessage({ start: [kind, n, len] });
    const t = process.hrtime.bigint();
    const m = run(rx, mode, s);
    return [Number(process.hrtime.bigint() - t) / 1e6, m];
  };
  const flags = (rule.flags.includes("i") ? "i" : "") + (rule.mode === "replace" ? "g" : "");
  const rx = new RegExp(rule[variant], flags);
  const posHits = rule.positives.filter((p) => run(rx, rule.mode, p)).length;
  row("pos", workerData.engine, rule.name, variant, posHits, rule.positives.length, 0, posHits === rule.positives.length ? "True" : "False");
  const samples = [];
  let hits = 0;
  for (let i = 0; i < 5; i++) {
    hits = 0;
    parentPort.postMessage({ start: ["benign", benign.length, 0] });
    const t = process.hrtime.bigint();
    for (const line of benign) if (run(rx, rule.mode, line)) hits++;
    samples.push(Number(process.hrtime.bigint() - t) / 1e6);
  }
  row("benign", workerData.engine, rule.name, variant, benign.length, benign.reduce((s, l) => s + bytes(l) + 1, 0), median(samples).toFixed(4), hits);
  const a = rule.attack;
  for (const n of ladder) {
    const s = a.prefix + a.unit.repeat(n) + a.suffix;
    const [first, m] = timed(rx, rule.mode, s, "attack", n, bytes(s));
    const samples = [first];
    const reps = first < 50 ? 5 : first < 300 ? 3 : 1;
    for (let i = 1; i < reps; i++) samples.push(timed(rx, rule.mode, s, "attack", n, bytes(s))[0]);
    const ms = median(samples);
    row("attack", workerData.engine, rule.name, variant, n, bytes(s), ms.toFixed(4), m ? "True" : "False");
    if (ms > budget) break;
  }
  const nat = rule.natural;
  for (let k = 1; k <= nat.words.length; k++) {
    const s = nat.prefix + nat.words.slice(0, k).join(nat.sep) + nat.suffix;
    const [first, m] = timed(rx, rule.mode, s, "natural", k, bytes(s));
    const samples = [first];
    if (first < 50) for (let i = 0; i < 4; i++) samples.push(timed(rx, rule.mode, s, "natural", k, bytes(s))[0]);
    const ms = median(samples);
    row("natural", workerData.engine, rule.name, variant, k, bytes(s), ms.toFixed(4), m ? "True" : "False");
    if (ms > budget) break;
  }
} else {
  const [rulesPath, benignPath, budgetArg] = process.argv.slice(2);
  const cfg = JSON.parse(readFileSync(rulesPath, "utf8"));
  const budget = Number(budgetArg || cfg.budget_ms);
  const capMs = (cfg.cap_s || 120) * 1000;
  const benign = readFileSync(benignPath, "utf8").split("\n");
  if (benign.at(-1) === "") benign.pop();
  const fallback = process.execArgv.some((a) => a.includes("excessive-backtracks"));
  const engine = `node${process.versions.node.split(".")[0]}-irregexp${fallback ? "+fallback" : ""}`;
  const out = (s) => process.stdout.write(s + "\n");
  for (const rule of cfg.rules) {
    for (const variant of ["naive", "hardened"]) {
      await new Promise((resolve) => {
        const w = new Worker(new URL(import.meta.url), {
          workerData: { rule, variant, ladder: cfg.ladder, budget, benign, engine },
        });
        let current = null;
        let timer = null;
        const arm = () => {
          clearTimeout(timer);
          timer = setTimeout(async () => {
            const [kind, n, len] = current;
            await w.terminate();
            out([kind, engine, rule.name, variant, n, len, capMs.toFixed(4), "capped"].join("\t"));
            resolve();
          }, capMs);
        };
        w.on("message", (m) => {
          if (m.start) { current = m.start; arm(); }
          if (m.row) out(m.row);
        });
        w.on("exit", () => { clearTimeout(timer); resolve(); });
        w.on("error", (e) => { clearTimeout(timer); out(`error\t${engine}\t${rule.name}\t${variant}\t${e.message}`); resolve(); });
      });
    }
  }
}
