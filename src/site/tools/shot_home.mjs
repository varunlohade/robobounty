// Pictures of Overview, Failures and Settings at three widths, with an overflow check. Needs vite on 5199 and the site server.
// The empty state is a MOCK: this check answers /site-api/data with no campaigns, in the browser, to draw what a server with no runs shows.
import { randomBytes } from 'node:crypto';
import { writeFileSync } from 'node:fs';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const BASE = `http://localhost:${process.env.CRASHLAB_WEB_PORT ?? 5199}`;
const OUT = process.argv[2] ?? 'design/site2';
const c = await openChrome({ width: 1440, height: 900 });
const { send, js } = c;
let failed = 0;
const say = (ok, what, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'} ${what}${extra ? `: ${extra}` : ''}`); if (!ok) failed += 1; };
const go = async path => { await send('Page.navigate', { url: `${BASE}/${path}` }); await wait(2500); };
const size = (w, h) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
const shot = async name => { const { result } = await send('Page.captureScreenshot', { format: 'png' }); writeFileSync(`${OUT}/${name}.png`, Buffer.from(result.data, 'base64')); };
const overflow = () => js(`(() => { const w = document.documentElement.clientWidth; const bad = []; if (document.documentElement.scrollWidth > w) bad.push('page ' + document.documentElement.scrollWidth);
  for (const n of document.querySelectorAll('body *')) { const r = n.getBoundingClientRect(); if (r.width && r.right > w + 1) bad.push(n.tagName + '.' + n.className + ' ' + Math.round(r.right)); if (bad.length > 4) break; }
  for (const n of document.querySelectorAll('.scroll')) if (n.scrollWidth > n.clientWidth + 1) bad.push('inner ' + n.scrollWidth + '>' + n.clientWidth);
  return bad; })()`);

await go('login.html');
const account = await js(`fetch('/site-api/auth/signup', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CrashLab-Request': '1' }, body: JSON.stringify({ email: 'home-${randomBytes(4).toString('hex')}@example.com', password: 'correct horse battery', company: 'Check Company' }) }).then(r => r.status)`);
say(account === 200 || account === 201, 'a check company signs up', String(account));
const WIDTHS = [[1440, 900], [1100, 800], [390, 844]];
for (const [page, name] of [['home.html', 'home'], ['failures.html', 'failures'], ['settings.html', 'settings']]) {
  await size(1440, 900);
  await go(page);
  for (const [w, h] of WIDTHS) {
    await size(w, h);
    await wait(300);
    const bad = await overflow();
    say(bad.length === 0, `${name} at ${w}px has no overflow`, bad.join(', '));
    await shot(`home-final-${name}-${w}`);
  }
}
await send('Page.addScriptToEvaluateOnNewDocument', { source: `{ const real = window.fetch; window.fetch = (u, o) => String(u).includes('/site-api/data') ? Promise.resolve(new Response(JSON.stringify({ campaigns: [] }))) : real(u, o); }` });
await size(1440, 900);
await go('home.html');
for (const [w, h] of WIDTHS) {
  await size(w, h);
  await wait(300);
  const bad = await overflow();
  say(bad.length === 0, `MOCK empty state at ${w}px has no overflow`, bad.join(', '));
  await shot(`home-final-empty-${w}`);
}
say(c.problems.length === 0, 'no console errors', c.problems.slice(0, 4).join(' | '));
c.close();
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
