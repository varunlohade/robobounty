// Drives lab.html with look changes and checks real pixels: node src/lab/tools/check_look.mjs [--live MODEL] [--out DIR]
// Needs vite on port 5199. It starts its own run server on port 5198 and stops it. With no --live it reads stored AI replies from policy/server/fixtures_lab and proves the routing, the view and the replay.
// With --live, the brief and the look messages make real AI calls, and it reports send to changed pixels. The time includes the screenshot that saw the change.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const LIVE = arg('live', null);
const SERVER = 'http://127.0.0.1:5198';
const ORIGIN = 'http://localhost:5199';
const PORT = 9750 + Math.floor(Math.random() * 100);
const profile = mkdtempSync(join(tmpdir(), 'crashlab-look-'));
mkdirSync(OUT, { recursive: true });

// Stored replies stand in for the planner in both modes: this check is about the look, and its live cost is the route calls.
const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--recorded', join(ROOT, 'policy/server/fixtures_lab'), ...(LIVE ? ['--live-route'] : [])],
  { stdio: 'inherit', env: { ...process.env, ...(LIVE ? { CRASHLAB_ROUTE_MODEL: LIVE } : {}) } });
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
  '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank'], { stdio: 'ignore' });
const wait = ms => new Promise(r => setTimeout(r, ms));
const finish = code => { chrome.kill(); server.kill(); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 400); };

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `: ${detail}` : ''}`); };

let url = null;
for (let i = 0; i < 60 && !url; i++) {
  try { url = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {}
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
});
const send = (method, params = {}) => new Promise(r => { const n = nextId++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
  return r.result.result.value;
};
const until = async (expr, what, seconds) => {
  const t0 = Date.now();
  while (Date.now() - t0 < seconds * 1000) { if (await js(expr)) return; await wait(100); }
  console.log('chat at timeout:', await js(`document.querySelector('.chat-log').innerText`));
  throw new Error(`timed out: ${what}`);
};
const type = text => js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`);
const idle = () => js(`Number(document.getElementById('lab').dataset.idle ?? 0)`);
const quiet = async n => until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${n}`, 'job finished', 120);
const chatText = () => js(`document.querySelector('.chat-list').innerText`);
const box = () => js(`(() => { const r = document.querySelector('.viewport canvas').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, scale: 1 }; })()`);

// A real screenshot of the 3D view, decoded in the page. It returns the mean colour of a grid of cells.
async function grab() {
  const clip = await box();
  const r = await send('Page.captureScreenshot', { format: 'png', clip });
  return { data: r.result.data, clip };
}
const STATS = `window.__stats = async (b64) => {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const img = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
  const c = new OffscreenCanvas(48, 32); const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0, 48, 32);
  return [...g.getImageData(0, 0, 48, 32).data];
}`;
const cells = async () => js(`window.__stats(${JSON.stringify((await grab()).data)})`);
const diff = (a, b) => { let s = 0; for (let i = 0; i < a.length; i += 4) s += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]); return s / (a.length / 4) / 3; };
// The wall fills this part of the default frame.
const WALL = { x0: 0.45, x1: 0.68, y0: 0.2, y1: 0.8 };
const wallMean = px => {
  let r = 0, g = 0, b = 0, n = 0;
  for (let y = Math.floor(WALL.y0 * 32); y < WALL.y1 * 32; y++) for (let x = Math.floor(WALL.x0 * 48); x < WALL.x1 * 48; x++) { const i = (y * 48 + x) * 4; r += px[i]; g += px[i + 1]; b += px[i + 2]; n++; }
  return [r / n, g / n, b / n].map(v => Math.round(v));
};
const skyMean = px => { let s = 0, n = 0; for (let x = 0; x < 48; x++) for (let y = 0; y < 3; y++) { const i = (y * 48 + x) * 4; s += (px[i] + px[i + 1] + px[i + 2]) / 3; n++; } return s / n; };
const lum = c => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];

async function save(name) {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, name), Buffer.from(r.result.data, 'base64'));
  console.log('PNG', join(OUT, name));
}

// Sends one message and watches the pixels. Returns milliseconds to the first screenshot that differs from the frame before it.
async function change(text, base, threshold = 4) {
  const before = await js(`document.querySelector('.viewport').dataset.look ?? ''`);
  const t0 = Date.now();
  await type(text);
  let px = base;
  let seenWorking = false;
  while (Date.now() - t0 < 150000) {
    seenWorking ||= await js(`!document.querySelector('.chat-live').hidden && /Reading your message/.test(document.querySelector('.chat-live').textContent)`);
    px = await cells();
    if (diff(base, px) >= threshold) break;
  }
  const ms = Date.now() - t0;
  await until(`document.querySelector('.chat-send').disabled === false`, 'send enabled', 60);
  await wait(500);
  const land = Number(await js(`document.querySelector('.viewport').dataset.lookLandMs ?? -1`));
  return { ms, px: await cells(), changed: (await js(`document.querySelector('.viewport').dataset.look ?? ''`)) !== before, land, seenWorking };
}

const median = v => [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)];

try {
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await wait(1000);
  await send('Page.navigate', { url: `${ORIGIN}/lab.html` });
  await until(`document.getElementById('lab')?.dataset.server === 'up'`, 'server up', 30);
  await js(STATS);

  const sid = await js(`(async () => { for (let i = 0; i < 50 && !sessionStorage.getItem('crashlab-session'); i++) await new Promise(r => setTimeout(r, 100)); return sessionStorage.getItem('crashlab-session'); })()`);
  const get = path => fetch(`${SERVER}/api/sessions/${sid}/${path}`, { headers: { Origin: ORIGIN } });
  const events = async () => {
    const res = await get('events');
    const reader = res.body.getReader();
    let text = '';
    const stop = setTimeout(() => reader.cancel(), 500);
    try { while (true) { const { value, done } = await reader.read(); if (done) break; text += new TextDecoder().decode(value); } } catch {}
    clearTimeout(stop);
    return text.split('\n').filter(l => l.startsWith('data: ')).map(l => JSON.parse(l.slice(6)));
  };

  // 1. A look before any world is kept, and the world loads with it.
  let n = await idle();
  await type('make the building black');
  await quiet(n);
  check('a look before a world waits for it', (await chatText()).includes('Building will be black when the world loads.'));
  n = await idle();
  await type('make the building white');
  await quiet(n);

  // 2. A brief with a place in it does both: the look and the planner.
  n = await idle();
  await type('Window robot for towers in Dubai. High floor.');
  await quiet(n);
  while (await js(`[...document.querySelectorAll('.chat-option')].some(b => !b.disabled)`)) {
    n = await idle();
    await js(`[...document.querySelectorAll('.chat-card')].pop().querySelector('.chat-option:not(:disabled)').click()`);
    await quiet(n);
  }
  await until(`document.querySelector('.viewport')?.dataset.tid === 'normal-1' && Number(document.querySelector('.viewport').dataset.frame) > 0`, 'run plays', 120);
  check('Dubai says it is scenery', (await chatText()).includes('Scenery look named Dubai. Not the real city.'));
  check('no Not built line for Dubai', !/Not built:.*dubai/i.test(await chatText()));
  check('the world loaded with the kept look', (await js(`document.querySelector('.viewport').dataset.look`)).includes('#f7f7f5'), await js(`document.querySelector('.viewport').dataset.look`));
  await save('look-white.png');

  // Pause the replay so only the look moves the pixels.
  await js(`document.querySelector('[aria-label="Go to start"]').click()`);
  await wait(1500);

  // 3. Each message: send to changed pixels. It costs one AI call, no run and no new world.
  const logBefore = await events();
  const count = t => t.filter(e => e.type === 'llm_count').length;
  const hasTrial = t => t.filter(e => e.type === 'trial').length;
  const worlds = t => t.filter(e => e.type === 'world').length;
  const times = [], lands = [];
  const step = async (text, png) => {
    const base = await cells();
    const r = await change(text, base);
    check(`"${text}" changes the view`, r.changed, `${r.ms} ms, ${r.land} ms after the AI answered`);
    times.push(r.ms); lands.push(r.land);
    if (png) await save(png);
    return r;
  };
  const black = await step('make the building black', 'look-black.png');
  const white = await step('make the building white');
  const grey = await step('make the building grey', 'look-grey.png');
  const bronze = await step('make the building bronze', 'look-bronze.png');
  const teal = await step('make the building teal', 'look-teal.png');
  const lb = wallMean(black.px), lw = wallMean(white.px), lg = wallMean(grey.px), lz = wallMean(bronze.px), lt = wallMean(teal.px);
  console.log('wall colour', JSON.stringify({ black: lb, white: lw, grey: lg, bronze: lz, teal: lt }));
  check('black reads as black', lum(lb) < 45, lum(lb).toFixed(0));
  check('white reads as white', lum(lw) > 190, lum(lw).toFixed(0));
  check('grey sits between them', lum(lg) > lum(lb) + 30 && lum(lg) < lum(lw) - 30, lum(lg).toFixed(0));
  check('bronze is warm', lz[0] > lz[2] + 25, lz.join(','));
  check('teal is teal', lt[1] > lt[0] + 25 && lt[2] > lt[0] + 25, lt.join(','));

  await step('make the building grey');
  const blue = await step('blue glass', 'look-glass-blue.png');
  const green = await step('green glass');
  const gold = await step('gold glass', 'look-glass-gold.png');
  const lbl = wallMean(blue.px), lgr = wallMean(green.px), lgo = wallMean(gold.px);
  console.log('tints', JSON.stringify({ blue: lbl, green: lgr, gold: lgo }));
  check('blue tint is blue', lbl[2] > lbl[0] + 15, lbl.join(','));
  check('green tint is green', lgr[1] > lgr[0] + 10 && lgr[1] > lgr[2], lgr.join(','));
  check('gold tint is warm', lgo[0] > lgo[2] + 15, lgo.join(','));
  await step('clear glass');

  const dusk = await step('dusk', 'look-dusk.png');
  const night = await step('night', 'look-night.png');
  const noon = await step('noon');
  console.log('sky', skyMean(noon.px).toFixed(0), skyMean(dusk.px).toFixed(0), skyMean(night.px).toFixed(0));
  check('night is darker than dusk, and dusk darker than noon', lum(wallMean(night.px)) < lum(wallMean(dusk.px)) && lum(wallMean(dusk.px)) < lum(wallMean(noon.px)));
  check('dusk is warm', (() => { const d = wallMean(dusk.px); return d[0] > d[2] + 8; })(), wallMean(dusk.px).join(','));
  check('night is dark', lum(wallMean(night.px)) < 50, lum(wallMean(night.px)).toFixed(0));
  await step('fog 2', 'look-fog.png');
  await step('no fog');
  await step('make the building black');

  const logAfter = await events();
  const looks = times.length;
  check('each look message is one AI call', count(logAfter) - count(logBefore) === looks, `${count(logAfter) - count(logBefore)} calls for ${looks} messages`);
  check('look changes start no run and no new world', hasTrial(logAfter) === hasTrial(logBefore) && worlds(logAfter) === worlds(logBefore));
  check('chat says it plainly', (await chatText()).includes('Building is now black.'));
  console.log(`send to changed pixels, ${times.length} messages: median ${median(times)} ms, worst ${Math.max(...times)} ms`);
  console.log(`AI answered to frame drawn: median ${median(lands)} ms, worst ${Math.max(...lands)} ms`);
  check('after the AI answers, the view changes in under 200 ms', median(lands) < 200 && Math.max(...lands) < 200, `median ${median(lands)}, worst ${Math.max(...lands)}`);

  // 4. A request no tool can do.
  n = await idle();
  await type('make the robot dance');
  await quiet(n);
  check('an unknown request is refused by code', (await chatText()).includes('I cannot do that yet: robot dance.'));
  // 5. An AI failure falls back and says so. This message has no stored reply.
  if (!LIVE) {
    n = await idle();
    await type('white frames');
    await quiet(n);
    check('a failed AI call says so', (await chatText()).includes('AI did not answer, so I used the simple parser.'));
    check('the simple parser still lands the change', (await chatText()).includes('Frames are now white') );
  }

  // 6. It persists: the export holds it, and a replay opened fresh shows it.
  const saved = await (await get('trials/normal-1/look.json')).json();
  check('look.json is in the export', saved.building === '#0a0a0a', JSON.stringify(saved));
  const worldText = await (await get('trials/normal-1/world.json')).text();
  check('look stays out of world.json', !/building|glass_tint|frames|#0a0a0a/.test(worldText));
  // 6b. A look changes no physics: the same brief with no look gives the same final state.
  {
    const h = { Origin: ORIGIN, 'Content-Type': 'application/json' };
    const base = `${SERVER}/api/sessions`;
    const { id } = await (await fetch(base, { method: 'POST', headers: h, body: '{}' })).json();
    const state = async () => (await fetch(`${base}/${id}/state`, { headers: h })).json();
    const settle = async () => { for (let i = 0; i < 240; i++) { await wait(500); const st = await state(); if (!st.busy) return st; } throw new Error('second session stuck'); };
    await fetch(`${base}/${id}/message`, { method: 'POST', headers: h, body: JSON.stringify({ text: 'Window robot for towers in Dubai. High floor.' }) });
    let st = await settle();
    while (st.phase === 'asking') {
      await fetch(`${base}/${id}/action`, { method: 'POST', headers: h, body: JSON.stringify({ action: 'answer', value: 0 }) });
      st = await settle();
    }
    const plain = await (await fetch(`${base}/${id}/trials/normal-1/result.json`, { headers: h })).json();
    const looked = await (await get('trials/normal-1/result.json')).json();
    check('a look keeps final_state_sha256', !!looked.final_state_sha256 && looked.final_state_sha256 === plain.final_state_sha256, `${String(looked.final_state_sha256).slice(0, 16)} and ${String(plain.final_state_sha256).slice(0, 16)}`);
  }
  await send('Page.navigate', { url: `${ORIGIN}/lab.html` });
  await until(`document.querySelector('.viewport')?.dataset.tid === 'normal-1'`, 'replay after reload', 60);
  await until(`document.querySelector('.viewport').dataset.look?.includes('#0a0a0a')`, 'look after reload', 20);
  await js(STATS);
  await js(`document.querySelector('[aria-label="Go to start"]').click()`);
  await wait(1500);
  const replayPx = await cells();
  check('the replay shows the look', lum(wallMean(replayPx)) < 45, lum(wallMean(replayPx)).toFixed(0));
  await save('look-replay-black.png');
  check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 6).join('\n'));
} catch (err) {
  check('the flow finished', false, String(err));
}
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
