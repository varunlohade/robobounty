import { el } from '../app/dom.ts';
import { LiveBackend, health, type ServerEvent } from '../app/chat/live.ts';
import { Replay, loadMujoco } from '../app/replay.ts';
import { loadTrial, loadTrialFrom, type Trial } from '../app/trial.ts';
import { SimView } from '../app/view.ts';
import { worldPage } from '../app/world_page.ts';
import { LabChat, replayNote } from './chat.ts';

const NS = 'http://www.w3.org/2000/svg';
// Lucide 0.400 outlines: panel-left, layout-grid, settings.
const ACTIVITY = [
  ['M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z', 'M9 3v18'],
  ['M4 3h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z', 'M15 3h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z', 'M15 14h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1h-5a1 1 0 0 1-1-1v-5a1 1 0 0 1 1-1z', 'M4 14h5a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5a1 1 0 0 1 1-1z'],
  ['M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z', 'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z'],
];

function outline(paths: string[]): SVGSVGElement {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  for (const d of paths) {
    const path = document.createElementNS(NS, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

function titleBar(name: HTMLElement): HTMLElement {
  const bar = el('header', 'lab-title');
  const lights = el('div', 'lab-lights');
  lights.setAttribute('aria-hidden', 'true');
  lights.append(el('i'), el('i'), el('i'));
  bar.append(lights, name);
  return bar;
}

function activityBar(): HTMLElement {
  const bar = el('nav', 'lab-activity');
  bar.setAttribute('aria-hidden', 'true');
  ACTIVITY.forEach((paths, i) => {
    const item = el('div', i === 0 ? 'lab-act on' : 'lab-act');
    item.append(outline(paths));
    bar.append(item);
  });
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
  const main = el('main', 'lab-main');
  main.append(tabs);
  const body = el('div', 'lab-body');
  body.append(activityBar(), chat, main);
  const statusRight = el('div', 'lab-status-end');
  const status = el('footer', 'lab-status');
  status.append(el('span', '', 'Simulated. Hand-built physics, not checked against real hardware.'), statusRight);
  root.append(titleBar(name), body, status);
  return { main, statusRight, setName };
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

// A name for the title bar from the user's words: the place they name, else the fixed tower.
function plainName(said: string[]): string {
  for (const text of said) {
    const place = text.match(/\btowers?\s+in\s+([a-z]+)/i) ?? text.match(/\b(?:in|at|near)\s+([A-Z][a-z]+)/);
    if (place) return `${place[1].toLowerCase()}_tower`;
  }
  return 'window_tower';
}

async function live(root: HTMLElement) {
  const onEvent = async (e: ServerEvent) => {
    switch (e.type) {
      case 'world': await showWorld(e); break;
      case 'look': applyLook(e); break;
      case 'trial': await showTrial(e.tid); break;
      case 'llm_count': aiLine.textContent = `AI calls ${e.used} of ${e.cap}`; break;
      case 'sim': simLine.textContent = `Sim ${e.sha ? String(e.sha).slice(0, 8) : 'unknown'}${e.sha && e.sha !== e.now ? `, now ${String(e.now).slice(0, 8)}: this run is from older code` : ''}`; break;
      case 'idle':
        root.dataset.idle = String(Number(root.dataset.idle ?? 0) + 1);
        chat.jobDone();
        break;
    }
  };
  const backend = new LiveBackend(onEvent);
  const chat = new LabChat(backend);
  const { main, statusRight, setName } = shell(root, chat.root);
  const simLine = el('span');
  const llmLine = el('span');
  const aiLine = el('span');
  statusRight.append(llmLine, aiLine, simLine);

  const host = el('div', 'page');
  const empty = el('div', 'lab-empty');
  empty.append(el('h2', '', 'Describe your robot and where it works'), el('p', '', 'The world builds here, then one run plays.'));
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
  const swap = (next: HTMLElement, stop: () => void) => {
    clear();
    clear = stop;
    host.replaceChildren(next);
  };

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
    viewport.append(el('div', 'sim-tag sim-label', 'Simulated. World preview. No robot has run yet.'));
    page.append(viewport);
    let view: SimView | null = null, replay: Replay | null = null;
    swap(page, () => { view?.dispose(); replay?.dispose(); });
    replay = new Replay(mj, trial);
    replay.seek(0);
    view = new SimView(viewport, replay, trial);
    view.setLook(look);
    current = () => view;
    view.sync();
    viewport.dataset.ready = 'true';
    viewport.dataset.hash = String(e.hash);
  }

  async function showTrial(tid: string) {
    const trial = await loadTrialFrom(backend.trialBase(tid));
    const world = worldPage(trial, statusRight);
    swap(world.page, () => world.stop());
    current = () => world.view;
    await world.start();
    world.view?.setLook(look);
    world.viewport.dataset.tid = tid;
  }

  void loadMujoco();
  try {
    const info = await health();
    simLine.textContent = `Sim ${info.sim_sha.slice(0, 8)}`;
    llmLine.textContent = `LLM: ${info.llm}`;
    root.dataset.server = 'up';
  } catch {
    llmLine.textContent = 'Run server not connected';
    chat.note('The run server is not running. Start it: policy/.venv/bin/python policy/server/server.py', true);
    return;
  }
  await chat.start();
}

async function main() {
  const root = document.getElementById('lab')!;
  const id = new URLSearchParams(location.search).get('trial');
  if (id) await replayOnly(root, id);
  else await live(root);
}

void main();
