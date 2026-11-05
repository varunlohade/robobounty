import { el, icon } from '../dom.ts';
import type { ChatAction, ChatBackend, ChatEvent } from './backend.ts';

export class ChatPanel {
  readonly root = el('section', 'chat');
  private list = el('div', 'chat-list');
  private input = el('textarea');
  private sendBtn = el('button', 'send');
  private busy = false;

  constructor(private backend: ChatBackend, private openTab: (tab: 'worlds' | 'code') => void, contextLabel: string) {
    this.root.setAttribute('aria-label', 'Chat');
    this.list.setAttribute('role', 'log');
    this.root.append(el('div', 'chat-notice', backend.notice), this.list, this.buildInput(contextLabel));
    this.reset();
  }

  reset() {
    this.list.replaceChildren();
    void this.play(this.backend.open(), false);
  }

  private buildInput(contextLabel: string): HTMLElement {
    const box = el('form', 'chat-input');
    this.input.rows = 2;
    this.input.placeholder = 'Change the robot or the world';
    this.input.setAttribute('aria-label', 'Message');
    this.input.addEventListener('input', () => this.fit());
    this.input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
    });
    const agent = el('select', 'select');
    agent.setAttribute('aria-label', 'Agent');
    agent.append(el('option', '', this.backend.isStub ? 'Agent (stub)' : 'Agent'));
    this.sendBtn.type = 'submit';
    this.sendBtn.title = 'Send (Cmd+Enter)';
    this.sendBtn.setAttribute('aria-label', 'Send');
    this.sendBtn.append(icon('send', true));
    const row = el('div', 'chat-input-row');
    row.append(agent, el('span', '', contextLabel), this.sendBtn);
    box.append(this.input, row);
    box.addEventListener('submit', e => { e.preventDefault(); this.submit(); });
    return box;
  }

  private fit() {
    this.input.style.height = 'auto';
    this.input.style.height = `${this.input.scrollHeight}px`;
  }

  private submit() {
    const text = this.input.value;
    if (!text.trim() || this.busy) return;
    this.input.value = '';
    this.fit();
    this.add({ type: 'user', text }, true);
    void this.play(this.backend.send(text), true);
  }

  private async play(events: AsyncIterable<ChatEvent>, follow: boolean) {
    this.busy = true;
    this.sendBtn.disabled = true;
    try {
      for await (const event of events) this.add(event, follow);
    } catch (err) {
      this.list.append(el('div', 'msg fail', `Chat error: ${String(err)}`));
    }
    this.busy = false;
    this.sendBtn.disabled = false;
  }

  private add(event: ChatEvent, follow: boolean) {
    this.list.append(this.render(event));
    if (follow) this.list.scrollTop = this.list.scrollHeight;
  }

  private button(action: ChatAction): HTMLButtonElement {
    const b = el('button', `btn btn-large${action.primary ? ' btn-primary' : ''}`, action.label);
    b.type = 'button';
    b.disabled = !!action.disabled;
    if (action.open) { const tab = action.open; b.addEventListener('click', () => this.openTab(tab)); }
    return b;
  }

  private actionRow(actions: ChatAction[], note?: string): HTMLElement {
    const row = el('div', 'actions');
    row.append(...actions.map(a => this.button(a)));
    if (note) row.append(el('span', '', note));
    return row;
  }

  private render(event: ChatEvent): HTMLElement {
    switch (event.type) {
      case 'user': return el('div', 'msg msg-user', event.text);
      case 'text': return el('div', event.fail ? 'msg fail' : 'msg', event.text);
      case 'tool': {
        const row = el('details', 'tool');
        row.open = !!event.open;
        const summary = el('summary');
        summary.append(icon('chevron', true), el('b', '', event.title));
        if (event.meta) summary.append(el('span', 'tool-meta', event.meta));
        row.append(summary, ...event.lines.map(l => el('div', 'tool-line', l)));
        return row;
      }
      case 'actions': return this.actionRow(event.actions, event.note);
      case 'card': {
        const card = el('div', 'card');
        card.append(el('h4', '', event.title));
        if (event.body) card.append(el('div', '', event.body));
        if (event.items) {
          const ul = el('ul');
          ul.append(...event.items.map(i => el('li', '', i)));
          card.append(ul);
        }
        if (event.actions) card.append(this.actionRow(event.actions, event.note));
        return card;
      }
      case 'counts': {
        const box = el('div');
        for (const r of event.rows) {
          const row = el('div', 'count-row');
          row.append(el('span', 'n', String(r.n)), el('span', '', r.label), el('span', 'meta', r.meta));
          box.append(row);
        }
        return box;
      }
      case 'diff': return this.renderDiff(event);
    }
  }

  private renderDiff(event: Extract<ChatEvent, { type: 'diff' }>): HTMLElement {
    const box = el('div', 'diff');
    const head = el('div', 'diff-head');
    const note = el('div', 'diff-note', event.note);
    const accept = el('button', 'btn btn-primary', 'Accept');
    const reject = el('button', 'btn', 'Reject');
    accept.type = reject.type = 'button';
    const answer = (word: string) => {
      accept.disabled = reject.disabled = true;
      note.textContent = `${word}. This is a stub, so nothing changed.`;
    };
    accept.addEventListener('click', () => answer('Accepted'));
    reject.addEventListener('click', () => answer('Rejected'));
    const actions = el('div', 'diff-actions');
    actions.append(reject, accept);
    head.append(el('code', '', event.file), el('span', '', event.meta), actions);
    box.append(head);
    const mark = { add: '+ ', del: '- ', same: '  ' };
    const cls = { add: 'diff-add', del: 'diff-del', same: '' };
    for (const l of event.lines) box.append(el('div', `diff-line ${cls[l.kind]}`, mark[l.kind] + l.text));
    box.append(note);
    return box;
  }
}
