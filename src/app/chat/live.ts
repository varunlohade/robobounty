// The chat backend for the local run server. DEMO SHORTCUT: an embedded runtime can replace this transport.
import type { ChatAction, ChatBackend, ChatEvent } from './backend.ts';

export const SERVER = (import.meta as unknown as { env?: { VITE_CRASHLAB_SERVER?: string } }).env?.VITE_CRASHLAB_SERVER ?? 'http://127.0.0.1:5198';
const STORE_KEY = 'crashlab-session';

function remembered(): string | null {
  try { return sessionStorage.getItem(STORE_KEY); } catch { return null; }
}
function remember(id: string | null) {
  try { if (id) sessionStorage.setItem(STORE_KEY, id); else sessionStorage.removeItem(STORE_KEY); } catch { /* no storage: a reload starts a new chat */ }
}

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(`${SERVER}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

export interface ServerInfo { sim_sha: string; llm: string; max_procs: number; sponsors?: { world: { label: string }; arc: { reason?: string | null } } }
export const health = async (): Promise<ServerInfo> => (await (await fetch(`${SERVER}/api/health`)).json());

export type ServerEvent = { type: string; [key: string]: any };
const CHAT_TYPES = new Set(['user', 'text', 'tool', 'card', 'working', 'retire', 'review', 'requirements', 'diff']);

export class LiveBackend implements ChatBackend {
  readonly isStub = false;
  readonly notice = '';
  id = '';
  private source: EventSource | null = null;
  private queue: ChatEvent[] = [];
  private wake: (() => void) | null = null;

  constructor(private onEvent: (e: ServerEvent) => void | Promise<void>) {}

  trialBase(tid: string) {
    return `${SERVER}/api/sessions/${this.id}/trials/${tid}`;
  }

  private async session(): Promise<void> {
    const old = remembered();
    if (old && (await fetch(`${SERVER}/api/sessions/${old}/state`)).ok) { this.id = old; return; }
    const res = await post('/api/sessions', {});
    if (!res.ok) throw new Error(`run server: HTTP ${res.status}`);
    this.id = (await res.json()).id;
    remember(this.id);
  }

  push(event: ChatEvent) {
    this.queue.push(event);
    this.wake?.();
  }

  async *open(): AsyncIterable<ChatEvent> {
    await this.session();
    // Events run in order: a world or a trial finishes loading before the next event starts.
    let chain: Promise<void> = Promise.resolve();
    this.source = new EventSource(`${SERVER}/api/sessions/${this.id}/events`);
    this.source.onmessage = m => {
      const event = JSON.parse(m.data) as ServerEvent;
      chain = chain.then(async () => {
        if (CHAT_TYPES.has(event.type)) this.push(event as unknown as ChatEvent);
        else await this.onEvent(event);
      }).catch(err => { this.push({ type: 'text', fail: true, text: `App error: ${String(err)}` }); });
    };
    this.source.onerror = () => {
      if (this.source?.readyState === EventSource.CLOSED) this.push({ type: 'text', fail: true, text: 'Lost the run server. Reload to start again.' });
    };
    while (true) {
      while (this.queue.length) yield this.queue.shift()!;
      await new Promise<void>(r => { this.wake = r; });
    }
  }

  async *send(text: string): AsyncIterable<ChatEvent> {
    const res = await post(`/api/sessions/${this.id}/message`, { text });
    if (res.status === 409) yield { type: 'text', fail: true, text: 'I am still working on the last step. Wait for it to finish.' };
    else if (!res.ok) yield { type: 'text', fail: true, text: `The run server refused that message: HTTP ${res.status}.` };
  }

  async act(action: ChatAction) {
    const res = await post(`/api/sessions/${this.id}/action`, { action: action.action, value: action.value ?? null });
    if (!res.ok) this.push({ type: 'text', fail: true, text: res.status === 409 ? 'That step is no longer open, or I am still working.' : `The run server refused that: HTTP ${res.status}.` });
  }

  /** Returns a problem to show, or null when the gate started. The world text is posted as data and shown back nowhere. */
  async submit(world: string, seed: string): Promise<string | null> {
    const res = await post(`/api/sessions/${this.id}/submit`, { world, seed });
    if (res.ok) return null;
    return res.status === 409 ? 'I am still working, or the bounty is not funded yet.' : res.status === 413 ? 'That file is too large.' : res.status === 400 ? 'The seed must be a whole number.' : `The run server refused that: HTTP ${res.status}.`;
  }

  async worldContext(): Promise<{ ok: boolean; body: any }> {
    const res = await post(`/api/sessions/${this.id}/world_context`, {});
    return { ok: res.ok, body: await res.json() };
  }

  async worldVerify(result: unknown): Promise<{ ok: boolean; body: any }> {
    const res = await post(`/api/sessions/${this.id}/world_verify`, { result });
    return { ok: res.ok, body: await res.json() };
  }

  reset() {
    remember(null);
    location.reload();
  }
}
