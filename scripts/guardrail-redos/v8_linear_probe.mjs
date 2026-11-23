// Which rules can V8's linear-time ("experimental") engine run at all?
//
//   node --enable-experimental-regexp-engine v8_linear_probe.mjs <rules.json>
//
// Compiles each pattern with the rule's own flags plus V8's `l` (linear) flag. The
// excessive-backtracks fallback can only switch to that engine for patterns it
// accepts; a SyntaxError here means the fallback flag cannot help that rule.
import { readFileSync } from "node:fs";

const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
console.log("$ node --enable-experimental-regexp-engine v8_linear_probe.mjs rules.json");
for (const r of cfg.rules) {
  for (const variant of ["naive", "hardened"]) {
    const flags = (r.flags.includes("i") ? "i" : "") + (r.mode === "replace" ? "g" : "");
    let res;
    try {
      new RegExp(r[variant], flags + "l");
      res = "linear ok";
    } catch (e) {
      res = "refused: " + e.message.replace(/^Invalid regular expression: \/.*\/[a-z]*: /, "");
    }
    console.log(`${r.name.padEnd(14)} ${variant.padEnd(9)} flags=${(flags || "-").padEnd(3)} ${res}`);
  }
}
