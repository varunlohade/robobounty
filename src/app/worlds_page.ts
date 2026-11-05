import { el } from './dom.ts';
import { fmtTime } from './world_page.ts';
import type { WorldRun, WorldsData } from './trial.ts';

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export interface PlannedWorld { name: string; group: string; reason: string; index?: number; held?: boolean }
export interface WorldsPlan {
  groups: { name: string; reason: string }[];
  not_tested: { factor: string; reason: string; source: string }[];
  worlds: PlannedWorld[];
}
export interface FailureType {
  id: string; rule: string; requirement: string | null; severity: string; count: number; worst: number; worst_name: string;
  worst_measure: string; worst_value: number; code: string | null; code_line: string | null; worlds: number[];
}
export interface Failures { types: FailureType[]; known: boolean; other: { type: string; count: number }[]; excluded: { index: number; name: string; why: string }[]; diverged: { index: number; name: string }[]; limits: string }
export interface Stage { name: string; state: 'todo' | 'now' | 'done' | 'off'; note: string | null }

function drawThumb(run: WorldRun): HTMLCanvasElement {
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

// Worlds with scene elements run and show, but stay out of the headline numbers, the same as in campaign.py and diagnose.py.
const apart = (r: WorldRun) => r.kind === 'elements';
const failedRun = (r: WorldRun) => !r.passed && !!r.failure && r.failure !== 'sim_diverged';

// One view of a batch. Squares start empty and fill in as results arrive. Recorded batches pass all their results at once.
export class WorldsPage {
  readonly page = el('div', 'page worlds');
  private heading = el('h1');
  private sub = el('p');
  private pipeline = el('div', 'pipeline');
  private gridHost = el('div');
  private mapHost = el('div', 'map-host');
  private failuresHost = el('div', 'failures');
  private detail = el('div');
  private notTested = el('div', 'not-tested');
  private toggle = el('button', 'btn btn-large', 'Show the map');
  private cells = new Map<string, { button: HTMLButtonElement; count: HTMLElement; group: string }>();
  private planned: PlannedWorld[] = [];
  private runs = new Map<string, WorldRun>();
  private colour = new Map<string, number>();
  private excluded = new Set<string>();
  private selected: string | null = null;
  private showMap = false;

  constructor(private onReplay: (run: WorldRun) => void, private onCounts: (text: string) => void = () => {}) {
    const head = el('div', 'worlds-head');
    head.append(this.heading, this.sub);
    const bar = el('div', 'map-bar');
    this.toggle.type = 'button';
    this.toggle.hidden = true;
    this.toggle.addEventListener('click', () => this.setMap(!this.showMap));
    bar.append(this.toggle);
    const foot = el('div', 'worlds-foot');
    foot.append(this.detail, this.notTested);
    this.page.append(this.pipeline, head, bar, this.gridHost, this.mapHost, this.failuresHost, foot);
    this.clear();
  }

  clear() {
    this.planned = [];
    this.runs.clear();
    this.colour.clear();
    this.excluded.clear();
    this.cells.clear();
    this.selected = null;
    this.setMap(false);
    this.toggle.hidden = true;
    this.heading.textContent = 'No worlds yet';
    this.sub.textContent = 'The scenario agent proposes them after the normal run.';
    this.pipeline.replaceChildren();
    this.gridHost.replaceChildren();
    this.mapHost.replaceChildren();
    this.failuresHost.replaceChildren();
    this.detail.replaceChildren();
    this.notTested.replaceChildren();
    this.onCounts('');
  }

  setPlan(plan: WorldsPlan) {
    this.clear();
    this.planned = plan.worlds;
    for (const group of plan.groups) {
      const row = el('div', 'group');
      const cells = el('div', 'cells');
      const count = el('div', 'group-count');
      for (const world of plan.worlds.filter(w => w.group === group.name)) {
        const b = el('button', world.held ? 'cell cell-held' : 'cell cell-empty');
        b.type = 'button';
        b.title = world.held ? `${world.name}: held back to check a fix` : `${world.name}: not tested yet`;
        b.setAttribute('aria-label', b.title);
        b.addEventListener('click', () => this.select(world.name));
        this.cells.set(world.name, { button: b, count, group: group.name });
        cells.append(b);
      }
      const name = el('h3', '', group.name);
      name.title = group.reason;
      row.append(name, cells, count);
      this.gridHost.append(row);
    }
    if (plan.not_tested.length) {
      this.notTested.append(el('h2', '', 'Not tested'));
      for (const t of plan.not_tested) {
        const p = el('p');
        p.append(el('b', '', `${t.factor}. `), document.createTextNode(t.reason));
        this.notTested.append(p);
      }
    }
    this.refresh();
  }

  addResult(run: WorldRun) {
    this.runs.set(run.name, run);
    const cell = this.cells.get(run.name);
    if (!cell) return;
    cell.button.className = apart(run) ? 'cell cell-excluded' : failedRun(run) ? 'cell cell-fail' : run.failure === 'sim_diverged' ? 'cell cell-excluded' : 'cell';
    if (apart(run)) cell.button.dataset.kind = 'elements';
    const said = run.passed ? 'passed' : run.failure ?? run.outcome ?? 'unknown';
    cell.button.title = `${run.name}: ${said}`;
    cell.button.setAttribute('aria-label', cell.button.title);
    cell.button.replaceChildren(drawThumb(run));
    this.refresh();
    if (!run.passed && !this.selected) this.select(run.name);
  }

  setPipeline(stages: Stage[]) {
    this.pipeline.replaceChildren(...stages.map(s => {
      const item = el('div', `stage stage-${s.state}`);
      item.append(el('span', '', s.name));
      if (s.note) item.append(el('span', 'stage-note', s.note));
      return item;
    }));
  }

  setFailures(f: Failures) {
    this.colour.clear();
    f.types.forEach((t, i) => t.worlds.forEach(index => {
      const w = this.planned.find(p => p.index === index);
      if (w) this.colour.set(w.name, i);
    }));
    this.excluded = new Set([...f.excluded, ...f.diverged].map(e => e.name));
    for (const name of this.excluded) {
      const c = this.cells.get(name);
      if (c) c.button.className = 'cell cell-excluded';
    }
    this.failuresHost.replaceChildren();
    if (f.types.length) this.failuresHost.append(el('h2', '', 'Failure types'));
    if (!f.known) this.failuresHost.append(el('p', 'excluded-row', 'The diagnosis step failed, so failure types and code lines are unknown.'));
    if (f.other.length) this.failuresHost.append(el('p', 'excluded-row', `Stopped and held on, not counted as failures: ${f.other.map(o => `${o.type} ${o.count}`).join(', ')}.`));
    f.types.forEach((t, i) => {
      const row = el('button', 'failure-row');
      row.type = 'button';
      const swatch = el('span', 'swatch');
      swatch.style.background = `var(--f${Math.min(i + 1, 5)})`;
      row.append(swatch, el('b', '', `${t.id} ${t.rule}`), el('span', 'sev', t.severity), el('span', '', `${t.count} world${t.count === 1 ? '' : 's'}`),
        el('span', '', `worst ${t.worst_name}, ${t.worst_measure} ${t.worst_value}`), el('code', '', t.code_line ?? 'code line unknown'));
      row.title = t.requirement ? `Breaks ${t.requirement}` : 'Requirement unknown';
      row.addEventListener('click', () => this.select(t.worst_name));
      this.failuresHost.append(row);
    });
    if (f.excluded.length || f.diverged.length) {
      this.failuresHost.append(el('h2', '', 'Excluded'));
      for (const e of f.excluded) this.failuresHost.append(el('p', 'excluded-row', `${e.name}: ${e.why}`));
      for (const e of f.diverged) this.failuresHost.append(el('p', 'excluded-row', `${e.name}: the simulation diverged numerically, so it says nothing about the robot.`));
    }
    if (f.types.length) this.failuresHost.append(el('p', 'excluded-row', f.limits));
    this.drawMap(f.types);
    this.toggle.hidden = false;
    this.setMap(true);
    this.refresh();
  }

  private setMap(on: boolean) {
    this.showMap = on;
    this.gridHost.hidden = on;
    this.mapHost.hidden = !on;
    this.toggle.textContent = on ? 'Show the glass' : 'Show the map';
  }

  private drawMap(types: FailureType[]) {
    const grid = el('div', 'map');
    for (const w of this.planned) {
      const run = this.runs.get(w.name);
      const c = this.colour.get(w.name);
      const square = el('button', 'map-cell');
      square.type = 'button';
      if (c !== undefined) square.style.background = `var(--f${Math.min(c + 1, 5)})`;
      else if (w.held) square.classList.add('map-held');
      else if (this.excluded.has(w.name) || (run && apart(run))) square.classList.add('map-excluded');
      else if (run) square.classList.add('map-pass');
      square.title = `${w.name}: ${c !== undefined ? types[c].rule : w.held ? 'held back' : this.excluded.has(w.name) ? 'excluded' : run && apart(run) ? 'scene elements, not counted' : run ? 'no failure' : 'not tested yet'}`;
      square.setAttribute('aria-label', square.title);
      square.addEventListener('click', () => this.select(w.name));
      grid.append(square);
    }
    const legend = el('div', 'legend');
    types.forEach((t, i) => {
      const item = el('span');
      const swatch = el('i', 'swatch');
      swatch.style.background = `var(--f${Math.min(i + 1, 5)})`;
      item.append(swatch, document.createTextNode(`${t.id} ${t.rule} ${t.count}`));
      legend.append(item);
    });
    for (const [cls, label] of [['map-pass', 'no failure'], ['map-excluded', 'excluded'], ['map-held', 'held back'], ['', 'not tested yet']]) {
      const item = el('span');
      item.append(el('i', `swatch map-cell ${cls}`), document.createTextNode(label));
      legend.append(item);
    }
    this.mapHost.replaceChildren(grid, legend);
  }

  private refresh() {
    const all = [...this.runs.values()];
    const runs = all.filter(r => !apart(r));
    const failed = runs.filter(r => failedRun(r) && !this.excluded.has(r.name)).length;
    const held = this.planned.filter(w => w.held).length;
    const waiting = this.planned.length - all.length - held;
    this.heading.textContent = runs.length ? `${failed} of ${runs.length} tested worlds failed` : `${this.planned.length} worlds proposed`;
    const notes = ['Simulated.'];
    if (held) notes.push(`${held} held back (bright dashes).`);
    if (waiting > 0) notes.push(`${waiting} not tested yet.`);
    if (all.length > runs.length) notes.push(`${all.length - runs.length} with scene elements, not counted.`);
    this.sub.textContent = notes.join(' ');
    this.onCounts(runs.length ? `${failed} failed, ${runs.length - failed - this.excluded.size} no failure, ${waiting > 0 ? waiting : 0} not tested yet` : '');
    for (const [name, c] of this.cells) {
      const same = [...this.cells].filter(([, v]) => v.group === c.group).map(([n]) => n);
      const ran = same.map(n => this.runs.get(n)).filter((r): r is WorldRun => !!r);
      const done = ran.filter(r => !apart(r));
      const bad = done.filter(r => failedRun(r) && !this.excluded.has(r.name)).length;
      c.count.className = bad ? 'group-count fail' : 'group-count';
      c.count.textContent = done.length ? `${bad} of ${done.length}` : ran.length ? 'Not counted' : 'Not tested yet';
      void name;
    }
  }

  private select(name: string) {
    this.selected = name;
    for (const [n, c] of this.cells) c.button.setAttribute('aria-pressed', String(n === name));
    const world = this.planned.find(w => w.name === name);
    const run = this.runs.get(name);
    if (!world) return;
    if (!run) {
      this.detail.replaceChildren(el('h2', '', `${world.group}, ${name}`), el('p', 'detail-sub', world.held ? 'Held back to check a fix. It has not run.' : 'Not tested yet.'), el('p', 'detail-sub', world.reason));
      return;
    }
    const flaky = this.excluded.has(name);
    const title = el('h2', failedRun(run) && !flaky ? 'fail' : '', `${run.group}, ${run.name}`);
    const note = apart(run) ? 'Scene elements: not counted in the headline numbers. ' : '';
    const summary = note + (run.passed ? 'Passed' : !run.failure ? `Stopped and held on: ${run.outcome ?? 'unknown'}` : flaky ? `Excluded: ${run.failure}` : `Failed: ${run.failure}`);
    const actions = el('div', 'detail-actions');
    const replay = el('button', 'btn btn-large', 'Replay the recorded run');
    replay.type = 'button';
    replay.addEventListener('click', () => this.onReplay(run));
    actions.append(replay);
    const events = Object.entries(run.fired).sort((a, b) => a[1].t - b[1].t).map(([rule, hit]) => {
      const row = el('div', 'event');
      row.append(el('span', '', fmtTime(hit.t)), el('span', '', `${rule}, value ${hit.value}`));
      return row;
    });
    this.detail.replaceChildren(
      title,
      el('p', 'detail-sub', `${summary}. Seed ${run.seed}. Cleaned ${(run.coverage * 100).toFixed(1)}% in ${run.time_s} s. Lowest suction ${(run.min_pressure_pa / 1000).toFixed(2)} kPa.`),
      el('p', 'detail-sub', world.reason),
      actions,
      ...events,
    );
  }
}

// A finished recorded batch, from public/trials/worlds.json.
export function worldsPage(data: WorldsData | null) {
  const view = new WorldsPage(run => { if (run.trial) location.search = `?trial=${encodeURIComponent(run.trial)}`; });
  if (!data) return view.page;
  view.setPlan({ groups: data.groups, not_tested: data.not_tested, worlds: data.worlds });
  for (const w of data.worlds) view.addResult(w);
  return view.page;
}
