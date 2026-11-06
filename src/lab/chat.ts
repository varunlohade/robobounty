import { el, icon } from '../app/dom.ts';
import type { ChatAction, ChatEvent } from '../app/chat/backend.ts';
import type { LiveBackend } from '../app/chat/live.ts';

// Server tool titles the chat shows, in plain words. Any other title stays hidden.
const STEP_WORDS: Record<string, string> = {
  read_message: 'Read your message',
  plan_world: 'Planned the change',
  build_world: 'Built the world',
  change_world: 'Changed the world',
  run_trial: 'Ran one test',
};
const NOT_DONE = /^(failed|rejected|refused)/;
// The server would start the campaign on these words. The lab stops at one run, so they stay here.
const CONFIRM = new Set(['yes', 'y', 'yep', 'ok', 'okay', 'looks right', 'looks good', 'it looks right', 'correct']);

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export class LabChat {
  readonly root = el('section', 'chat');
  // User messages, oldest first. The page takes its name from them.
  readonly said: string[] = [];
  private log = el('div', 'chat-log');
  private list = el('div', 'chat-list');
  private live = el('div', 'chat-step chat-live');
  private input = el('textarea', 'chat-input');
  private send = el('button', 'chat-send');
  private busy = false;
  private hasWorld = false;
  private timer = 0;

  constructor(private backend: LiveBackend) {
    const head = el('div', 'chat-head');
    const fresh = el('button', 'chat-new', 'New chat');
    fresh.type = 'button';
    fresh.addEventListener('click', () => backend.reset());
    head.append(el('span', '', 'Chat'), fresh);
    this.live.hidden = true;
    this.log.setAttribute('role', 'log');
    this.log.append(this.list, this.live);

    const box = el('form', 'chat-box');
    this.input.placeholder = 'Describe your robot and where it works';
    this.input.setAttribute('aria-label', 'Message');
    this.input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
    });
    const foot = el('div', 'chat-foot');
    this.send.type = 'submit';
    this.send.setAttribute('aria-label', 'Send');
    this.send.append(icon('send', true));
    foot.append(el('span', '', 'Agent'), this.send);
    box.append(this.input, foot);
    box.addEventListener('submit', e => { e.preventDefault(); this.submit(); });
    this.root.append(head, this.log, box);
  }

  async start() {
    try {
      for await (const event of this.backend.open()) this.add(event);
    } catch (err) {
      this.note(`Lost the run server: ${String(err)}`, true);
    }
  }

  worldReady() {
    this.hasWorld = true;
    this.input.placeholder = 'Ask for a change to the world';
  }

  jobDone() {
    this.setBusy(false);
  }

  note(text: string, fail = false) {
    this.append(el('div', fail ? 'chat-agent chat-fail' : 'chat-agent', text));
  }

  private setBusy(on: boolean) {
    this.busy = on;
    this.send.disabled = on;
  }

  private submit() {
    const text = this.input.value;
    // A message may go while a job runs: a look change lands at once, and the server says if the rest must wait.
    if (!text.trim()) return;
    this.input.value = '';
    if (this.hasWorld && CONFIRM.has(text.toLowerCase().replace(/[ .!]+$/, '').trim())) {
      this.append(el('div', 'chat-me', text));
      this.note('Good. Say what to change, or start a new chat.');
      return;
    }
    this.setBusy(true);
    void this.post(text);
  }

  private async post(text: string) {
    try {
      for await (const event of this.backend.send(text)) this.add(event);
    } catch (err) {
      this.note(`Could not reach the run server: ${String(err)}`, true);
      this.setBusy(false);
    }
  }

  private add(event: ChatEvent) {
    switch (event.type) {
      case 'user':
        this.said.push(event.text);
        this.append(el('div', 'chat-me', event.text));
        break;
      case 'text':
        this.note(event.text, event.fail);
        break;
      case 'working':
        this.working(event.text);
        break;
      case 'retire':
        for (const b of this.list.querySelectorAll('button')) b.disabled = true;
        for (const c of this.list.querySelectorAll('.chat-card')) c.classList.add('chat-answered');
        break;
      case 'tool':
        this.tool(event);
        break;
      case 'card':
        this.card(event);
        break;
      // Requirements, reviews and diffs belong to the campaign. The lab stops before it.
    }
  }

  private append(node: HTMLElement) {
    this.list.append(node);
    this.log.scrollTop = this.log.scrollHeight;
  }

  private working(text: string | null) {
    clearInterval(this.timer);
    this.live.hidden = !text;
    if (!text) return;
    const words = el('span', '', sentence(text));
    const clock = el('span', 'chat-clock', '0 s');
    this.live.replaceChildren(words, clock);
    const t0 = performance.now();
    this.timer = window.setInterval(() => { clock.textContent = `${Math.round((performance.now() - t0) / 1000)} s`; }, 1000);
    this.log.scrollTop = this.log.scrollHeight;
  }

  private tool(event: Extract<ChatEvent, { type: 'tool' }>) {
    if (event.title === 'could_not_build') {
      this.note(`Not built: ${event.lines[0].replace(/[.,;:!?]+$/, '')}. ${event.lines[1]}`);
      return;
    }
    const words = STEP_WORDS[event.title];
    if (!words || NOT_DONE.test(event.meta ?? '')) return;
    let steps = this.list.lastElementChild as HTMLElement | null;
    if (!steps?.classList.contains('chat-steps')) {
      steps = el('div', 'chat-steps');
      this.append(steps);
    }
    steps.append(el('div', 'chat-step', words));
    this.log.scrollTop = this.log.scrollHeight;
  }

  private card(event: Extract<ChatEvent, { type: 'card' }> & { result?: string }) {
    if (event.result) {
      this.note(`${event.result.replaceAll('_', ' ')} Watch the run. Say what to change.`);
      return;
    }
    const options = (event.actions ?? []).filter(a => a.action === 'answer');
    if (!options.length) return;
    const card = el('div', 'chat-card');
    const row = el('div', 'chat-options');
    row.append(...options.map(a => this.option(a)));
    card.append(el('div', '', event.title), row);
    this.append(card);
  }

  private option(action: ChatAction): HTMLButtonElement {
    const b = el('button', 'chat-option', action.label);
    b.type = 'button';
    b.addEventListener('click', () => {
      for (const other of b.parentElement!.querySelectorAll('button')) other.disabled = true;
      this.setBusy(true);
      void this.backend.act(action);
    });
    return b;
  }
}

// The chat column for a replay opened by address. No agent stands behind it.
export function replayNote(): HTMLElement {
  const root = el('section', 'chat');
  const head = el('div', 'chat-head');
  const fresh = el('a', 'chat-new', 'New chat');
  fresh.href = 'lab.html';
  head.append(el('span', '', 'Chat'), fresh);
  const log = el('div', 'chat-log');
  log.append(el('div', 'chat-agent', 'This is a replay of a recorded run. Start a new chat to describe your robot.'));
  root.append(head, log);
  return root;
}
