// The weather in lab.html, on real pixels: node src/lab/tools/check_weather.mjs [--out DIR] [--wind-only]
// Needs vite on port 5199. It starts its own run server on a free port, with stored AI replies, and its own Chrome. With --wind-only it stops after the wind.
// 1. Streak speed equals wind.json at 3 frames, and a calm world shows almost none.
// 2. Dust, rain and snow: one message each, with a picture and a re-run.
// 3. Drops go from glass the recording shows as cleaned.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const WIND_ONLY = process.argv.includes('--wind-only');
const SERVER_PORT = await new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });
const SERVER = `http://127.0.0.1:${SERVER_PORT}`;
const ORIGIN = 'http://localhost:5199';
const PAGE = `${ORIGIN}/lab.html?server=${SERVER_PORT}`;
const BRIEF = 'Window robot for towers in Dubai. High floor.';
const PORT = 9850 + Math.floor(Math.random() * 100);
const profile = mkdtempSync(join(tmpdir(), 'crashlab-weather-'));
mkdirSync(OUT, { recursive: true });

const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(SERVER_PORT), '--recorded', join(ROOT, 'policy/server/fixtures_lab')], { stdio: 'inherit' });
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
const quiet = n => until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${n}`, 'job finished', 120);
const chatText = () => js(`document.querySelector('.chat-list').innerText`);
const shot = async name => {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, name), Buffer.from(r.result.data, 'base64'));
  console.log('PNG', join(OUT, name));
};
const seek = frame => js(`(() => { const s = document.querySelector('input[aria-label="Timeline"]'); s.value = ${frame}; s.dispatchEvent(new Event('input')); })()`);
const weather = () => js(`JSON.parse(document.querySelector('.viewport').dataset.weather)`);
const trial = async (tid, file) => (await fetch(`${SERVER}/api/sessions/${await js(`sessionStorage.getItem('crashlab-session')`)}/trials/${tid}/${file}`, { headers: { Origin: ORIGIN } })).json();
// A new chat with one brief. pick gives the option number for each quick question.
async function brief(pick, label) {
  await send('Page.navigate', { url: 'about:blank' });
  await wait(300);
  await send('Page.navigate', { url: PAGE });
  await until(`document.getElementById('lab')?.dataset.server === 'up'`, 'server up', 30);
  await js(`sessionStorage.removeItem('crashlab-session')`);
  await send('Page.navigate', { url: PAGE });
  await until(`document.getElementById('lab')?.dataset.server === 'up' && !!sessionStorage.getItem('crashlab-session')`, 'fresh session', 30);
  let n = await idle();
  await type(BRIEF);
  await quiet(n);
  let asked = 0;
  while (await js(`[...document.querySelectorAll('.chat-option')].some(b => !b.disabled)`)) {
    n = await idle();
    await js(`[...document.querySelectorAll('.chat-card')].pop().querySelectorAll('.chat-option')[${pick[asked++] ?? 0}].click()`);
    await quiet(n);
  }
  await until(`document.querySelector('.viewport')?.dataset.tid === 'normal-1' && Number(document.querySelector('.viewport').dataset.frame) > 0`, `${label} run plays`, 120);
}
// The streak speed the view really used over half a second, against the record for that frame.
async function measure(frame) {
  await seek(frame);
  await wait(250);
  const a = await weather();
  await wait(500);
  const b = await weather();
  return { speed: (b.travel - a.travel) / ((b.at - a.at) / 1000), ms: b.ms, streaks: b.streaks };
}
// How much the picture moves from one moment to the next, on the sky and the street past the wall.
const SHOT_STATS = `window.__cells = async (b64) => {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const img = await createImageBitmap(new Blob([bytes], { type: 'image/png' }));
  const c = new OffscreenCanvas(img.width, img.height); const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  return [...g.getImageData(0, 0, img.width, img.height).data].filter((_, i) => i % 4 === 1);
}`;
async function motion() {
  await js(SHOT_STATS);
  const r = await js(`document.querySelector('.viewport canvas').getBoundingClientRect().toJSON()`);
  const clip = { x: r.x + r.width * 0.05, y: r.y + r.height * 0.05, width: r.width * 0.3, height: r.height * 0.4, scale: 1 };
  const take = async () => js(`window.__cells(${JSON.stringify((await send('Page.captureScreenshot', { format: 'png', clip })).result.data)})`);
  const a = await take();
  await wait(120);
  const b = await take();
  let moved = 0;
  for (let i = 0; i < a.length; i++) if (Math.abs(a[i] - b[i]) > 6) moved++;
  return moved / a.length;
}

try {
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await wait(1000);

  // 1. A calm world: no streaks to speak of.
  await brief([0, 0], 'calm');
  const calmWind = await trial('normal-1', 'wind.json');
  const calm = await measure(600);
  await wait(800);
  const calmMoved = await motion();
  check('a calm world shows almost no streaks', calm.streaks <= 90, `wind ${calm.ms} m/s, ${calm.streaks} streaks, ${(calmMoved * 100).toFixed(2)}% of pixels moved`);
  await shot('weather-calm.png');
  console.log(`calm wind range ${Math.min(...calmWind)} to ${Math.max(...calmWind)}`);

  // 2. A very windy world: speed against the record at 3 frames.
  await brief([2, 0], 'windy');
  const wind = await trial('normal-1', 'wind.json');
  const world = await trial('normal-1', 'world.json');
  const peak = wind.indexOf(Math.max(...wind)), low = wind.indexOf(Math.min(...wind));
  for (const f of [low + 1, 2000, peak + 1]) {
    const m = await measure(f);
    const want = wind[f - 1];
    check(`streak speed at frame ${f} equals wind.json`, Math.abs(m.speed - want) <= 0.03 * want && m.ms === want, `drew ${m.speed.toFixed(2)} m/s, record ${want} m/s, ${m.streaks} streaks`);
  }
  const view = await weather();
  check('direction is the world\'s', view.dir === world.wind_dir_deg, `${view.dir} degrees`);
  await seek(peak + 1);
  await wait(500);
  const windMoved = await motion();
  check('wind moves more pixels than calm', windMoved > calmMoved * 3 && windMoved > 0.002, `${(windMoved * 100).toFixed(2)}% against ${(calmMoved * 100).toFixed(2)}%`);
  await shot('weather-wind.png');

  if (!WIND_ONLY) {
    // 3. One word: the picture and the physics, then a new run.
    let round = 1;
    for (const [word, png, field, modelled] of [['make the weather dusty', 'weather-dust.png', 'dust_gm2', 'Blowing dust on screen is scenery.'], ['make it rain', 'weather-rain.png', 'wetness', 'Rain on screen is scenery.'], ['make it snow', 'weather-snow.png', 'temperature_c', 'Snow on screen is scenery.']]) {
      const n = await idle();
      const before = await trial(`normal-${round}`, 'world.json');
      const sha = (await trial(`normal-${round}`, 'result.json')).final_state_sha256;
      await type(word);
      await quiet(n);
      round++;
      await until(`document.querySelector('.viewport')?.dataset.tid === 'normal-${round}' && Number(document.querySelector('.viewport').dataset.frame) > 0`, `${word} re-run`, 60);
      const after = await trial(`normal-${round}`, 'world.json');
      const result = await trial(`normal-${round}`, 'result.json');
      check(`"${word}" moves ${field}`, before[field] !== after[field], `${before[field]} -> ${after[field]}`);
      check(`"${word}" re-runs with a new final state`, result.final_state_sha256 !== sha);
      check(`"${word}" says what is scenery`, (await chatText()).includes(modelled));
      await seek(4000);
      await wait(1200);
      await shot(png);
    }
    check('the old reply is gone', !(await chatText()).includes('does not draw'));

    // 4. A wet world at a late frame: drops on the glass the robot has not reached, none on the lanes it cleaned.
    await brief([0, 1], 'wet');
    await seek(0);
    await wait(1000);
    await shot('drops-start.png');
    const frames = Number((await trial('normal-1', 'manifest.json')).frames);
    await seek(Math.floor(frames * 0.45));
    await wait(1200);
    console.log('cleaned share at that frame', await js(`document.querySelector('.viewport').dataset.drawnClean`));
    await shot('drops-cleaned.png');
  }
  check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 6).join('\n'));
} catch (err) {
  check('the flow finished', false, String(err));
}
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
