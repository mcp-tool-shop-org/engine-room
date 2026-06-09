#!/usr/bin/env node
// Zero-dependency Control Panel gallery generator.
// Drives ../dist/control-panel.html through its real states (via [data-act] clicks over CDP)
// and writes a PNG per state. No npm install — uses system Chrome + Node 22's global WebSocket/fetch.
//
//   node capture.mjs [outDir]      (default outDir: this folder)
//
// Override the browser with ER_CHROME=/path/to/chrome.exe.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(process.argv[2] || HERE);
const PAGE = pathToFileURL(resolve(HERE, '..', 'dist', 'control-panel.html')).href;
const PORT = 9456;
const W = 1512, H = 982;

const CHROME = process.env.ER_CHROME ||
  ['C:/Program Files/Google/Chrome/Application/chrome.exe',
   'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(p => existsSync(p))
  || 'chrome';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function main() {
  const profile = mkdtempSync(join(tmpdir(), 'er-gallery-'));
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
    `--window-size=${W},${H}`, `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', 'about:blank',
  ], { stdio: 'ignore' });

  try {
    const wsUrl = await waitForWs();
    const cdp = await connect(wsUrl);
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
    await cdp.send('Page.navigate', { url: PAGE });
    await waitFor(cdp, `!!document.querySelector('[data-act="select"]')`, 8000); // real cards, past the boot skeleton
    await sleep(250);

    let n = 0;
    const shot = async (name) => {
      const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
      const file = join(OUT, `${String(++n).padStart(2, '0')}-${name}.png`);
      writeFileSync(file, Buffer.from(data, 'base64'));
      console.log('  wrote', file);
    };
    const click = (sel) => cdp.send('Runtime.evaluate', { expression: `document.querySelector(${JSON.stringify(sel)})?.click()` });
    const select = async (id) => { await click(`[data-act="select"][data-id="${id}"]`); await sleep(200); };

    const preflight = (id) => click(`[data-act="preflight"][data-id="${id}"]`);

    await shot('catalog-dark');
    // clean theme + offline captures from the unselected catalog (parity check)
    await click(`[data-act="toggle-theme"]`); await sleep(180); await shot('catalog-light');
    await click(`[data-act="toggle-theme"]`); await sleep(120);
    await click(`[data-act="toggle-exec"]`); await sleep(180); await shot('offline-readonly');
    await click(`[data-act="toggle-exec"]`); await sleep(120);
    await select('llamacpp-swap'); await shot('detail-server');
    await preflight('llamacpp-swap'); await sleep(1600);
    await click(`[data-act="run"][data-id="llamacpp-swap"]`); await sleep(3600); await shot('server-running');
    await select('gguf-imatrix'); await shot('detail-producer');
    await select('sageattention'); await shot('detail-modifier');
    await select('litellm'); await shot('detail-router');
    await select('exllama-cu128'); await preflight('exllama-cu128'); await sleep(1600); await shot('andon-halt');
    await cdp.send('Runtime.evaluate', { expression:
      `(()=>{const s=document.querySelector('#search');s.value='zzqq-nothing';s.dispatchEvent(new Event('input',{bubbles:true}));})()` });
    await sleep(200); await shot('empty-search');

    cdp.close();
    console.log(`\n${n} states captured to ${OUT}`);
  } finally {
    chrome.kill();
    try { rmSync(profile, { recursive: true, force: true }); } catch {}
  }
}

async function waitForWs() {
  for (let i = 0; i < 50; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json`);
      const targets = await r.json();
      const page = targets.find(t => t.type === 'page' && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(200);
  }
  throw new Error('Chrome DevTools page target did not come up');
}

function connect(wsUrl) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pending = new Map();
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { resolve, reject } = pending.get(msg.id); pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
      }
    };
    ws.onerror = (e) => rej(new Error('ws error: ' + (e.message || e.type)));
    ws.onopen = () => res({
      send: (method, params = {}) => new Promise((resolve, reject) => { const i = ++id; pending.set(i, { resolve, reject }); ws.send(JSON.stringify({ id: i, method, params })); }),
      close: () => ws.close(),
    });
  });
}

async function waitFor(cdp, expr, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const { result } = await cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (result.value) return;
    await sleep(150);
  }
  throw new Error('waitFor timed out: ' + expr);
}

main().catch((e) => { console.error(e); process.exit(1); });
