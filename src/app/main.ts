import { el, icon } from './dom.ts';
import { ChatPanel } from './chat/panel.ts';
import { StubBackend } from './chat/backend.ts';
import { LABEL, worldPage } from './world_page.ts';
import { worldsPage } from './worlds_page.ts';
import { loadTrial, loadWorlds, trialIndex, type Trial, type TrialEntry, type WorldsData } from './trial.ts';

const app = document.getElementById('app')!;

function fatal(host: HTMLElement, what: string, err: unknown) {
  host.append(el('div', 'sim-error', `${what}\n${String(err)}`));
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

function trialPicker(trials: TrialEntry[], current: string): HTMLElement {
  const pick = el('select', 'select');
  pick.setAttribute('aria-label', 'Recorded run');
  for (const t of trials) {
    const opt = el('option', '', t.label);
    opt.value = t.id;
    opt.selected = t.id === current;
    pick.append(opt);
  }
  pick.addEventListener('change', () => { location.search = `?trial=${encodeURIComponent(pick.value)}`; });
  return pick;
}

function codePage(trial: Trial) {
  const page = el('div', 'page');
  page.append(el('div', 'code-head', 'controller.py, read only. Its hash matches the code that recorded this run.'));
  const pre = el('pre', 'code');
  pre.tabIndex = 0;
  for (const line of trial.controller.replace(/\n$/, '').split('\n')) pre.append(el('span', 'code-line', line));
  page.append(pre);
  return page;
}

async function main() {
  const params = new URLSearchParams(location.search);
  let trials: TrialEntry[];
  let trial: Trial;
  try {
    trials = await trialIndex();
    trial = await loadTrial(params.get('trial') ?? trials[0].id);
  } catch (err) {
    fatal(app, 'Could not load the recorded run.', err);
    return;
  }
  const worlds: WorldsData | null = await loadWorlds().catch(() => null);

  const title = el('header', 'title', trial.manifest.label);
  const lights = el('div', 'lights');
  lights.setAttribute('aria-hidden', 'true');
  lights.append(el('i'), el('i'), el('i'));
  title.append(lights, el('div', 'brand', 'CrashLab'));

  const statusRight = el('div', 'status-end');
  const world = worldPage(trial, statusRight);
  const worldsTitle = worlds ? `${worlds.total} worlds` : 'Worlds';
  const pages: [string, HTMLElement][] = [['World', world.page], [worldsTitle, worldsPage(worlds)], ['Code', codePage(trial)]];
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
  const tabsEnd = el('div', 'tabs-end');
  tabsEnd.append(trialPicker(trials, trial.manifest.id));
  tabs.append(tabsEnd);
  show(0);

  const chat = new ChatPanel(new StubBackend(trial, worlds), tab => show(tab === 'worlds' ? 1 : 2), 'world.json');
  const chatHead = el('div', 'chat-head');
  chatHead.append(el('span', '', 'Chat'));
  const newChat = el('button', 'icon-btn');
  newChat.setAttribute('aria-label', 'New chat');
  newChat.title = 'New chat';
  newChat.append(icon('plus', true));
  newChat.addEventListener('click', () => chat.reset());
  chatHead.append(newChat);

  const status = el('footer', 'status');
  status.append(el('span', '', LABEL), el('span', '', 'Stub chat'), el('span', '', 'Hand-built physics, not checked against real hardware'), statusRight);
  app.append(title, chatHead, el('div', 'head-rule'), tabs, chat.root, divider(), pane, status);

  try {
    const replay = await world.start();
    statusRight.append(el('span', '', `Recorded in MuJoCo ${trial.manifest.python_mujoco}, shown with ${replay.version}`));
  } catch (err) {
    fatal(world.viewport, 'MuJoCo could not load this model in the browser, so there is no 3D view.', err);
  }
}

void main();
