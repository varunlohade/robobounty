import { plainNote } from '../site/plain_note.ts';
import { el, icon } from '../app/dom.ts';
import type { ChatAction, ChatEvent } from '../app/chat/backend.ts';
import { SERVER, type LiveBackend, type ServerEvent } from '../app/chat/live.ts';

// Server tool titles the chat shows, in plain words. Any other title stays hidden.
const STEP_WORDS: Record<string, string> = {
  read_message: 'Read your message',
  fix_read: 'Read the failure',
  fix_ai: 'The AI wrote the change',
  fix_target: 'Ran the failing worlds',
  fix_others: 'Ran the other worlds',
  plan_world: 'Planned the change',
  build_world: 'Built the world',
  change_world: 'Changed the world',
  run_trial: 'Ran one test',
};
const NOT_DONE = /^(failed|rejected|refused)/;
// The server would start the campaign on these words. The lab stops at one run, so they stay here.
const CONFIRM = new Set(['yes', 'y', 'yep', 'ok', 'okay', 'looks right', 'looks good', 'it looks right', 'correct']);

const PLACEHOLDER: Record<string, { empty: string; world: string }> = {
  window: { empty: 'Describe your robot and where it works', world: 'Ask for a change to the world' },
  inspection: { empty: 'Ask for a change to the plant', world: 'Ask for a change to the plant' },
};
const FALLBACK_NAME: Record<string, string> = { window: 'Window cleaning robot', inspection: 'Inspection robot' };

interface PackRow { name: string; label: string }
interface PackList { packs: PackRow[]; import: { available: boolean; note: string } }

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

const COUNT_WORDS: Record<string, number> = { two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19, twenty: 20 };
// The AI's stored reason can name a count from before the code checked its list. A sentence stays only if each number in it is one the card itself shows.
function reasonWithoutOtherCounts(reason: string, shown: number[]) {
  const counts = (sentence: string) => [...sentence.matchAll(/\b\d+(?:\.\d+)?\b|\b[a-z]+\b/gi)].map(m => /^\d/.test(m[0]) ? Number(m[0]) : COUNT_WORDS[m[0].toLowerCase()]).filter(n => n !== undefined);
  return (reason.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) ?? []).filter(sentence => counts(sentence).every(n => shown.includes(n))).join('').trim();
}

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
  private menu = el('div', 'chat-menu');
  private test = el('button', 'chat-test', 'List test scenarios');
  private robotName = el('span', 'chat-robot');
  private route = el('select', 'chat-route');
  private routeNow = '';
  /** The user chose a robot from the + menu. */
  onPick: (pack: string) => void = () => {};
  private runCards: HTMLElement[] = [];

  constructor(private backend: LiveBackend, private pack = 'window') {
    const head = el('div', 'chat-head');
    const fresh = el('button', 'chat-new', 'New chat');
    fresh.type = 'button';
    fresh.addEventListener('click', () => backend.reset());
    head.append(el('span', '', 'Chat'), fresh);
    this.live.hidden = true;
    this.log.setAttribute('role', 'log');
    this.log.append(this.list, this.live);

    const box = el('form', 'chat-box');
    this.input.placeholder = this.words().empty;
    this.input.setAttribute('aria-label', 'Message');
    this.input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
    });
    const foot = el('div', 'chat-foot');
    this.send.type = 'submit';
    this.send.setAttribute('aria-label', 'Send');
    this.send.append(icon('send', true));
    const plus = el('button', 'chat-plus');
    plus.type = 'button';
    plus.setAttribute('aria-label', 'Choose a robot');
    plus.setAttribute('aria-haspopup', 'menu');
    plus.title = 'Choose a robot';
    plus.append(icon('plus', true));
    plus.addEventListener('click', e => { e.stopPropagation(); void this.toggleMenu(); });
    const left = el('div', 'chat-foot-left');
    this.robotName.textContent = FALLBACK_NAME[pack] ?? pack;
    // The server's llm_route event shows it. A recorded run sends none, so it stays hidden.
    this.route.hidden = true;
    this.route.setAttribute('aria-label', 'AI that answers this chat');
    this.route.title = 'AI that answers this chat';
    this.route.addEventListener('change', () => void this.chooseRoute());
    left.append(plus, this.robotName, this.route);
    foot.append(left, this.send);
    this.menu.hidden = true;
    this.menu.setAttribute('role', 'menu');
    box.append(this.menu, this.input, foot);
    box.addEventListener('submit', e => { e.preventDefault(); this.submit(); });
    addEventListener('click', e => { if (!this.menu.contains(e.target as Node)) this.menu.hidden = true; });
    addEventListener('keydown', e => { if (e.key === 'Escape') this.menu.hidden = true; });
    this.test.type = 'button';
    this.test.hidden = true;
    this.test.addEventListener('click', () => {
      this.setBusy(true);
      void this.backend.act({ action: 'list_scenarios' } as ChatAction);
    });
    this.root.append(head, this.log, this.test, box);
  }

  private words() {
    return PLACEHOLDER[this.pack] ?? PLACEHOLDER.window;
  }

  private async toggleMenu() {
    if (!this.menu.hidden) { this.menu.hidden = true; return; }
    this.menu.replaceChildren(el('div', 'chat-menu-note', 'Loading robots'));
    this.menu.hidden = false;
    let list: PackList;
    try {
      const res = await fetch(`${SERVER}/api/packs`, { signal: AbortSignal.timeout(5_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      list = await res.json();
    } catch (err) {
      this.menu.replaceChildren(el('div', 'chat-menu-note chat-fail', `Could not list the robots: ${String(err)}`));
      return;
    }
    const rows: HTMLElement[] = [el('div', 'chat-menu-head', 'Robot')];
    for (const p of list.packs) {
      const row = el('button', p.name === this.pack ? 'chat-menu-row on' : 'chat-menu-row');
      row.type = 'button';
      row.setAttribute('role', 'menuitem');
      row.dataset.pack = p.name;
      row.append(el('span', '', p.label), el('span', 'chat-menu-tag', p.name === this.pack ? 'Current' : ''));
      row.addEventListener('click', () => {
        this.menu.hidden = true;
        if (p.name !== this.pack) this.onPick(p.name);
      });
      rows.push(row);
    }
    const file = el('button', 'chat-menu-row chat-menu-import');
    file.type = 'button';
    file.disabled = true;
    file.title = list.import.note;
    file.setAttribute('role', 'menuitem');
    file.append(el('span', '', 'Import a robot file'), el('span', 'chat-menu-tag', list.import.available ? '' : 'Not yet'));
    rows.push(el('div', 'chat-menu-line'), file);
    this.menu.replaceChildren(...rows);
    const named = list.packs.find(p => p.name === this.pack);
    if (named) this.robotName.textContent = named.label;
  }

  /** The route the server now has for this chat. */
  llmRoute(e: ServerEvent) {
    this.route.replaceChildren(...(e.routes as { id: string; label: string; open: boolean }[]).map(r => {
      const option = el('option', '', r.label);
      option.value = r.id;
      option.disabled = !r.open;
      return option;
    }));
    this.route.value = this.routeNow = e.route;
    this.route.hidden = false;
  }

  private async chooseRoute() {
    this.route.disabled = true;
    const done = await this.backend.chooseRoute(this.route.value);
    this.route.disabled = this.busy;
    if (done) return;
    this.route.value = this.routeNow;
    this.note('The AI did not change. Wait for the last step to finish, then try again.', true);
  }

  /** The agent's list of test scenarios, with the button that runs it. */
  scenarios(e: ServerEvent) {
    if (e.rejection) {
      this.note(`No scenario list came: ${String(e.rejection).replaceAll('_', ' ')}. Ask again.`, true);
      return;
    }
    const card = el('div', 'chat-card chat-list-card');
    const run = el('button', 'chat-run', `Run ${e.to_run} scenarios`);
    run.type = 'button';
    run.addEventListener('click', () => {
      run.disabled = true;
      this.setBusy(true);
      void this.backend.act({ action: 'run_campaign' } as ChatAction);
    });
    card.append(el('div', 'chat-card-title', `${e.count} scenarios: ${e.to_run} to run, ${e.held_back} held back`));
    const reason = reasonWithoutOtherCounts(String(e.count_reason ?? ''), [e.count, (e.groups ?? []).length]);
    if (reason) card.append(el('div', 'chat-card-text', reason));
    const groups = el('details', 'chat-details');
    groups.append(el('summary', '', `${(e.groups ?? []).length} groups`));
    for (const g of e.groups ?? []) groups.append(el('div', 'chat-group', `${g.name} (${g.count}). ${g.reason}`));
    card.append(groups);
    if (e.note) card.append(el('div', 'chat-card-note', plainNote(e.note)));
    card.append(run);
    this.runCards.push(run);
    this.append(card);
  }

  /** A campaign started, so no list waits for its button. */
  campaignRunning() {
    for (const b of this.runCards) (b as HTMLButtonElement).disabled = true;
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
    this.input.placeholder = this.words().world;
    this.test.hidden = this.busy;
  }

  worldGone() {
    this.hasWorld = false;
    this.input.placeholder = this.words().empty;
    this.test.hidden = true;
  }

  jobDone() {
    this.setBusy(false);
  }

  note(text: string, fail = false) {
    this.append(el('div', fail ? 'chat-agent chat-fail' : 'chat-agent', text));
  }

  /** A card another part of the page built, such as an AI fix's diff. */
  attach(node: HTMLElement) {
    this.append(node);
  }

  private setBusy(on: boolean) {
    this.busy = on;
    this.send.disabled = on;
    this.route.disabled = on;
    this.test.hidden = on || !this.hasWorld;
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
      // send yields only when the message did not start a job, so no idle event will come for it.
      for await (const event of this.backend.send(text)) { this.add(event); this.setBusy(false); }
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
        this.note(plainNote(event.text), event.fail);
        break;
      case 'picture': {
        const figure = el('figure', 'chat-picture');
        const image = document.createElement('img');
        image.src = event.url;
        image.alt = event.caption;
        image.style.maxWidth = '100%';
        figure.append(image, el('figcaption', 'chat-note', event.caption));
        this.append(figure);
        break;
      }
      case 'working':
        this.working(event.text, (event as { since?: number }).since);
        break;
      case 'retire':
        // A Show it button still works later: it only moves the camera.
        for (const b of this.list.querySelectorAll<HTMLButtonElement>('button:not([data-keep])')) b.disabled = true;
        for (const c of this.list.querySelectorAll('.chat-card:not(:has([data-keep]))')) c.classList.add('chat-answered');
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

  private working(text: string | null, since?: number) {
    clearInterval(this.timer);
    this.live.hidden = !text;
    if (!text) return;
    const words = el('span', '', sentence(text));
    const t0 = since ?? Date.now();
    const seconds = () => `${Math.max(0, Math.round((Date.now() - t0) / 1000))} s`;
    const clock = el('span', 'chat-clock', seconds());
    this.live.replaceChildren(words, clock);
    this.timer = window.setInterval(() => { clock.textContent = seconds(); }, 1000);
    this.log.scrollTop = this.log.scrollHeight;
  }

  private tool(event: Extract<ChatEvent, { type: 'tool' }>) {
    if (event.title === 'could_not_build') {
      this.note(`Not built: ${event.lines[0].replace(/[.,;:!?]+$/, '')}. ${event.lines[1]}`);
      return;
    }
    // The raw engine lines stay one click away, closed by default.
    if (event.title === 'details') {
      const box = el('details', 'chat-details');
      box.append(el('summary', '', 'Details'), ...event.lines.map(line => el('div', 'chat-detail', line)));
      this.append(box);
      return;
    }
    const words = STEP_WORDS[event.title];
    if (!words || NOT_DONE.test(event.meta ?? '')) return;
    let steps = this.list.lastElementChild as HTMLElement | null;
    if (!steps?.classList.contains('chat-steps')) {
      steps = el('div', 'chat-steps');
      this.append(steps);
    }
    steps.append(el('div', 'chat-step', /^\d+ s$/.test(event.meta ?? '') ? `${words}, ${event.meta}` : words));
    this.log.scrollTop = this.log.scrollHeight;
  }

  private card(event: Extract<ChatEvent, { type: 'card' }> & { result?: string }) {
    if (event.result) {
      this.note(`${event.result.replaceAll('_', ' ')} Watch the run. Say what to change.`);
      return;
    }
    const options = (event.actions ?? []).filter(a => a.action === 'answer' || a.action === 'focus');
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
    if (action.action === 'focus') b.dataset.keep = '1';
    b.addEventListener('click', () => {
      if (action.action === 'focus') { void this.backend.act(action); return; } // Only the camera moves, so no job starts and the button stays.
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
