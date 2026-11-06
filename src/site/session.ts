// Who is at the keyboard, in the shape the pages read. It all comes from the server, through auth.ts.
import { me, signOut, type Me } from './auth.ts';
export { signOut };

export type Who = { kind: 'company' | 'engineer' | 'guest' | 'none' } & Me;

export async function whoIs(): Promise<Who> {
  const m = await me();
  return { ...m, kind: m.role ?? 'none' };
}
