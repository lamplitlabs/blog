// Guardrail service with V8 Irregexp: POST /check with a text body runs every rule.
//
//   node [--enable-experimental-regexp-engine-on-excessive-backtracks] server.mjs <rules.json> <naive|hardened> <port>
//
// One event loop, like most Node services: a slow match blocks every request.
// Reply: {"flagged": [rule names], "ms": guard time}.
import { readFileSync } from "node:fs";
import http from "node:http";

const [rulesPath, variant, port] = process.argv.slice(2);
const cfg = JSON.parse(readFileSync(rulesPath, "utf8"));
const rules = cfg.rules.map((r) => ({
  name: r.name,
  mode: r.mode,
  rx: new RegExp(r[variant], (r.flags.includes("i") ? "i" : "") + (r.mode === "replace" ? "g" : "")),
}));

function check(text) {
  const flagged = [];
  for (const r of rules) {
    if (r.mode === "search") {
      if (r.rx.test(text)) flagged.push(r.name);
    } else {
      const next = text.replace(r.rx, "#");
      if (next !== text) { flagged.push(r.name); text = next; }
    }
  }
  return flagged;
}

const server = http.createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    const t = process.hrtime.bigint();
    const flagged = check(Buffer.concat(chunks).toString("utf8"));
    const body = JSON.stringify({ flagged, ms: Number(process.hrtime.bigint() - t) / 1e6 });
    res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
    res.end(body);
  });
});
server.listen(Number(port), "127.0.0.1", 511, () => console.log(`node guard (${variant}) on :${port}`));
