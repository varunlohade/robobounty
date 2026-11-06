// The whole judge flow in headless Chrome, started by scripts/demo.sh on its own ports, with its own Chrome profile and its own board folder.
// node scripts/check_e2e.mjs [--mode recorded|stored|both]. Saves design/e2e/<mode>/NN-step.png and design/e2e/<mode>/timing.json.
// recorded: stored results, no AI and no sim in the lab. stored: stored AI replies and real physics. In both, a fix sent to the board runs real sims, since that proof must be real. No AI call runs.
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openChrome, wait } from '../src/lab/tools/browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '..');
const MODES = arg('mode', 'both') === 'both' ? ['recorded', 'stored'] : [arg('mode')];
const PORTS = { web: 6199, run: 6198, site: 6297, board: 6298 };
const OWNER_PORTS = [5198, 5199, 5297];
const WEB = `http://localhost:${PORTS.web}`;
const GOOD_FIX = readFileSync(join(ROOT, 'policy/bounty/fixtures/fix5/good_match_fan.py'), 'utf8');
const CAMPAIGN_S = 600, AI_FIX_S = 900, PROOF_S = 1500;

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${String(detail).slice(0, 400)}` : ''}`); };
const listening = port => { try { return execFileSync('lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'], { encoding: 'utf8' }).trim().length > 0; } catch { return false; } };

async function flow(mode) {
  const live = mode === 'stored';
  const OUT = join(ROOT, 'design/e2e', mode);
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  const boardRoot = join(ROOT, `policy/runs/board/e2e_${mode}_${Date.now()}`);
  const downloads = mkdtempSync(join(tmpdir(), 'e2e-downloads-'));
  const timing = [];
  const log = [];
  const demo = spawn('bash', [join(ROOT, 'scripts/demo.sh'), mode === 'recorded' ? '--recorded' : '--stored', '--ports', `${PORTS.web},${PORTS.run},${PORTS.site},${PORTS.board}`, '--board-root', boardRoot], { stdio: ['ignore', 'pipe', 'pipe'] });
  demo.stdout.on('data', d => log.push(String(d)));
  demo.stderr.on('data', d => log.push(String(d)));
  const t0 = Date.now();
  while (!log.join('').includes('Press Ctrl+C')) {
    if (demo.exitCode !== null || Date.now() - t0 > 120_000) throw new Error(`demo.sh did not start: ${log.join('')}`);
    await wait(200);
  }
  timing.push({ step: 'npm run demo, until the URL prints', s: (Date.now() - t0) / 1000 });
  check(`${mode}: demo.sh prints the URL`, log.join('').includes(`Open ${WEB}/`));

  const c = await openChrome({ width: 1440, height: 900 });
  await c.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: downloads });
  const text = () => c.js('document.body.innerText');
  const go = path => c.send('Page.navigate', { url: `${WEB}/${path}` });
  const rect = sel => c.js(`(() => { const n = ${sel}; n.scrollIntoView({ block: 'nearest' }); const r = n.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  const clickOn = async sel => { const b = await rect(`document.querySelector(${JSON.stringify(sel)})`); await c.click(b.x, b.y); };
  const clickText = async (label, within = 'body') => {
    const find = `[...document.querySelector(${JSON.stringify(within)}).querySelectorAll('button, a')].find(n => n.textContent.trim().startsWith(${JSON.stringify(label)}))`;
    await c.until(`!!${find}`, `the control "${label}"`, 30);
    const b = await rect(find);
    await c.click(b.x, b.y);
  };
  const say = words => c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(words)}; document.querySelector('.chat-send').click(); })()`);
  const noVerifiedClaim = async where => {
    const words = await text();
    check(`${mode}: ${where} says local guest, never verified`, words.includes('Local guest, not verified') && !words.includes('Verified human'));
  };
  let number = 0;
  const step = async (name, run, settle = 500) => {
    const started = Date.now();
    await run();
    const s = (Date.now() - started) / 1000;
    await wait(settle);
    number += 1;
    const label = `${String(number).padStart(2, '0')}-${name}`;
    await c.shot(join(OUT, `${label}.png`));
    timing.push({ step: label, s });
    console.log(`  ${label} ${s.toFixed(1)} s`);
  };

  try {
    // The address with ?post= must survive the login.
    await step('post-link-without-login', async () => {
      await go('login.html');
      await c.until(`document.readyState === 'complete'`, 'login page', 30);
      await c.js(`localStorage.clear(); sessionStorage.clear()`);
      await go('bounties.html?post=nosession/c1/slip_distance');
      await c.until(`location.pathname === '/login.html'`, 'login after a post link', 30);
      check(`${mode}: login keeps ?post=`, (await c.js('location.search')).includes(encodeURIComponent('bounties.html?post=nosession/c1/slip_distance')), await c.js('location.search'));
    });
    await step('post-link-after-guest', async () => {
      await clickText('Enter as local guest');
      await c.until(`location.pathname === '/bounties.html' && !!document.querySelector('.overlay')`, 'the post dialog after login', 30);
      await c.until(`document.querySelector('.overlay .bad')?.textContent.includes('cannot be posted')`, 'a plain refusal of a bad link', 30);
      await noVerifiedClaim('the bounty page');
    });
    await step('tampered-storage', async () => {
      await c.js(`localStorage.setItem('verified','true'); localStorage.setItem('crashlab-verified','1'); localStorage.setItem('worldid','connected')`);
      await go('bounties.html');
      await c.until(`document.querySelector('.sh-who')?.dataset.who === 'guest'`, 'the side bar', 30);
      await noVerifiedClaim('the bounty page with forged storage');
      check(`${mode}: the board says World ID is not connected`, (await text()).includes('World ID is not connected'));
      await c.js(`localStorage.clear(); sessionStorage.clear()`);
    });

    await step('login', async () => {
      await go('');
      await c.until(`location.pathname === '/login.html' && document.body.innerText.includes('Enter as local guest')`, '/ leads to login', 30);
    });
    await step('home', async () => {
      await clickText('Enter as local guest');
      await c.until(`location.pathname === '/home.html' && document.querySelector('.sh-who')?.dataset.who === 'guest'`, 'home', 30);
    }, 1500);
    await step('crashlab', async () => {
      await clickText('CrashLab', 'nav .sh-item[href="crashlab.html"]').catch(async () => { await go('crashlab.html'); });
      await c.until(`location.pathname === '/crashlab.html' && document.body.innerText.includes('Choose a robot')`, 'crashlab page', 30);
    }, 1200);
    await step('pick-robot', async () => {
      await c.js(`document.querySelector('input[name=robot][value=window]').click()`);
      await clickText('Open CrashLab');
      await c.until(`location.pathname === '/lab.html' && document.getElementById('lab')?.dataset.server === 'up' && document.getElementById('lab')?.dataset.pack === 'window'`, 'the lab', 60);
    }, 1000);
    if (live) {
      await step('ai-builds', async () => {
        await c.until(`!!document.querySelector('.chat-input')`, 'chat', 30);
        await say('Window robot for towers in Dubai. High floor.');
        await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true' && document.querySelector('.chat-test') && !document.querySelector('.chat-test').hidden && !document.querySelector('.chat-test').disabled`, 'the world and one run', 180);
      }, 2000);
      await step('change-world', async () => {
        const idle = await c.js(`document.getElementById('lab').dataset.idle ?? '0'`);
        await say('make the building bronze');
        await c.until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${Number(idle)}`, 'the change', 120);
      }, 2000);
    } else {
      await step('recorded-world', async () => {
        await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true' && document.querySelector('.chat-test') && !document.querySelector('.chat-test').hidden`, 'the stored world', 60);
        check(`${mode}: Recorded run is on screen`, /Recorded run/.test(await text()));
      }, 1500);
      await step('change-world-refused', async () => {
        const idle = await c.js(`document.getElementById('lab').dataset.idle ?? '0'`);
        await say('make the building bronze');
        await c.until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${Number(idle)}`, 'a reply', 30);
        check(`${mode}: words say a recorded run cannot change`, /recorded run, so words cannot change/.test(await text()));
      });
    }
    await step('list-scenarios', async () => {
      await clickOn('.chat-test');
      await c.until(`!!document.querySelector('.chat-run')`, 'the scenario list', 240);
      const card = await c.js(`document.querySelector('.chat-list-card').innerText`);
      check(`${mode}: the list has the guess note`, /guess/i.test(card));
    });
    await step('run-zoom-out', async () => {
      await clickOn('.chat-run');
      await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'the grid', 60);
    }, 3000);
    await step('grid-done', async () => {
      await c.until(`document.querySelector('.grid-page').dataset.done === 'true'`, 'the campaign', CAMPAIGN_S);
      await c.until(`document.querySelectorAll('.sq[data-picture=film]').length >= document.querySelectorAll('.sq:not([data-held=true])').length * 0.9`, 'video squares', 60);
    }, 1000);
    const redSquare = async word => c.js(`document.querySelector('.sq[data-status=failed][aria-label*="${word}."]')?.dataset.index ?? null`);
    const slip = await redSquare('Slipped');
    check(`${mode}: a red Slipped square exists`, slip !== null);
    const replayOk = `document.querySelector('.grid-replay .viewport')?.dataset.ready === 'true' && Number(document.querySelector('.grid-replay .viewport').dataset.frame) > 0`;
    await step('red-square-detail-replay', async () => {
      await clickOn(`.sq[data-index="${slip}"]`);
      await c.until(replayOk, 'the replay', 90);
      const rail = await c.js(`document.querySelector('.grid-rail').innerText`);
      check(`${mode}: the detail shows the judge and the log`, rail.includes('Judge') && rail.includes('Last log lines'));
      check(`${mode}: the charts mark the failure`, await c.js(`document.querySelectorAll('.spark .spark-fail').length > 0`));
      check(`${mode}: no bounty offer before an AI try`, !(await c.js(`!!document.querySelector('.grid-post')`)));
    }, 2500);
    await step('open-in-rerun', async () => {
      await clickText('Open in Rerun', '.grid-file');
      await c.until(`document.querySelector('.grid-page').dataset.rerun === 'done'`, 'the Rerun file', 300);
      await wait(800);
      const file = readdirSync(downloads).find(f => f.endsWith('.rrd'));
      check(`${mode}: Open in Rerun downloads a real .rrd`, Boolean(file) && readFileSync(join(downloads, file)).subarray(0, 3).toString() === 'RRF', file);
    });
    await step('open-file', async () => {
      await clickText('Open file', '.grid-file');
      await c.until(`!!document.querySelector('.code-page .cm-code-focus')`, 'the file at its line', 30);
    }, 1000);

    if (live) {
      const coverage = await redSquare('Low coverage');
      await step('edit', async () => {
        await clickOn('.lab-tab-grid');
        await c.until(`!!document.querySelector('.grid-page')`, 'the grid again', 10);
        await clickOn(`.sq[data-index="${coverage}"]`);
        await clickText('Open file', '.grid-file');
        await c.until(`!!document.querySelector('.code-page .cm-editor')`, 'the editor', 30);
        await c.js(`(() => { const v = __lab.code().view; const s = v.state.doc.toString(); const at = s.indexOf('MAX_RETREATS_PER_LANE = 3'); v.dispatch({ changes: { from: at, to: at + 'MAX_RETREATS_PER_LANE = 3'.length, insert: 'MAX_RETREATS_PER_LANE = 2' } }); })()`);
        await c.until(`document.querySelector('.code-state').textContent.includes('not run yet')`, 'the edit shows', 5);
      });
      await step('re-run', async () => {
        await clickText('Run this world', '.code-page');
        await c.until(`!document.querySelector('.code-results').hidden`, 'the re-run', 300);
      }, 800);
      await step('re-run-square-has-picture', async () => {
        await clickOn('.lab-tab-grid');
        await c.until(`document.querySelector('.sq[data-index="${coverage}"]')?.dataset.picture === 'film'`, 'the re-run square film', 30);
        const url = await c.js(`performance.getEntriesByType('resource').map(e => e.name).filter(n => n.includes('film.jpg?run=r')).pop() ?? ''`);
        check(`${mode}: the square draws the re-run's own film`, url.includes(`worlds/${coverage}/film.jpg?run=r`), url);
        await clickOn(`.sq[data-index="${coverage}"]`);
        await c.until(`document.querySelector('.grid-rail')?.innerText.includes('Before and after')`, 'before and after note', 30);
        check(`${mode}: the note says before and after`, /Before: .* After: /s.test(await c.js(`document.querySelector('.grid-rail').innerText`)));
      }, 1500);
      await step('reset-to-source', async () => {
        await clickText('Open file', '.grid-file');
        await c.until(`!!document.querySelector('.code-page .cm-editor')`, 'the editor', 30);
        await clickText('Reset to source', '.code-page');
        await c.until(`document.querySelector('.code-state').textContent.includes('Same as source')`, 'the reset', 20);
        await clickOn('.lab-tab-grid');
        await clickOn(`.sq[data-index="${slip}"]`);
        await clickText('Open file', '.grid-file');
        await c.until(`!!document.querySelector('.code-page .cm-editor')`, 'the editor', 30);
      });
    } else {
      check(`${mode}: a re-run is off, with a plain reason`, await c.js(`[...document.querySelectorAll('.code-page .grid-btn')].find(b => b.textContent === 'Run this world').disabled`) && /recorded run/i.test(await c.js(`document.querySelector('.code-foot').textContent`)));
    }

    await step('ask-ai-did-not-help', async () => {
      await clickOn('.code-ai');
      await c.until(`!!document.querySelector('.code-fix')`, 'the AI fix result', AI_FIX_S);
      const card = await c.js(`document.querySelector('.code-fix').innerText`);
      check(`${mode}: the fix did not help, in plain words`, /did not help/i.test(card), card.slice(0, 200));
      check(`${mode}: the card offers Post a bounty`, /Post a bounty/.test(card));
      if (!live) {
        check(`${mode}: the card says recorded result`, /Recorded result/.test(card));
        check(`${mode}: the stored numbers: held-back 1 better, 13 same`, /Held back, never seen \(14\)\s*1\s*0\s*13/.test(card));
      } else check(`${mode}: the card says a stored AI edit`, /Stored AI edit/.test(card), card.slice(0, 200));
      await c.js(`document.querySelector('.code-fix').scrollIntoView({ block: 'end' })`);
    }, 800);

    let ref = '';
    await step('post-a-bounty-link', async () => {
      ref = new URL(await c.js(`document.querySelector('.code-fix-bounty').href`)).searchParams.get('post');
      await clickOn('.code-fix-bounty');
      await c.until(`location.pathname === '/bounties.html' && !!document.querySelector('.overlay select')?.value`, 'the post dialog', 60);
      check(`${mode}: the dialog holds this failure`, (await c.js(`document.querySelector('.overlay select').value`)) === ref, ref);
      await noVerifiedClaim('the bounty page');
    });
    const session = ref.split('/')[0];
    const fillPost = (company, title) => c.js(`(() => { const inputs = [...document.querySelectorAll('.overlay input')]; inputs[0].value = ${JSON.stringify(title)}; inputs[1].value = ${JSON.stringify(company)}; })()`);
    await step('bounty-shows', async () => {
      await fillPost('Tower Services (test company)', 'The robot slides on low suction');
      await clickText('Post the bounty', '.overlay');
      await c.until(`!document.querySelector('.overlay') && document.body.innerText.includes('The robot slides on low suction')`, 'the slip bounty', 60);
    }, 800);
    // No fix for the slip exists yet. The real fix on file is for the stalled worlds, so the paid path uses that failure of the same run.
    await step('second-bounty', async () => {
      await clickText('Post a bounty', '.sh-actions');
      await c.until(`[...document.querySelectorAll('.overlay select option')].some(o => o.value === ${JSON.stringify(`${session}/${ref.split('/')[1]}/stalled`)})`, 'the stalled failure', 30);
      await c.js(`document.querySelector('.overlay select').value = ${JSON.stringify(`${session}/${ref.split('/')[1]}/stalled`)}; document.querySelector('.overlay select').dispatchEvent(new Event('change'))`);
      await fillPost('Tower Services (test company)', 'The robot stops short near the top');
      await clickText('Post the bounty', '.overlay');
      await c.until(`!document.querySelector('.overlay') && document.body.innerText.includes('The robot stops short near the top')`, 'the stalled bounty', 60);
    }, 800);
    await step('submit-a-fix', async () => {
      await clickText('Submit a fix', '.detail');
      await c.until(`document.querySelector('.overlay textarea')?.dataset.ready === '1'`, 'the source', 30);
      await c.js(`(() => { document.querySelector('.overlay input').value = 'ana'; document.querySelector('.overlay textarea').value = ${JSON.stringify(GOOD_FIX)}; })()`);
      await clickText('Run check, then simulation', '.overlay');
      await c.until(`!document.querySelector('.overlay')`, 'the submit', 30);
    }, 3000);
    await step('hidden-world-proof', async () => {
      await c.until(`[...document.querySelectorAll('.detail button')].some(b => b.textContent.trim() === 'Finalize') || /Refused|Not fixed|Worse on hidden|Overfit|Limit hit|Replay differs|Stopped/.test(document.querySelector('.detail').innerText.split('Submission')[1] ?? '')`, 'the proof', PROOF_S);
      const detail = await c.js(`document.querySelector('.detail').innerText`);
      check(`${mode}: the proof passes on hidden worlds`, /The fix holds on the hidden worlds/.test(detail), detail.slice(0, 200));
      check(`${mode}: the page names only counts for hidden worlds`, /stay hidden/.test(detail));
      await c.js(`[...document.querySelectorAll('.detail h2')].find(n => n.textContent.includes('Payout'))?.scrollIntoView({ block: 'center' })`);
    }, 800);
    await step('dispute-window', async () => {
      await c.until(`[...document.querySelectorAll('.detail button')].find(b => b.textContent.trim() === 'Reject in the window')?.disabled === false`, 'the open window', 10).catch(() => {});
      await c.js(`[...document.querySelectorAll('.detail h2')].find(n => n.textContent.includes('Payout'))?.scrollIntoView({ block: 'center' })`);
    }, 300);
    await step('finalize', async () => {
      await c.until(`[...document.querySelectorAll('.detail button')].find(b => b.textContent.trim() === 'Finalize')?.disabled === false`, 'the end of the window', 300);
      await clickText('Finalize', '.detail');
      await c.until(`[...document.querySelectorAll('.detail button')].some(b => b.textContent.trim() === 'Claim')`, 'finalized', 30);
      await c.js(`[...document.querySelectorAll('.detail h2')].find(n => n.textContent.includes('Payout'))?.scrollIntoView({ block: 'center' })`);
    });
    await step('claim', async () => {
      await c.js(`(() => { const who = document.querySelector('.detail .acts input'); who.value = 'ana'; [...document.querySelectorAll('.detail button')].find(b => b.textContent.trim() === 'Claim').click(); })()`);
      await c.until(`document.querySelector('.detail').innerText.includes('claimed')`, 'the claim', 30);
      check(`${mode}: pay is in test units, with the ledger label`, /test units/.test(await c.js(`document.querySelector('.detail').innerText`)) && /Local ledger\. Not on chain\./.test(await text()));
      await c.js(`[...document.querySelectorAll('.detail h2')].find(n => n.textContent.includes('Payout'))?.scrollIntoView({ block: 'center' })`);
    });
    await step('data-shows-runs', async () => {
      await clickText('Data', 'nav');
      await c.until(`location.pathname === '/data.html' && !!document.querySelector('.campaigns')?.children.length`, 'the data page', 30);
      const words = await c.js(`document.querySelector('.campaigns').innerText`);
      if (live) check(`${mode}: Data lists this lab run`, words.includes(`Lab run ${session.slice(0, 8)}`), words.slice(0, 200));
      else check(`${mode}: Data lists the stored window batch`, /Window|window/.test(words), words.slice(0, 200));
    }, 1000);
    check(`${mode}: no console errors`, c.problems.length === 0, [...new Set(c.problems)].slice(0, 6).join(' | '));
  } catch (err) {
    check(`${mode}: the flow finished`, false, String(err));
    try { await c.shot(join(OUT, 'failure.png')); console.log('body:', (await text()).slice(0, 600)); } catch { /* the page is gone */ }
  } finally {
    c.close();
  }

  const stopped = Date.now();
  demo.kill('SIGINT');
  while (demo.exitCode === null && Date.now() - stopped < 15_000) await wait(100);
  check(`${mode}: Ctrl+C stops all four servers`, Object.values(PORTS).every(p => !listening(p)), Object.values(PORTS).filter(listening).join());
  check(`${mode}: the owner's servers still run`, OWNER_PORTS.every(listening), OWNER_PORTS.filter(p => !listening(p)).join());
  writeFileSync(join(OUT, 'timing.json'), `${JSON.stringify(timing, null, 1)}\n`);
  rmSync(downloads, { recursive: true, force: true });
  rmSync(boardRoot, { recursive: true, force: true });
  return timing;
}

for (const mode of MODES) {
  console.log(`\n== ${mode}`);
  const timing = await flow(mode);
  for (const t of timing) console.log(`${String(t.s.toFixed(1)).padStart(7)} s  ${t.step}`);
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 300);
