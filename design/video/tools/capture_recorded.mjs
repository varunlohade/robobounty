// Captures the real app in recorded mode, frame by frame, through its own controls. A replay moves through its timeline slider, so playback speed is exact.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './cdp.mjs';

const BASE = process.env.CRASHLAB_BASE ?? 'http://localhost:5199';
const OUT = resolve(import.meta.dirname, '../_cap/rec');
const FPS = 24;
const c = await openChrome(9379);
const { js, until } = c;
process.on('exit', () => c.close());

function scene(name) {
  const dir = join(OUT, name);
  mkdirSync(dir, { recursive: true });
  const frames = [];
  return {
    async still(seconds) {
      const file = `f${String(frames.length).padStart(5, '0')}.jpg`;
      await c.shot(join(dir, file), 'jpeg');
      frames.push({ file, d: seconds });
    },
    done() { writeFileSync(join(dir, 'frames.json'), JSON.stringify(frames)); console.log(name, frames.length, frames.reduce((a, f) => a + f.d, 0).toFixed(1), 's'); },
  };
}
const tab = name => js(`[...document.querySelectorAll('.tab')].find(t => t.textContent.endsWith(${JSON.stringify(name)})).click()`);
const scrub = frame => js(`(() => { const s = document.querySelector('.scrub input'); s.value = ${frame}; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
const scrollTo = (sel, y) => js(`document.querySelector(${JSON.stringify(sel)}).scrollTop = ${y}`);
const smooth = async (s, sel, y0, y1, seconds) => {
  const n = Math.round(seconds * FPS);
  for (let i = 0; i <= n; i++) {
    const u = i / n, e = u * u * (3 - 2 * u);
    await scrollTo(sel, y0 + (y1 - y0) * e);
    await wait(20);
    await s.still(1 / FPS);
  }
};
const openReplay = async name => {
  await js(`[...document.querySelectorAll('.chat-list button')].find(b => b.textContent.startsWith(${JSON.stringify(name)})).click()`);
  const tid = `dubai-final-${name.replace('_', '-')}`;
  await until(`document.querySelector('.viewport')?.dataset.tid === ${JSON.stringify(tid)} && document.querySelector('.viewport')?.dataset.ready === 'true'`, 'replay');
  await wait(800);
  await scrub(0);
  await wait(300);
};
const setSpeed = v => js(`(() => { const s = document.querySelector('.player select'); s.value = ${JSON.stringify(String(v))}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
// speed x: the slider advances hz x speed / FPS recorded frames for each video frame.
const play = async (s, hz, speed, from, to) => {
  await setSpeed(speed);
  for (let f = from; f <= to; f += (hz * speed) / FPS) {
    await scrub(Math.round(f));
    await wait(30);
    await s.still(1 / FPS);
  }
};

await c.send('Page.navigate', { url: `${BASE}/app.html?recorded=1` });
await wait(800);
await until(`[...document.querySelectorAll('.chat-list button')].length > 2`, 'app');
await wait(3000);

let s = scene('chat_brief');
await scrollTo('.chat-list', 0);
await wait(300);
await s.still(1);
s.done();

s = scene('chat_requirements');
await smooth(s, '.chat-list', 0, 230, 3);
await s.still(1);
s.done();

await tab('worlds');
await scrollTo('.page.worlds', 0);
await wait(400);
s = scene('map');
await s.still(1);
s.done();

s = scene('map_groups');
const worldsMax = await js(`(() => { const p = document.querySelector('.page.worlds'); return p.scrollHeight - p.clientHeight; })()`);
console.log('worlds scroll', worldsMax);
await js(`document.querySelector('.map-bar button')?.click()`);
await wait(500);
await s.still(1);
s.done();
await js(`document.querySelector('.map-bar button')?.click()`);
await wait(300);

s = scene('world_detail');
await js(`[...document.querySelectorAll('.map-cell')].find(b => (b.title || b.textContent || '').startsWith('world_016'))?.click()`);
await wait(500);
await js(`document.querySelector('.worlds-foot')?.scrollIntoView({ block: 'end' })`);
await wait(300);
await s.still(1);
s.done();
await scrollTo('.page.worlds', 0);

s = scene('not_tested');
await js(`document.querySelector('.not-tested').scrollIntoView({ block: 'center' })`);
await wait(400);
await s.still(1);
s.done();
await scrollTo('.page.worlds', 0);

await openReplay('world_016');
s = scene('replay_016_start');
await play(s, 20, 1, 0, 200);
s.done();
s = scene('replay_016_end');
await scrub(11000);
await wait(400);
await s.still(1);
s.done();

s = scene('code_240');
await tab('controller.py');
await wait(300);
const lineY = n => js(`document.querySelectorAll('.code-line')[${n - 1}].offsetTop`);
const codeScroller = await js(`(() => { let e = document.querySelector('.code'); while (e && e.scrollHeight <= e.clientHeight + 4) e = e.parentElement; return e ? (e.id = 'code-scroll', true) : false; })()`);
console.log('code scroller', codeScroller);
await scrollTo('#code-scroll', Math.max(0, (await lineY(244)) - 400));
await wait(300);
await s.still(1);
s.done();
s = scene('code_108');
await scrollTo('#code-scroll', Math.max(0, (await lineY(108)) - 400));
await wait(300);
await s.still(1);
s.done();

await openReplay('world_033');
s = scene('replay_033');
await play(s, 20, 2, 300, 607);
await s.still(3);
s.done();

await openReplay('world_038');
s = scene('replay_038');
await js(`[...document.querySelectorAll('.event')].find(b => b.textContent.includes('false_done')).click()`);
await wait(500);
await s.still(1);
s.done();

s = scene('fix_top');
await tab('Fix');
await js(`document.querySelector('.chat-list').scrollTop = 1e9`);
await wait(400);
await s.still(1);
s.done();

s = scene('report');
await tab('Report');
await wait(300);
await s.still(1);
s.done();

console.log('problems', c.problems);
process.exit(0);
