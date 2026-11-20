// Node policy gate of the tool-call argument differential bench.
//   node gate.mjs <payloads.b64>
// JSON.parse each raw `arguments` string (a duplicate key keeps the last value),
// apply the shared policy and print {"allow","path","err"} per line.
import { readFileSync } from "node:fs";

const policyOk = (p) => p.startsWith("workspace/") && !p.split("/").includes("..");
const out = [];
for (const line of readFileSync(process.argv[2], "utf8").split("\n")) {
  if (!line) continue;
  const raw = Buffer.from(line, "base64").toString("utf8");
  let res = { allow: false, path: null, err: "" };
  try {
    const a = JSON.parse(raw);
    if (a && typeof a.path === "string") res = { allow: policyOk(a.path), path: a.path, err: "" };
  } catch (e) {
    res.err = String(e.message);
  }
  out.push(JSON.stringify(res));
}
process.stdout.write(out.join("\n") + "\n");
