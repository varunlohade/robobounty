// The auth journeys in headless Chrome, against a real site server, a real board server and vite on their own ports, with a throwaway store.
// The engineer's World ID reply is a MOCK (policy/server/check_auth_server.py). No real scan runs and no email is sent. Pictures: design/site2/auth-*.png.
// Run: node src/site/tools/check_auth.mjs
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = join(ROOT, 'design/site2');
const [WEB, SITE, BOARD] = [7499, 7497, 7498];
const BASE = `http://localhost:${WEB}`;
const tmp = mkdtempSync(join(tmpdir(), 'check-auth-web-'));
const env = { ...process.env, CRASHLAB_DEMO: '1', CRASHLAB_AUTH_DB: join(tmp, 'auth.sqlite'), CHECK_WORLD_DB: join(tmp, 'world.sqlite'), CRASHLAB_WEB_PORT: String(WEB), CRASHLAB_SITE_PORT: String(SITE), VITE_BOARD_PORT: String(BOARD), VITE_RUN_PORT: '7496',
  WORLD_APP_ID: 'app_mock', WORLD_ACTION: 'crashlab-site-login', WORLD_RP_ID: 'rp_mock', WORLD_RP_SIGNING_KEY: `0x${randomBytes(32).toString('hex')}`, WORLD_ENVIRONMENT: 'staging', WORLD_CREDENTIAL: 'human' };
const PY = join(ROOT, 'policy/.venv/bin/python');
const procs = [
  spawn(PY, ['policy/server/check_auth_server.py', '--port', String(SITE)], { cwd: ROOT, env, stdio: 'ignore' }),
  spawn(PY, ['policy/bounty/board_server.py', '--root', join(tmp, 'board'), '--port', String(BOARD)], { cwd: ROOT, env, stdio: 'ignore' }),
  spawn('node_modules/.bin/vite', ['--port', String(WEB), '--strictPort'], { cwd: ROOT, env, stdio: 'ignore' }),
];
let failed = 0;
const say = (ok, what, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${!ok && extra ? `: ${String(extra).slice(0, 300)}` : ''}`); if (!ok) failed += 1; };
for (let i = 0; i < 150; i++) { try { if ((await fetch(`${BASE}/login.html`)).ok) break; } catch { /* starting */ } await wait(200); }

const c = await openChrome({ width: 1440, height: 900, guestForLab: false });
const { send, js, until, problems } = c;
await send('Network.enable');
const shot = name => c.shot(join(OUT, `auth-${name}.png`));
const go = async path => { await send('Page.navigate', { url: `${BASE}/${path}` }); await wait(500); };
const at = (path, what, sec = 30) => until(`location.pathname === '/${path}'`, what, sec);
const text = () => js('document.body.innerText');
const click = words => js(`[...document.querySelectorAll('button')].find(b => b.textContent.includes(${JSON.stringify(words)})).click()`);
const hasButton = words => `[...document.querySelectorAll('button')].some(b => b.textContent.includes(${JSON.stringify(words)}))`;
const clickWhenReady = async words => { await until(hasButton(words), words, 30); await wait(400); await click(words); };
const who = () => js(`fetch('/site-api/auth/me').then(r => r.json())`);
const cookies = async () => (await send('Network.getCookies', { urls: [BASE] })).result.cookies;
const fill = v => js(`(() => { const set = (n, x) => { const i = document.querySelector('input[name=' + n + ']'); if (i) i.value = x; }; ${Object.entries(v).map(([k, x]) => `set(${JSON.stringify(k)}, ${JSON.stringify(x)});`).join('')} document.querySelector('form button[type=submit]').click(); })()`);
const sidebar = () => until(`!!document.querySelector('.sh-who')?.dataset.who`, 'the sidebar', 30);
const signOut = async () => { await sidebar(); await js(`document.querySelector('.sh-out').click()`); await at('login.html', 'login after sign-out'); await wait(300); };
const EMAIL = `owner-${randomBytes(3).toString('hex')}@acme.example`;
const PASSWORD = 'correct horse battery';

try {
  // Signed out: every page goes to login, and next stays.
  await go('bounties.html?post=a/c1/stalled');
  await at('login.html', 'login');
  say((await js('location.search')).includes(encodeURIComponent('bounties.html?post=a/c1/stalled')), 'a signed-out visit keeps ?next=', await js('location.search'));
  await go('lab.html');
  await at('login.html', 'login from the lab');
  say((await js('location.search')).includes('lab.html'), 'the lab sends a signed-out visitor to login too');
  await until(hasButton('Continue with work email'), 'login', 20);
  await wait(500);
  await shot('1-login');

  // Company: refusal, sign-up, reload, sign-out, wrong password, sign-in.
  await go('login.html?next=data.html');
  await clickWhenReady('Continue with work email');
  await clickWhenReady('Create account');
  await wait(300);
  await fill({ email: EMAIL, password: 'short', company: 'Acme Robots' });
  await until(`!document.querySelector('p.bad')?.hidden`, 'the refusal', 10);
  await shot('2-company-refused');
  say((await js('location.pathname')) === '/login.html', 'a short password stays on login');
  await fill({ email: EMAIL, password: PASSWORD, company: 'Acme Robots' });
  await at('data.html', 'next after sign-up');
  await sidebar();
  say(/Acme Robots/.test(await js(`document.querySelector('.sh-who').innerText`)) && /Email not verified/.test(await js(`document.querySelector('.sh-who').innerText`)), 'the sidebar names the company and says Email not verified');
  await shot('3-company-signed-in');
  const session = (await cookies()).find(x => x.name === 'crashlab_session');
  say(session?.httpOnly && session.sameSite === 'Lax', 'the session cookie is HttpOnly and SameSite=Lax', JSON.stringify(session));
  say(!(await js(`document.cookie`)).includes('crashlab_session'), 'a script cannot read the session');
  say(await js(`localStorage.length === 0`), 'nothing in localStorage');
  await go('home.html');
  await sidebar();
  say((await who()).role === 'company', 'reload keeps the session');
  await go('bounties.html');
  await sidebar();
  await until(hasButton('Post a bounty'), 'the post button', 20);
  say(true, 'a company sees Post a bounty');
  say(await js(`!document.querySelector('a.sh-item[href="simulation.html"]').hidden && document.querySelector('a.sh-item[href="simulation.html"]').textContent === 'Simulation'`), 'a company sees Simulation');
  await go('crashlab.html');
  await at('simulation.html', 'the old address');
  await until(`document.querySelector('.sh-title')?.textContent === 'Simulation' && document.body.innerText.includes('Open Simulation')`, 'the Simulation page', 20);
  say(true, 'crashlab.html redirects to simulation.html, and the page says Simulation');
  say(/^CrashLab/.test(await js('document.title')) && (await js(`document.querySelector('.sh-brand').textContent`)) === 'CrashLab', 'the product name stays CrashLab');
  await signOut();
  say((await who()).signed_in === false, 'sign-out ends the session on the server');
  await go('login.html');
  await clickWhenReady('Continue with work email');
  await wait(300);
  await fill({ email: EMAIL, password: 'this is the wrong one' });
  await until(`!document.querySelector('p.bad')?.hidden`, 'the refusal', 10);
  say((await text()).includes('That email or password is wrong.'), 'a wrong password gets generic words');
  await fill({ email: EMAIL, password: PASSWORD });
  await at('home.html', 'home after sign-in');
  say((await who()).role === 'company', 'the right password signs in again');
  await signOut();

  // Open redirect.
  for (const bad of ['https://evil.example/', '//evil.example', 'javascript:alert(1)']) {
    await go('login.html');
    await until(`!!document.querySelector('.lg-sheet button')`, 'login', 20);
    await js(`history.replaceState(null, '', 'login.html?next=' + encodeURIComponent(${JSON.stringify(bad)}))`);
    await js(`import('/src/site/auth.ts').then(m => { window.__next = m.nextPage(); })`);
    say((await js('window.__next')) === 'home.html', `next refuses ${bad}`);
  }

  // Engineer: MOCK World reply, through the real server path. Same account after sign-out.
  const enrol = (nullifier, session_id) => js(`import('/src/site/auth.ts').then(async m => { const c = (await m.worldContext()).body; const r = await m.worldVerify({ protocol_version: '4.0', nonce: c.rp_context.nonce, action: c.action, session_id: ${JSON.stringify(session_id)}, environment: 'staging', responses: [{ identifier: 'proof_of_human', nullifier: ${JSON.stringify(nullifier)}, proof: ['0x1'] }] }); return { ok: r.ok, mode: c.mode, tester: r.body.tester, label: r.body.verification_label }; })`);
  const prove = (session_id, sn) => js(`import('/src/site/auth.ts').then(async m => { const c = (await m.worldContext()).body; const r = await m.worldVerify({ protocol_version: '4.0', nonce: c.rp_context.nonce, session_id: ${JSON.stringify(session_id)}, environment: 'staging', responses: [{ identifier: 'proof_of_human', session_nullifier: [${JSON.stringify(sn)}, '0x1'], proof: ['0x1'] }] }); return { ok: r.ok, mode: c.mode, tester: r.body.tester }; })`);
  await go('login.html');
  await until(`!!document.querySelector('.lg-sheet button')`, 'login', 20);
  const first = await enrol('0x' + 'ab'.repeat(16), 'session_browser1');
  say(first.ok && first.label === 'Verified human', 'MOCK engineer: a first scan makes an account', JSON.stringify(first));
  await go('home.html');
  await sidebar();
  say(/Verified human/.test(await js(`document.querySelector('.sh-who').innerText`)), 'MOCK engineer: the sidebar shows it');
  await shot('4-engineer-mock');
  const key = JSON.parse(execFileSync(PY, ['policy/server/screener.py', 'key'], { cwd: ROOT, encoding: 'utf8' }));
  const links = await js(`[...document.querySelectorAll('nav a.sh-item')].filter(a => !a.hidden).map(a => a.textContent)`);
  say(links.length === 1 && links[0] === 'Bounties', 'an engineer sees only Bounties in the sidebar', links.join());
  for (const page of ['home.html', 'simulation.html', 'failures.html', 'settings.html', 'crashlab.html', 'data.html', 'providers.html', 'lab.html']) {
    await go(page);
    await at('bounties.html', `${page} to Bounties`);
    await until(`document.body.innerText.includes('Engineers work from Bounties')`, 'the plain message', 15);
    say(true, `an engineer on ${page} lands on Bounties, with a plain message`);
  }
  await shot('9-engineer-bounties');
  await go('screener.html');
  await clickWhenReady('Start');
  await until(`!!document.querySelector('[data-question]')`, 'a question', 15);
  await wait(300);
  await shot('10-screener-question');
  for (let i = 0; i < 6; i++) {
    await until(`document.querySelector('[data-question]')?.dataset.index === '${i}'`, `question ${i + 1}`, 15);
    const id = await js(`document.querySelector('[data-question]').dataset.question`);
    await js(`document.querySelector('[data-choice="${key[id]}"]').click()`);
  }
  await until(`document.body.innerText.includes('coming soon')`, 'the card', 15);
  say(/AI interview:\s+coming soon/.test(await text()) && /not proof of skill/.test(await text()), 'a pass shows a calm card, with an honest label');
  await shot('11-screener-passed');
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__answer = ['0xdeadbeef00000000000000000000000000000000']; window.prompt = () => window.__next_address ?? sessionStorage.getItem('addr'); window.alert = t => { sessionStorage.setItem('alerted', t); };` });
  await go('home.html');
  await sidebar();
  await js(`sessionStorage.setItem('addr', '0x' + 'a'.repeat(64))`);
  await click('Add payout address');
  await until(`sessionStorage.getItem('alerted')?.includes('private key')`, 'the refusal of a key', 10);
  say(true, 'the payout field refuses a private key');
  await js(`sessionStorage.setItem('addr', '0x' + '12ab'.repeat(10))`);
  await click('Add payout address');
  await until(`document.querySelector('.sh-who')?.innerText.includes('0x12ab…12ab')`, 'the masked address', 15);
  say(!(await text()).includes('12ab'.repeat(10)), 'the payout address shows masked');
  await shot('5-engineer-payout');
  await go('bounties.html');
  await sidebar();
  await wait(800);
  say(!(await js(hasButton('Post a bounty'))) || await js(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Post a bounty')).hidden`), 'an engineer sees no Post a bounty');
  await signOut();
  const back = await prove('session_browser1', '0x71');
  say(back.ok && back.mode === 'prove' && back.tester === first.tester, 'MOCK engineer: sign-out and sign-in again reach the same account', JSON.stringify(back));
  await go('home.html');
  await sidebar();
  say(/0x12ab…12ab/.test(await js(`document.querySelector('.sh-who').innerText`)), 'MOCK engineer: the payout address is still on the account');
  await signOut();

  // Guest.
  await go('login.html');
  await clickWhenReady('Continue with World ID');
  await clickWhenReady('Enter as local guest');
  await at('home.html', 'home as guest');
  await sidebar();
  say(/Guest, not verified/.test(await js(`document.querySelector('.sh-who').innerText`)), 'a guest is labelled');
  await shot('6-guest');
  await go('bounties.html?post=a/c1/stalled');
  await sidebar();
  await until(`document.querySelector('.sh-actions')?.innerText.includes('Guest')`, 'the guest line', 15);
  say(!(await js(`!!document.querySelector('.overlay')`)), 'a guest does not get the post dialog');
  await shot('7-guest-bounties');
  const refused = await js(`import('/src/board/api.ts').then(m => m.api.stop().then(() => 'allowed', e => e.code))`);
  say(refused === 'guest_refused', 'the board refuses a guest, even from code in the page', refused);

  // Expired session: the next page goes to login once and stays there.
  const row = (await cookies()).find(x => x.name === 'crashlab_session');
  await send('Network.setCookie', { name: 'crashlab_session', value: 'expired-or-forged', url: BASE, httpOnly: true, sameSite: 'Lax' });
  say(!!row, 'the guest had a session');
  await go('home.html');
  await at('login.html', 'login after a dead session');
  await wait(1500);
  say((await js('location.pathname')) === '/login.html', 'a dead session lands on login, with no loop');
  await shot('8-expired');
  say(!readFileSync(env.CRASHLAB_AUTH_DB).includes(PASSWORD), 'no password in the store');
  const real = problems.filter(p => !/401|403|409|400|Failed to load resource/.test(p));
  say(real.length === 0, 'no console errors', real.slice(0, 4).join(' | '));
} catch (err) {
  say(false, 'the journey finished', err);
  try { await shot('failure'); console.log(await text()); } catch { /* the page is gone */ }
} finally {
  c.close();
  for (const p of procs) p.kill();
  setTimeout(() => rmSync(tmp, { recursive: true, force: true }), 500);
}
console.log(failed ? `${failed} FAILED` : 'ALL PASS (World ID reply is a mock. No real scan and no email.)');
setTimeout(() => process.exit(failed ? 1 : 0), 800);
