// The chat backend for the local run server. DEMO SHORTCUT: an embedded runtime can replace this transport.
import type { ChatAction, ChatBackend, ChatEvent } from './backend.ts';

// ?server=PORT points the page at another local run server. Checks use it, so they never touch one that is already open.
const ASKED_PORT = new URLSearchParams(location.search).get('server');
export const SERVER = `http://127.0.0.1:${ASKED_PORT && /^\d{4,5}$/.test(ASKED_PORT) ? ASKED_PORT : 5198}`;
const PORT = ASKED_PORT && /^\d{4,5}$/.test(ASKED_PORT) ? ASKED_PORT : '5198';
const STORE_KEY = 'crashlab-session';
const REPLY_DEADLINE_MS = 15_000; // A POST only starts a job, so it answers at once.
const STREAM_STALE_MS = 15_000; // Three missed pings.
const RECONNECT_MS = 2_000;
const RESTART_LINE_WAIT_MS = 1_500; // A restarted server says so itself, so the chat needs only that one line.
const LATE_WORDS = 'The run server did not answer within 15 s, so that did not go through. Send it again.';
const LOST_WORDS = 'I could not reach the run server, so that did not go through. Send it again.';

function remembered(): string | null {
  try { return sessionStorage.getItem(STORE_KEY); } catch { return null; }
}
function remember(id: string | null) {
  try { if (id) sessionStorage.setItem(STORE_KEY, id); else sessionStorage.removeItem(STORE_KEY); } catch { /* no storage: a reload starts a new chat */ }
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${SERVER}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(REPLY_DEADLINE_MS) });
}

export interface ServerInfo { sim_sha: string; llm: string; max_procs: number; stream_host?: boolean }
export const health = async (): Promise<ServerInfo> => (await (await fetch(`${SERVER}/api/health`, { signal: AbortSignal.timeout(REPLY_DEADLINE_MS) })).json());

export type ServerEvent = { type: string; [key: string]: any };
const CHAT_TYPES = new Set(['user', 'text', 'tool', 'card', 'working', 'retire', 'review', 'requirements', 'diff']);

export class LiveBackend implements ChatBackend {
  readonly isStub = false;
  readonly notice = '';
  id = '';
  private source: EventSource | null = null;
  private queue: ChatEvent[] = [];
  private wake: (() => void) | null = null;
  private lastId = -1;
  private ownHost = false; // The stream has its own host name, so a browser's limit per host never makes it starve a fetch.
  private opens = 0;
  private lastSeen = 0;
  private pinged = false; // An older server sends no pings, and its stream cannot be called stale.
  private lostAt = 0;
  private retry = 0;
  private quietNote = 0;
  private ended = false;

  constructor(private onEvent: (e: ServerEvent) => void | Promise<void>, private newSession: object = {}) {}

  trialBase(tid: string) {
    return `${SERVER}/api/sessions/${this.id}/trials/${tid}`;
  }

  private async session(): Promise<void> {
    const old = remembered();
    if (old) {
      const res = await fetch(`${SERVER}/api/sessions/${old}/state`, { signal: AbortSignal.timeout(REPLY_DEADLINE_MS) });
      // A tab can remember a session from the other page or an older build. Keep it only if it runs the engine this page asked for.
      const { engine, pack } = this.newSession as { engine?: string; pack?: string };
      const wanted = engine === 'v5' ? 'v5' : 'old';
      const state = res.ok ? await res.json() : null;
      if (state && (pack ? state.pack === pack : state.engine === wanted)) { this.id = old; return; }
    }
    const res = await post('/api/sessions', this.newSession);
    if (!res.ok) throw new Error(`run server: HTTP ${res.status}`);
    this.id = (await res.json()).id;
    remember(this.id);
  }

  push(event: ChatEvent) {
    this.queue.push(event);
    this.wake?.();
  }

  async *open(): AsyncIterable<ChatEvent> {
    while (true) {
      try {
        await this.session();
        this.ownHost = (await health()).stream_host === true;
        break;
      } catch {
        await new Promise(r => setTimeout(r, RECONNECT_MS));
      }
    }
    this.connect();
    addEventListener('pagehide', () => { this.source?.close(); clearTimeout(this.retry); });
    addEventListener('pageshow', e => { if (e.persisted && !this.ended) this.connect(); });
    setInterval(() => { if (this.pinged && !this.lostAt && Date.now() - this.lastSeen > STREAM_STALE_MS) this.lost(); }, RECONNECT_MS);
    while (true) {
      while (this.queue.length) yield this.queue.shift()!;
      await new Promise<void>(r => { this.wake = r; });
    }
  }

  // Events run in order: a world or a trial finishes loading before the next event starts.
  private chain: Promise<void> = Promise.resolve();

  private connect() {
    this.source?.close();
    const base = this.ownHost ? `http://${this.id}.localhost:${PORT}` : SERVER;
    const source = new EventSource(`${base}/api/sessions/${this.id}/events?page=1${this.lastId >= 0 ? `&after=${this.lastId}` : ''}`);
    this.source = source;
    this.lastSeen = Date.now();
    source.onopen = () => {
      this.opens++;
      this.lastSeen = Date.now();
      if (!this.lostAt) return;
      this.lostAt = 0;
      this.quietNote = window.setTimeout(() => {
        this.push({ type: 'text', text: 'I lost the connection to the run server, so I reconnected.' });
        this.report('stream_lost');
      }, RESTART_LINE_WAIT_MS);
    };
    source.addEventListener('ping', () => { this.lastSeen = Date.now(); this.pinged = true; });
    source.addEventListener('replaced', () => {
      this.ended = true;
      source.close();
      this.push({ type: 'text', fail: true, text: 'This chat opened in another tab, so this tab stopped updating.' });
    });
    source.onmessage = m => {
      this.lastSeen = Date.now();
      if (m.lastEventId) this.lastId = Number(m.lastEventId); // A grid event has no id, and must not reset the place in the list.
      const event = JSON.parse(m.data) as ServerEvent;
      if (event.restart) clearTimeout(this.quietNote);
      this.chain = this.chain.then(async () => {
        if (CHAT_TYPES.has(event.type)) this.push(event as unknown as ChatEvent);
        else await this.onEvent(event);
      }).catch(err => { this.push({ type: 'text', fail: true, text: `App error: ${String(err)}` }); });
    };
    source.onerror = () => this.lost();
  }

  private lost() {
    if (this.ended || this.retry) return;
    this.source?.close();
    this.lostAt ||= Date.now();
    if (!this.opens) this.ownHost = false; // A browser that cannot open the stream's host name falls back to the plain one.
    this.retry = window.setTimeout(() => void this.reconnect(), RECONNECT_MS);
  }

  private async reconnect() {
    this.retry = 0;
    try {
      const res = await fetch(`${SERVER}/api/sessions/${this.id}/state`, { signal: AbortSignal.timeout(RECONNECT_MS * 2) });
      if (res.status === 404) {
        this.ended = true;
        clearTimeout(this.quietNote);
        this.push({ type: 'text', fail: true, text: 'The run server no longer has this chat. Start a new chat.' });
        return;
      }
      this.connect();
    } catch {
      this.lost(); // Still down. Keep trying.
    }
  }

  /** One line in the server's recovery log for a fix made in the browser. */
  report(code: string) {
    post(`/api/sessions/${this.id}/fixed`, { code }).catch(err => console.warn(`recovery log: ${code} not written: ${String(err)}`));
  }

  async *send(text: string): AsyncIterable<ChatEvent> {
    let res: Response;
    try {
      res = await post(`/api/sessions/${this.id}/message`, { text });
    } catch (err) {
      const late = (err as Error).name === 'TimeoutError';
      if (late) this.report('reply_late');
      yield { type: 'text', fail: true, text: late ? LATE_WORDS : LOST_WORDS };
      return;
    }
    if (res.status === 409) yield { type: 'text', fail: true, text: 'I am still working on the last step. Wait for it to finish.' };
    else if (!res.ok) yield { type: 'text', fail: true, text: `The run server refused that message: HTTP ${res.status}.` };
  }

  async act(action: ChatAction) {
    let res: Response;
    try {
      res = await post(`/api/sessions/${this.id}/action`, { action: action.action, value: action.value ?? null });
    } catch (err) {
      const late = (err as Error).name === 'TimeoutError';
      if (late) this.report('reply_late');
      this.push({ type: 'text', fail: true, text: late ? LATE_WORDS : LOST_WORDS });
      return;
    }
    if (!res.ok) this.push({ type: 'text', fail: true, text: res.status === 409 ? 'That step is no longer open, or I am still working.' : `The run server refused that: HTTP ${res.status}.` });
  }

  /** Returns a problem to show, or null when the gate started. The world text is posted as data and shown back nowhere. */
  async submit(world: string, seed: string): Promise<string | null> {
    const res = await post(`/api/sessions/${this.id}/submit`, { world, seed });
    if (res.ok) return null;
    return res.status === 409 ? 'I am still working, or the bounty is not funded yet.' : res.status === 413 ? 'That file is too large.' : res.status === 400 ? 'The seed must be a whole number.' : `The run server refused that: HTTP ${res.status}.`;
  }

  reset() {
    remember(null);
    location.reload();
  }
}
