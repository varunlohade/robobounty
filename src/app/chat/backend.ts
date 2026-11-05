import type { Trial, WorldsData } from '../trial.ts';

export interface ChatAction { label: string; primary?: boolean; open?: 'worlds' | 'code'; disabled?: boolean }

export type ChatEvent =
  | { type: 'user'; text: string }
  | { type: 'text'; text: string; fail?: boolean }
  | { type: 'tool'; title: string; meta?: string; lines: string[]; open?: boolean }
  | { type: 'diff'; file: string; meta: string; lines: { kind: 'add' | 'del' | 'same'; text: string }[]; note: string }
  | { type: 'actions'; actions: ChatAction[]; note?: string }
  | { type: 'card'; title: string; body?: string; items?: string[]; actions?: ChatAction[]; note?: string }
  | { type: 'counts'; rows: { n: number; label: string; meta: string }[] };

// The one interface the chat panel talks to. The local run server replaces the stub behind it.
export interface ChatBackend {
  readonly isStub: boolean;
  readonly notice: string;
  open(): AsyncIterable<ChatEvent>;
  send(text: string): AsyncIterable<ChatEvent>;
}

const WORLD_DIFF_FIELDS = ['steady_wind_ms', 'gust_speed_ms', 'wetness', 'temperature_c', 'humidity_pct', 'dust_gm2', 'mullion_depth_m', 'suction_pa', 'seal_leak_mm2', 'pad_force_n'];

// Fixed words around real values: every number comes from the recorded trial and the recorded batch.
export class StubBackend implements ChatBackend {
  readonly isStub = true;
  readonly notice = 'Stub chat. No AI yet. The numbers are recorded data.';

  constructor(private trial: Trial, private worlds: WorldsData | null) {}

  async *open(): AsyncIterable<ChatEvent> {
    const { result, world, manifest } = this.trial;
    const lowest = Number(result.min_pressure_pa);
    yield { type: 'user', text: 'I am building a window-cleaning robot for towers in Dubai. Test it for what could go wrong there.' };
    yield { type: 'tool', title: 'Read robot model', meta: 'model.xml', lines: [`${manifest.nq} recorded joint values per frame`] };
    yield { type: 'tool', title: 'Built world', meta: 'world.json', lines: [`${String(world.area_width_m)} m by ${String(world.area_height_m)} m of glass, ${String(world.drop_below_roof_m)} m below the roof`] };
    yield {
      type: 'diff', file: 'world.json', meta: `+${WORLD_DIFF_FIELDS.filter(k => k in world).length}`,
      lines: WORLD_DIFF_FIELDS.filter(k => k in world).map(k => ({ kind: 'add' as const, text: `${k}: ${String(world[k])}` })),
      note: 'Real values of this world. Accept and Reject change nothing yet.',
    };
    yield {
      type: 'tool', title: 'Ran 1 test', meta: 'Simulated',
      lines: [`seed ${result.seed}`, `${result.steps} steps`, `${result.time_s} s simulated`],
    };
    yield result.passed
      ? { type: 'text', text: `It held for the whole run. Lowest suction ${(lowest / 1000).toFixed(2)} kPa. It cleaned ${(result.coverage * 100).toFixed(1)}% in ${result.time_s} s.` }
      : { type: 'text', fail: true, text: `It failed: ${result.failure}. It cleaned ${(result.coverage * 100).toFixed(1)}% before the run stopped at ${result.time_s} s.` };
    yield { type: 'actions', actions: [{ label: 'Test it once', disabled: true }, { label: 'Open the code', open: 'code' }], note: 'Run server not connected' };
    if (this.worlds) yield* this.batch(this.worlds);
  }

  private *batch(w: WorldsData): Iterable<ChatEvent> {
    const failed = w.worlds.filter(r => !r.passed);
    yield { type: 'tool', title: `Scenario agent: why ${w.total}`, meta: '1 step', lines: [w.count_reason], open: true };
    yield {
      type: 'card', title: `Tested on ${w.total} worlds`, body: `${failed.length} failed and ${w.worlds.length - failed.length} held. Same robot, same code in each.`,
      actions: [{ label: `See the ${w.total} worlds`, primary: true, open: 'worlds' }],
    };
    const kinds = new Map<string, Set<string>>();
    const counts = new Map<string, number>();
    for (const r of failed) {
      const k = r.failure ?? 'unknown';
      counts.set(k, (counts.get(k) ?? 0) + 1);
      kinds.set(k, (kinds.get(k) ?? new Set()).add(r.group));
    }
    yield {
      type: 'counts',
      rows: [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ n, label: k, meta: `${kinds.get(k)!.size} of ${w.groups.length} groups` })),
    };
    yield {
      type: 'card', title: 'Not tested', body: 'No physics for these here, so they get no pass.',
      items: w.not_tested.map(t => t.factor), actions: [{ label: 'Send to a bounty', disabled: true }], note: 'Not connected yet',
    };
  }

  async *send(text: string): AsyncIterable<ChatEvent> {
    yield { type: 'text', text: `Stub reply. No AI ran and nothing changed. You wrote:\n${text}` };
  }
}
