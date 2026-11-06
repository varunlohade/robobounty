import { mountShell } from './shell.ts';
import { icon } from './icons.ts';
import { getJson, h, link, serverDown } from './ui.ts';

interface Entry { id: string; kind: string; name: string; by: string; does: string; version: string | null; status: string; tone: string; detail: string; frame: string | null }
interface Person { name: string; submissions: number; states: string[] }
interface Data { entries: Entry[]; bounties: number; testers: Person[]; authors: Person[] }

const { main } = mountShell({ page: 'providers', title: 'Providers', subtitle: 'Who provides what in this product. Real entries only.' });
const list = h('section', '');
const detail = h('section', 'pdetail');
main.append(h('div', 'prov', list, detail));

function show(e: Entry, rows: HTMLElement[], row: HTMLElement) {
  rows.forEach(r => r.setAttribute('aria-selected', r === row ? 'true' : 'false'));
  const dl = h('dl', '', h('dt', '', 'Status'), h('dd', `tone-${e.tone}`, e.status), h('dt', '', 'Version'), h('dd', 'mono', e.version ?? 'unknown'));
  detail.replaceChildren(h('div', 'swap',
    e.frame ? h('div', 'frame', Object.assign(h('img'), { src: `/site/frames/${e.frame}`, alt: '' }), h('div', 'frame-note', 'Simulated')) : null,
    h('div', 'in', h('h2', '', e.name), h('p', '', e.detail), dl)));
}

function people(title: string, rows: Person[], emptyHead: string, emptyBody: string, action?: HTMLElement): HTMLElement {
  const box = h('div', 'kind', h('h2', '', title));
  if (!rows.length) {
    box.append(h('div', 'empty', h('p', '', emptyHead), h('p', 'quiet', emptyBody), action));
    return box;
  }
  const body = h('tbody');
  for (const p of rows) body.append(h('tr', '', h('td', '', h('span', 'nm', p.name)), h('td', '', `${p.submissions} submissions`), h('td', '', p.states.join(', ').replace(/_/g, ' '))));
  box.append(h('table', '', body));
  return box;
}

getJson<Data>('/site-api/providers').then(d => {
  const rows: HTMLElement[] = [];
  const kinds = [...new Set(d.entries.map(e => e.kind))];
  const blocks = kinds.map(kind => {
    const body = h('tbody');
    for (const e of d.entries.filter(x => x.kind === kind)) {
      const row = h('tr', 'row',
        h('td', '', h('span', 'nm', e.name), h('span', 'by', e.by)),
        h('td', 'does', e.does),
        h('td', 'mono vers', e.version ?? 'unknown'),
        h('td', '', h('span', `stat tone-${e.tone}`, e.tone === 'ok' ? icon('ok', 14) : icon('circle', 14), e.status)));
      row.tabIndex = 0;
      row.dataset.id = e.id;
      row.addEventListener('click', () => show(e, rows, row));
      row.addEventListener('keydown', ev => {
        if (ev.key === 'Enter') show(e, rows, row);
        const step = ev.key === 'ArrowDown' ? 1 : ev.key === 'ArrowUp' ? -1 : 0;
        if (step) { ev.preventDefault(); rows[rows.indexOf(row) + step]?.focus(); }
      });
      rows.push(row);
      body.append(row);
    }
    return h('div', 'kind', h('h2', '', kind), h('table', 'fixed', body));
  });
  list.replaceChildren(...blocks,
    people('Testers', d.testers, 'No testers yet.', 'A tester submits a world that breaks a robot. Names appear here after a real submission.'),
    people('Fix authors', d.authors, 'No fix authors yet.', 'Names appear here when someone submits a fix to a bounty. This list holds no sample rows.', link('btn sec self', 'bounties.html', 'See the bounties')));
  const first = d.entries.findIndex(e => e.id === 'window');
  show(d.entries[first], rows, rows[first]);
}).catch(() => { list.replaceChildren(serverDown('This list')); });
