// Drives lab.html end to end: a brief, one run, a follow-up, a second run of the same world.
// node src/lab/tools/check_lab.mjs [--recorded DIR] [--out DIR] [--brief text] [--change text]
// Needs vite on port 5199. It starts its own run server on port 5198 and stops it. With no --recorded it makes 2 real LLM calls.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const RECORDED = arg('recorded', null);
const BRIEF = arg('brief', 'Window robot for towers in Dubai. High floor.');
const CHANGE = arg('change', 'Make the wind stronger and wet the glass.');
const SERVER = 'http://127.0.0.1:5198';
const ORIGIN = 'http://localhost:5199';
const PORT = 9650 + Math.floor(Math.random() * 100);
const profile = mkdtempSync(join(tmpdir(), 'crashlab-lab-live-'));
mkdirSync(OUT, { recursive: true });

const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), ...(RECORDED ? ['--recorded', resolve(RECORDED)] : [])],
  { stdio: 'inherit', env: { ...process.env, CRASHLAB_LLM_MODEL: 'claude-opus-5-5' } });
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
  '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank'], { stdio: 'ignore' });
const wait = ms => new Promise(r => setTimeout(r, ms));
const finish = code => { chrome.kill(); server.kill(); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 400); };

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

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
  if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') problems.push(`${msg.params.entry.text} ${msg.params.entry.url ?? ''}`);
});
const send = (method, params = {}) => new Promise(r => { const n = nextId++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
  return r.result.result.value;
};
const shot = async name => { const r = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(OUT, name), Buffer.from(r.result.data, 'base64')); console.log('PNG', join(OUT, name)); };
const until = async (expr, what, seconds) => {
  const t0 = Date.now();
  while (Date.now() - t0 < seconds * 1000) { if (await js(expr)) return (Date.now() - t0) / 1000; await wait(250); }
  await shot('lab-timeout.png');
  console.log('chat at timeout:', await js(`document.querySelector('.chat-log').innerText`));
  throw new Error(`timed out: ${what}`);
};
const type = text => js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`);
const idle = () => js(`Number(document.getElementById('lab').dataset.idle ?? 0)`);
const idleAfter = (n, seconds) => until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${n}`, 'job finished', seconds);
const chatText = () => js(`document.querySelector('.chat-list').innerText`);
const steps = () => js(`[...document.querySelectorAll('.chat-step:not(.chat-live)')].map(e => e.textContent)`);
const playing = tid => `document.querySelector('.viewport')?.dataset.tid === ${JSON.stringify(tid)} && Number(document.querySelector('.viewport').dataset.frame) > 0`;
const frame = () => js(`Number(document.querySelector('.viewport').dataset.frame)`);

try {
  await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await wait(1000);
  await send('Page.navigate', { url: `${ORIGIN}/lab.html` });
  await until(`document.getElementById('lab')?.dataset.server === 'up'`, 'server up', 30);

  // 1. Empty start.
  check('starts empty', (await js(`document.querySelector('.lab-empty h2').textContent`)) === 'Describe your robot and where it works');
  check('no replay or preview before a brief', !(await js(`!!document.querySelector('.viewport')`)));
  check('title is plain before a brief', (await js(`document.querySelector('.lab-name').textContent`)) === 'CrashLab');

  // 2. A brief plays one run. Quick questions get the first option, so the world differs from the defaults.
  const t0 = Date.now();
  let n = await idle();
  await js(`(() => { window.__live = new Set(); const row = document.querySelector('.chat-live'); new MutationObserver(() => { const t = row.firstElementChild?.textContent; if (t && !row.hidden) window.__live.add(t); }).observe(row, { childList: true, subtree: true }); })()`);
  await type(BRIEF);
  await idleAfter(n, 90);
  let asked = 0;
  while (await js(`[...document.querySelectorAll('.chat-option')].some(b => !b.disabled)`)) {
    asked++;
    if (asked === 1) await shot('lab-question.png');
    n = await idle();
    await js(`[...document.querySelectorAll('.chat-card')].pop().querySelector('.chat-option:not(:disabled)').click()`);
    await idleAfter(n, 90);
  }
  await until(playing('normal-1'), 'first run plays', Math.max(1, 90 - (Date.now() - t0) / 1000));
  const firstSeconds = (Date.now() - t0) / 1000;
  check('a brief plays a run within 90 s', firstSeconds <= 90, `${firstSeconds.toFixed(1)} s, ${asked} questions`);
  const stages = await js(`[...window.__live]`);
  check('a live step row showed the stages', stages.length >= 3, stages.join(', '));
  const f0 = await frame();
  await wait(1500);
  check('the run plays', (await frame()) > f0, `${f0} -> ${await frame()}`);

  const firstSteps = await steps();
  check('check rows in plain words', firstSteps.includes('Built the world') && firstSteps.includes('Ran one test'), firstSteps.join(', '));
  check('no brace in chat text', !(await chatText()).includes('{'));
  check('user bubble shows the brief', await js(`[...document.querySelectorAll('.chat-me')].some(e => e.textContent === ${JSON.stringify(BRIEF)})`));
  const name = await js(`document.querySelector('.lab-name').textContent`);
  const tabName = await js(`document.querySelector('.lab-tab').textContent`);
  check('title and tab show a plain name', name === 'CrashLab — dubai_tower' && tabName === 'dubai_tower.world' && (await js('document.title')) === 'dubai_tower — CrashLab', `${name} | ${tabName}`);
  check('no campaign button after the run', !(await js(`[...document.querySelectorAll('button')].some(b => /looks right|approve|test on/i.test(b.textContent))`)));
  await shot('lab-2.png');

  // 3. A follow-up changes that world.
  const sid = await js(`sessionStorage.getItem('crashlab-session')`);
  const get = path => fetch(`${SERVER}/api/sessions/${sid}/${path}`, { headers: { Origin: ORIGIN } });
  const events = async () => {
    const res = await get('events');
    const reader = res.body.getReader();
    let text = '';
    const stop = setTimeout(() => reader.cancel(), 600);
    try { while (true) { const { value, done } = await reader.read(); if (done) break; text += new TextDecoder().decode(value); } } catch {}
    clearTimeout(stop);
    return text.split('\n').filter(l => l.startsWith('data: ')).map(l => JSON.parse(l.slice(6)));
  };
  const cardsBefore = await js(`document.querySelectorAll('.chat-card').length`);
  n = await idle();
  const t1 = Date.now();
  await type(CHANGE);
  await idleAfter(n, 150);
  await until(playing('normal-2'), 'second run plays', 30);
  console.log(`follow-up took ${((Date.now() - t1) / 1000).toFixed(1)} s`);
  check('no question asked again', (await js(`document.querySelectorAll('.chat-card').length`)) === cardsBefore);
  check('chat says Changed the world', (await steps()).includes('Changed the world'));
  check('no brace in chat text after the change', !(await chatText()).includes('{'));

  const w1 = await (await get('trials/normal-1/world.json')).json();
  const w2 = await (await get('trials/normal-2/world.json')).json();
  const r1 = await (await get('trials/normal-1/result.json')).json();
  const r2 = await (await get('trials/normal-2/result.json')).json();
  const log = await events();
  const planned = log.filter(e => e.type === 'tool' && e.title === 'plan_world').pop();
  const cited = Object.keys(JSON.parse(planned.lines[0]));
  const moved = Object.keys(w2).filter(k => JSON.stringify(w1[k]) !== JSON.stringify(w2[k]));
  console.log('cited', cited.join(','), '| moved', moved.join(','));
  check('world_2 differs from world_1', moved.length > 0);
  check('world_2 differs only in the cited fields', moved.every(k => cited.includes(k)), moved.filter(k => !cited.includes(k)).join(','));
  check('the run seed stays', r1.seed === r2.seed, `${r1.seed} and ${r2.seed}`);
  const said = log.filter(e => e.type === 'text' && !e.fail).map(e => e.text).filter(t => / to .*\d/.test(t)).pop() ?? '';
  console.log('said:', said);
  const shown = v => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : String(Number(v.toPrecision(3))));
  check('chat says each moved value in plain numbers', moved.length > 0 && moved.every(k => said.includes(`${shown(w1[k])} to ${shown(w2[k])}`)), said);
  check('chat shows those numbers', (await chatText()).includes(said) && said.length > 0);
  const f1 = await frame();
  await wait(1500);
  check('the second run plays', (await frame()) > f1, `${f1} -> ${await frame()}`);
  await js(`document.querySelector('.chat-log').scrollTop = 1e6`);
  await shot('lab-3.png');

  // 4. Words on the page, and the end of the flow.
  const body = await js(`document.body.textContent`);
  const html = await js(`document.body.outerHTML`);
  const banned = /\b(fix|bounty|report|worlds)\b|controller\.py/i;
  check('DOM text has no campaign words', !banned.test(body), body.match(banned)?.[0]);
  check('DOM markup has no campaign words', !banned.test(html), html.match(banned)?.[0]);
  check('Simulated stays in the status bar', (await js(`document.querySelector('.lab-status').textContent`)).startsWith('Simulated'));
  check('replay label stays', (await js(`document.querySelector('.sim-label').textContent`)) === 'Simulated. Replay of a recorded run.');
  check('fonts load from src/lab/fonts', await js(`document.fonts.ready.then(() => document.fonts.check('13px Inter') && document.fonts.check('12px "JetBrains Mono"'))`));
  const fonts = await js(`performance.getEntriesByType('resource').map(r => r.name).filter(n => n.endsWith('.woff2'))`);
  check('font paths', fonts.length === 2 && fonts.every(f => f.includes('/src/lab/fonts/')), fonts.join(' '));

  const count = log.filter(e => e.type === 'llm_count').length;
  await type('looks right');
  await wait(1200);
  const state = await (await get('state')).json();
  const after = await events();
  check('confirming ends there', state.phase === 'review_scene' && !state.busy && !after.some(e => e.title === 'scenario_agent') && after.filter(e => e.type === 'llm_count').length === count, JSON.stringify(state));
  check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 8).join('\n'));
} catch (err) {
  check('the flow finished', false, String(err));
}
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
