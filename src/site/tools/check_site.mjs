// Site check in headless Chrome, with its own profile. Needs vite on 5199 and policy/server/site_data.py on 5297.
// Run: node src/site/tools/check_site.mjs [outdir]. Steps named MOCK use replies invented inside this check.
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const BASE = `http://localhost:${process.env.CRASHLAB_WEB_PORT ?? 5199}`; // scripts/demo.sh's --ports picks another.
const OUT = process.argv[2] ?? 'design/site2';
mkdirSync(OUT, { recursive: true });
const PAGES = ['home', 'crashlab', 'data', 'providers'];
let failed = 0;
const say = (ok, what, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${extra ? `: ${extra}` : ''}`); if (!ok) failed += 1; };

const MOCK_KEY = randomBytes(32).toString('hex');
const signed = JSON.parse(execFileSync('node', ['policy/server/site_world_helper.mjs'], { input: JSON.stringify({ action: 'crashlab-site-login' }), env: { ...process.env, WORLD_RP_SIGNING_KEY: MOCK_KEY } }).toString());
const MOCK_CTX = { mode: 'enrol', app_id: 'app_0000000000000000000000000000000000', action: 'crashlab-site-login', environment: 'staging', rp_context: { rp_id: 'rp_0000000000000000', nonce: signed.nonce, created_at: signed.created_at, expires_at: signed.expires_at, signature: signed.sig } };
const b = await openChrome({ width: 1440, height: 900 });
const { send, js: ev, problems, until } = b;
const waitText = (t, sec = 15) => until(`document.body.innerText.includes(${JSON.stringify(t)})`, t, sec).catch(() => null);

async function go(path, settle = 700) {
  await send('Page.navigate', { url: `${BASE}/${path}` });
  await wait(settle);
  for (let i = 0; i < 40; i++) {
    try { if (await ev(`document.readyState === 'complete'`)) break; } catch { /* still navigating */ }
    await wait(100);
  }
  await wait(settle);
}
const size = (width, height) => send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
async function shot(name) {
  const { result } = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(result.data, 'base64'));
}
const text = () => ev(`document.body.innerText`);
const overflow = () => ev(`(() => { const w = document.documentElement.clientWidth; const bad = []; if (document.documentElement.scrollWidth > w) bad.push('page ' + document.documentElement.scrollWidth);
  for (const n of document.querySelectorAll('body *')) { const r = n.getBoundingClientRect(); if (r.width && r.right > w + 1 && !n.closest('.drawer')) { bad.push(n.tagName + '.' + n.className + ' ' + Math.round(r.right)); if (bad.length > 4) break; } }
  for (const n of document.querySelectorAll('.scroll,.campaigns,.stage,.prov>section')) if (n.scrollWidth > n.clientWidth + 1) bad.push('inner ' + n.className + ' ' + n.scrollWidth + '>' + n.clientWidth);
  return bad; })()`);
const clearAll = async () => { await ev(`try { localStorage.clear(); sessionStorage.clear(); } catch {}`); await send('Network.clearBrowserCookies').catch(() => {}); };
await send('Network.enable').catch(() => {});

await go('login.html');
await clearAll();

// A visitor with no session goes to login, from / and from any page.
await go('');
await until(`location.pathname === '/login.html'`, 'login', 20).catch(() => null);
const worldOn = await ev(`fetch('/site-api/auth/world').then(r => r.json()).then(s => s.on)`);
await waitText(worldOn ? 'Sign in with World ID' : 'World ID is not set up');
say((await ev(`location.pathname`)) === '/login.html', '/ leads to login with no session', await ev(`location.pathname`));
const offWords = await text();
say(worldOn ? offWords.includes('Sign in with World ID') : offWords.includes('World ID is not set up on this server yet'), worldOn ? 'login offers World ID, as the server says it is set up' : 'login says World ID is not set up');
say(!offWords.includes('Verified human'), 'login shows no verified state');
await shot('live-login');

// Guest flow.
await ev(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Enter as local guest')).click()`);
await until(`location.pathname === '/home.html'`, 'home', 20).catch(() => null);
await waitText('Local guest');
say((await ev(`location.pathname`)) === '/home.html', 'guest reaches home', await ev(`location.pathname`));
const homeText = await text();
say(homeText.includes('Local guest, not verified'), 'sidebar says local guest');
say(!homeText.includes('Verified human'), 'guest never sees verified');

// Local storage cannot claim verified.
await ev(`localStorage.setItem('verified','true'); localStorage.setItem('crashlab-verified','1'); localStorage.setItem('crashlab-guest','1');`);
await go('home.html');
say(!(await text()).includes('Verified human'), 'tampered storage does not show verified');
// A forged cookie cannot either.
await ev(`document.cookie = 'crashlab_login=forged; path=/'`);
await go('home.html');
say(!(await text()).includes('Verified human'), 'forged cookie does not show verified');
const me = await ev(`fetch('/site-api/auth/me').then(r => r.json())`);
say(me.verified === false, 'server refuses a forged cookie', JSON.stringify(me));
await ev(`document.cookie = 'crashlab_login=; path=/; max-age=0'`);

// Every page: loads, links resolve, no overflow, picture saved.
const seen = new Set();
for (const p of [...PAGES, 'bounties']) {
  await size(1440, 900);
  await go(`${p}.html`, 900);
  if (p !== 'bounties') await shot(`live-${p}`);
  const hrefs = await ev(`[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))`);
  hrefs.forEach(h => seen.add(h.split('?')[0]));
  for (const [w, h] of [[1440, 900], [1100, 800]]) {
    await size(w, h);
    await wait(300);
    if (p === 'bounties') continue;
    const bad = await overflow();
    say(bad.length === 0, `${p} at ${w}px has no overflow`, bad.join(', '));
  }
  if (p !== 'bounties') await shot(`live-${p}-1100`);
  await size(1440, 900);
}
for (const h of seen) {
  if (h.startsWith('http') || !h) continue;
  const code = await ev(`fetch(${JSON.stringify(`/${h.replace(/^\//, '')}`)}, { method: 'GET' }).then(r => r.status)`);
  say(code === 200, `link ${h}`, String(code));
}

// Images load.
for (const p of PAGES) {
  await go(`${p}.html`, 900);
  const broken = await ev(`[...document.images].filter(i => !i.complete || !i.naturalWidth).map(i => i.src)`);
  say(broken.length === 0, `${p} images load`, broken.join(', '));
}

// Data: search, sort, filter, row opens the run, no sample words.
await go('data.html?c=campaign_dubai_final', 1000);
await until(`document.querySelectorAll('.lib tbody tr.row').length > 0`, 'library', 20).catch(() => null);
const rows = () => ev(`document.querySelectorAll('.lib tbody tr.row').length`);
const firstCell = () => ev(`document.querySelector('.lib tbody tr.row td')?.textContent`);
say(await rows() === 52, 'campaign_dubai_final shows 52 world rows', String(await rows()));
say((await text()).includes('0e36d3bf97fe'), 'campaign shows its sim version');
await ev(`document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))`);
say(await ev(`document.activeElement.id === 'lib-search'`), 'slash focuses the search');
await ev(`(() => { const i = document.getElementById('lib-search'); i.value = 'detach'; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
await wait(100);
const hits = await rows();
say(hits > 0 && hits < 52, 'search narrows the rows', String(hits));
say(await ev(`[...document.querySelectorAll('.lib tbody tr.row')].every(r => r.querySelector('mark'))`), 'each search hit marks the word');
await shot('live-data-search');
await ev(`(() => { const i = document.getElementById('lib-search'); i.value = ''; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
await ev(`document.querySelector('th[data-sort=id]').click()`);
await wait(60);
const up = await firstCell();
await ev(`document.querySelector('th[data-sort=id]').click()`);
await wait(60);
const down = await firstCell();
say(up === 't0000' && down !== up, 'sort by world flips', `${up} then ${down}`);
await ev(`[...document.querySelectorAll('.chips button')].find(b => b.textContent.startsWith('Passed')).click()`);
await wait(60);
say(await rows() === 3, 'filter shows the 3 passed', String(await rows()));
await ev(`[...document.querySelectorAll('.chips button')].find(b => b.textContent.startsWith('All')).click()`);
await go('data.html?c=demo-inspection', 1000);
await until(`document.querySelectorAll('.lib tbody tr.row').length > 0`, 'library', 20).catch(() => null);
await ev(`document.querySelector('.lib tbody tr.row').click()`);
await wait(300);
say(await ev(`document.querySelector('.drawer').classList.contains('on')`), 'a row opens the run');
const replay = await ev(`document.querySelector('.drawer a.btn')?.getAttribute('href')`);
say(!!replay, 'an inspection run links its replay', String(replay));
await shot('live-data-run');
await go('data.html?c=retest_patched', 800);
say((await text()).includes('kept totals only'), 'totals-only campaign says so');
await go('data.html', 800);
const all = await text();
say(!/\bSample\b|Sign in to CrashLab/.test(all), 'data page holds no sample label');

// Open CrashLab reaches lab.html with the chosen robot.
for (const pack of ['inspection', 'window']) {
  await go('crashlab.html', 800);
  await until(`!!document.querySelector('input[value=${pack}]')`, 'cards', 20);
  await ev(`document.querySelector('input[value=${pack}]').click()`);
  await wait(250);
  await shot(`live-crashlab-${pack}`);
  await ev(`[...document.querySelectorAll('button')].find(b => b.textContent === 'Open CrashLab').click()`);
  await until(`location.pathname === '/lab.html' && !!document.querySelector('.lab-title a')`, 'the lab page', 60).catch(() => null);
  say((await ev(`location.pathname`)) === '/lab.html', `Open CrashLab reaches lab.html for ${pack}`);
  say((await ev(`sessionStorage.getItem('crashlab-pack')`)) === pack, `lab.html has ${pack} preselected`);
  say(await ev(`[...document.querySelectorAll('.lab-title a')].some(a => a.getAttribute('href') === 'home.html')`), 'lab has a way home');
}
await go('home.html', 400);

// Replays open from rows.
await send('Page.navigate', { url: `${BASE}/lab.html?poses=/site-api/replay/inspection/w000` });
const drawn = until(`!!document.querySelector('canvas') && document.body.innerText.includes('recorded_run')`, 'replay', 90).then(() => true, () => false);
const replayOk = await drawn;
await wait(4000);
await shot('live-replay-inspection');
say(replayOk && !(await text()).includes('Could not load'), 'inspection row replay draws');
await send('Page.navigate', { url: `${BASE}/lab.html?trial=demo-window-w000` });
const windowOk = await until(`!!document.querySelector('canvas') && document.body.innerText.includes('recorded_run')`, 'replay', 90).then(() => true, () => false);
await wait(3000);
await shot('live-replay-window');
say(windowOk && !(await text()).includes('Could not load'), 'window row replay draws');

// bounties.html belongs to the board worker, and asks its own server on 5298. That server may be off, and this check does not own it.
const boardOff = problems.filter(p => p.includes('127.0.0.1:5298'));
if (boardOff.length) console.log(`NOTE board server on 5298 is off: ${boardOff.length} refused requests from bounties.html`);
const real = problems.filter(p => !p.includes('127.0.0.1:5298'));
say(real.length === 0, 'no console errors', real.slice(0, 5).join(' | '));
problems.length = 0;

// MOCK: the page reads "verified" only from the server's reply. This reply is invented here, in the browser, to prove the sidebar follows it.
await go('home.html', 200);
await send('Page.addScriptToEvaluateOnNewDocument', { source: `{ const real = window.fetch; window.fetch = (u, o) => String(u).includes('/site-api/auth/me') ? Promise.resolve(new Response(JSON.stringify({ verified: true, credential: 'human', human_id: '0xabc1230000000000000000000000000000def456', environment: 'staging' }))) : real(u, o); }` });
await go('home.html', 700);
say((await text()).includes('Verified human'), 'MOCK: a verified server reply shows Verified human');
await shot('live-mock-verified-state');

// MOCK: the signing flow on the login page, with an invented server and an invented bridge. Nothing leaves this browser.
await send('Page.addScriptToEvaluateOnNewDocument', { source: `{ const real = window.fetch; const json = (v, status = 200) => Promise.resolve(new Response(JSON.stringify(v), { status }));
  window.fetch = (u, o) => { const url = String(u?.url ?? u);
    if (url.includes('/site-api/auth/me')) return json({ verified: false });
    if (url.includes('/site-api/auth/world/context')) return json(${JSON.stringify(MOCK_CTX)});
    if (url.includes('/site-api/auth/world')) return json({ on: true, missing: [] });
    if (url.includes('/request')) return json({ request_id: '4d5f0a1e-7c3b-4f6a-9d21-1a2b3c4d5e6f' });
    if (url.includes('/response/')) return json({ status: 'initialized' });
    return real(u, o); }; try { localStorage.clear(); } catch {} }` });
await go('login.html', 900);
say((await text()).includes('Sign in with World ID'), 'MOCK: with settings, login offers World ID');
await shot('live-mock-login-on');
await ev(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('Sign in with World ID')).click()`);
await wait(3000);
const hasQr = await ev(`!!document.querySelector('.qr svg')`);
say(hasQr, 'MOCK: IDKit builds a request and the page draws its QR code', hasQr ? '' : (await text()).slice(0, 300));
await shot('live-mock-login-verifying');
say(!(await text()).includes('Verified human'), 'MOCK: waiting never shows verified');

b.close();
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
