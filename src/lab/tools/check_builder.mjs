// Types the builder's messages into lab.html through the real AI and looks at what changed: node src/lab/tools/check_builder.mjs [--recorded DIR] [--out DIR] [--only N]
// Needs vite on port 5199. It starts policy/server/supervise.py on a free port and its own Chrome profile, and touches no other server. Live, it sends each message once. The replies go to policy/runs/builder-replies.json, so --recorded with that folder repeats a run with no AI.
// It prints one table row for each message, saves design/shell/build-*.png, and compares the compiled physics geoms with the drawn ones after each message.
import { execFileSync, spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const RECORDED = arg('recorded', null);
const PY = join(ROOT, 'policy/.venv/bin/python');
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });
const SERVER_PORT = await freePort();
const DEBUG = await freePort();
const SERVER = `http://127.0.0.1:${SERVER_PORT}`;
const ORIGIN = 'http://localhost:5199';
const work = mkdtempSync(join(tmpdir(), 'crashlab-builder-'));
mkdirSync(OUT, { recursive: true });
const SAVED = join(ROOT, 'policy/runs/agent5.json');

const STEPS = [
  { text: 'make the tower 200 m tall', png: 'tower', physics: true },
  { text: 'add a crane on the roof', png: 'crane', physics: false },
  { text: "put a big box in the robot's path", png: 'box', physics: true, meet: true },
  { text: 'make the building black and the wind 8 m/s', png: 'black-wind', physics: true },
  { text: 'make the robot faster', png: 'faster', physics: true },
  { text: 'undo that', png: 'undo', physics: true },
  { text: 'make the glass curved', png: 'curved', physics: false, nothing: true },
];

const server = spawn(PY, [join(ROOT, 'policy/server/supervise.py'), '--port', String(SERVER_PORT), ...(RECORDED ? ['--recorded', resolve(RECORDED)] : [])],
  { stdio: 'inherit', env: { ...process.env, ...(RECORDED ? {} : { CRASHLAB_SAVE_AGENT: SAVED }) } });
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${DEBUG}`, `--user-data-dir=${work}/chrome`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
  '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank'], { stdio: 'ignore' });
const wait = ms => new Promise(r => setTimeout(r, ms));
const finish = code => { chrome.kill(); server.kill(); setTimeout(() => { try { rmSync(work, { recursive: true, force: true }); } catch {} process.exit(code); }, 800); };

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `: ${detail}` : ''}`); };

let url = null;
for (let i = 0; i < 60 && !url; i++) {
  try { url = (await (await fetch(`http://127.0.0.1:${DEBUG}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {}
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
  if (r.result.exceptionDetails) throw new Error(`${expr.slice(0, 200)}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
  return r.result.result.value;
};
const until = async (expr, what, seconds) => {
  const t0 = Date.now();
  while (Date.now() - t0 < seconds * 1000) { if (await js(expr)) return; await wait(150); }
  console.log('chat at timeout:', await js(`document.querySelector('.chat-log').innerText`));
  throw new Error(`timed out: ${what}`);
};
const type = text => js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`);
const idle = () => js(`Number(document.getElementById('lab').dataset.idle ?? 0)`);
const seek = frame => js(`(() => { const s = document.querySelector('input[aria-label="Timeline"]'); if (!s) return; s.value = ${frame}; s.dispatchEvent(new Event('input')); })()`);
const save = async name => {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, name), Buffer.from(r.result.data, 'base64'));
  console.log('PNG', join(OUT, name));
};
const canvas = async () => {
  const rect = await js(`(() => { const r = document.querySelector('.viewport canvas').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, scale: 1 }; })()`);
  return (await send('Page.captureScreenshot', { format: 'png', clip: rect })).result.data;
};
const PIXELS = `window.__pixels = async (a, b) => {
  const read = async s => { const img = await createImageBitmap(new Blob([Uint8Array.from(atob(s), c => c.charCodeAt(0))], { type: 'image/png' })); const c = new OffscreenCanvas(480, 320); const g = c.getContext('2d'); g.drawImage(img, 0, 0, 480, 320); return g.getImageData(0, 0, 480, 320).data; };
  const p = await read(a), q = await read(b); let n = 0;
  for (let i = 0; i < p.length; i += 4) if (Math.abs(p[i] - q[i]) + Math.abs(p[i + 1] - q[i + 1]) + Math.abs(p[i + 2] - q[i + 2]) > 36) n++;
  return n / (p.length / 4);
}`;
const session = () => js(`sessionStorage.getItem('crashlab-session')`);
const get = async path => fetch(`${SERVER}/api/sessions/${await session()}/${path}`, { headers: { Origin: ORIGIN } });
const events = async () => {
  const res = await get('events');
  const reader = res.body.getReader();
  let text = '';
  const stop = setTimeout(() => reader.cancel(), 600);
  try { while (true) { const { value, done } = await reader.read(); if (done) break; text += new TextDecoder().decode(value); } } catch {}
  clearTimeout(stop);
  return text.split('\n').filter(l => l.startsWith('data: ')).map(l => JSON.parse(l.slice(6)));
};
// The world the page holds now, and what the physics hash is, from the last event that set them.
const current = async log => {
  const last = log.filter(e => e.type === 'view' || e.type === 'trial' || e.type === 'world').pop();
  if (last.type === 'trial') {
    const r = await (await get(`trials/${last.tid}/result.json`)).json();
    return { hash: r.physics_sha256, world: await (await get(`trials/${last.tid}/world.json`)).json(), result: r, tid: last.tid };
  }
  return { hash: last.hash, world: last.world, xml: last.xml };
};
function physicsFacts(world) {
  const file = join(work, 'world.json');
  writeFileSync(file, JSON.stringify(world));
  return JSON.parse(execFileSync(PY, [join(ROOT, 'policy/highrise5/geoms5.py'), file], { maxBuffer: 1 << 26 }).toString());
}
// Each physics solid must be drawn where it is. The tolerance covers a cylinder's facets, which sit a little inside its true round.
async function compareGeoms(world, label) {
  const facts = physicsFacts(world);
  const drawn = await js(`window.__lab.view().drawnScene()`);
  const off = [];
  for (const [name, box] of Object.entries(facts.solids)) {
    const d = drawn.geoms[name];
    if (!d) { off.push(`${name} not drawn`); continue; }
    const worst = Math.max(...box.map((v, i) => Math.abs(v - d[i])));
    const size = Math.max(box[3] - box[0], box[4] - box[1], box[5] - box[2]);
    if (worst > Math.max(0.002, size * 0.02)) off.push(`${name} off by ${worst.toFixed(4)} m`);
  }
  const g = facts.glass;
  if (g[0] < drawn.wall[0] || g[3] > drawn.wall[1] || g[5] > drawn.wall[3]) off.push('the glass runs past the drawn wall');
  for (const x of facts.mullions) if (!drawn.bars.x.some(b => Math.abs(b - x) < 0.001)) off.push(`joint at x ${x} not drawn`);
  for (const z of facts.transoms) if (!drawn.bars.z.some(b => Math.abs(b - z) < 0.001)) off.push(`joint at z ${z} not drawn`);
  check(`${label}: drawn geoms match the physics`, off.length === 0, off.length ? off.slice(0, 5).join('; ') : `${Object.keys(facts.solids).length} solids, ${facts.mullions.length + facts.transoms.length} joints`);
}

const rows = [];
try {
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await wait(1000);
  await send('Page.navigate', { url: `${ORIGIN}/lab.html?server=${SERVER_PORT}` });
  await until(`document.getElementById('lab')?.dataset.server === 'up'`, 'server up', 40);
  await js(PIXELS);

  const COMPARE_FRAME = 400; // 20 s into the run: a faster robot is somewhere else by then.
  let before = null, count = 0, seen = 0;
  for (const step of STEPS) {
    const t0 = Date.now();
    const n = await idle();
    if (before) { await seek(COMPARE_FRAME); await wait(1200); }
    const pictureBefore = before ? await canvas() : null;
    await type(step.text);
    if (!before) { await until(`document.querySelector('.viewport')?.dataset.ready === 'true'`, 'preview', 30); await wait(1500); }
    const firstPicture = before ? null : await canvas();
    await until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${n}`, `"${step.text}" finished`, 500);
    const log = await events();
    const fresh = log.slice(seen);
    seen = log.length;
    const now = await current(log);
    if (now.tid) await until(`document.querySelector('.viewport')?.dataset.tid === ${JSON.stringify(now.tid)}`, 'replay loads', 60);
    await wait(step.meet ? 300 : 1400);

    const calls = fresh.filter(e => e.type === 'tool' && e.title === 'engine_call').map(e => e.lines[0]);
    const names = calls.map(l => l.split('(')[0].split(':')[0]);
    const ai = fresh.filter(e => e.type === 'llm_count').length;
    const hashMoved = before ? before.hash !== now.hash : now.hash !== log.find(e => e.type === 'world').hash;
    const said = fresh.filter(e => e.type === 'text').map(e => e.text);
    const card = fresh.find(e => e.type === 'card')?.result;
    const cannot = said.find(t => t.startsWith('cannot_build:'));
    const result = cannot ? cannot.split(':').slice(0, 2).join(':') : card ?? (hashMoved ? 'no run shown' : 'picture only, no re-run');
    const framed = await js(`document.querySelector('.viewport').dataset.framed === 'true'`);

    let pixels;
    if (framed) {
      pixels = await js(`window.__pixels(${JSON.stringify(pictureBefore ?? firstPicture)}, ${JSON.stringify(await canvas())})`);
      await save(`build-${step.png}.png`);
    } else if (step.meet) {
      // The first moment the robot's body reaches the new box, from the recorded path.
      const box = now.world.objects.filter(o => o.solid && o.pos.out_m < 0.5).pop();
      const trace = await (await get(`trials/${now.tid}/trace.json`)).json();
      const X = trace.columns.indexOf('x'), Z = trace.columns.indexOf('z');
      const top = now.world.tower.height_m - now.world.area.drop_below_roof_m;
      const bz = top - box.pos.below_top_m, bx = box.pos.x_m;
      const row = trace.rows.findIndex(r => Math.abs(r[X] - bx) < box.size[0] / 2 + 0.24 && Math.abs(r[Z] - bz) < box.size[2] / 2 + 0.24);
      check('the robot reaches the box', row >= 0, row >= 0 ? `frame ${row + 1} of ${trace.rows.length}, at ${(row / 20).toFixed(1)} s, x ${trace.rows[row][X]} z ${trace.rows[row][Z]}, box at x ${bx} z ${bz.toFixed(2)}` : `box at x ${bx} z ${bz.toFixed(2)}`);
      await seek(COMPARE_FRAME);
      await wait(1500);
      pixels = await js(`window.__pixels(${JSON.stringify(pictureBefore)}, ${JSON.stringify(await canvas())})`);
      await seek(Math.max(row + 1, 0));
      await wait(2200);
      await save(`build-${step.png}.png`);
      await seek(Math.max(row + 1, 0) + 80);
      await wait(2200);
      await save(`build-${step.png}-after.png`);
      console.log('what the box did:', JSON.stringify({ outcome: now.result.outcome, failure: now.result.failure, coverage: now.result.coverage, time_s: now.result.time_s }));
    } else {
      await seek(COMPARE_FRAME);
      await wait(1500);
      pixels = await js(`window.__pixels(${JSON.stringify(pictureBefore ?? firstPicture)}, ${JSON.stringify(await canvas())})`);
      await save(`build-${step.png}.png`);
    }

    rows.push({ words: step.text, calls: `${calls.length}: ${[...new Set(names)].join(' ')}`, ai, hash: hashMoved ? 'yes' : 'no', result: result.replaceAll('_', ' '), pixels: pixels.toFixed(3), seconds: ((Date.now() - t0) / 1000).toFixed(0) });
    check(`"${step.text}": physics hash ${step.physics ? 'changes' : 'stays'}`, hashMoved === step.physics);
    check(`"${step.text}": ${step.nothing ? 'the picture stays' : 'the picture changes'}`, step.nothing ? pixels < 0.02 : pixels > 0.02, pixels.toFixed(3));
    if (now.result) check(`"${step.text}": the label is the v5 one`, /^sim highrise5 [0-9a-f]{12}$/.test(now.result.label), now.result.label);
    if (step.nothing) check(`"${step.text}": says it cannot`, !!cannot, cannot ?? said.join(' | '));
    await compareGeoms(now.world, step.png);
    if (await js(`document.querySelector('.viewport').dataset.framed === 'true'`)) await js(`document.querySelector('.view-back').click()`);
    before = now;
    count++;
    console.log(`chat for "${step.text}":\n  ${[...calls, ...said].join('\n  ')}`);
  }

  // Tower height from 40 to 300 m, in the same view. The worlds come from the real compiler, with no AI.
  const base = before.world;
  for (const height of [40, 300]) {
    const world = { ...base, tower: { ...base.tower, height_m: height }, area: { ...base.area, drop_below_roof_m: height === 40 ? 8 : base.area.drop_below_roof_m }, objects: base.objects.filter(o => o.pos.out_m > 0 && o.pos.below_top_m > 0) };
    const { view_xml: xml } = physicsFacts(world);
    const validated = JSON.parse(execFileSync(PY, ['-c', `import sys,json; sys.path.insert(0, ${JSON.stringify(join(ROOT, 'policy/highrise5'))}); import world5 as W; print(json.dumps(W.load(${JSON.stringify(join(work, 'world.json'))})))`]).toString());
    await js(`(() => { const v = window.__lab.view(); v.applyWorld(${JSON.stringify(xml)}, ${JSON.stringify(validated)}); v.frameOn([${validated.tower.width_m / -2 + 1.2}, 0, 0, ${validated.tower.width_m / 2 + 1.2}, 0, ${height}]); })()`);
    await wait(1500);
    await save(`build-tower-${height}.png`);
    await compareGeoms(validated, `tower ${height} m`);
  }
  check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 6).join('\n'));
} catch (err) {
  check('the flow finished', false, String(err));
}
const col = (k, w) => r => String(r[k]).padEnd(w).slice(0, w);
console.log('\nwords                                       | calls                                   | AI | hash | result                                                     | pixels | s');
for (const r of rows) console.log(`${col('words', 43)(r)} | ${col('calls', 39)(r)} | ${String(r.ai).padEnd(2)} | ${r.hash.padEnd(4)} | ${col('result', 58)(r)} | ${r.pixels}  | ${r.seconds}`);
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
