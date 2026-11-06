// Opens viewer.html in headless Chrome for each .rrd and checks that it loads and shows data. Saves the screenshots.
// node policy/rerun_lab/check_viewer.mjs. Needs vite on 5333: node_modules/.bin/vite --config policy/rerun_lab/vite.config.mjs
import { readFileSync, statSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { openChrome, wait } from '../../src/lab/tools/browser.mjs';

const HERE = import.meta.dirname, ROOT = resolve(HERE, '../..');
const summary = JSON.parse(readFileSync(resolve(HERE, 'out/summary.json')));
const BASE = 'http://127.0.0.1:5333/viewer.html';
const HOOK = `(() => {
  window.gl = { contexts: 0, kinds: [], webgpu: 0 };
  const real = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
    const had = this.__counted;
    const out = real.call(this, kind, ...rest);
    if (out && !had && /webgl|webgpu/.test(kind)) { this.__counted = true; window.gl.contexts++; window.gl.kinds.push(kind); }
    return out;
  };
})();`;

setTimeout(() => { console.log('FAIL watchdog: the check took over 150 s'); process.exit(2); }, 150000);

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };
const results = {};

async function one(key, query, shotName) {
  const b = await openChrome({ width: 1440, height: 900 });
  await b.send('Page.addScriptToEvaluateOnNewDocument', { source: HOOK });
  const t0 = Date.now();
  await b.send('Page.navigate', { url: `${BASE}?${query}` });
  await b.until('window.lab && (window.lab.opened || window.lab.error)', `${key} opened`, 120);
  const lab = await b.js('JSON.stringify(window.lab)').then(JSON.parse);
  let visual = null;
  for (let i = 0; i < 100 && visual === null; i++) {
    const shot = (await b.send('Page.captureScreenshot', { format: 'png' })).result.data;
    if (shot.length > 200000) visual = (Date.now() - t0) / 1000;
    else await wait(100);
  }
  await wait(3000);
  const state = await b.js(`viewer.get_state().then(s => JSON.stringify(s, (_, v) => typeof v === 'bigint' ? Number(v) : v))`);
  const gl = await b.js('JSON.stringify(window.gl)').then(JSON.parse);
  const res = await b.js(`JSON.stringify(performance.getEntriesByType('resource').map(r => [r.name, r.transferSize, r.decodedBodySize, Math.round(r.duration)]))`).then(JSON.parse);
  const heap = await b.js('performance.memory.usedJSHeapSize');
  const canvas = await b.js(`JSON.stringify([...document.querySelectorAll('canvas')].map(c => { const r = c.getBoundingClientRect(); return [c.width, c.height, r.top, r.bottom]; }))`);
  if (shotName) await b.shot(resolve(ROOT, 'design/shell', shotName));
  // Scrubbing must move the 3D view and the cursor: the picture and the state both change.
  const fail = Number(new URLSearchParams(query).get('t'));
  const png = async () => (await b.send('Page.captureScreenshot', { format: 'png' })).result.data;
  const atFail = await png();
  await b.js(`viewer.set_time({ duration_nanos: ${BigInt(Math.round(fail * 0.5e9))}n, play_state: 'paused' }).then(() => 1)`);
  await wait(1500);
  const cursor = await b.js(`viewer.get_state().then(s => Number(s.recordings[0].timelines[0].current_time))`);
  check(`${key}: scrub moves the cursor and the picture`, Math.abs(cursor - fail * 0.5e9) < 1e9 && atFail !== await png(), `cursor ${cursor / 1e9} s`);
  const external = res.filter(r => !r[0].startsWith('http://127.0.0.1:5333')).map(r => r[0]);
  check(`${key}: no load error`, !lab.error, lab.error ?? '');
  check(`${key}: no console errors`, b.problems.length === 0, b.problems.slice(0, 4).join(' | ').slice(0, 600));
  check(`${key}: no request leaves this machine`, external.length === 0, external.join(' '));
  check(`${key}: one GPU context`, gl.contexts === 1, JSON.stringify(gl));
  check(`${key}: state lists the recording`, /crashlab/.test(state), state.slice(0, 500));
  results[key] = { first_rich_frame_s: visual, open_s: (lab.openMs / 1000).toFixed(2), start_s: (lab.startMs / 1000).toFixed(2), total_wall_s: (Date.now() - t0) / 1000, gl, canvas, heap_mb: Math.round(heap / 1e6), biggest: res.sort((a, c) => c[2] - a[2]).slice(0, 4), problems: b.problems.slice(0, 6) };

  // Stop must release the context, or a panel that opens and closes would leak one each time.
  await b.js('viewer.stop()');
  await wait(500);
  results[key].canvases_after_stop = await b.js(`document.querySelectorAll('canvas').length`);
  // Open and close five more times. Backing store includes the Wasm memory.
  const usage = async () => { const u = (await b.send('Runtime.getHeapUsage')).result; return Math.round((u.backingStorageSize ?? 0) / 1e6); };
  const cycles = [await usage()];
  for (let i = 0; i < 5; i++) {
    await b.js(`viewer.start(null, document.getElementById('host'), { width: '800px', height: '600px', hide_welcome_screen: true, check_for_updates_on_startup: false${query.includes('webgl') ? `, render_backend: 'webgl'` : ''} }).then(() => viewer.open(new URL('out/window.rrd', location.href).href)).then(() => 1)`);
    await wait(800);
    await b.js('viewer.stop()');
    await wait(300);
    cycles.push(await usage());
  }
  results[key].backing_mb_over_cycles = cycles;
  results[key].contexts_after_cycles = (await b.js('JSON.stringify(window.gl)').then(JSON.parse)).contexts;
  b.close();
}

await one('window', `run=window&t=${summary.window.fail_t}`, 'rerun-window.png');
await one('inspection', `run=inspection&t=${summary.inspection.fail_t}`, 'rerun-inspection.png');
await one('compare', `run=compare&t=${summary.compare.fail_t}`, 'rerun-compare.png');
await one('window-webgl', `run=window&backend=webgl&t=${summary.window.fail_t}`, null);

writeFileSync(resolve(HERE, 'out/viewer_check.json'), JSON.stringify(results, null, 1));
console.log(JSON.stringify(results, null, 1));
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
