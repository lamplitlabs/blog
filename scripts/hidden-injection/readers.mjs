// Browser-side readers for scripts/hidden-injection/bench.py.
//
//   BROWSER_PATH=<chrome-headless-shell> node scripts/hidden-injection/readers.mjs <pages.json> <out.jsonl> [shots-dir]
//
// Starts a headless Chromium with a throwaway profile, talks to it over the
// DevTools protocol (Node 22's built-in WebSocket, no npm packages), and for
// every page in pages.json ([{id, url}]) records what four browser-based page
// readers hand to a model:
//   inner_text   document.body.innerText (CSS-aware, what most "read page" tools return)
//   text_content document.body.textContent (DOM text, CSS ignored)
//   ax_tree      names and static text of the accessibility tree (Accessibility.getFullAXTree),
//                the raw material of accessibility snapshots that browser agents read
//   visible      the visible-text filter from visible_text.js (the defence under test)
//   visible_basic the same filter without its gradient colour-stop check
// plus a full-page screenshot (PNG) for the OCR reader when shots-dir is given.
// Timings are measured in the page with performance.now().
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const [pagesFile, outFile, shotsDir] = process.argv.slice(2);
const bin = process.env.BROWSER_PATH;
if (!bin || !pagesFile || !outFile) {
  console.error('usage: BROWSER_PATH=... node readers.mjs <pages.json> <out.jsonl> [shots-dir]');
  process.exit(2);
}
const pages = JSON.parse(fs.readFileSync(pagesFile, 'utf8'));
const visibleJs = fs.readFileSync(new URL('./visible_text.js', import.meta.url), 'utf8');
const profile = fs.mkdtempSync(path.join(path.dirname(path.resolve(outFile)), 'chrome-profile-'));
const chrome = spawn(bin, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--hide-scrollbars', '--font-render-hinting=none', 'about:blank'], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let port;
for (let i = 0; i < 200 && !port; i++) {
  try { port = fs.readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch { await sleep(50); }
}
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let nextId = 1;
const pending = new Map();
const waiters = [];
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  } else if (msg.method) {
    for (const w of waiters.splice(0)) w(msg);
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const until = (method) => new Promise((resolve) => {
  const check = (msg) => (msg.method === method ? resolve(msg) : waiters.push(check));
  waiters.push(check);
});
const evaluate = async (expression) => {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
  return r.result.value;
};

await send('Page.enable');
await send('Accessibility.enable');
const out = fs.createWriteStream(outFile);
for (const page of pages) {
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const loaded = until('Page.loadEventFired');
  await send('Page.navigate', { url: page.url });
  await loaded;
  // Make the viewport as tall as the document, so every element has real
  // geometry and elementFromPoint can see the whole page.
  const height = await evaluate('Math.ceil(document.documentElement.scrollHeight)');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height, deviceScaleFactor: 1, mobile: false });
  await evaluate('document.fonts.ready.then(() => new Promise(r => requestAnimationFrame(() => r(1))))');
  const res = { id: page.id, height };
  const t = await evaluate(`(() => {
    let t0 = performance.now(); const it = document.body.innerText; const t1 = performance.now();
    const tc = document.body.textContent; const t2 = performance.now();
    return { inner_text: it, text_content: tc, ms_inner_text: t1 - t0, ms_text_content: t2 - t1 };
  })()`);
  Object.assign(res, t);
  const v = await evaluate(`(() => { ${visibleJs}; const t0 = performance.now(); const r = visibleText(document); return { visible: r.text, dropped: r.dropped, removed: r.removed, format_chars: r.formatChars, ms_visible: performance.now() - t0 }; })()`);
  Object.assign(res, v);
  const vb = await evaluate(`(() => { ${visibleJs}; const t0 = performance.now(); const r = visibleText(document, { gradientStops: false }); return { visible_basic: r.text, ms_visible_basic: performance.now() - t0 }; })()`);
  Object.assign(res, vb);
  const t0 = Date.now();
  const ax = await send('Accessibility.getFullAXTree');
  res.ms_ax_tree = Date.now() - t0;
  const names = [];
  for (const n of ax.nodes) {
    if (n.ignored) continue;
    const name = n.name && n.name.value;
    if (name) names.push(name);
    else if (n.value && typeof n.value.value === 'string' && n.value.value) names.push(n.value.value);
  }
  res.ax_tree = names.join('\n');
  if (shotsDir) {
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    const file = path.join(shotsDir, `${page.id}.png`);
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    res.screenshot = file;
  }
  out.write(JSON.stringify(res) + '\n');
}
out.end();
await new Promise((r) => out.on('finish', r));
ws.close();
chrome.kill();
await sleep(300);
fs.rmSync(profile, { recursive: true, force: true });
