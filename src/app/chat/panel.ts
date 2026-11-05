import { el, icon } from '../dom.ts';
import type { ChatAction, ChatBackend, ChatEvent } from './backend.ts';

// A mono agent log: short tool results, the user's words highlighted, and a rounded input pinned at the bottom.
export class ChatPanel {
  readonly root = el('section', 'chat');
  private list = el('div', 'chat-list');
  private input = el('textarea');
  private sendBtn = el('button', 'send');
  private workingLine = el('div', 'working');
  private busy = false;
  private byId = new Map<string, HTMLElement>();

  constructor(private backend: ChatBackend, private openTab: (tab: 'worlds' | 'code') => void, contextLabel: string) {
    this.root.setAttribute('aria-label', 'Chat');
    this.list.setAttribute('role', 'log');
    this.workingLine.hidden = true;
    if (backend.notice) this.root.append(el('div', 'chat-notice', backend.notice));
    this.root.append(this.list, this.workingLine, this.buildInput(contextLabel));
    this.reset();
  }

  reset() {
    if (this.list.childElementCount && this.backend.reset) { this.backend.reset(); return; }
    this.list.replaceChildren();
    void this.play(this.backend.open(), true);
  }

  // Lets the app add its own steps to the log, such as the pictures of the built world.
  addEvent(event: ChatEvent) {
    this.add(event, true);
  }

  private buildInput(contextLabel: string): HTMLElement {
    const box = el('form', 'chat-input');
    this.input.rows = 2;
    this.input.placeholder = 'Describe the robot and where it works';
    this.input.setAttribute('aria-label', 'Message');
    this.input.addEventListener('input', () => this.fit());
    this.input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
    });
    this.sendBtn.type = 'submit';
    this.sendBtn.title = 'Send (Enter)';
    this.sendBtn.setAttribute('aria-label', 'Send');
    this.sendBtn.append(icon('send', true));
    const row = el('div', 'chat-input-row');
    row.append(el('span', '', contextLabel), this.sendBtn);
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
    if (this.backend.isStub) this.add({ type: 'user', text }, true);
    void this.sending(text);
  }

  private async sending(text: string) {
    this.busy = true;
    this.sendBtn.disabled = true;
    await this.play(this.backend.send(text), true);
    this.busy = false;
    this.sendBtn.disabled = false;
  }

  private async play(events: AsyncIterable<ChatEvent>, follow: boolean) {
    try {
      for await (const event of events) this.add(event, follow);
    } catch (err) {
      this.list.append(el('div', 'msg fail', `Chat error: ${String(err)}`));
    }
  }

  private add(event: ChatEvent, follow: boolean) {
    if (event.type === 'working') {
      this.workingLine.hidden = !event.text;
      this.workingLine.replaceChildren(el('span', '', event.text ?? ''), el('u'));
      return;
    }
    if (event.type === 'retire') {
      for (const b of this.list.querySelectorAll<HTMLButtonElement>('button[data-act="once"]')) b.disabled = true;
      return;
    }
    const node = this.render(event);
    const id = event.type === 'tool' ? event.id : null;
    const old = id ? this.byId.get(id) : null;
    if (old) old.replaceWith(node);
    else this.list.append(node);
    if (id) this.byId.set(id, node);
    if (follow) this.list.scrollTop = this.list.scrollHeight;
  }

  private button(action: ChatAction): HTMLButtonElement {
    const b = el('button', `tb${action.primary ? ' tb-primary' : ''}`, action.label);
    b.type = 'button';
    b.disabled = !!action.disabled;
    if (action.open) { const tab = action.open; b.addEventListener('click', () => this.openTab(tab)); }
    if (action.action) {
      if (!action.keep) b.dataset.act = 'once';
      b.addEventListener('click', () => {
        if (!action.keep) for (const other of b.parentElement!.querySelectorAll('button')) other.disabled = true;
        void this.backend.act?.(action);
      });
    }
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
        const row = el('div', 'tool');
        const head = el('div', 'tool-head');
        head.append(el('b', '', event.title));
        if (event.meta) head.append(el('span', 'tool-meta', event.meta));
        row.append(head, ...event.lines.map(l => el('div', 'tool-line', l)));
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
      case 'requirements': {
        const card = el('div', 'card');
        card.append(el('h4', '', 'Pass or fail, written before any run'));
        for (const r of event.rows) {
          const row = el('div', 'req-row');
          row.append(el('b', '', r.id), el('span', '', r.text), el('span', 'tool-meta', r.severity));
          card.append(row);
        }
        card.append(el('div', 'tool-line', event.note), el('div', 'tool-line', event.limits));
        return card;
      }
      case 'review': {
        const card = el('div', 'card review');
        card.append(el('h4', '', event.title));
        for (const s of event.sections) {
          const part = el('div', 'review-part');
          part.append(el('div', 'review-head', s.head), ...s.lines.map(l => el('div', 'tool-line', l)));
          card.append(part);
        }
        card.append(this.actionRow(event.actions));
        return card;
      }
      case 'views': {
        const box = el('div', 'tool');
        const head = el('div', 'tool-head');
        head.append(el('b', '', event.title));
        const pics = el('div', 'views');
        for (const image of event.images) {
          const fig = el('figure');
          const img = el('img');
          img.src = image.src;
          img.alt = image.label;
          fig.append(img, el('figcaption', '', image.label));
          pics.append(fig);
        }
        box.append(head, pics, el('div', 'tool-line', event.note));
        return box;
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
      default: throw new Error(`no drawing for chat event ${event.type}`);
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
