import { el } from '../app/dom.ts';
import { ENGINEER_HOME, loginHref, me } from '../site/auth.ts';
import { mountRail } from '../site/shell.ts';
import { icon } from '../site/icons.ts';
import { LiveBackend, SERVER, health, type ServerEvent } from '../app/chat/live.ts';
import { Replay, loadMujoco } from '../app/replay.ts';
import { isV5, loadTrial, loadTrialFrom, type Trial } from '../app/trial.ts';
import { SimView, restoreOnLoss } from '../app/view.ts';
import { LABEL, THIS_RUN_LABEL, worldPage } from '../app/world_page.ts';
import { lookOf } from '../view/real/look.ts';
import { LabChat, replayNote } from './chat.ts';
import { CodeTab } from './code_tab.ts';
import { Grid } from './grid.ts';
const HIDE_AI = import.meta.env.VITE_HIDE_AI === '1'; // A film can leave out which AI answers.
import { PosesView, loadPoses, posesPage, previewReplay, type PoseReplay } from './poses.ts';

// Signed-out visitors go to login and come back here. With no site server the lab still opens, because nobody can sign in then.
void me().then(m => { if (!m.signedIn && !m.offline) location.replace(loginHref()); else if (m.role === 'engineer') location.replace(ENGINEER_HOME); });

const HEALTH_RETRY_MS = 2_000;
const TRIAL_TRIES = 3;
const TRIAL_RETRY_MS = 3_000;
const TRIAL_DEADLINE_MS = 15_000;
const PACK_KEY = 'crashlab-pack';

function chosenPack(): string | null {
  try { return sessionStorage.getItem(PACK_KEY); } catch { return null; }
}
function choosePack(pack: string) {
  try { sessionStorage.setItem(PACK_KEY, pack); } catch { /* no storage: the page keeps the window robot */ }
}
function titleBar(name: HTMLElement): HTMLElement {
  const bar = el('header', 'lab-title');
  const way = el('a', 'lab-way');
  way.href = 'simulation.html';
  way.append(icon('back'), 'Simulation');
  bar.append(way, name);
  return bar;
}

// The window around the chat column: title, tab, main area and status bar. The title and the tab always carry the same plain name.
function shell(root: HTMLElement, chat: HTMLElement) {
  const name = el('div', 'lab-name', 'CrashLab');
  const tab = el('div', 'lab-tab', 'new.world');
  const setName = (plain: string) => {
    name.textContent = `CrashLab — ${plain}`;
    tab.textContent = `${plain}.world`;
    document.title = `${plain} — CrashLab`;
  };
  const tabs = el('div', 'lab-tabs');
  tabs.append(tab);
  const gridTab = el('button', 'lab-tab lab-tab-grid', 'test_run.grid');
  gridTab.type = 'button';
  gridTab.hidden = true;
  tabs.append(gridTab);
  const main = el('main', 'lab-main');
  main.append(tabs);
  const body = el('div', 'lab-body');
  body.append(chat, main);
  const statusRight = el('div', 'lab-status-end');
  const status = el('footer', 'lab-status');
  status.append(statusRight);
  root.append(mountRail(root), titleBar(name), body, status);
  return { main, statusRight, setName, tab, gridTab, tabs };
}

async function replayOnly(root: HTMLElement, id: string) {
  let trial;
  try {
    trial = await loadTrial(id);
  } catch (err) {
    root.append(el('div', 'sim-error', `Could not load the recorded run.\n${String(err)}`));
    return;
  }
  const { main, statusRight, setName } = shell(root, replayNote());
  setName('recorded_run');
  const world = worldPage(trial, statusRight);
  main.append(world.page);
  try {
    const replay = await world.start();
    statusRight.append(el('span', '', `Recorded in MuJoCo ${trial.manifest.python_mujoco}, shown with ${replay.version}`));
  } catch (err) {
    world.viewport.append(el('div', 'sim-error', `MuJoCo could not load this model in the browser, so there is no 3D view.\n${String(err)}`));
  }
}

// A pack's replay file opened by address.
async function posesOnly(root: HTMLElement, url: string) {
  const { main, statusRight, setName } = shell(root, replayNote());
  setName('recorded_run');
  try {
    const replay = await loadPoses(url);
    const world = posesPage(replay, statusRight);
    main.append(world.page);
    world.start();
    (window as unknown as { __lab: unknown }).__lab = { view: () => world.view, jump: world.jump };
  } catch (err) {
    main.append(el('div', 'sim-error', `Could not load the recorded run.\n${String(err)}`));
  }
}

// A name for the title bar from the user's words: the place they name, else the fixed tower.
function plainName(said: string[]): string {
  for (const text of said) {
    const place = text.match(/\btowers?\s+in\s+([a-z]+)/i) ?? text.match(/\b(?:in|at|near)\s+([A-Z][a-z]+)/);
    if (place) return `${place[1].toLowerCase()}_tower`;
  }
  return 'window_tower';
}

// What this session has already built, so a reload, a reconnect, an undo or a tab change never builds it again. Only for the blueprint effect.
function buildMemory(session: () => string) {
  const own = new Map<string, string[]>(); // No storage: remembered for this page only.
  const read = (key: string): string[] | null => {
    try { const held = sessionStorage.getItem(key); if (held) return JSON.parse(held) as string[]; } catch { /* no storage, or a bad value */ }
    return own.get(key) ?? null;
  };
  return (objects: string[]) => {
    const key = `crashlab-built-${session()}`, seen = read(key);
    const all = [...new Set([...(seen ?? []), ...objects])];
    own.set(key, all);
    try { sessionStorage.setItem(key, JSON.stringify(all)); } catch { /* the page's own copy is enough */ }
    return { first: seen === null, fresh: seen === null ? [] : [...new Set(objects)].filter(o => !seen.includes(o)) };
  };
}
const windowObjects = (world: unknown): string[] => isV5(world as Record<string, unknown>) ? ((world as { objects: { name: string }[] }).objects).map(o => o.name) : [];
const plantObjects = (scene: Pick<PoseReplay, 'solids' | 'scenery'>): string[] => [...scene.solids, ...scene.scenery].map(p => p.object ?? p.name ?? '').filter(Boolean);

async function live(root: HTMLElement) {
  const pack = chosenPack();
  root.dataset.pack = pack ?? 'window';
  const built = buildMemory(() => backend.id);
  let runLabel = THIS_RUN_LABEL;
  const onEvent = async (e: ServerEvent) => {
    switch (e.type) {
      case 'pose_world': showPoseWorld(e); break;
      case 'pose_trial': await showPoseTrial(String(e.url)); break;
      case 'scenarios': scenarios = e; chat.scenarios(e); grid?.setScenarios(e); break;
      case 'grid': onGrid(e); code.setGrid(e); break;
      case 'code_run': case 'code_changed': case 'code_fix': case 'code_fix_decided': code.event(e); break;
      case 'campaign_done': await onCampaignDone(e); break;
      case 'world': await showWorld(e); break;
      case 'no_world': clear(); clear = () => {}; current = () => null; host.replaceChildren(empty); setName('new'); chat.worldGone(); break;
      case 'look': applyLook(e); break;
      case 'view': applyView(e); break;
      case 'camera': if (e.box) current()?.frameOn(e.box); else current()?.backToRobot(); break;
      case 'trial': await showTrial(e.tid); break;
      case 'llm_route': routeLine = HIDE_AI ? '' : `LLM: ${e.label}`; llmLine.textContent = routeLine; chat.llmRoute(e); break;
      case 'llm_count': aiLine.textContent = `AI calls ${e.used} of ${e.cap}`; break;
      case 'sim': simLine.textContent = e.label ? String(e.label) : `Sim ${e.sha ? String(e.sha).slice(0, 8) : 'unknown'}${e.sha && e.sha !== e.now ? `, now ${String(e.now).slice(0, 8)}: this run is from older code` : ''}`; break;
      case 'idle':
        root.dataset.idle = String(Number(root.dataset.idle ?? 0) + 1);
        chat.jobDone();
        code.jobDone();
        break;
    }
  };
  const backend = new LiveBackend(onEvent, pack ? { pack } : { engine: 'v5' });
  const chat = new LabChat(backend, pack ?? 'window');
  chat.onPick = next => { choosePack(next); backend.reset(); };
  const { main, statusRight, setName, tab, gridTab, tabs } = shell(root, chat.root);
  const code = new CodeTab({
    session: () => backend.id!,
    tabs,
    show: page => { swap(page, () => {}); tab.classList.add('off'); },
    back: () => { if (grid) showGrid(); else again?.(); },
    chat: node => chat.attach(node),
    note: (text, fail) => chat.note(text, fail),
  });
  const simLine = el('span');
  const llmLine = el('span');
  let routeLine = '';
  const aiLine = el('span');
  statusRight.append(llmLine, aiLine, simLine);

  const host = el('div', 'page');
  const empty = el('div', 'lab-empty');
  empty.append(el('h2', '', 'Describe your robot and where it works'), el('p', '', 'The world builds here, then one run plays. Press + in the chat box to choose a robot.'));
  host.append(empty);
  main.append(host);

  let clear: () => void = () => {};
  // The session's look. A view built later starts from it. Scenery only.
  let look: unknown = {};
  let current: (() => SimView | null) = () => null;
  const applyLook = (e: ServerEvent) => {
    look = e.look;
    const view = current();
    view?.setLook(look);
    const viewport = document.querySelector<HTMLElement>('.viewport');
    // The time from the AI's answer reaching the server to the next frame drawn.
    if (viewport) requestAnimationFrame(() => requestAnimationFrame(() => { viewport.dataset.lookLandMs = String(Math.round(Date.now() - e.sent)); }));
  };
  // The world changed with no new run: the same replay, a new view model.
  const applyView = (e: ServerEvent) => {
    const view = current();
    if (!view) return;
    // The first build finishes before a picture edit lands, so an early edit does not cut it short.
    if (view.building) { view.afterBuild = () => applyView(e); return; }
    view.applyWorld(e.xml, e.world);
    view.buildObjects(built(windowObjects(e.world)).fresh);
    const viewport = document.querySelector<HTMLElement>('.viewport');
    if (viewport) {
      viewport.dataset.hash = String(e.hash);
      requestAnimationFrame(() => requestAnimationFrame(() => { viewport.dataset.lookLandMs = String(Math.round(Date.now() - e.sent)); }));
    }
  };
  const swap = (next: HTMLElement, stop: () => void) => {
    clear();
    clear = stop;
    host.replaceChildren(next);
    tab.classList.remove('off');
    gridTab.classList.remove('on');
    code.blur();
  };

  // The inspection robot's scene. The newest run, if any, keeps playing when only the picture changed.
  let poseView: () => PosesView | null = () => null;
  let shownReplay: PoseReplay | null = null;
  let shownHash = '';
  let again: (() => void) | null = null;

  function playPoses(replay: PoseReplay, key: string, fresh?: ReadonlySet<string>) {
    const world = posesPage(replay, statusRight, fixed, fresh);
    swap(world.page, () => { world.stop(); poseView = () => null; });
    world.start();
    poseView = () => world.view;
    world.viewport.dataset.tid = key;
    shownReplay = replay;
    jump = world.jump;
  }
  let jump: (frame: number) => void = () => {};

  function showPoseWorld(e: ServerEvent) {
    setName('inspection_plant');
    chat.worldReady();
    const same = shownReplay && e.hash === shownHash;
    shownHash = String(e.hash);
    const scene = { solids: e.solids, scenery: e.scenery, route: e.route, floor_friction: e.floor_friction };
    const { first, fresh } = built(plantObjects(scene));
    if (same && shownReplay!.frames.length) {
      playPoses({ ...shownReplay!, ...scene }, 'same_physics', new Set(fresh));
      return;
    }
    const replay = previewReplay({ ...scene, note: String(e.note) });
    again = () => playPreview(replay);
    playPreview(replay, first, fresh);
  }

  function playPreview(replay: PoseReplay, first = false, fresh: string[] = []) {
    const page = el('div', 'world-body');
    const viewport = el('div', 'viewport');
    viewport.append(el('div', 'sim-tag sim-label', 'World preview. No robot has run yet.'));
    page.append(viewport);
    let view: PosesView | null = null;
    swap(page, () => { view?.dispose(); poseView = () => null; });
    view = new PosesView(viewport, replay, new Set(fresh));
    if (first) view.buildFirst(); else view.buildObjects();
    poseView = () => view;
    shownReplay = replay;
    viewport.dataset.ready = 'true';
  }

  async function showPoseTrial(url: string) {
    const replay = await fetchWith(() => loadPoses(`${SERVER}${url}`), url);
    if (!replay) return;
    built(plantObjects(replay));
    again = () => playPoses(replay, url);
    playPoses(replay, url);
  }

  // The test run. One grid per session, kept while the main area shows something else.
  let scenarios: ServerEvent | null = null;
  let grid: Grid | null = null;
  const showGrid = () => {
    if (!grid) return;
    const g = grid;
    swap(g.root, () => g.leave());
    tab.classList.add('off');
    gridTab.classList.add('on');
    g.enter();
  };
  gridTab.addEventListener('click', () => { if (!gridTab.classList.contains('on')) showGrid(); });
  tab.addEventListener('click', () => { if (tab.classList.contains('off')) again?.(); });

  function makeGrid(e: ServerEvent) {
    return new Grid({
      base: `${SERVER}/api/sessions/${backend.id}/campaigns/${e.campaign}`,
      statusRight,
      openFile: d => void code.openFile(String(e.campaign), d),
      openWorld: d => code.openWorld(String(e.campaign), d),
      bountyLink: verdict => code.bountyLink(String(e.campaign), verdict),
      play: async (how: ServerEvent, say: (words: string) => void) => {
        say('Downloading the recorded run');
        if (how.kind === 'poses') {
          const replay = await fetchWith(() => loadPoses(`${SERVER}${how.url}`), String(how.url));
          if (!replay) return null;
          const world = posesPage(replay, statusRight, fixed);
          return { page: world.page, start: async () => { world.start(); poseView = () => world.view; world.viewport.dataset.tid = String(how.url); }, stop: () => { world.stop(); poseView = () => null; }, jump: (t: number) => world.jump(Math.round(t * replay.fps)) };
        }
        const trial = await fetchTrial(String(how.tid));
        if (!trial) return null;
        const world = worldPage(trial, statusRight, fixed, runLabel);
        return { page: world.page, start: async () => { await world.start(); current = () => world.view; world.viewport.dataset.tid = String(how.tid); }, stop: () => { world.stop(); current = () => null; }, jump: (t: number) => {
          const slider = world.page.querySelector<HTMLInputElement>('.scrub input');
          if (!slider) return;
          slider.value = String(Math.round(t * trial.manifest.hz));
          slider.dispatchEvent(new Event('input'));
        } };
      },
    });
  }

  function onGrid(e: ServerEvent) {
    if (!grid || grid.campaign !== e.campaign) {
      current()?.finishBuilds();
      poseView()?.finishBuilds();
      grid?.leave();
      grid = makeGrid(e);
      const list = scenarios;
      if (list && list.campaign === e.campaign) grid.setScenarios(list);
      grid.update(e);
      chat.campaignRunning();
      gridTab.hidden = false;
      const outgoing = host.firstElementChild === empty ? (empty.remove(), null) : host.firstElementChild as HTMLElement | null;
      const stopOld = clear;
      const g = grid;
      if (outgoing) Object.assign(outgoing.style, { position: 'absolute', inset: '0', zIndex: '4', pointerEvents: 'none' });
      host.append(g.root);
      tab.classList.add('off');
      gridTab.classList.add('on');
      g.enter();
      clear = () => g.leave();
      void g.zoomFrom(outgoing).then(() => { stopOld(); outgoing?.remove(); });
      return;
    }
    grid.update(e);
  }

  // After a reload the stored events come back, and a finished campaign sends no grid event, so the page asks for the last one.
  async function onCampaignDone(e: ServerEvent) {
    if (!grid || grid.campaign !== e.campaign) {
      const res = await fetch(`${SERVER}/api/sessions/${backend.id}/campaigns/${e.campaign}/grid`, { signal: AbortSignal.timeout(TRIAL_DEADLINE_MS) });
      if (!res.ok) return;
      onGrid(await res.json());
    }
    grid?.done(e);
  }

  async function showWorld(e: ServerEvent) {
    const area = e.area as Trial['manifest']['area'];
    const mj = await loadMujoco();
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
    setName(plainName(chat.said));
    chat.worldReady();
    const page = el('div', 'world-body');
    const viewport = el('div', 'viewport');
    viewport.append(el('div', 'sim-tag sim-label', 'World preview. No robot has run yet.'));
    page.append(viewport);
    let view: SimView | null = null, replay: Replay | null = null;
    swap(page, () => { view?.dispose(); replay?.dispose(); });
    replay = new Replay(mj, trial);
    replay.seek(0);
    view = new SimView(viewport, replay, trial);
    view.setLook(isV5(e.world) ? lookOf(e.world) : look);
    restoreOnLoss(view, fresh => { view = fresh; }, fixed);
    current = () => view;
    view.sync();
    if (built(windowObjects(e.world)).first) view.buildFirst();
    viewport.dataset.ready = 'true';
    viewport.dataset.hash = String(e.hash);
  }

  const fixed = (code: string, words: string) => { chat.note(words, /gave_up|failed/.test(code)); backend.report(code); };

  const fetchTrial = (tid: string) => fetchWith(() => loadTrialFrom(backend.trialBase(tid)), tid);

  async function fetchWith<T>(load: () => Promise<T>, what: string): Promise<T | null> {
    for (let attempt = 1; ; attempt++) {
      try {
        return await load();
      } catch (err) {
        console.warn(`replay ${what}, try ${attempt}: ${String(err)}`);
        if (attempt === TRIAL_TRIES) {
          fixed('trial_failed', 'The replay did not load after 3 tries. The run itself is safe. Ask for a change to run it again, or reload the page.');
          return null;
        }
        if (attempt === 1) fixed('trial_retry', 'The replay did not load in time, so I am fetching it again.');
        await new Promise(r => setTimeout(r, TRIAL_RETRY_MS));
      }
    }
  }

  async function showTrial(tid: string) {
    const trial = await fetchTrial(tid);
    if (!trial) return;
    again = () => void showTrial(tid);
    const world = worldPage(trial, statusRight, fixed, runLabel);
    swap(world.page, () => world.stop());
    current = () => world.view;
    await world.start();
    if (!isV5(trial.world)) world.view?.setLook(look);
    // A solid new object first shows in the run that tested it. It builds itself as the replay starts.
    world.view?.buildObjects(built(windowObjects(trial.world)).fresh);
    world.viewport.dataset.tid = tid;
  }

  void loadMujoco();
  for (let told = false; ;) {
    try {
      const info = await health();
      runLabel = info.recorded_batch ? LABEL : THIS_RUN_LABEL;
      llmLine.textContent = HIDE_AI ? '' : routeLine || `LLM: ${info.llm}`;
      root.dataset.server = 'up';
      break;
    } catch {
      llmLine.textContent = 'Run server not connected';
      if (!told) chat.note('The run server is not running. Start it: policy/.venv/bin/python policy/server/supervise.py. This page connects by itself once it is up.', true);
      told = true;
      await new Promise(r => setTimeout(r, HEALTH_RETRY_MS));
    }
  }
  (window as unknown as { __lab: unknown }).__lab = { view: () => current() ?? poseView(), jump: (f: number) => jump(f), grid: () => grid, code: () => code };
  await chat.start();
}

async function main() {
  const root = document.getElementById('lab')!;
  const params = new URLSearchParams(location.search);
  const id = params.get('trial'), poses = params.get('poses');
  if (poses) await posesOnly(root, poses);
  else if (id) await replayOnly(root, id);
  else await live(root);
}

void main();
