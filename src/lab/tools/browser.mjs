// One headless Chrome with its own profile and debug port, for the checks in this folder.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const wait = ms => new Promise(r => setTimeout(r, ms));

export async function openChrome({ width = 1440, height = 900, guestForLab = true } = {}) {
  const port = 9750 + Math.floor(Math.random() * 200);
  const profile = mkdtempSync(join(tmpdir(), 'lab-check-'));
  const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `--window-size=${width},${height}`,
    '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
    '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank'], { stdio: 'ignore' });
  let url = null;
  for (let i = 0; i < 60 && !url; i++) {
    try { url = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {}
    if (!url) await wait(200);
  }
  const ws = new WebSocket(url);
  await new Promise(r => ws.addEventListener('open', r));
  let nextId = 1;
  const pending = new Map();
  const problems = [];
  ws.addEventListener('message', m => {
    const msg = JSON.parse(m.data);
    if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); return; }
    if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') problems.push(msg.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 600));
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') problems.push(`${msg.params.entry.text} ${msg.params.entry.url ?? ''}`);
  });
  const raw = (method, params = {}) => new Promise(r => { const n = nextId++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  // The lab page needs a session. A check that opens it directly signs in as a guest first, as a visitor would.
  const guested = new Set();
  const send = async (method, params = {}) => {
    if (guestForLab && method === 'Page.navigate' && /\/lab\.html/.test(params.url) && !guested.has(new URL(params.url).origin)) {
      const { origin } = new URL(params.url);
      guested.add(origin);
      await raw('Page.navigate', { url: `${origin}/site-api/health` });
      await wait(300);
      await raw('Runtime.evaluate', { expression: `fetch('/site-api/auth/me').then(r => r.json()).then(m => m.signed_in ? null : fetch('/site-api/auth/guest', { method: 'POST', headers: { 'X-CrashLab-Request': '1' } }))`, awaitPromise: true });
    }
    return raw(method, params);
  };
  const js = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.error) throw new Error(`${expr.slice(0, 200)}: ${r.error.message}`);
    if (r.result.exceptionDetails) throw new Error(`${expr.slice(0, 300)}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
    return r.result.result.value;
  };
  const shot = async path => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(path, Buffer.from(r.result.data, 'base64')); console.log('PNG', path); };
  const until = async (expr, what, seconds) => {
    const t0 = Date.now();
    while (Date.now() - t0 < seconds * 1000) {
      // A page that is loading has no context to ask, so it counts as not yet.
      let met = false;
      try { met = await js(expr); } catch (err) { if (!/context|navigat|collected/i.test(String(err))) throw err; }
      if (met) return (Date.now() - t0) / 1000;
      await wait(100);
    }
    throw new Error(`timed out: ${what}`);
  };
  const mouse = (type, x, y, extra = {}) => send('Input.dispatchMouseEvent', { type, x, y, button: 'none', ...extra });
  const click = async (x, y) => { await mouse('mouseMoved', x, y); await mouse('mousePressed', x, y, { button: 'left', clickCount: 1 }); await mouse('mouseReleased', x, y, { button: 'left', clickCount: 1 }); };
  const close = () => { try { ws.close(); } catch {} chrome.kill(); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} }, 300); };
  await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  return { send, js, shot, until, mouse, click, close, problems };
}
