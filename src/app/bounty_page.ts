import { el } from './dom.ts';
import type { ChatAction } from './chat/backend.ts';
import type { ServerEvent } from './chat/live.ts';
import { WorldPanel, type WorldHooks, type WorldInfo } from './world_panel.ts';

const STEPS = ['Funded', 'Proposed', 'Dispute window', 'Finalized', 'Claim'];
const STEP_OF: Record<string, number> = { Pending: 2, Rejected: 1, Finalized: 3, Claimed: 4 };

interface Hooks extends WorldHooks { act(action: ChatAction): Promise<void>; submit(world: string, seed: string): Promise<string | null>; sampleWorld(): string | null }

// USDC has 6 decimals. The string keeps a whole token plain: 100, not 100.000000.
const usdc = (base: number, decimals: number) => `${(base / 10 ** decimals).toFixed(decimals).replace(/\.?0+$/, '')} USDC`;

// The draft, the tester's paste box and the ledger: local, or read from the chain. This page holds no key.
export class BountyPage {
  readonly page = el('div', 'page page-text bounty');
  private draft = el('div');
  private ledger = el('div', 'ledger');
  private tester = el('div');
  private verdicts = el('div');
  private area = el('textarea', 'world-paste');
  private seed = el('input', 'num');
  private runBtn = el('button', 'btn btn-large btn-primary', 'Run the gate');
  private timer = 0;
  private serverSkew = 0;
  private gate: ServerEvent['gate'] = null;
  private world: WorldPanel;

  constructor(private hooks: Hooks) {
    this.world = new WorldPanel(hooks);
    this.page.append(el('h2', '', 'No bounty yet'), el('p', '', 'Send what is not tested or not fixed to a bounty from the chat.'));
  }

  showDraft(e: ServerEvent) {
    this.gate = e.gate;
    const banner = el('div', 'ledger-label', e.label);
    const list = (head: string, rows: string[]) => {
      const box = el('div');
      box.append(el('h3', '', head));
      if (!rows.length) box.append(el('p', '', 'None.'));
      for (const r of rows) box.append(el('p', '', r));
      return box;
    };
    const limits = el('details', 'limits');
    limits.append(el('summary', '', `Company limits on ${Object.keys(e.limits).length} world fields`));
    for (const [name, [lo, hi]] of Object.entries(e.limits as Record<string, [number, number]>)) {
      const row = el('div', 'fact');
      row.append(el('span', '', name), el('span', '', `${lo} to ${hi}${(e.narrowed as string[]).includes(name) ? '' : ' (schema limits)'}`));
      limits.append(row);
    }
    const form = el('form', 'fund');
    const chain = e.chain as { bounty: { per_failure: number; available: number; dispute_window_s: number }; address: string; usdc: string; chain_id: number } | null;
    const field = (label: string, value: number, min: number) => {
      const input = el('input', 'num');
      input.type = 'number';
      input.value = String(value);
      input.min = String(min);
      input.step = '1';
      input.setAttribute('aria-label', label);
      const wrap = el('label', '', label);
      wrap.append(input);
      form.append(wrap);
      return input;
    };
    const cap = field('Cap, test units', e.defaults.cap, 1);
    const per = field('Per failure, test units', e.defaults.per_failure, 1);
    const window = field(`Dispute window, seconds (at least ${e.min_window})`, e.defaults.window, e.min_window);
    const fund = el('button', 'btn btn-large btn-primary', chain ? 'Use the bounty on chain' : 'Fund on the local ledger');
    fund.type = 'submit';
    form.append(fund);
    form.addEventListener('submit', ev => {
      ev.preventDefault();
      fund.disabled = true;
      void this.hooks.act({ label: 'fund', action: 'fund', value: { cap: Number(cap.value), per_failure: Number(per.value), window: Number(window.value) } as never });
    });
    if (chain) {
      for (const label of form.querySelectorAll('label')) label.hidden = true;
      form.prepend(el('p', '', `Contract ${chain.address}, chain ${chain.chain_id}, token ${chain.usdc}. The company funded it with the deploy script. Available: ${usdc(chain.bounty.available, 6)}. Per failure: ${usdc(chain.bounty.per_failure, 6)}.`));
    }
    this.draft.replaceChildren(
      el('h2', '', 'Bounty draft'), banner,
      el('p', '', chain ? 'A tester earns the per-failure amount for a new failure the gate accepts. The amounts move on this test chain, and they have no real value.' : 'A tester earns the per-failure amount for a new failure the gate accepts. The amounts are test units. No money moves.'),
      ...(e.arc_note ? [el('p', 'fail', e.arc_note)] : []),
      list('Not tested', (e.not_tested as { factor: string; reason: string }[]).map(t => `${t.factor}: ${t.reason}`)),
      list('Failures still open', (e.unresolved as { id: string; rule: string; severity: string; count: number }[]).map(u => `${u.id} ${u.rule}, ${u.severity}, ${u.count} world${u.count === 1 ? '' : 's'}`)),
      el('p', '', e.fix ?? 'No fix tried yet.'),
      limits, form,
    );
    this.buildTester(e);
    this.world.show(e.world);
    this.page.replaceChildren(this.draft, this.ledger, this.tester, this.verdicts);
  }

  private buildTester(e: ServerEvent) {
    this.area.rows = 8;
    this.area.spellcheck = false;
    this.area.placeholder = 'Paste a numeric world file (JSON)';
    this.area.setAttribute('aria-label', 'World file');
    this.seed.type = 'text';
    this.seed.value = '1';
    this.seed.setAttribute('aria-label', 'Seed');
    this.runBtn.type = 'button';
    this.runBtn.disabled = true;
    this.runBtn.addEventListener('click', () => void this.run());
    const sample = el('button', 'btn btn-large', 'Paste a failed world from this run');
    sample.type = 'button';
    sample.addEventListener('click', () => { const w = this.hooks.sampleWorld(); if (w) this.area.value = w; });
    const row = el('div', 'detail-actions');
    const seedLabel = el('label', '', 'Seed ');
    seedLabel.append(this.seed);
    row.append(sample, seedLabel, this.runBtn);
    const g = e.gate;
    this.tester.replaceChildren(
      el('h2', '', 'Tester'),
      el('p', '', `Paste a world file, up to ${g.max_world_bytes} bytes. gate.py runs it once, then ${g.reruns} times with hidden jitter. ${g.repeat_need} of ${g.reruns} must end in the same failure, and a world moved ${Math.round((1 - g.reference_keep) * 100)}% of the way back to nominal must pass.`),
      el('p', 'excluded-row', e.chain ? `Tester address ${e.tester}. The tester's key stays outside this app.` : `Tester address ${e.tester}. A local test value, with no key or wallet.`),
      this.world.root, this.area, row,
    );
  }

  private async run() {
    this.runBtn.disabled = true;
    const problem = await this.hooks.submit(this.area.value, this.seed.value.trim());
    if (problem) { this.verdicts.prepend(el('p', 'fail', problem)); this.runBtn.disabled = false; }
  }

  showWorld(info: WorldInfo) {
    this.world.show(info);
  }

  gateRunning(e: ServerEvent) {
    this.verdicts.prepend(el('p', 'gate-running', `Submission ${e.n}: the gate is running.`));
  }

  showVerdict(e: ServerEvent) {
    this.verdicts.querySelector('.gate-running')?.remove();
    const box = el('div', 'verdict');
    box.dataset.code = e.code;
    box.append(el('h3', e.accepted ? '' : 'fail', `Submission ${e.n}: ${e.accepted ? 'Accepted' : 'Rejected'} (${e.code})`), el('p', '', e.reason));
    if (e.repeat) box.append(el('p', '', `Repeats: ${e.repeat.same} of ${e.repeat.of} ended in ${e.repeat.failure}. The gate needs ${e.repeat.need}.`));
    if (e.reference_check) box.append(el('p', '', `Reference twin: ${e.reference_check.label}. ${e.reference_check.meaning}`));
    box.append(el('p', 'excluded-row', `${e.runs ?? 0} sim runs, ${e.wall} s. Simulated. Not checked: ${((e.not_checked ?? []) as string[]).join(' ')}`));
    this.verdicts.prepend(box);
    box.scrollIntoView({ block: 'center' });
    if (this.gate) this.runBtn.disabled = false;
  }

  showLedger(e: ServerEvent) {
    this.serverSkew = e.now * 1000 - Date.now();
    this.runBtn.disabled = false;
    clearInterval(this.timer);
    const b = e.bounty;
    const rows = Object.entries(e.failures as Record<string, any>);
    const onChain = e.chain_id !== undefined;
    const money = (n: number) => (onChain ? usdc(n, e.decimals) : String(n));
    const draw = () => {
      const now = (Date.now() + this.serverSkew) / 1000;
      const parts: HTMLElement[] = [el('h2', '', 'Ledger'), el('div', 'ledger-label', e.label),
        el('p', '', `Funded: ${onChain ? money(b.cap) : `${b.cap} test units`}. Available: ${money(b.available)}. Per failure: ${money(b.per_failure)}. Dispute window: ${b.dispute_window_s} s. Spec ${String(b.spec_hash).slice(0, 18)}.`)];
      if (onChain) {
        const balances = el('div', 'chain-balances');
        for (const [who, amount] of Object.entries(e.balances as Record<string, number>)) {
          const row = el('div', 'fact');
          row.append(el('span', '', `Balance, ${who}`), el('span', '', money(amount)));
          balances.append(row);
        }
        parts.push(balances);
        for (const fp of e.waiting as string[]) if (!(fp in e.failures)) parts.push(el('p', '', `Failure ${fp.slice(0, 18)}: waiting for the resolver.`));
      }
      if (!rows.length) parts.push(this.track(0));
      for (const [fp, f] of rows) {
        const open = f.status === 'Pending' && now < f.dispute_ends_at;
        const step = f.status === 'Pending' && !open ? 2 : STEP_OF[f.status];
        parts.push(this.track(step), el('p', '', `Failure ${fp.slice(0, 18)}: ${f.status === 'Pending' ? (open ? `dispute window open, ${Math.ceil(f.dispute_ends_at - now)} s left` : 'dispute window closed') : f.status}. Amount ${money(f.amount)}.${f.tx ? ` Propose tx ${f.tx}.` : ''}`));
        if (onChain) {
          if (f.status === 'Pending') parts.push(el('p', 'excluded-row', open ? 'The arbiter can reject with its own key until the window ends.' : 'The resolver finalizes this next.'));
          if (f.status === 'Finalized') parts.push(el('p', 'excluded-row', 'Only the tester can claim, with the tester key, from outside this app: policy/sponsors/resolver.py claim.'));
          continue;
        }
        const actions = el('div', 'detail-actions');
        const button = (label: string, action: string) => {
          const x = el('button', 'btn btn-large', label);
          x.type = 'button';
          x.dataset.ledger = action;
          x.addEventListener('click', () => { x.disabled = true; void this.hooks.act({ label, action, value: fp as never }); });
          actions.append(x);
        };
        if (open) button('Arbiter rejects', 'ledger_reject');
        if (f.status === 'Pending' && !open) button('Finalize', 'ledger_finalize');
        if (f.status === 'Finalized') button('Claim as the tester', 'ledger_claim');
        parts.push(actions);
      }
      this.ledger.replaceChildren(...parts);
      if (!rows.some(([, f]) => f.status === 'Pending' && now < f.dispute_ends_at + 1)) clearInterval(this.timer);
    };
    draw();
    this.timer = window.setInterval(draw, 1000);
  }

  private track(at: number): HTMLElement {
    const line = el('div', 'pipeline ledger-track');
    STEPS.forEach((name, i) => line.append(el('div', `stage ${i < at ? 'stage-done' : i === at ? 'stage-now' : 'stage-todo'}`, name)));
    return line;
  }
}
