import { el } from './dom.ts';
import { fmtTime } from './world_page.ts';
import type { WorldRun, WorldsData } from './trial.ts';

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function thumbnail(run: WorldRun): HTMLCanvasElement {
  const rows = run.thumb, nz = rows.length, nx = rows[0].length;
  const scale = 4;
  const c = el('canvas');
  c.width = nx * scale;
  c.height = nz * scale;
  const g = c.getContext('2d')!;
  g.fillStyle = token('--cell-held');
  g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = token('--cell-dust');
  rows.forEach((row, iz) => {
    for (let ix = 0; ix < nx; ix++) if (row[ix] === '1') g.fillRect(ix * scale, (nz - 1 - iz) * scale, scale, scale);
  });
  const x = Math.max(0, Math.min(1, run.end[0])), z = Math.max(0, Math.min(1, run.end[1]));
  g.fillStyle = token(run.passed ? '--cell-robot' : '--fail');
  g.fillRect(x * c.width - 6, (1 - z) * c.height - 6, 12, 12);
  return c;
}

export function worldsPage(data: WorldsData | null) {
  const page = el('div', 'page worlds');
  if (!data) {
    page.classList.remove('worlds');
    page.classList.add('page-text');
    page.append(el('h2', '', 'No recorded batch'), el('p', '', 'This tab shows no worlds and no numbers until a batch exists.'));
    return page;
  }
  const failed = data.worlds.filter(w => !w.passed).length;
  const head = el('div', 'worlds-head');
  head.append(el('h1', '', `${failed} of ${data.worlds.length} tested worlds failed`), el('p', '', 'Simulated. Each square shows the glass at the end of one run.'));
  page.append(head);

  const detail = el('div');
  const buttons: HTMLButtonElement[] = [];
  const select = (run: WorldRun, button: HTMLButtonElement) => {
    for (const b of buttons) b.setAttribute('aria-pressed', String(b === button));
    const title = el('h2', run.passed ? '' : 'fail', `${run.group}, ${run.name}`);
    const summary = run.passed ? 'Held' : `Failed: ${run.failure}`;
    const actions = el('div', 'detail-actions');
    const replay = el('button', 'btn btn-large', 'Replay the recorded run');
    replay.type = 'button';
    replay.disabled = !run.trial;
    if (run.trial) { const id = run.trial; replay.addEventListener('click', () => { location.search = `?trial=${encodeURIComponent(id)}`; }); }
    actions.append(replay);
    if (!run.trial) actions.append(el('span', '', 'Replay not exported for this world'));
    const events = Object.entries(run.fired).sort((a, b) => a[1].t - b[1].t).map(([rule, hit]) => {
      const row = el('div', 'event');
      row.append(el('span', '', fmtTime(hit.t)), el('span', '', `${rule}, value ${hit.value}`));
      return row;
    });
    detail.replaceChildren(
      title,
      el('p', 'detail-sub', `${summary}. Seed ${run.seed}. Cleaned ${(run.coverage * 100).toFixed(1)}% in ${run.time_s} s. Lowest suction ${(run.min_pressure_pa / 1000).toFixed(2)} kPa.`),
      el('p', 'detail-sub', run.reason),
      actions,
      ...events,
    );
  };

  let first: [WorldRun, HTMLButtonElement] | null = null;
  for (const group of data.groups) {
    const runs = data.worlds.filter(w => w.group === group.name);
    const row = el('div', 'group');
    const cells = el('div', 'cells');
    for (const run of runs) {
      const b = el('button', run.passed ? 'cell' : 'cell cell-fail');
      b.type = 'button';
      b.title = `${run.name}: ${run.passed ? 'held' : run.failure}`;
      b.setAttribute('aria-label', b.title);
      b.append(thumbnail(run));
      b.addEventListener('click', () => select(run, b));
      buttons.push(b);
      cells.append(b);
      if (!run.passed && (!first || (!first[0].trial && run.trial))) first = [run, b];
    }
    const bad = runs.filter(r => !r.passed).length;
    row.append(el('h3', '', group.name), cells, el('div', bad ? 'group-count fail' : 'group-count', `${bad} of ${runs.length}`));
    page.append(row);
  }

  const foot = el('div', 'worlds-foot');
  const notTested = el('div', 'not-tested');
  notTested.append(el('h2', '', 'Not tested'));
  for (const t of data.not_tested) {
    const p = el('p');
    p.append(el('b', '', `${t.factor}. `), document.createTextNode(t.reason));
    notTested.append(p);
  }
  foot.append(detail, notTested);
  page.append(foot);
  const pick = first as [WorldRun, HTMLButtonElement] | null;
  if (pick) select(pick[0], pick[1]);
  return page;
}
