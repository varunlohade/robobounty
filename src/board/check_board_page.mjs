// The real page in headless Chrome with its own profile. Needs the vite on 5199 and board_server.py on 5298 with a new, empty root.
// node src/board/check_board_page.mjs <session/cid/group> <fix source file>
import { readFileSync } from 'node:fs';
import { openChrome, wait } from '../lab/tools/browser.mjs';

const [ref, sourcePath] = process.argv.slice(2);
const PAGE = 'http://localhost:5199/bounties.html';
const OUT = new URL('../../design/board/', import.meta.url).pathname;
const chrome = await openChrome({ width: 1440, height: 900 });
const { js, send, until, shot, problems, close } = chrome;
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  ${detail}`); };
const text = () => js('document.body.innerText');
const clickText = (label) => js(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(label)}).click()`);

// The site's login gate: enter as the local guest, as a visitor would. This claims no verified human.
await send('Page.navigate', { url: 'http://localhost:5199/login.html' });
await until(`document.readyState === 'complete'`, 'login page', 15);
await js(`fetch('/site-api/auth/guest', { method: 'POST', headers: { 'X-CrashLab-Request': '1' } })`); // NOTE: a guest can read this page, and cannot post or submit, so the steps below need a company and an engineer.
await send('Page.navigate', { url: PAGE });
await until(`document.querySelector('.sh-app') && document.body.innerText.includes('No bounties yet')`, 'empty state', 15);
await js('document.fonts.ready.then(() => true)');
let body = await text();
const visible = await js(`[...document.fonts].filter(f => f.status === 'loaded').length > 0`);
check('the fonts load, so the text shows', visible);
check('empty state shows, with no sample rows', body.includes('No bounties yet') && !/sample/i.test(body), '');
check('both labels are fixed on the page', body.includes('Local ledger. Not on chain.') && body.includes('World ID is not connected'));
await shot(`${OUT}board-empty.png`);

await send('Page.navigate', { url: `${PAGE}?post=${ref}` });
await until(`document.querySelector('.dialog select')?.value === ${JSON.stringify(ref)}`, 'dialog opened on the deep link', 15);
check('the grid link opens the post dialog on that failure', true, ref);
await shot(`${OUT}board-post.png`);
await js(`(() => { const set = (i, v) => { const e = document.querySelectorAll('.dialog input')[i]; e.value = v; e.dispatchEvent(new Event('input')); }; set(0, 'Robot stalls with a strong fan'); set(1, 'CrashLab test company'); set(2, '40'); set(3, '60'); })()`);
await clickText('Post the bounty');
await until(`!document.querySelector('.dialog') && document.querySelector('tr.row')?.innerText.includes('Robot stalls')`, 'the post shows in the list', 90);
body = await text();
check('a real post shows, with its real failing worlds', body.includes('strong climb') && body.includes('Stalled'));
check('hidden worlds show as counts only', body.includes('Hidden worlds') && body.includes('stay hidden') && body.includes('shows only a count'));
await clickText('Submit a fix');
await until(`document.querySelector('.dialog textarea')?.value.includes('class Controller')`, 'the controller source fills the form', 10);

const source = readFileSync(sourcePath, 'utf8');
await js(`(() => { const inp = document.querySelector('.dialog input'); inp.value = 'ana'; document.querySelector('.dialog textarea').value = ${JSON.stringify(source)}; })()`);
await clickText('Run check, then simulation');
await until(`document.body.innerText.includes('The fix holds on the hidden worlds')`, 'the gate result', 300);
await until(`document.body.innerText.includes('dispute window left')`, 'the dispute window counts', 10);
body = await text();
check('the result shows the real proof counts', body.includes('3 of 3') && body.includes('Held back') && body.includes('Replay re-judge') && !/sample/i.test(body) && body.includes('World ID is not connected'));
await wait(300);
check('no dialog covers the result', await js(`!document.querySelector('.dialog')`));
await js(`document.querySelector('.detail').scrollTop = 0`);
await js('document.fonts.ready.then(() => true)');
await shot(`${OUT}board-real.png`);
check('no console errors', problems.length === 0, problems.join(' | ').slice(0, 300));
const wide = await js(`document.documentElement.scrollWidth <= innerWidth`);
check('no sideways scroll at 1440', wide);
close();
console.log(failed ? `${failed} failed` : 'all passed');
process.exit(failed ? 1 : 0);
