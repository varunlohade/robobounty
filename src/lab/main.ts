import { el } from '../app/dom.ts';
import { loadTrial } from '../app/trial.ts';
import { worldPage } from '../app/world_page.ts';
import { chatPanel } from './chat.ts';

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

function titleBar(name: string): HTMLElement {
  const bar = el('header', 'lab-title');
  const lights = el('div', 'lab-lights');
  lights.setAttribute('aria-hidden', 'true');
  lights.append(el('i'), el('i'), el('i'));
  bar.append(lights, el('div', 'lab-name', name));
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

async function main() {
  const root = document.getElementById('lab')!;
  const id = new URLSearchParams(location.search).get('trial');
  if (!id) {
    root.append(el('div', 'sim-error', 'Add ?trial=<id> to the address to open a recorded run.'));
    return;
  }
  let trial;
  try {
    trial = await loadTrial(id);
  } catch (err) {
    root.append(el('div', 'sim-error', `Could not load the recorded run.\n${String(err)}`));
    return;
  }

  const statusRight = el('div', 'lab-status-end');
  const world = worldPage(trial, statusRight);
  const tabs = el('div', 'lab-tabs');
  tabs.append(el('div', 'lab-tab', `${id}.world`));
  const sim = el('main', 'lab-main');
  sim.append(tabs, world.page);
  const body = el('div', 'lab-body');
  body.append(activityBar(), chatPanel(), sim);
  const status = el('footer', 'lab-status');
  status.append(el('span', '', 'Simulated. Hand-built physics, not checked against real hardware.'), statusRight);
  root.append(titleBar(`CrashLab — ${id}`), body, status);

  try {
    const replay = await world.start();
    statusRight.append(el('span', '', `Recorded in MuJoCo ${trial.manifest.python_mujoco}, shown with ${replay.version}`));
  } catch (err) {
    world.viewport.append(el('div', 'sim-error', `MuJoCo could not load this model in the browser, so there is no 3D view.\n${String(err)}`));
  }
}

void main();
