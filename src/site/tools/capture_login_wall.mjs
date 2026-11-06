// Films the login page's wall: 32 recorded runs replayed in lab.html, one picture at a time, from the real pose records. Nothing is simulated or drawn here.
// node capture_login_wall.mjs [--base URL] [--out DIR] [--tiles 0,1,2] [--plan]. --plan writes src/site/assets/login-wall.json only.
// Fix tiles need the "after" runs exported with policy/highrise5/export5.py, which replays each one and refuses a mismatch, as /trials/wall-*; serve them with a vite on --base.
import { mkdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const BASE = arg('base', 'http://localhost:5206');
const OUT = arg('out', '/tmp/lg/frames');
const SIZE = 360, FPS = 15, LOOP_S = 12, N = FPS * LOOP_S, FADE = 4;
const get = async p => { const r = await fetch(BASE + p); if (!r.ok) throw new Error(`${p}: ${r.status}`); return r; };
const data = await (await get('/site-api/data')).json();
const camp = id => data.campaigns.find(c => c.id === id);
const pretty = s => { const t = s.replace(/_/g, ' '); return t[0].toUpperCase() + t.slice(1); };

// Grid order is reading order: 8 by 4. A narrow screen shows the first columns.
const LIST = [
  'i:w015', 'f:041', 'w:w040', 'i:w032', 'i:w046', 'w:w020', 'i:w040', 'w:w039',
  'w:w001', 'i:w021', 'i:w016', 'w:w009', 'i:w022', 'i:w005', 'w:w037', 'i:w043',
  'i:w019', 'w:w034', 'c:000', 'i:w026', 'w:w007', 'i:w009', 'w:w023', 'i:w025',
  'w:w004', 'f:042', 'i:w029', 'w:w042', 'i:w008', 'w:w033', 'i:w035', 'w:w041'];
const FIX = {
  f: { from: 'public/w{n}, the bounty "Robot stalls with a strong fan"', who: 'Bounty fix', diff: ['LOW_PRESSURE_PA = 1500.0', 'LOW_PRESSURE_PA = 1400.0'], before: n => `wall-fix${n}-before`, after: n => `wall-fix${n}-after`, name: { '041': 'Strong climb, smallest margin', '042': 'Strong climb, low setback' } },
  c: { from: 'a code tab edit, session 9f15ed1a', who: 'Code edit', diff: ['SUCTION_CLEAN = 0.85', 'SUCTION_CLEAN = 1.0'], before: () => 'demo-window-w000', after: n => `wall-code${n}-after`, name: { '000': 'Suction slightly reduced' } },
};
const manifest = async id => (await get(`/trials/${id}/manifest.json`)).json();
const result = async id => (await get(`/trials/${id}/result.json`)).json();

async function plan(spec, index) {
  const [kind, id] = spec.split(':');
  const frames = Array(N);
  const phase = Math.round(((index * 0.618034) % 1) * N);
  if (kind === 'i') {
    const w = camp('demo-inspection').worlds.find(x => x.id === id);
    const replay = JSON.parse(gunzipSync(Buffer.from(await (await get(`/site-api/replay/inspection/${id}`)).arrayBuffer())).toString());
    const url = `lab.html?poses=/site-api/replay/inspection/${id}`;
    const times = replay.frames.map(f => f.t), last = times.length - 1;
    const end = w.outcome === 'pass' ? times[last] : w.at, verdict = w.outcome === 'pass' ? 10 : 7.5;
    const t0 = end - verdict; // Before zero, the run has not begun: the first picture holds.
    for (let i = 0; i < N; i++) {
      const t = t0 + i / FPS;
      let f = 0; while (f < last && times[f + 1] <= t) f++;
      frames[i] = { url, frame: f };
    }
    const words = w.outcome === 'pass' ? `Passed, ${w.reading}` : `${w.kind_name} at ${w.at.toFixed(1)} s`;
    return { frames, tile: { robot: 'inspection', world: id, name: pretty(w.name), phase, states: [{ at: 0, s: 'run', words: 'Running' }, { at: verdict, s: w.outcome === 'pass' ? 'pass' : 'fail', words }] } };
  }
  if (kind === 'w') {
    const w = camp('demo-window').worlds.find(x => x.id === id);
    const m = await manifest(`demo-window-${id}`);
    const url = `lab.html?trial=demo-window-${id}`, last = m.frames - 1;
    const end = w.outcome === 'pass' ? last / m.hz : w.at, verdict = w.outcome === 'pass' ? 10 : 8;
    for (let i = 0; i < N; i++) frames[i] = { url, frame: Math.min(last, Math.round((end * i / FPS / verdict) * m.hz)) };
    const words = w.outcome === 'pass' ? `Passed, ${w.reading}` : w.kind === 'slip_distance' ? `Slipped ${w.reading.replace(' slide', '')}` : `${w.kind_name === 'False done' ? 'False finish' : w.kind_name}, ${w.reading}`;
    return { frames, tile: { robot: 'window', world: id, name: pretty(w.name), phase, states: [{ at: 0, s: 'run', words: 'Running' }, { at: verdict, s: w.outcome === 'pass' ? 'pass' : 'fail', words }] } };
  }
  const fix = FIX[kind];
  const beforeId = fix.before(id), afterId = fix.after(id);
  const [mb, ma, rb, ra] = [await manifest(beforeId), await manifest(afterId), await result(beforeId), await result(afterId)];
  if (rb.passed || !ra.passed) throw new Error(`${spec}: not a real before and after`);
  const failT = rb.time_s, passT = ra.time_s;
  const failAt = 3.8, fixAt = 5, runAt = 6.4, passAt = 10.4;
  for (let i = 0; i < N; i++) {
    const v = i / FPS;
    if (v < fixAt) frames[i] = { url: `lab.html?trial=${beforeId}`, frame: Math.min(mb.frames - 1, Math.round(failT * Math.min(1, v / failAt) * mb.hz)) };
    else frames[i] = { url: `lab.html?trial=${afterId}`, frame: Math.min(ma.frames - 1, Math.round(passT * Math.max(0, Math.min(1, (v - runAt) / (passAt - runAt))) * ma.hz)) };
  }
  const failWords = rb.failure === 'stalled' ? 'Stalled' : rb.failure === 'false_done' ? 'False finish' : pretty(String(rb.failure));
  return { frames, tile: { robot: 'window', world: id, name: fix.name[id], phase, fix: { who: fix.who, from: fix.from, minus: fix.diff[0], plus: fix.diff[1] }, states: [{ at: 0, s: 'run', words: 'Before the fix' }, { at: failAt, s: 'fail', words: failWords }, { at: fixAt, s: 'fix', words: `${fix.who} applied` }, { at: runAt, s: 'run', words: 'After the fix' }, { at: passAt, s: 'pass', words: `Passed, ${Math.round(ra.coverage * 100)}% cleaned` }] } };
}

const planned = [];
for (let i = 0; i < LIST.length; i++) planned.push(await plan(LIST[i], i));
// The still for reduced motion: the moment with the most failures showing and every fix shown at some stage past its failure.
const stateAt = (tile, t) => { const local = (t - tile.phase / FPS + LOOP_S * 2) % LOOP_S; let now = tile.states[0]; for (const s of tile.states) if (s.at <= local) now = s; return now.s; };
let poster_t = 0, best = -1;
for (let i = 0; i < N; i++) { const n = planned.filter(p => stateAt(p.tile, i / FPS) === 'fail').length + planned.filter(p => stateAt(p.tile, i / FPS) === 'fix').length * 2; if (n > best) { best = n; poster_t = i / FPS; } }
writeFileSync(new URL('../assets/login-wall.json', import.meta.url), JSON.stringify({ cols: 8, rows: 4, loop_s: LOOP_S, poster_t: Math.round(poster_t * 1000) / 1000, tiles: planned.map(p => p.tile) }, null, 1) + '\n');
if (process.argv.includes('--plan')) process.exit(0);

const CSS = `body{background:#000!important}.viewport{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;z-index:9999;background:#000}.viewport>*:not(canvas){display:none!important}`;
const c = await openChrome({ width: SIZE, height: SIZE });
const only = arg('tiles', null)?.split(',').map(Number);
let open = null;
async function goTo(url) {
  if (open === url) return;
  await c.send('Page.navigate', { url: `${BASE}/${url}` });
  await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true'`, url, 90);
  await c.js(`(async () => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(CSS)}; document.head.append(s); dispatchEvent(new Event('resize'));
    if (location.search.includes('trial=')) { // The window view follows slowly, so a jump can leave the robot out of frame. Here the camera sits on the robot every picture.
      const { SimView } = await import('/src/app/view.ts');
      const step = SimView.prototype.stepCamera;
      SimView.prototype.stepCamera = function (now) { step.call(this, now); const r = this.robotPos; this.camera.position.set(r.x + 1.25, r.y - 0.72, r.z + 0.34); this.controls.target.set(r.x - 0.6, r.y - 0.26, r.z - 0.24); this.controls.update(); this.dirty = true; };
    }
  })()`);
  await wait(500);
  open = url;
}
const seek = f => c.js(`(() => { const s = document.querySelector('.scrub input'); s.value = ${f}; s.dispatchEvent(new Event('input', { bubbles: true })); return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r)))); })()`);
for (let t = 0; t < planned.length; t++) {
  if (only && !only.includes(t)) continue;
  const dir = `${OUT}/t${String(t).padStart(2, '0')}`;
  mkdirSync(dir, { recursive: true });
  const { frames, tile } = planned[t];
  let prev = null, prevPath = null;
  for (let i = 0; i < N; i++) {
    const out = `${dir}/${String((i + tile.phase) % N).padStart(4, '0')}.jpg`;
    const fade = Math.min(1, (i + 0.5) / FADE, (N - i - 0.5) / FADE);
    const key = `${frames[i].url}#${frames[i].frame}#${fade}`;
    if (key === prev) { copyFileSync(prevPath, out); continue; }
    await goTo(frames[i].url);
    await c.js(`document.querySelector('.viewport canvas').style.opacity = ${fade}`);
    await seek(frames[i].frame);
    const shot = await c.send('Page.captureScreenshot', { format: 'jpeg', quality: 90 });
    writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    prev = key; prevPath = out;
  }
  console.log('done', t, LIST[t]);
}
if (c.problems.length) console.log(c.problems.slice(0, 3));
c.close();
process.exit(0);
