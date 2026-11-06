import { el, icon } from '../app/dom.ts';

type Entry = { kind: 'me' | 'agent'; text: string } | { kind: 'steps'; steps: string[] };

// PLACEHOLDER: sample text from design/shell/build.py. No agent wrote it and no run backs it. The next task replaces it with live chat.
const PLACEHOLDER_LOG: Entry[] = [
  { kind: 'me', text: 'Window robot for towers in Dubai. High floor, strong wind.' },
  { kind: 'steps', steps: ['Built the world', 'Ran one test'] },
  { kind: 'agent', text: 'The world is ready. The robot finished one run. Does the scene look right?' },
  { kind: 'me', text: 'Make the wind stronger and wet the glass.' },
  { kind: 'steps', steps: ['Changed the world'] },
  { kind: 'agent', text: 'Done. Watch the run again.' },
];

function entry(item: Entry): HTMLElement {
  if (item.kind !== 'steps') return el('div', item.kind === 'me' ? 'chat-me' : 'chat-agent', item.text);
  const steps = el('div', 'chat-steps');
  steps.append(...item.steps.map(step => el('div', 'chat-step', step)));
  return steps;
}

export function chatPanel(): HTMLElement {
  const root = el('section', 'chat');
  const head = el('div', 'chat-head');
  head.append(el('span', '', 'Chat'), el('span', 'chat-new', 'New chat'));
  const log = el('div', 'chat-log');
  log.append(...PLACEHOLDER_LOG.map(entry));

  const box = el('div', 'chat-box');
  const input = el('textarea', 'chat-input');
  input.placeholder = 'Ask for a change to the world';
  input.setAttribute('aria-label', 'Message');
  const foot = el('div', 'chat-foot');
  const send = el('button', 'chat-send');
  send.setAttribute('aria-label', 'Send');
  send.append(icon('send', true));
  foot.append(el('span', '', 'Agent'), send);
  box.append(input, foot);

  root.append(head, log, box);
  return root;
}
