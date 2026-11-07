// Settings: who is signed in, from the server, and a way out.
import { mountShell } from './shell.ts';
import { signOut } from './session.ts';
import { h } from './ui.ts';
import './overview.css';

const { main, who } = mountShell({ page: 'settings', title: 'Settings', status: 'Local ledger. Not on chain.' });
const page = h('div', 'scroll ov');
main.append(page);

void who.then(w => {
  if (w.kind === 'none' || w.kind === 'engineer') return;
  const row = (k: string, v: string) => [h('dt', '', k), h('dd', '', v)];
  const out = h('button', 'ov-btn', 'Sign out');
  out.type = 'button';
  out.addEventListener('click', async () => { await signOut(); location.href = 'login.html'; });
  page.replaceChildren(h('div', 'ov-set', h('dl', '', ...row('Account', w.kind === 'guest' ? 'Local guest' : 'Company'), ...row('Company', w.kind === 'guest' ? 'None' : w.label), h('dt', '', 'Email'), h('dd', '', w.email ?? '', h('small', 'ov-set-note', w.verificationLabel))), out));
});
