// The chat backend for the Recorded run: the finished Dubai campaign from public/trials/worlds.json. No run server, no AI, no simulation.
import type { ChatAction, ChatBackend, ChatEvent } from './backend.ts';
import type { ServerEvent } from './live.ts';
import type { WorldsData } from '../trial.ts';

export class RecordedBackend implements ChatBackend {
  readonly isStub = false;
  readonly notice = 'Recorded run. No AI and no simulation run now.';
  readonly id = 'recorded';
  private later: ChatEvent[] = [];
  private wake: (() => void) | null = null;

  constructor(private onEvent: (e: ServerEvent) => void | Promise<void>, private data: WorldsData) {}

  trialBase(tid: string) {
    return `/trials/${encodeURIComponent(tid)}`;
  }

  async *open(): AsyncIterable<ChatEvent> {
    const d = this.data;
    const run = d.worlds.filter(w => w.kind !== 'elements');
    const flaky = run.filter(w => w.flaky);
    const failed = run.filter(w => !w.passed && w.failure && !w.flaky);
    const holds = run.filter(w => !w.passed && !w.failure);
    const passed = run.filter(w => w.passed);
    const replays = d.worlds.filter(w => w.trial);
    yield { type: 'user', text: d.chat };
    yield { type: 'text', text: `Recorded run: campaign ${d.campaign}, ${d.total} worlds, sim ${d.sim_sha256.slice(0, 8)}. These results load from a file.` };
    yield { type: 'requirements', rows: d.requirements, note: 'Written before the campaign ran.', limits: 'In this simulation only. The physics is uncalibrated.' };
    await this.onEvent({ type: 'sim', sha: d.sim_sha256, now: d.sim_sha256 });
    await this.onEvent({ type: 'plan', total: d.total, groups: d.groups, not_tested: d.not_tested, worlds: d.worlds });
    for (const w of d.worlds) await this.onEvent({ type: 'result', ...w });
    await this.onEvent({ type: 'fix', recorded: true, ...d.fix });
    await this.onEvent({ type: 'chapter', index: 4, note: 'Recorded run' });
    await this.onEvent({ type: 'failures', ...d.failures });
    await this.onEvent({
      type: 'report', recorded: true, seconds: d.campaign_seconds, safe_holds: holds.length, diverged: d.failures.diverged.length, fixes: d.fix_summary, sim_recorded: d.sim_sha256,
      numbers: [{ n: run.length, label: 'worlds run' }, { n: d.failures.types.length, label: 'failure types' }, { n: failed.length, label: 'worlds failed' }, { n: flaky.length, label: 'flaky, excluded' },
        { n: d.controls.passed, label: `of ${d.controls.n} normal runs passed` }, { n: d.not_tested.length, label: 'not tested' }],
    });
    await this.onEvent({ type: 'pipeline', stages: ['queued', 'running', 'reproducing', 'diagnosing', 'fixing', 'validating', 'report'].map(name => ({ name, state: 'done', note: null })) });
    yield { type: 'tool', title: 'campaign', meta: `${d.campaign_seconds} s when recorded`, lines: [JSON.stringify({ failed: failed.length, stopped_and_held: holds.length, flaky_excluded: flaky.length, passed: passed.length, controls: `${d.controls.passed}/${d.controls.n}` })] };
    yield { type: 'tool', title: 'fix_report', meta: 'Recorded result', lines: [d.fix_log] };
    yield { type: 'text', text: d.fix.plain };
    yield { type: 'diff', file: 'policy/highrise/controller.py', meta: 'not applied', lines: d.fix_diff, note: 'Not applied. controller.py does not change.', readonly: true };
    yield { type: 'card', title: 'Replays', body: 'Each one repeated when run again. Flaky worlds have no replay here.', actions: replays.map(w => ({ label: `${w.name}: ${w.failure ?? 'passed'}`, action: 'replay', value: w.index as number, keep: true })) };
    while (true) {
      while (this.later.length) yield this.later.shift()!;
      await new Promise<void>(r => { this.wake = r; });
    }
  }

  async *send(): AsyncIterable<ChatEvent> {
    yield { type: 'text', text: 'This is a recorded run, so it reads no new brief. Use Live run for that.' };
  }

  async act(action: ChatAction) {
    const world = this.data.worlds.find(w => w.index === action.value);
    if (action.action === 'replay' && world?.trial) await this.onEvent({ type: 'trial', tid: world.trial, open: true });
    else this.later.push({ type: 'text', text: 'This recorded run has no replay for that.' });
    this.wake?.();
  }

  async submit(): Promise<string | null> {
    return 'A recorded run takes no bounty. Use Live run for that.';
  }

  reset() {
    location.reload();
  }
}
