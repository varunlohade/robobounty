// The live app: chat on the left, and on the right whatever the run server's events say is true now.
import { el, icon } from './dom.ts';
import { ChatPanel } from './chat/panel.ts';
import { LiveBackend, health, type ServerEvent } from './chat/live.ts';
import { RecordedBackend } from './chat/recorded.ts';
import { Replay, loadMujoco, wasmStats } from './replay.ts';
import { SimView } from './view.ts';
import { worldPage } from './world_page.ts';
import { WorldsPage } from './worlds_page.ts';
import { FixPage } from './fix_page.ts';
import { BountyPage } from './bounty_page.ts';
import { loadTrialFrom, type Trial, type WorldRun, type WorldsData } from './trial.ts';

const CHAPTERS = ['Brief', 'Worlds', 'Test', 'Find', 'Fix', 'Bounty'];

function chapterBar() {
  const root = el('div', 'chapters');
  const play = el('button', 'icon-btn');
  play.setAttribute('aria-label', 'Play or pause the run');
  play.disabled = true;
  play.append(icon('play'));
  const line = el('div', 'chapter-line');
  const items = CHAPTERS.map(name => {
    const item = el('div', 'chapter');
    item.append(el('i'), el('span', '', name));
    line.append(item);
    return item;
  });
  const step = el('div', 'chapter-step', 'Step 1 of 6');
  root.append(play, line, step);
  const set = (index: number, note?: string | null) => {
    items.forEach((item, i) => {
      item.classList.toggle('done', i < index);
      item.classList.toggle('now', i === index);
    });
    root.dataset.current = CHAPTERS[index];
    step.textContent = `Step ${index + 1} of 6${note ? `: ${note}` : ''}`;
  };
  set(0);
  return { root, set, play };
}

// Each run shows the code that produced it. The tab fills in after the first run.
function codeText(page: HTMLElement, text: string, head: string) {
  const pre = el('pre', 'code');
  pre.tabIndex = 0;
  for (const line of text.replace(/\n$/, '').split('\n')) pre.append(el('span', 'code-line', line));
  page.replaceChildren(el('div', 'code-head', head), pre);
}

export async function liveApp(app: HTMLElement, title: HTMLElement, recorded: WorldsData | null = null) {
  const statusEnd = el('div', 'status-end');
  const counts = el('span');
  const simLine = el('span', '', 'sim unknown');
  const llmLine = el('span', '', 'LLM unknown');
  const llmCount = el('span');
  const bountyLabel = el('span', 'status-ledger');
  const worldLabel = el('span', 'status-ledger');
  const receiptLine = el('span', 'status-keep');
  statusEnd.append(counts, simLine);

  const worldHost = el('div', 'page');
  const worldEmpty = el('div', 'page-text');
  worldEmpty.append(el('h2', '', 'No world yet'), el('p', '', 'Describe your robot and where it works. The world builds here.'));
  worldHost.append(worldEmpty);
  const worldsView = new WorldsPage(run => void openReplay(run), text => { counts.textContent = text; }, run => !recorded || !!run.trial);
  const reportPage = el('div', 'page page-text report');
  reportPage.append(el('h2', '', 'No report yet'), el('p', '', 'The report comes after the campaign.'));
  const codePage = el('div', 'page page-text');
  codePage.append(el('h2', '', 'No run yet'), el('p', '', 'The code shows here after the normal run.'));

  const fixView = new FixPage();
  let lastFailedWorld: unknown = null;
  const bountyView = new BountyPage({
    act: action => backend.act(action),
    submit: (world, seed) => backend.submit(world, seed),
    sampleWorld: () => (lastFailedWorld ? JSON.stringify(lastFailedWorld, null, 1) : null),
    worldContext: () => (backend as LiveBackend).worldContext(),
    worldVerify: result => (backend as LiveBackend).worldVerify(result),
  });
  const pages: [string, HTMLElement][] = [['World', worldHost], ['Worlds', worldsView.page], ['Fix', fixView.page], ['Bounty', bountyView.page], ['Report', reportPage], ['controller.py', codePage]];
  const TAB = { worlds: 1, fix: 2, bounty: 3, report: 4, code: 5 };
  const tabs = el('nav', 'tabs');
  tabs.setAttribute('role', 'tablist');
  const pane = el('main', 'pane');
  const buttons: HTMLButtonElement[] = [];
  const show = (index: number) => {
    pages.forEach(([, page], i) => { page.hidden = i !== index; });
    buttons.forEach((b, i) => b.setAttribute('aria-selected', String(i === index)));
  };
  pages.forEach(([name, page], i) => {
    const tab = el('button', 'tab', name);
    tab.setAttribute('role', 'tab');
    tab.addEventListener('click', () => show(i));
    buttons.push(tab);
    tabs.append(tab);
    pane.append(page);
  });
  show(0);

  const bar = chapterBar();
  let clear: () => void = () => {};
  const swap = (next: HTMLElement, stop: () => void) => {
    clear();
    clear = stop;
    worldHost.replaceChildren(next);
    show(0);
  };

  async function showWorld(e: ServerEvent) {
    const area = e.area as Trial['manifest']['area'];
    const mj = await loadMujoco();
    const t1 = performance.now();
    const model = mj.MjModel.from_xml_string(e.xml);
    const nq = model.nq;
    const qpos0 = new Float64Array(model.qpos0);
    model.delete();
    const trial: Trial = {
      manifest: { id: 'preview', label: 'preview', hz: 1, nq, frames: 1, python_mujoco: 'none', area, friction: e.facts.friction,
        dirt: { nx: 1, nz: 1, every_steps: 1, scale: 1, clean_below: 1, count: 1 } },
      xml: e.xml, qpos: qpos0, result: { passed: true, failure: null, seed: 0, time_s: 0, coverage: 0, steps: 0, fired: {} },
      world: e.world, worldText: '', controller: '', trace: { columns: [], rows: [] }, wind: [], dirt: new Uint8Array(1),
    };
    const page = el('div', 'world-body');
    const rail = el('aside', 'rail');
    const viewport = el('div', 'viewport');
    const moved = new Set(e.moved as string[]);
    rail.append(el('div', 'rail-note', 'Values of this world. Bold ones came from your words or answers.'));
    const facts = el('div', 'facts');
    for (const [name, value] of Object.entries(e.world as Record<string, unknown>)) {
      if (name === 'schema') continue;
      const row = el('div', moved.has(name) ? 'fact fact-moved' : 'fact');
      row.append(el('span', '', name), el('span', '', typeof value === 'object' ? JSON.stringify(value) : String(value)));
      facts.append(row);
    }
    rail.append(facts);
    viewport.append(el('div', 'sim-tag sim-label', 'Simulated. World preview. No robot has run yet.'));
    page.append(rail, viewport);
    let view: SimView | null = null, replay: Replay | null = null;
    swap(page, () => { view?.dispose(); replay?.dispose(); });
    replay = new Replay(mj, trial);
    replay.seek(0);
    view = new SimView(viewport, replay, trial);
    view.sync();
    const t2 = performance.now();
    viewport.dataset.ready = 'true';
    viewport.dataset.hash = String(e.hash);
    title.replaceChildren(el('span', '', `World ${String(e.hash).slice(0, 12)}`));
    const cx = (area.x0 + area.x1) / 2, cz = (area.z0 + area.z1) / 2;
    const [rx, , rz] = replay.bodyPos('robot');
    chat.addEvent({ type: 'tool', title: 'load_in_browser', meta: `${(t2 - t1).toFixed(0)} ms`, lines: [JSON.stringify({ wasm_module_ms: Math.round(wasmStats.ms), compile_and_draw_ms: Math.round(t2 - t1), nq })] });
    chat.addEvent({
      type: 'views', title: 'look_at_world',
      note: 'Pictures of the model, drawn in your browser. The AI did not look at them. The checks above came from code.',
      images: [
        { label: 'Facade', src: view.snapshot([cx - 3, -11, cz + 2], [cx, 0, cz]) },
        { label: 'Robot', src: view.snapshot([rx - 0.7, -1.6, rz + 0.5], [rx, 0, rz]) },
      ],
    });
  }

  async function showTrial(tid: string, open: boolean) {
    const trial = await loadTrialFrom(backend.trialBase(tid));
    const statusRight = el('div');
    const world = worldPage(trial, statusRight);
    swap(world.page, () => world.stop());
    await world.start();
    world.viewport.dataset.tid = tid;
    bar.play.disabled = false;
    bar.play.onclick = () => world.toggle();
    codeText(codePage, trial.controller, 'controller.py, read only. This copy recorded the run on the World tab.');
    if (!open) show(1);
  }

  async function openReplay(run: WorldRun) {
    await backend.act({ label: 'replay', action: 'replay', value: run.index });
  }

  function report(e: ServerEvent) {
    const numbers = el('div', 'big-numbers');
    for (const row of e.numbers as { n: number; label: string }[]) {
      const box = el('div', 'big-number');
      box.append(el('b', '', String(row.n)), el('span', '', row.label));
      numbers.append(box);
    }
    reportPage.replaceChildren(
      el('h2', '', 'Report'), numbers,
      el('p', '', `${e.recorded ? `Recorded run: nothing ran now. The campaign took ${e.seconds} s on this Mac, before its diagnosis.` : `The campaign and its diagnosis took ${e.seconds} s on this Mac.`} Stopped and held on: ${e.safe_holds}. Numerical divergence: ${e.diverged}.`),
      el('p', '', e.fixes),
      el('p', '', `Simulated. Hand-built physics, not checked against real hardware. Sim ${String(e.sim_recorded ?? 'unknown').slice(0, 8)} recorded these results.`),
    );
    chat.addEvent({ type: 'tool', title: 'report', meta: `${e.seconds} s`, lines: [(e.numbers as { n: number; label: string }[]).map(r => `${r.n} ${r.label}`).join(', '), e.fixes] });
  }

  void loadMujoco();
  const onEvent = async (e: ServerEvent) => {
    switch (e.type) {
      case 'chapter': bar.set(e.index, e.note); break;
      case 'world': await showWorld(e); break;
      case 'trial': await showTrial(e.tid, e.open); break;
      case 'sim': simLine.textContent = `sim ${e.sha ? String(e.sha).slice(0, 8) : 'unknown'}${e.sha && e.sha !== e.now ? `, now ${String(e.now).slice(0, 8)}: results are from older code` : ''}`; break;
      case 'plan':
        worldsView.setPlan(e as never);
        buttons[1].textContent = `${e.total} worlds`;
        break;
      case 'reset_campaign':
        worldsView.clear();
        buttons[1].textContent = 'Worlds';
        break;
      case 'pipeline':
        worldsView.setPipeline(e.stages);
        if (e.stages.every((x: { name: string; state: string }) => x.name !== 'fixing' || x.state !== 'now')) show(TAB.worlds);
        break;
      case 'result':
        worldsView.addResult(e as never);
        if (!e.passed && e.failure && e.kind !== 'elements') lastFailedWorld = e.world;
        break;
      case 'llm_count': llmCount.textContent = `AI calls ${e.used} of ${e.cap}`; break;
      case 'fix': fixView.show(e); show(TAB.fix); break;
      case 'fix_decision':
        fixView.decided(e);
        if (e.code) codeText(codePage, e.code, `controller.py, session copy ${e.copy_sha}. The real file did not change (${e.real_sha}). Runs here still use the real file.`);
        break;
      case 'bounty_draft': bountyView.showDraft(e); bountyLabel.textContent = e.label; worldLabel.textContent = e.world.label; show(TAB.bounty); break;
      case 'ledger': bountyView.showLedger(e); bountyLabel.textContent = e.label; break;
      case 'world_id': bountyView.showWorld(e.world); break;
      case 'llm_used':
        receiptLine.textContent = e.line;
        receiptLine.title = `${e.limits} Request IDs: ${e.request_ids.join(', ') || 'none'}. File: ${e.file}. Hash chain head: ${e.commit}.`;
        break;
      case 'gate_running': bountyView.gateRunning(e); break;
      case 'verdict': bountyView.showVerdict(e); break;
      case 'failures': worldsView.setFailures(e as never); break;
      case 'report': report(e); break;
      case 'idle': app.dataset.idle = String(Number(app.dataset.idle ?? 0) + 1); break;
    }
  };
  const backend = recorded ? new RecordedBackend(onEvent, recorded) : new LiveBackend(onEvent);

  const chat = new ChatPanel(backend, tab => show(tab === 'worlds' ? TAB.worlds : TAB.code), 'Simulated');
  const chatHead = el('div', 'chat-head');
  const mode = el('a', 'chat-mode', recorded ? 'Live run' : 'Recorded run');
  mode.href = recorded ? 'app.html' : '?recorded=1';
  chatHead.append(el('span', '', 'Chat'), mode);
  const newChat = el('button', 'icon-btn');
  newChat.setAttribute('aria-label', 'New chat');
  newChat.title = 'New chat';
  newChat.append(icon('plus', true));
  newChat.addEventListener('click', () => chat.reset());
  chatHead.append(newChat);

  const status = el('footer', 'status');
  status.append(el('span', '', 'Simulated'), llmLine, receiptLine, llmCount, bountyLabel, worldLabel, el('span', '', 'Hand-built physics, not checked against real hardware'), statusEnd);
  app.classList.add('live');
  app.append(chatHead, el('div', 'head-rule'), tabs, chat.root, divider(), pane, bar.root, status);

  if (recorded) {
    title.textContent = 'Recorded run';
    llmLine.textContent = 'Recorded run. No AI ran now.';
    app.dataset.recorded = 'true';
    return;
  }
  try {
    const info = await health();
    simLine.textContent = `sim ${info.sim_sha.slice(0, 8)}`;
    llmLine.textContent = `LLM: ${info.llm}`;
    llmLine.title = llmLine.textContent;
    app.dataset.server = 'up';
  } catch {
    chat.addEvent({ type: 'text', fail: true, text: 'The run server is not running. Start it: policy/.venv/bin/python policy/server/server.py, or open the Recorded run.' });
    llmLine.textContent = 'Run server not connected';
  }
}

function divider(): HTMLElement {
  const bar = el('div', 'divider');
  bar.setAttribute('role', 'separator');
  bar.setAttribute('aria-orientation', 'vertical');
  bar.title = 'Drag to resize';
  const styles = getComputedStyle(document.documentElement);
  const min = parseFloat(styles.getPropertyValue('--chat-width-min'));
  const max = parseFloat(styles.getPropertyValue('--chat-width-max'));
  bar.addEventListener('pointerdown', down => {
    bar.setPointerCapture(down.pointerId);
    bar.classList.add('dragging');
    const move = (e: PointerEvent) => {
      const w = Math.max(min, Math.min(max, e.clientX));
      document.documentElement.style.setProperty('--chat-width', `${w}px`);
    };
    const up = () => {
      bar.classList.remove('dragging');
      bar.removeEventListener('pointermove', move);
      bar.removeEventListener('pointerup', up);
    };
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', up);
  });
  return bar;
}
