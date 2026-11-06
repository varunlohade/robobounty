// Who is at the keyboard. "Verified" comes only from the server's reply, and no browser storage can claim it.
const GUEST_KEY = 'crashlab-guest';

export type Who =
  | { kind: 'verified'; humanId: string; environment: string }
  | { kind: 'guest' }
  | { kind: 'none' };

function guestChosen(): boolean {
  try { return localStorage.getItem(GUEST_KEY) === '1'; } catch { return false; }
}

export function enterAsGuest() {
  try { localStorage.setItem(GUEST_KEY, '1'); } catch { /* no storage: the next page asks again */ }
}

export async function whoIs(): Promise<Who> {
  try {
    const res = await fetch('/site-api/auth/me', { signal: AbortSignal.timeout(4_000) });
    if (res.ok) {
      const me = await res.json();
      if (me.verified === true && typeof me.human_id === 'string') return { kind: 'verified', humanId: me.human_id, environment: String(me.environment ?? '') };
    }
  } catch { /* no server: nobody can be verified */ }
  return guestChosen() ? { kind: 'guest' } : { kind: 'none' };
}

export async function signOut() {
  try { localStorage.removeItem(GUEST_KEY); } catch { /* nothing stored */ }
  try { await fetch('/site-api/auth/logout', { method: 'POST', signal: AbortSignal.timeout(4_000) }); } catch { /* no server: no server session either */ }
}
