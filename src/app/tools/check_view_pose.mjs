// Headless check that the realistic view draws the recording: node src/app/tools/check_view_pose.mjs [trial] [--gl metal|swiftshader]
// Compares the drawn robot root with Python's recorded positions, and the drawn dirt texture's clean share with the recorded coverage. Needs vite on 5199.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const trial = process.argv[2]?.startsWith('--') ? 'nominal-seed1' : process.argv[2] ?? 'nominal-seed1';
const gl = process.argv.includes('--gl') ? process.argv[process.argv.indexOf('--gl') + 1] : 'swiftshader';
const ROOT = resolve(import.meta.dirname, '../../..');
const PORT = 9811;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'crashlab-pose-'))}`, '--window-size=1440,900',
  ...(gl === 'metal' ? ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist'] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']), 'about:blank'], { stdio: 'ignore' });
process.on('exit', () => chrome.kill());
const wait = ms => new Promise(r => setTimeout(r, ms));
let url;
for (let i = 0; i < 60 && !url; i++) { try { url = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {} if (!url) await wait(200); }
const ws = new WebSocket(url);
await new Promise(r => ws.addEventListener('open', r));
let id = 1; const pending = new Map();
ws.addEventListener('message', m => { const msg = JSON.parse(m.data); if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); } });
const send = (method, params = {}) => new Promise(r => { const n = id++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const js = async e => { const r = await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result.result.value; };
await send('Page.navigate', { url: `http://localhost:5199/app.html?trial=${trial}` });
for (let i = 0; i < 600 && !(await js(`document.querySelector('.viewport')?.dataset.ready === 'true' && !!document.querySelector('input[aria-label=Timeline]')`)); i++) await wait(200);
const ref = JSON.parse(readFileSync(join(ROOT, 'public/trials', trial, 'reference.json'), 'utf8'));
const frames = ref.frames ?? ref;
const trace = JSON.parse(readFileSync(join(ROOT, 'public/trials', trial, 'trace.json'), 'utf8'));
const cov = trace.columns.indexOf('coverage');
const every = JSON.parse(readFileSync(join(ROOT, 'public/trials', trial, 'manifest.json'), 'utf8')).dirt.every_steps;
let worstPose = 0, worstClean = 0, nClean = 0;
for (const r of frames) {
  const out = JSON.parse(await js(`(() => { const s = document.querySelector('input[aria-label=Timeline]'); s.value = '${r.frame}'; s.dispatchEvent(new Event('input', { bubbles: true })); const v = document.querySelector('.viewport'); return JSON.stringify({ drawn: JSON.parse(v.dataset.drawnRobot), clean: v.dataset.drawnClean }); })()`));
  worstPose = Math.max(worstPose, ...out.drawn.map((x, i) => Math.abs(x - r.robot[i])));
  // The trace writes coverage once per grid. Compare with the row where this frame's grid was written.
  const row = Math.max(0, Math.floor(r.frame / every) * every - 1);
  let recorded = trace.rows[row]?.[cov];
  for (let k = row; recorded === null && k >= 0; k--) recorded = trace.rows[k][cov];
  if (recorded !== null && recorded !== undefined) { worstClean = Math.max(worstClean, Math.abs(Number(out.clean) - Number(recorded))); nClean++; }
}
console.log(`${worstPose < 2e-5 ? 'PASS' : 'FAIL'} ${trial}: drawn robot equals recorded position at ${frames.length} frames, worst ${worstPose.toExponential(2)} m (dataset rounds to 1e-5 m)`);
console.log(`${worstClean < 0.02 ? 'PASS' : 'FAIL'} ${trial}: clean share of the drawn dirt grid equals recorded coverage at ${nClean} frames, worst ${worstClean.toFixed(4)}`);
process.exit(worstPose < 2e-5 && worstClean < 0.02 ? 0 : 1);
