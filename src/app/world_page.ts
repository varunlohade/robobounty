import { el, icon } from './dom.ts';
import { Replay } from './replay.ts';
import { SimView } from './view.ts';
import type { Trial } from './trial.ts';

export const LABEL = 'Simulated. Replay of a recorded run.';
const SPARK_POINTS = 96;
const OFF_GLASS_M = 0.5;
const NS = 'http://www.w3.org/2000/svg';

export const fmtTime = (s: number) => `${Math.floor(s / 60)}:${Math.floor(s % 60).toString().padStart(2, '0')}`;

// A small line chart of one whole recorded series, with a cursor at the current frame.
function sparkline(series: number[]) {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'spark');
  svg.setAttribute('viewBox', '0 0 100 26');
  svg.setAttribute('preserveAspectRatio', 'none');
  const lo = Math.min(...series), hi = Math.max(...series), range = hi - lo || 1;
  const n = Math.min(SPARK_POINTS, series.length);
  const pts: string[] = [];
  for (let i = 0; i < n; i++) {
    const v = series[Math.floor((i * (series.length - 1)) / Math.max(1, n - 1))];
    pts.push(`${((i / Math.max(1, n - 1)) * 100).toFixed(2)},${(24 - ((v - lo) / range) * 22).toFixed(2)}`);
  }
  const line = document.createElementNS(NS, 'polyline');
  line.setAttribute('points', pts.join(' '));
  const cursor = document.createElementNS(NS, 'line');
  cursor.setAttribute('y1', '0');
  cursor.setAttribute('y2', '26');
  svg.append(line, cursor);
  return { svg, seek: (fraction: number) => { const x = String(fraction * 100); cursor.setAttribute('x1', x); cursor.setAttribute('x2', x); } };
}

interface Metric { value: (row: number) => string; series?: number[] }

export function worldPage(trial: Trial, statusRight: HTMLElement) {
  const { result, manifest, trace, wind, world } = trial;
  const page = el('div', 'page');
  const body = el('div', 'world-body');
  const rail = el('aside', 'rail');
  const viewport = el('div', 'viewport');
  const maxFrame = manifest.frames - 1;
  const total = maxFrame / manifest.hz;

  const head = el('div', 'rail-head');
  const when = el('div', 'rail-note');
  const lowest = `Lowest suction ${(Number(result.min_pressure_pa) / 1000).toFixed(2)} kPa`;
  const outcome = String(result.outcome ?? 'unknown');
  head.append(
    result.passed ? el('h2', '', 'Test passed') : result.failure ? el('h2', 'fail', 'Test failed') : el('h2', '', 'Stopped and held on'),
    el('p', '', result.passed ? lowest : `${result.failure ?? outcome}. ${lowest}`),
  );

  const col = (name: string) => trace.columns.indexOf(name);
  const series = (name: string, scale = 1) => trace.rows.map(r => Number(r[col(name)]) * scale);
  const coverage: number[] = [];
  let lastCoverage = 0;
  for (const r of trace.rows) {
    const c = r[col('coverage')];
    if (c !== null) lastCoverage = Number(c);
    coverage.push(lastCoverage);
  }
  const dp = series('dp', 0.001), tension = series('tension'), volts = series('volts');
  const fixed = (s: number[], digits: number) => (row: number) => s[row].toFixed(digits);
  const metrics: [string, string, Metric][] = [
    ['Wind', 'm/s', { value: fixed(wind, 1), series: wind }],
    ['Suction', 'kPa', { value: fixed(dp, 2), series: dp }],
    ['Grip', 'μ', { value: () => manifest.friction.toFixed(2) }],
    ['Tether', 'N', { value: fixed(tension, 0), series: tension }],
    ['Battery', 'V', { value: fixed(volts, 2), series: volts }],
    ['Cleaned', '%', { value: row => (coverage[row] * 100).toFixed(1), series: coverage }],
  ];
  const rows = metrics.map(([name, unit, m]) => {
    const box = el('div', 'metric');
    const value = el('span', '', '');
    const line = el('div', 'metric-value');
    line.append(value, el('span', 'metric-unit', unit));
    const spark = m.series ? sparkline(m.series) : null;
    box.append(el('div', 'metric-name', name), line);
    if (spark) box.append(spark.svg);
    return { box, value, m, spark };
  });
  rail.append(head, when, ...rows.map(r => r.box));

  const position = { phase: el('span'), x: el('span'), z: el('span') };
  const fact = (name: string, value: HTMLElement | string) => {
    const row = el('div', 'fact');
    row.append(el('span', '', name), typeof value === 'string' ? el('span', '', value) : value);
    return row;
  };
  const facts = el('div', 'facts');
  facts.append(
    fact('Phase', position.phase), fact('x', position.x), fact('z', position.z),
    fact('Seed', String(result.seed)), fact('Wetness', String(world.wetness)), fact('Suction setting', `${String(world.suction_pa)} Pa`),
    fact('Seal leak', `${String(world.seal_leak_mm2)} mm²`),
  );

  const fired = Object.entries(result.fired).sort((a, b) => a[1].t - b[1].t);
  const events = el('div', 'events');
  if (fired.length) rail.append(events);
  rail.append(facts);

  viewport.append(el('div', 'sim-tag sim-label', LABEL), el('div', 'sim-tag sim-key', 'Grey is dirt from this run. Bare glass is clean.'));
  if (manifest.elements?.length) viewport.append(el('div', 'sim-tag sim-elements', `Scene elements: ${manifest.elements.join(', ')}. Not counted in the headline numbers.`));
  const offGlass = el('div', 'sim-tag sim-off fail', 'Robot off the glass. The red line is its recorded path.');
  offGlass.hidden = true;
  viewport.append(offGlass);
  body.append(rail, viewport);

  const player = el('div', 'player');
  const startBtn = el('button', 'icon-btn');
  startBtn.setAttribute('aria-label', 'Go to start');
  startBtn.append(icon('start'));
  const playBtn = el('button', 'icon-btn');
  playBtn.setAttribute('aria-label', 'Play or pause (Space)');
  playBtn.title = 'Play or pause (Space)';
  const endBtn = el('button', 'icon-btn');
  endBtn.setAttribute('aria-label', 'Go to end');
  endBtn.append(icon('end'));
  const scrub = el('div', 'scrub');
  const slider = el('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = String(maxFrame);
  slider.step = '1';
  slider.value = '0';
  slider.setAttribute('aria-label', 'Timeline');
  scrub.append(slider);
  for (const [rule, hit] of fired) {
    const mark = el('div', 'mark');
    mark.style.left = `${((hit.t * manifest.hz) / maxFrame) * 100}%`;
    mark.title = `${rule} at ${hit.t} s`;
    scrub.append(mark);
  }
  const time = el('span', 'time');
  const speed = el('select', 'select');
  speed.setAttribute('aria-label', 'Playback speed');
  for (const s of [1, 2, 4, 8, 16]) {
    const opt = el('option', '', `${s}x`);
    opt.value = String(s);
    opt.selected = s === 8;
    speed.append(opt);
  }
  player.append(startBtn, playBtn, endBtn, scrub, time, speed);
  page.append(body, player);

  const statusTime = el('span');
  statusRight.prepend(statusTime);
  let stop = () => { statusTime.remove(); };
  let toggleRun = () => {};

  async function start() {
    const replay = await Replay.open(trial);
    const view = new SimView(viewport, replay, trial);
    let playing = true;
    let at = 0;
    let last = performance.now();

    const show = (frame: number) => {
      replay.seek(frame);
      view.sync();
      const f = replay.frame;
      const robot = replay.bodyPos('robot');
      viewport.dataset.frame = String(f);
      viewport.dataset.robot = JSON.stringify(robot);
      viewport.dataset.roller = JSON.stringify(replay.bodyPos('roller_lf'));
      time.textContent = `${fmtTime(f / manifest.hz)} / ${fmtTime(total)}`;
      when.textContent = `Replay, ${fmtTime(f / manifest.hz)} into the run`;
      statusTime.textContent = `Frame ${f} of ${maxFrame}`;
      slider.value = String(f);
      slider.style.setProperty('--done', `${(f / maxFrame) * 100}%`);
      const { area } = manifest;
      offGlass.hidden = !result.failure || !(Math.abs(robot[1]) > OFF_GLASS_M || robot[0] < area.x0 - OFF_GLASS_M || robot[0] > area.x1 + OFF_GLASS_M
        || robot[2] < area.z0 - OFF_GLASS_M || robot[2] > area.z1 + OFF_GLASS_M);
      position.x.textContent = `${robot[0].toFixed(3)} m`;
      position.z.textContent = `${robot[2].toFixed(3)} m`;
      // trace row i describes the state after step i, which is frame i + 1.
      const row = Math.max(0, f - 1);
      position.phase.textContent = String(trace.rows[row][col('phase')]);
      for (const r of rows) {
        r.value.textContent = r.m.value(row);
        r.spark?.seek(row / Math.max(1, trace.rows.length - 1));
      }
    };

    const setPlaying = (on: boolean) => {
      playing = on;
      playBtn.replaceChildren(icon(on ? 'pause' : 'play'));
      viewport.dataset.playing = String(on);
      last = performance.now();
    };
    const toggle = () => {
      if (!playing && at >= maxFrame) at = 0;
      setPlaying(!playing);
    };
    const jump = (frame: number) => {
      setPlaying(false);
      at = frame;
      show(at);
    };

    playBtn.addEventListener('click', toggle);
    startBtn.addEventListener('click', () => jump(0));
    endBtn.addEventListener('click', () => jump(maxFrame));
    slider.addEventListener('input', () => jump(Number(slider.value)));
    for (const [rule, hit] of fired) {
      const row = el('button', 'event');
      row.type = 'button';
      row.append(el('span', '', fmtTime(hit.t)), el('span', '', `${rule}, value ${hit.value}`));
      row.addEventListener('click', () => jump(Math.min(maxFrame, Math.round(hit.t * manifest.hz))));
      events.append(row);
    }
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.code !== 'Space' || page.hidden || t.closest('textarea, select, button, summary')) return;
      e.preventDefault();
      toggle();
    };
    addEventListener('keydown', onKey);
    toggleRun = toggle;
    let stopped = false;
    stop = () => {
      stopped = true;
      removeEventListener('keydown', onKey);
      view.dispose();
      replay.dispose();
      statusTime.remove();
    };

    const tick = (now: number) => {
      if (stopped) return;
      if (playing) {
        at += ((now - last) / 1000) * manifest.hz * Number(speed.value);
        if (at >= maxFrame) { at = maxFrame; setPlaying(false); }
        show(Math.floor(at));
      }
      last = now;
      requestAnimationFrame(tick);
    };
    setPlaying(true);
    show(0);
    viewport.dataset.ready = 'true';
    requestAnimationFrame(tick);
    return replay;
  }

  return { page, start, viewport, stop: () => stop(), toggle: () => toggleRun() };
}
