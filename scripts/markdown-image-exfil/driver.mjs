// Headless Chromium driver for scripts/markdown-image-exfil/bench.py.
//
//   BROWSER_PATH=<chrome-headless-shell> node driver.mjs <pages.json> <out.jsonl> [settle-ms]
//
// pages.json is [{id, url, shot?}]. For every page it navigates, waits for the
// load event plus settle-ms (default 600) so late image, poster, CSS and
// prefetch requests and a meta refresh have time to fire, then records
// window.__measure() and the URL the tab ended on. When `shot` is set it also
// saves a PNG screenshot of the page to that path. Same DevTools-protocol
// approach as scripts/hidden-injection/readers.mjs: Node 22's built-in
// WebSocket and fetch, no npm packages, a throwaway profile.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const [pagesFile, outFile, settleArg] = process.argv.slice(2);
const settle = Number(settleArg || 600);
const bin = process.env.BROWSER_PATH;
if (!bin || !pagesFile || !outFile) {
  console.error('usage: BROWSER_PATH=... node driver.mjs <pages.json> <out.jsonl> [settle-ms]');
  process.exit(2);
}
const pages = JSON.parse(fs.readFileSync(pagesFile, 'utf8'));
const profile = fs.mkdtempSync(path.join(path.dirname(path.resolve(outFile)), 'chrome-profile-'));
const chrome = spawn(bin, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--hide-scrollbars', '--font-render-hinting=none', '--disable-background-networking',
  '--no-first-run', 'about:blank'], { stdio: 'ignore' });

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
const consoleLines = [];
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  } else if (msg.method) {
    if (msg.method === 'Log.entryAdded') consoleLines.push(msg.params.entry.text);
    for (const w of waiters.splice(0)) w(msg);
  }
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const until = (method, ms) => new Promise((resolve) => {
  const timer = setTimeout(() => resolve(null), ms);
  const check = (msg) => {
    if (msg.method === method) { clearTimeout(timer); resolve(msg); } else waiters.push(check);
  };
  waiters.push(check);
});

await send('Page.enable');
await send('Log.enable');
await send('Network.enable');
await send('Network.setCacheDisabled', { cacheDisabled: true });
const out = fs.createWriteStream(outFile);
for (const page of pages) {
  consoleLines.length = 0;
  await send('Emulation.setDeviceMetricsOverride', { width: page.width || 1280, height: page.height || 900, deviceScaleFactor: 1, mobile: false });
  const loaded = until('Page.loadEventFired', 8000);
  const t0 = Date.now();
  await send('Page.navigate', { url: page.url });
  await loaded;
  await sleep(page.settle || settle);
  let measure = null;
  let finalUrl = null;
  try {
    const r = await send('Runtime.evaluate', {
      expression: 'JSON.stringify({u: location.href, m: window.__measure ? window.__measure() : null})',
      returnByValue: true,
    });
    const v = JSON.parse(r.result.value);
    finalUrl = v.u;
    measure = v.m;
  } catch (e) {
    finalUrl = 'error: ' + e.message;
  }
  if (page.shot) {
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(page.shot, Buffer.from(shot.data, 'base64'));
  }
  out.write(JSON.stringify({ id: page.id, nav_epoch_ms: t0, final_url: finalUrl, measure, wall_ms: Date.now() - t0,
    csp_violations: consoleLines.filter((l) => l.includes('Content Security Policy')).length }) + '\n');
  await send('Page.navigate', { url: 'about:blank' });
  await sleep(50);
}
out.end();
await new Promise((r) => out.on('finish', r));
ws.close();
chrome.kill();
await sleep(300);
fs.rmSync(profile, { recursive: true, force: true });
