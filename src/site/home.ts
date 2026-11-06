import { mountShell } from './shell.ts';
import { icon, type IconName } from './icons.ts';
import { getJson, h, link, outcomeBar, resultWords, serverDown, type Tally } from './ui.ts';

interface Run extends Tally { id: string; label: string; robot: string; pack: string; sim: string | null; types: { name: string; count: number }[]; note: string; source: string }
interface Work { title: string; body: string; tone: string; icon: IconName; href: string; tag: string }
interface Recent { runs: Run[]; work: Work[] }

const { main, setStatus } = mountShell({ page: 'home', title: 'Home' });
const page = h('div', 'scroll home');
main.append(page);

function hero(run: Run | undefined): HTMLElement {
  const picture = h('div', 'frame', Object.assign(h('img'), { src: '/site/frames/tower-wind.jpg', alt: 'The window robot on wet tower glass in strong wind' }), h('div', 'frame-note', 'Simulated. Still from a recorded run.'));
  const info = h('div', 'info');
  if (run) {
    info.append(h('h2', '', `Latest batch: ${run.robot.toLowerCase()} robot`), h('div', 'where mono', `sim ${run.sim ?? 'unknown'}`));
    const n = (value: number, word: string, cls = '') => h('div', cls, h('b', '', String(value)), h('span', '', word));
    info.append(h('div', 'nums', n(run.total, 'Worlds run'), n(run.passed, 'Passed'), n(run.failed, 'Failed', 'f'), n(run.holds, 'Safe holds')), outcomeBar(run, true));
    info.append(h('ul', 'types', ...run.types.map(t => h('li', '', t.name, h('b', '', String(t.count))))));
  } else {
    info.append(h('h2', '', 'No batch yet'), h('p', 'quiet', 'Open CrashLab, choose a robot and run its scenarios. The numbers appear here.'));
  }
  info.append(h('div', 'acts', link('btn pri lg', 'crashlab.html', 'Open CrashLab'), run ? link('btn sec lg', `data.html?c=${run.id}`, `See the ${run.total} worlds`) : null));
  return h('section', 'hero', picture, info);
}

function runsTable(runs: Run[]): HTMLElement {
  const box = h('section', '', h('div', 'sect', h('h2', '', 'Recent runs'), h('div', 'r', link('more', 'data.html', 'All data'))));
  if (!runs.length) {
    box.append(h('div', 'empty', h('p', '', 'No runs yet.'), h('p', 'quiet', 'Open CrashLab and run a batch. It appears here.')));
    return box;
  }
  const body = h('tbody');
  for (const r of runs.slice(0, 6)) {
    const row = h('tr', 'row',
      h('td', 'main', r.label), h('td', 'num', String(r.total)), h('td', 'hide-s', outcomeBar(r)), h('td', '', resultWords(r)));
    row.tabIndex = 0;
    const go = () => { location.href = `data.html?c=${encodeURIComponent(r.id)}`; };
    row.addEventListener('click', go);
    row.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
    body.append(row);
  }
  const headRow = h('tr', '', h('th', '', 'Run'), h('th', 'num', 'Worlds'), h('th', 'hide-s', 'Outcome'), h('th', '', 'Result'));
  box.append(h('table', '', h('thead', '', headRow), body));
  return box;
}

function workList(work: Work[]): HTMLElement {
  const box = h('section', '', h('div', 'sect', h('h2', '', 'Open work'), h('div', 'r', String(work.length))));
  if (!work.length) box.append(h('div', 'empty', h('p', '', 'Nothing is waiting for you.')));
  else box.append(h('ul', 'work', ...work.map(w => {
    const ic = icon(w.icon, 16);
    ic.classList.add(`tone-${w.tone}`);
    return h('li', '', link('', w.href, ic, h('div', '', h('div', '', w.title), h('p', '', w.body)), h('span', 'tag', w.tag)));
  })));
  return box;
}

getJson<Recent>('/site-api/recent').then(data => {
  const newest = data.runs[0];
  page.replaceChildren(hero(newest), h('div', 'under', runsTable(data.runs), workList(data.work)));
  if (newest) setStatus(newest.note, [`sim ${newest.sim ?? 'unknown'}`]);
}).catch(() => {
  page.replaceChildren(hero(undefined), serverDown('The run list'));
});
