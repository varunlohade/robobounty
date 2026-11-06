// Headless Chrome over CDP with no extra libraries, in the pattern of src/app/tools/check_app.mjs. Own profile and port; never touches a visible window.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
export const wait = ms => new Promise(r => setTimeout(r, ms));

export async function openChrome(port = 9377) {
  const profile = mkdtempSync(join(tmpdir(), 'crashlab-video-'));
  const chrome = spawn('nice', ['-n', '15', CHROME, '--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--window-size=1800,900',
    '--hide-scrollbars', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--mute-audio', 'about:blank'], { stdio: 'ignore' });
  let url = null;
  for (let i = 0; i < 60 && !url; i++) {
    try { url = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {}
    if (!url) await wait(250);
  }
  if (!url) throw new Error('Chrome did not start');
  const ws = new WebSocket(url);
  await new Promise(r => ws.addEventListener('open', r));
  let nextId = 1;
  const pending = new Map();
  const problems = [];
  ws.addEventListener('message', m => {
    const msg = JSON.parse(m.data);
    if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); return; }
    if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
    if (msg.method === 'Page.frameNavigated' && !msg.params.frame.parentId) problems.push(`navigated: ${msg.params.frame.url}`);
  });
  const send = (method, params = {}) => new Promise(r => { const id = nextId++; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1800, height: 900, deviceScaleFactor: 16 / 15, mobile: false });
  const js = async expr => {
    const res = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (res.result?.exceptionDetails) throw new Error(res.result.exceptionDetails.exception?.description ?? 'js error');
    return res.result?.result?.value;
  };
  const until = async (expr, what, tries = 600) => {
    for (let i = 0; i < tries; i++) { if (await js(expr)) return; await wait(200); }
    throw new Error(`timed out: ${what}`);
  };
  const shot = async (path, format = 'png') => {
    const res = await send('Page.captureScreenshot', { format, ...(format === 'jpeg' ? { quality: 95 } : {}), captureBeyondViewport: false });
    writeFileSync(path, Buffer.from(res.result.data, 'base64'));
  };
  const close = () => { chrome.kill(); ws.close(); setTimeout(() => rmSync(profile, { recursive: true, force: true }), 500); };
  return { send, js, until, shot, close, problems };
}
