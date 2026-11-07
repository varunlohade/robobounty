import { mountShell } from './shell.ts';
import { button, h } from './ui.ts';

// The same key lab.html reads to pick its robot.
const PACK_KEY = 'crashlab-pack';
const ROBOTS = [
  { pack: 'window', name: 'Window cleaning', line: 'Suction climber for tower glass', picture: '/site/robot-window.png', alt: 'The window cleaning robot' },
  { pack: 'inspection', name: 'Plant inspection', line: 'ANYmal C on a plant route', picture: '/site/robot-anymal.png', alt: 'The ANYmal C robot' },
] as const;
type Pack = typeof ROBOTS[number]['pack'];

const { main } = mountShell({ page: 'simulation', title: 'Simulation' });
let chosen: Pack = 'window';
try { if (sessionStorage.getItem(PACK_KEY) === 'inspection') chosen = 'inspection'; } catch { /* no storage: the window robot */ }

function open() {
  try { sessionStorage.setItem(PACK_KEY, chosen); } catch { /* no storage: the lab keeps its own default */ }
  location.href = 'lab.html';
}

const cards = h('fieldset', 'cards', h('legend', '', ''));
for (const r of ROBOTS) {
  const input = Object.assign(h('input'), { type: 'radio', name: 'robot', value: r.pack, checked: r.pack === chosen });
  input.addEventListener('change', () => { chosen = r.pack; paint(); });
  const img = Object.assign(h('img'), { src: r.picture, alt: '' });
  cards.append(h('label', 'card', input, img, h('span', '', h('b', '', r.name), h('small', '', r.line)), h('span', 'radio')));
}

const picture = h('div', 'pick-picture');
const name = h('h2', 'pick-name');
const line = h('p', 'pick-line');
const stage = h('section', 'stage pick', picture, h('div', 'pick-foot', h('div', '', name, line), button('pri lg', 'Open Simulation', open)));
main.append(h('div', 'lab', h('aside', '', h('h2', '', 'Choose a robot'), cards), stage));

function paint() {
  const r = ROBOTS.find(x => x.pack === chosen)!;
  picture.replaceChildren(Object.assign(h('img', 'swap'), { src: r.picture, alt: r.alt }));
  name.textContent = r.name;
  line.textContent = r.line;
}

paint();
