import { el } from './dom.ts';

export interface WorldInfo { on: boolean; label: string; mock: boolean; missing: string[]; verified?: boolean; used?: number; cap?: number }
interface Reply { ok: boolean; body: any }
export interface WorldHooks { worldContext(): Promise<Reply>; worldVerify(result: unknown): Promise<Reply> }

// World ID for the tester: off, ready, waiting, verified, rejected or cancelled. The server signs each request and checks each proof.
export class WorldPanel {
  readonly root = el('div', 'world-id');
  private info: WorldInfo | null = null;
  private note = el('p');
  private cancel: AbortController | null = null;

  constructor(private hooks: WorldHooks) {}

  show(info: WorldInfo) {
    this.info = info;
    this.root.dataset.state = !info.on ? 'off' : info.verified ? 'verified' : 'ready';
    const parts: HTMLElement[] = [el('div', 'ledger-label', info.label)];
    if (!info.on) {
      parts.push(el('p', 'excluded-row', 'No proof of a unique human is checked. The per-human cap does not apply here.'));
    } else if (info.verified) {
      parts.push(el('p', '', `Verified human for this wallet. Submissions used: ${info.used} of ${info.cap}.`));
    } else {
      parts.push(el('p', '', `The gate needs one verified human per wallet. The cap is ${info.cap} submissions a bounty.`), this.actions());
    }
    this.note.textContent = '';
    this.note.className = '';
    parts.push(this.note);
    this.root.replaceChildren(...parts);
  }

  private actions(): HTMLElement {
    const row = el('div', 'detail-actions');
    const button = (label: string, run: () => Promise<void>, primary = false) => {
      const b = el('button', `btn btn-large${primary ? ' btn-primary' : ''}`, label);
      b.type = 'button';
      b.addEventListener('click', () => { void run(); });
      row.append(b);
    };
    if (this.info?.mock) {
      button('Mock World App: approve', () => this.start('approve'), true);
      button('Mock World App: reject', () => this.start('reject'));
    } else {
      button('Verify with World ID', () => this.start(null), true);
    }
    return row;
  }

  private say(text: string, fail: boolean, state?: string) {
    this.note.textContent = text;
    this.note.className = fail ? 'fail' : '';
    if (state) this.root.dataset.state = state;
  }

  private async start(mockOutcome: 'approve' | 'reject' | null) {
    this.say('Asking the server to sign this request.', false, 'waiting');
    const ctx = await this.hooks.worldContext();
    if (!ctx.ok) { this.say(ctx.body.words ?? 'The server would not sign this request.', true, 'rejected'); return; }
    const done = ctx.body.mock_world_app ? await this.mockApp(ctx.body, mockOutcome ?? 'approve') : await this.realApp(ctx.body);
    if (!done.success) { this.say(`World ID did not finish (${done.error}). Nothing was stored. You can try again.`, true, 'cancelled'); return; }
    const reply = await this.hooks.worldVerify(done.result);
    if (reply.ok) { this.say('Verified.', false, 'verified'); return; }
    this.root.dataset.code = reply.body.code ?? '';
    this.say(reply.body.words ?? 'The server refused this proof.', true, 'rejected');
  }

  // A mock stands in for the phone only when the server's verify URL is on this machine. See world_id.py.
  private async mockApp(ctx: any, outcome: string) {
    const res = await fetch(ctx.mock_world_app, { method: 'POST', body: JSON.stringify({ outcome, action: ctx.action, nonce: ctx.rp_context.nonce, environment: ctx.environment, signal_hash: ctx.mock_signal_hash }) });
    return res.json();
  }

  private async realApp(ctx: any): Promise<{ success: boolean; result?: unknown; error?: string }> {
    try {
      const { IDKit, proofOfHuman } = await import('@worldcoin/idkit-core');
      const request = await IDKit.request({ app_id: ctx.app_id, action: ctx.action, rp_context: ctx.rp_context, allow_legacy_proofs: ctx.allow_legacy_proofs, environment: ctx.environment }).preset(proofOfHuman({ signal: ctx.signal }));
      this.cancel = new AbortController();
      const link = el('a', '', 'Open World App');
      link.href = request.connectorURI;
      link.target = '_blank';
      link.rel = 'noopener';
      const stop = el('button', 'btn btn-large', 'Cancel');
      stop.type = 'button';
      stop.addEventListener('click', () => this.cancel?.abort());
      this.note.replaceChildren('Scan or open this in World App: ', link, ' ', stop);
      this.note.className = '';
      const done = await request.pollUntilCompletion({ signal: this.cancel.signal });
      return done.success ? { success: true, result: done.result } : { success: false, error: String(done.error) };
    } catch {
      return { success: false, error: this.cancel?.signal.aborted ? 'cancelled' : 'widget_failed' };
    }
  }
}
