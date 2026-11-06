import { mountShell } from './shell.ts';
import { icon } from './icons.ts';
import { button, filmStrip, getJson, h, link, outcomeBar, resultWords, serverDown, type Tally } from './ui.ts';

interface Run extends Tally { id: string; label: string; pack: string; sim: string | null; note: string; held_back: number }
interface Sample { name: string; group: string; reason: string; line: string; film: string | null; replay: string | null; kind_name: string }
interface Recent { runs: Run[]; samples: Record<string, Sample | null> }

// The same key lab.html reads to pick its robot.
const PACK_KEY = 'crashlab-pack';
const ROBOTS = [
  { pack: 'window', name: 'Window cleaning', line: 'Suction climber on tower glass', frame: '/site/frames/tower-wind.jpg', alt: 'The window robot on a tower facade',
    where: 'Glass tower', controller: 'Scripted Python', physics: 'MuJoCo, hand-built', about: 'Change the glass, the weather and the tower. See where the controller holds, slips or falls off.' },
  { pack: 'inspection', name: 'Plant inspection', line: 'ANYmal C on a plant route', frame: '/site/frames/plant-walk.jpg', alt: 'The ANYmal C robot on a plant route',
    where: 'Plant route', controller: 'Upstream policy, ONNX', physics: 'Newton, not calibrated', about: 'Change the floor, the pipes and the load. See where the walking policy trips, sticks or falls.' },
] as const;
type Pack = typeof ROBOTS[number]['pack'];

const { main, setStatus } = mountShell({ page: 'simulation', title: 'Simulation', subtitle: 'Say the job. The AI builds the world, lists what could go wrong and runs it all.' });
let data: Recent | null = null;
let down = false;
let chosen: Pack = 'window';
try { if (sessionStorage.getItem(PACK_KEY) === 'inspection') chosen = 'inspection'; } catch { /* no storage: the window robot */ }

const facts = h('dl', 'facts');
const about = h('p', 'about');
const stage = h('section', 'stage');

function open() {
  try { sessionStorage.setItem(PACK_KEY, chosen); } catch { /* no storage: the lab keeps its own default */ }
  location.href = 'lab.html';
}

const cards = h('fieldset', 'cards', h('legend', '', ''));
for (const r of ROBOTS) {
  const input = Object.assign(h('input'), { type: 'radio', name: 'robot', value: r.pack, checked: r.pack === chosen });
  input.addEventListener('change', () => { chosen = r.pack; paint(); });
  const img = Object.assign(h('img'), { src: r.frame, alt: '' });
  cards.append(h('label', 'card', input, img, h('span', '', h('b', '', r.name), h('small', '', r.line)), h('span', 'radio')));
}

const aside = h('aside', '', h('h2', '', 'Choose a robot'), cards, about, facts,
  h('div', '', button('pri lg wide', 'Open Simulation', open), h('p', 'open-note', 'Opens the tool with this robot.')),
  h('div', 'later', icon('upload', 16), 'Importing a robot file is not built yet.'));
main.append(h('div', 'lab', aside, stage));

function paint() {
  const r = ROBOTS.find(x => x.pack === chosen)!;
  const runs = (data?.runs ?? []).filter(x => x.pack === chosen);
  const batch = runs[0];
  about.textContent = r.about;
  const row = (k: string, v: string) => [h('dt', '', k), h('dd', '', v)];
  facts.replaceChildren(...row('Where', r.where), ...row('Controller', r.controller), ...row('Physics', r.physics), ...row('Last batch', batch ? `${batch.total} run, ${batch.passed} passed` : 'None yet'));
  const big = h('div', 'frame big swap', Object.assign(h('img'), { src: r.frame, alt: r.alt }), h('div', 'frame-note', 'Simulated. Still from a recorded run.'));
  stage.replaceChildren(big);
  const sample = data?.samples[chosen];
  if (sample) {
    stage.append(h('div', chosen === 'inspection' ? 'detail' : 'detail plain',
      chosen === 'inspection' && sample.film ? filmStrip(sample.film, `Frames from world ${sample.name}. Move across to step through them.`) : null,
      h('div', '', h('h2', '', sample.kind_name), h('p', '', sample.reason), h('small', '', h('code', '', sample.name), sample.line ? ' at ' : '', sample.line ? h('code', '', sample.line) : null)),
      sample.replay ? link('btn sec', sample.replay, icon('play'), 'Replay the recorded run') : null));
  }
  const table = h('div', '', h('div', 'sect', h('h2', '', 'Recent runs'), h('div', 'r', String(runs.length))));
  if (down) table.append(serverDown('The run list'));
  else if (!data) table.append(h('div', 'empty', h('p', 'quiet', 'Reading runs.')));
  else if (!runs.length) table.append(h('div', 'empty', h('p', '', 'No runs with this robot yet.'), h('p', 'quiet', 'Open Simulation and run its scenarios. They appear here.')));
  else {
    const body = h('tbody');
    for (const x of runs.slice(0, 4)) {
      const tr = h('tr', 'row', h('td', 'main', x.label), h('td', 'num', String(x.total)), h('td', 'hide-s', outcomeBar(x)), h('td', '', resultWords(x)), h('td', 'mono hide-n', x.sim ?? 'unknown'));
      tr.tabIndex = 0;
      const go = () => { location.href = `data.html?c=${encodeURIComponent(x.id)}`; };
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
      body.append(tr);
    }
    table.append(h('table', '', h('thead', '', h('tr', '', h('th', '', 'Run'), h('th', 'num', 'Worlds'), h('th', 'hide-s', 'Outcome'), h('th', '', 'Result'), h('th', 'hide-n', 'Sim'))), body));
  }
  stage.append(table);
  if (batch) setStatus(batch.note, batch.sim ? [`sim ${batch.sim}`] : []);
}

paint();
getJson<Recent>('/site-api/recent').then(d => { data = d; paint(); }).catch(() => { down = true; paint(); });
