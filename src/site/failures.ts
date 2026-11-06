// Failures: one row for each failed world in the newest run of each robot.
import { mountShell } from './shell.ts';
import { h, serverDown } from './ui.ts';
import { askAi, board, campaigns, OPEN_SCOPE, openRuns, postBounty, postRef, rowGo } from './overview_data.ts';

const { main, who } = mountShell({ page: 'failures', title: 'Failures', subtitle: 'Simulated', light: true });
const page = h('div', 'scroll ov');
main.append(page);

void who.then(async w => {
  if (w.kind === 'none' || w.kind === 'engineer') return;
  const [list, b] = await Promise.all([campaigns().catch(() => null), board()]);
  if (!list) { page.replaceChildren(serverDown('The failure list')); return; }
  const rows = openRuns(list).flatMap(run => run.worlds.filter(x => x.outcome === 'fail').map(x => ({ run, x })));
  if (!rows.length) { page.replaceChildren(h('div', 'ov-none', 'No open failures. A failed world from a simulation appears here.')); return; }
  const body = h('tbody', '', ...rows.map(({ run, x }) => {
    const ref = postRef(b.fixable, run.pack, x.kind);
    return rowGo(h('tr', '', h('td', '', h('b', '', x.kind_name), h('div', 'ov-lg', x.name)), h('td', 'hs', run.robot), h('td', 'hs hm', run.label), h('td', 'sm hs', x.reading),
      h('td', '', h('div', 'ov-acts', askAi(run.pack), postBounty(ref)))),
    () => { location.href = x.replay ?? `data.html?c=${encodeURIComponent(run.id)}&q=${encodeURIComponent(x.id)}`; }, `Open ${x.name}`);
  }));
  page.replaceChildren(h('p', 'ov-note', `${rows.length} open. ${OPEN_SCOPE}`), h('table', '', h('thead', '', h('tr', '', h('th', '', 'Failure'), h('th', 'hs', 'Robot'), h('th', 'hs hm', 'Run'), h('th', 'hs', 'Reading'), h('th', 'n', 'Next step'))), body));
});
