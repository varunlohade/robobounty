import { el } from './dom.ts';
import type { ServerEvent } from './chat/live.ts';

const COLUMNS: [string, (r: any) => string][] = [
  ['Set', r => r.set], ['Worlds', r => String(r.n)], ['Passes', r => `${r.pass_a} to ${r.pass_b}`], ['Failures', r => `${r.fail_a} to ${r.fail_b}`],
  ['Better', r => String(r.better)], ['Worse', r => String(r.worse)], ['Same', r => String(r.same)], ['p, one-sided', r => String(r.p)],
];

// What fix.py found, in its own numbers. It never changes controller.py.
export class FixPage {
  readonly page = el('div', 'page page-text fix');
  private decision = el('div', 'fix-decision');

  constructor() {
    this.page.append(el('h2', '', 'No fix tried yet'), el('p', '', 'A fix can be tried after the campaign finds failures.'));
  }

  show(e: ServerEvent) {
    const title = el('h2', '', e.title);
    const tag = el('div', 'fix-tag', e.recorded ? 'Recorded result. No AI ran now.' : e.title);
    const parts: HTMLElement[] = [title, tag, el('p', '', e.source)];
    parts.push(el('h3', '', 'Conclusion'), el('p', 'fix-conclusion', e.conclusion));
    for (const c of e.caveats as string[]) parts.push(el('p', 'fix-caveat', c));
    for (const t of e.tables as { head: string; rows: any[] }[]) {
      parts.push(el('h3', '', t.head));
      const table = el('table', 'ab');
      const head = el('tr');
      for (const [name] of COLUMNS) head.append(el('th', '', name));
      table.append(head);
      for (const r of t.rows) {
        const row = el('tr');
        for (const [, cell] of COLUMNS) row.append(el('td', '', cell(r)));
        table.append(row);
      }
      parts.push(table);
    }
    if (e.failing_base != null) parts.push(el('p', '', `${e.failing_base} of the held-back worlds failed before the patch.`));
    if ((e.first_verdict as string[]).length) parts.push(el('p', '', `First test, rule result ${e.first_status}: ${(e.first_verdict as string[]).join('; ')}.`));
    if ((e.changed as unknown[]).length) {
      parts.push(el('h3', '', 'Before and after, by world'));
      const list = el('div', 'fix-changes');
      for (const c of e.changed as { world: string; before: string; after: string }[]) {
        const row = el('div', 'fix-change');
        row.append(el('span', '', c.world), el('span', 'fail', c.before), el('span', '', c.after));
        list.append(row);
      }
      parts.push(list);
    }
    const s = e.sandbox;
    parts.push(el('h3', '', 'Sandbox and validation'));
    parts.push(el('p', '', `Validation: ${(s.validation as string[]).join('; ')}. Sandbox limits hit: ${s.limits_hit}. Replay mismatches: ${s.replay_mismatch}. Held-back worlds shown to the AI: ${s.held_back_shown_to_ai}.`));
    parts.push(el('p', '', `${s.note} ${e.limits} Recorded on sim ${e.sim_recorded}, sim now ${e.sim_now}.`));
    this.decision.replaceChildren();
    parts.push(this.decision);
    this.page.replaceChildren(...parts);
  }

  decided(e: ServerEvent) {
    this.decision.replaceChildren(el('h3', '', e.accepted ? 'Accepted, session copy only' : 'Rejected'), el('p', '', e.text),
      el('p', '', `policy/highrise/controller.py ${e.real_sha}${e.copy_sha ? `. Session copy ${e.copy_sha}.` : '.'}`));
  }
}
