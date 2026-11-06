// The short quiz for a new engineer. One question a screen. The server holds the answers and grades.
import './login.css';
import { loginHref, me, screenerGrade, screenerStart } from './auth.ts';
import { h } from './ui.ts';

interface Question { id: string; question: string; choices: { n: number; text: string }[] }
const root = document.getElementById('site')!;
const film = Object.assign(document.createElement('video'), { className: 'lg-film', muted: true, poster: '/login/film-poster.jpg' });
film.setAttribute('aria-hidden', 'true');
const sheet = h('section', 'lg-sheet');
sheet.setAttribute('aria-label', 'Short quiz');
root.append(h('div', 'lg', film, sheet));

function place() {
  const step = sheet.firstElementChild as HTMLElement | null;
  if (step) sheet.style.transform = `translateY(${Math.max(16, innerHeight - step.offsetHeight)}px)`;
}
addEventListener('resize', place);
const show = (...kids: (Node | null)[]) => { sheet.replaceChildren(h('div', 'lg-step', ...kids)); place(); };
const title = (a: string, b: string) => h('h1', '', a, h('br'), b);
function pill(label: string, on: () => void, cls = '') {
  const b = h('button', `lg-pill ${cls}`, label);
  b.type = 'button';
  b.addEventListener('click', on);
  return b;
}
function later() {
  const a = h('a', 'lg-text', 'Not now, go to Bounties') as HTMLAnchorElement;
  a.href = 'bounties.html';
  return h('div', 'lg-links', a);
}

function intro() {
  show(h('div', 'lg-left', h('div', '', title('A short', 'quiz.'), h('p', 'lg-say', 'Six questions on robot control, simulation and debugging. Five right lets you submit fixes. Browsing stays open.')), later()),
    h('div', 'lg-opts', pill('Start', () => { void begin(); })));
}

function words(text: string) {
  show(h('div', 'lg-left', h('div', '', title('Not', 'this time.'), h('p', 'lg-say bad', text)), later()));
}

function passed() {
  show(h('div', 'lg-left', h('div', '', title('AI interview:', 'coming soon.'), h('p', 'lg-say', 'Screened. A short quiz is not proof of skill.'), h('p', 'lg-small', 'No interview runs today.')), later()));
}

async function begin() {
  const r = await screenerStart();
  if (r.body.screened) { passed(); return; }
  if (!r.ok) { words(String(r.body.words ?? 'The server refused this.')); return; }
  ask(r.body.questions as Question[], 0, {});
}

function ask(questions: Question[], at: number, answers: Record<string, number>) {
  const q = questions[at];
  const list = h('div', 'lg-opts');
  list.dataset.question = q.id;
  list.dataset.index = String(at);
  for (const c of q.choices) {
    const b = pill(c.text, () => {
      answers[q.id] = c.n;
      if (at + 1 < questions.length) ask(questions, at + 1, answers);
      else void finish(answers);
    }, 'grey');
    b.dataset.choice = String(c.n);
    Object.assign(b.style, { width: '100%', height: 'auto', minHeight: '56px', padding: '12px 24px', fontSize: '18px', textAlign: 'left', justifyContent: 'flex-start' });
    list.append(b);
  }
  show(h('div', 'lg-left', h('div', '', title(`${at + 1} of`, `${questions.length}.`), h('p', 'lg-say lg-status', q.question)), later()), list);
}

async function finish(answers: Record<string, number>) {
  const r = await screenerGrade(answers);
  if (r.ok && r.body.passed) passed();
  else words(String(r.body.words ?? 'The server refused this.'));
}

void me().then(m => {
  if (!m.signedIn) location.replace(loginHref());
  else if (m.role !== 'engineer') location.replace('home.html');
  else if (m.screened) passed();
  else intro();
});
