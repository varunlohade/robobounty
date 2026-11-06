// The code tab: a real editor for a session copy of the robot's controller, opened from a square, and a read-only world file. The source files never change.
import { history, defaultKeymap, historyKeymap, indentWithTab } from '@codemirror/commands';
import { json } from '@codemirror/lang-json';
import { python } from '@codemirror/lang-python';
import { HighlightStyle, bracketMatching, indentOnInput, indentUnit, syntaxHighlighting } from '@codemirror/language';
import { EditorState, RangeSetBuilder, StateEffect, StateField, type Extension } from '@codemirror/state';
import { Decoration, EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, type DecorationSet } from '@codemirror/view';
import { tags as t } from '@lezer/highlight';
import { el } from '../app/dom.ts';
import { SERVER, type ServerEvent } from '../app/chat/live.ts';
import { statusWord, type Row } from './grid.ts';
import './code_tab.css';

const FETCH_MS = 15_000;
const TRACE_MS = 200_000;
const SET_NAMES: [string, string][] = [['target', 'Failed in this group'], ['held_back', 'Held back, never seen'], ['passed_before', 'Passed or held before'], ['other_failed', 'Other failed worlds']];

const theme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'var(--lab-app)', color: 'var(--lab-text)', fontSize: '12px' },
  '.cm-scroller': { fontFamily: 'var(--lab-mono)', lineHeight: '20px', overflow: 'auto' },
  '.cm-content': { caretColor: 'var(--lab-text)', padding: '8px 0' },
  '.cm-cursor': { borderLeftColor: 'var(--lab-text)' },
  '.cm-gutters': { backgroundColor: 'var(--lab-app)', color: 'var(--lab-muted)', border: '0' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 12px 0 16px', minWidth: '44px' },
  '.cm-activeLine': { backgroundColor: 'rgba(255, 255, 255, .03)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--lab-text-2)' },
  '&.cm-focused': { outline: 'none' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': { backgroundColor: 'rgba(62, 123, 250, .28)' },
  '.cm-matchingBracket': { backgroundColor: 'rgba(255, 255, 255, .1)', color: 'inherit' },
}, { dark: true });

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword], color: '#8FB4FC' },
  { tag: [t.string, t.special(t.string)], color: '#5CC186' },
  { tag: [t.comment, t.lineComment, t.blockComment], color: 'var(--lab-muted)' },
  { tag: [t.number, t.bool, t.null], color: '#E3B04F' },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: '#ECEEF1', fontWeight: '500' },
  { tag: [t.className, t.definition(t.className)], color: '#ECEEF1', fontWeight: '500' },
  { tag: [t.propertyName, t.attributeName], color: '#A3A9B3' },
  { tag: [t.self], color: '#A3A9B3' },
  { tag: [t.operator, t.punctuation, t.bracket], color: '#A3A9B3' },
]);

// The marked lines: the line the run points at, and the lines a refusal names.
const setLines = StateEffect.define<{ focus: number | null; bad: number[] }>();
const lineMarks = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, tr) {
    marks = marks.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setLines)) continue;
      const wanted = new Map<number, string>();
      if (e.value.focus) wanted.set(e.value.focus, 'cm-code-focus');
      for (const n of e.value.bad) wanted.set(n, 'cm-code-bad');
      const b = new RangeSetBuilder<Decoration>();
      for (const n of [...wanted.keys()].sort((x, y) => x - y)) {
        if (n >= 1 && n <= tr.state.doc.lines) b.add(tr.state.doc.line(n).from, tr.state.doc.line(n).from, Decoration.line({ class: wanted.get(n)! }));
      }
      marks = b.finish();
    }
    return marks;
  },
  provide: f => EditorView.decorations.from(f),
});

function editor(parent: HTMLElement, doc: string, lang: Extension, readOnly: boolean, onChange?: () => void) {
  return new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: [lineNumbers(), highlightActiveLine(), highlightActiveLineGutter(), history(), drawSelection(), indentOnInput(), bracketMatching(), indentUnit.of('    '),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]), lang, theme, syntaxHighlighting(highlight), lineMarks, EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
        EditorView.contentAttributes.of({ 'aria-label': readOnly ? 'World file, read only' : 'Controller code' }),
        EditorView.updateListener.of(u => { if (u.docChanged) onChange?.(); })],
    }),
  });
}

function goTo(view: EditorView, line: number | null, bad: number[] = []) {
  const focus = line && line >= 1 && line <= view.state.doc.lines ? line : null;
  const target = bad[0] ?? focus;
  const pos = target && target <= view.state.doc.lines ? view.state.doc.line(target).from : null;
  view.dispatch({ effects: [setLines.of({ focus, bad }), ...(pos === null ? [] : [EditorView.scrollIntoView(pos, { y: 'center' })])], ...(pos === null ? {} : { selection: { anchor: pos } }) });
}

const plain = (name: string) => { const s = name.replaceAll('_', ' '); return s.charAt(0).toUpperCase() + s.slice(1); };
const asRow = (r: unknown) => statusWord({ ...(r as object), held_back: false } as unknown as Row);

interface Deps {
  session: () => string;
  tabs: HTMLElement;
  show: (page: HTMLElement) => void;
  back: () => void;
  chat: (node: HTMLElement) => void;
  note: (text: string, fail?: boolean) => void;
}
interface Picked { campaign: string; d: ServerEvent }
interface Source { pack: string; name: string; file: string; source: string; original: string; sha: string; original_sha: string; edited: boolean; scope: string; fix_scope: string; note: string; trace: boolean }

class FileTab {
  readonly root = el('div', 'code-tab');
  private label = el('button', 'code-tab-name');
  private close = el('button', 'code-tab-close', '×');
  constructor(onOpen: () => void, onClose: () => void) {
    this.label.type = 'button';
    this.close.type = 'button';
    this.close.setAttribute('aria-label', 'Close tab');
    this.label.addEventListener('click', onOpen);
    this.close.addEventListener('click', e => { e.stopPropagation(); onClose(); });
    this.root.append(this.label, this.close);
    this.root.hidden = true;
  }
  name(text: string, dirty = false) {
    this.label.textContent = text;
    this.root.dataset.dirty = String(dirty);
    this.close.textContent = dirty ? '●' : '×';
  }
  on(yes: boolean) { this.root.classList.toggle('on', yes); }
}

export class CodeTab {
  private page = el('div', 'code-page');
  private worldPage = el('div', 'code-page');
  private fileTab = new FileTab(() => this.showCode(), () => this.closeTab(this.fileTab));
  private worldTab = new FileTab(() => this.showWorld(), () => this.closeTab(this.worldTab));
  private view: EditorView | null = null;
  private worldView: EditorView | null = null;
  private src: Source | null = null;
  private saved = '';
  private picked: Picked | null = null;
  private rows: Row[] = [];
  private busy = false;
  private results = new Map<number, ServerEvent>();

  private path = el('span', 'code-path');
  private state = el('span', 'code-state');
  private reset = this.button('Reset to source', () => this.resetToSource());
  private runOne = this.button('Run this world', () => void this.run('one'));
  private runAll = this.button('Run all', () => void this.run('all'));
  private askAi = this.button('Ask AI to fix', () => void this.fix(), 'code-ai');
  private chip = el('span', 'code-chip');
  private whyText = el('span', 'code-why-text');
  private worldLink = this.button('World file', () => { if (this.picked) this.openWorld(this.picked.campaign, this.picked.d); });
  private why = el('div', 'code-why');
  private refused = el('div', 'code-refused');
  private host = el('div', 'code-editor');
  private table = el('div', 'code-results');
  private foot = el('div', 'code-foot');
  private worldBar = el('div', 'code-bar');
  private worldHost = el('div', 'code-editor');

  constructor(private deps: Deps) {
    deps.tabs.append(this.fileTab.root, this.worldTab.root);
    const bar = el('div', 'code-bar');
    const left = el('div', 'code-bar-left');
    left.append(this.path, this.state);
    const end = el('div', 'code-bar-end');
    end.append(this.reset, this.runOne, this.runAll, this.askAi);
    bar.append(left, end);
    const whyLeft = el('div', 'code-why-left');
    whyLeft.append(this.chip, this.whyText);
    this.why.append(whyLeft, this.worldLink);
    this.refused.hidden = true;
    this.refused.setAttribute('role', 'alert');
    this.table.hidden = true;
    this.page.append(bar, this.why, this.refused, this.host, this.table, this.foot);
    this.worldPage.append(this.worldBar, this.worldHost);
    this.refresh();
  }

  private button(words: string, onClick: () => void, extra = '') {
    const b = el('button', `grid-btn ${extra}`.trim(), words);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  private url(rest: string) {
    return `${SERVER}/api/sessions/${this.deps.session()}${rest}`;
  }

  private async load() {
    const res = await fetch(this.url('/code'), { signal: AbortSignal.timeout(FETCH_MS) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    this.src = await res.json();
    this.saved = this.src!.source;
    this.path.textContent = this.src!.file;
    this.foot.textContent = `${this.src!.note} ${this.src!.scope} Simulated.`;
    if (this.view) this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: this.saved } });
    else this.view = editor(this.host, this.saved, python(), false, () => this.changed());
    this.refresh();
  }

  private changed() {
    this.clearRefusal();
    this.refresh();
  }

  private get text() { return this.view?.state.doc.toString() ?? ''; }
  private get dirty() { return Boolean(this.src) && this.text !== this.saved; }

  private refresh() {
    const src = this.src;
    if (src) {
      this.fileTab.name(src.name, this.dirty);
      const same = this.text === src.original;
      this.state.textContent = same ? 'Same as source' : this.dirty ? 'Session copy, not run yet' : 'Session copy, edited';
      this.state.dataset.edited = String(!same);
      this.reset.disabled = same || this.busy;
    }
    const held = this.picked?.d.held_back;
    this.runOne.disabled = this.busy || !this.picked || Boolean(held);
    this.runOne.title = held ? 'A held-back world stays out of re-runs. It tests AI fixes.' : '';
    this.runAll.disabled = this.busy || !this.rows.length;
    this.worldLink.hidden = !this.picked;
    const verdict = this.picked?.d.verdict;
    const n = verdict ? this.rows.filter(r => r.verdict === verdict && !r.held_back).length : 0;
    const failing = this.picked && (this.picked.d.status === 'failed' || this.picked.d.status === 'stuck');
    this.askAi.disabled = this.busy || !failing;
    this.askAi.textContent = failing ? `Ask AI to fix: ${asRow(this.picked!.d)} (${n})` : 'Ask AI to fix';
    this.askAi.title = failing ? `The AI edits a copy to lower the ${asRow(this.picked!.d).toLowerCase()} failures. It sees only those ${n} worlds, and it is then tested on worlds it never saw.` : 'Open a failed world first.';
  }

  /** The main area left this tab. */
  blur() {
    this.fileTab.on(false);
    this.worldTab.on(false);
  }

  private closeTab(tab: FileTab) {
    tab.root.hidden = true;
    tab.on(false);
    this.deps.back();
  }

  private showCode() {
    this.deps.show(this.page);
    this.fileTab.root.hidden = false;
    this.fileTab.on(true);
    this.view?.requestMeasure();
  }

  private showWorld() {
    this.deps.show(this.worldPage);
    this.worldTab.root.hidden = false;
    this.worldTab.on(true);
    this.worldView?.requestMeasure();
  }

  /** From a square: the controller at the line of that run. d is the world's detail. */
  async openFile(campaign: string, d: ServerEvent) {
    this.picked = { campaign, d };
    try {
      if (!this.src) await this.load();
    } catch (err) {
      this.deps.note(`Could not open the file: ${String(err)}`, true);
      return;
    }
    this.showCode();
    this.refresh();
    this.pointAt(d.code);
    if (this.src!.trace && d.code && !d.code.traced && d.status !== 'queued') void this.trace(campaign, d);
  }

  private pointAt(code: { line: number; traced: boolean; why?: string } | null, tracing = false) {
    const d = this.picked?.d;
    const name = d ? `${plain(String(d.name))}: ${d.verdict_reason ?? statusWord(d as unknown as Row)}` : '';
    this.chip.dataset.kind = code?.traced ? 'traced' : 'active';
    if (!code) {
      this.chip.textContent = 'No line';
      this.whyText.textContent = `${name} This run fired no rule, so no line stands out.`;
      if (this.view) goTo(this.view, null);
      return;
    }
    this.chip.textContent = code.traced ? `Traced, line ${code.line}` : `Active code at that moment, line ${code.line}`;
    const older = d && this.src && d.controller_sha !== this.src.sha ? ' This line comes from the version that ran, and the file has changed since.' : '';
    this.whyText.textContent = `${name} ${code.why ?? ''}${tracing ? ' Tracing the run to find the executed line.' : ''}${older}`;
    if (this.view) goTo(this.view, code.line);
  }

  private async trace(campaign: string, d: ServerEvent) {
    this.pointAt(d.code, true);
    try {
      const res = await fetch(this.url(`/campaigns/${campaign}/worlds/${d.index}/trace`), { signal: AbortSignal.timeout(TRACE_MS) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const traced = await res.json();
      if (this.picked?.d !== d) return;
      d.code = traced.code;
      this.pointAt(traced.code);
    } catch {
      if (this.picked?.d === d) this.pointAt(d.code);
    }
  }

  /** The world this run used, read only. */
  openWorld(_campaign: string, d: ServerEvent) {
    const text = `${JSON.stringify(d.world, null, 2)}\n`;
    const name = `${String(d.name)}.world.json`;
    this.worldTab.name(name);
    this.worldBar.replaceChildren(el('span', 'code-path', name), el('span', 'code-state', 'Read only'), el('span', 'code-bar-note', `Seed ${d.seed}. An edit or an AI fix can change only the controller, never this world or the judge.`));
    if (this.worldView) this.worldView.dispatch({ changes: { from: 0, to: this.worldView.state.doc.length, insert: text } });
    else this.worldView = editor(this.worldHost, text, json(), true);
    this.showWorld();
  }

  private clearRefusal() {
    if (this.refused.hidden) return;
    this.refused.hidden = true;
    if (this.view) goTo(this.view, this.picked?.d.code?.line ?? null);
  }

  private refuse(words: string, reasons: string[]) {
    this.refused.replaceChildren(el('div', 'code-refused-head', words), ...reasons.map(r => el('div', 'code-refused-line', r)));
    this.refused.hidden = false;
    const bad = reasons.map(r => r.match(/^line (\d+)/)).filter(Boolean).map(m => Number(m![1]));
    if (this.view) goTo(this.view, null, bad);
  }

  private async post(rest: string, body: unknown) {
    const res = await fetch(this.url(rest), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(FETCH_MS * 2) });
    return { status: res.status, body: await res.json().catch(() => ({})) };
  }

  private async run(scope: 'one' | 'all') {
    if (this.busy) return;
    const source = this.text;
    const campaign = this.picked?.campaign ?? (this.campaign || null);
    this.setBusy(true);
    try {
      const out = await this.post('/code', { source, run: scope, campaign, index: this.picked?.d.index });
      if (out.status === 422) { this.setBusy(false); this.refuse(out.body.words, out.body.reasons); return; }
      if (out.status !== 202) { this.setBusy(false); this.deps.note(out.body.words ?? `The run did not start: ${out.body.error ?? out.status}.`, true); return; }
      this.saved = source;
      await this.afterSave();
    } catch (err) {
      this.setBusy(false);
      this.deps.note(`Could not reach the run server: ${String(err)}`, true);
    }
  }

  private async afterSave() {
    const res = await fetch(this.url('/code'), { signal: AbortSignal.timeout(FETCH_MS) });
    if (res.ok) this.src = await res.json();
    this.refresh();
  }

  private resetToSource() {
    if (!this.src || !this.view) return;
    this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: this.src.original } });
    void this.post('/code', { source: this.src.original }).then(() => { this.saved = this.src!.original; return this.afterSave(); });
  }

  private async fix() {
    if (this.busy || !this.picked) return;
    if (this.dirty) {
      const saved = await this.post('/code', { source: this.text });
      if (saved.status === 422) { this.refuse(saved.body.words, saved.body.reasons); return; }
      this.saved = this.text;
      await this.afterSave();
    }
    this.setBusy(true);
    const out = await this.post('/code_fix', { campaign: this.picked.campaign, group: this.picked.d.verdict });
    if (out.status !== 202) { this.setBusy(false); this.deps.note(out.body.words ?? `The fix did not start: ${out.body.error ?? out.status}.`, true); }
  }

  private setBusy(on: boolean) {
    this.busy = on;
    this.refresh();
  }

  private campaign = '';

  setGrid(e: ServerEvent) {
    this.campaign = String(e.campaign);
    this.rows = e.rows as Row[];
    if (this.picked) {
      const row = this.rows.find(r => r.index === this.picked!.d.index);
      if (row) Object.assign(this.picked.d, { status: row.status, verdict: row.verdict, verdict_reason: row.verdict_reason });
    }
    this.refresh();
  }

  /** The server's idle event: its job ended. */
  jobDone() {
    if (this.busy) this.setBusy(false);
  }

  event(e: ServerEvent) {
    switch (e.type) {
      case 'code_run': this.onRun(e); break;
      case 'code_changed': void this.load(); break;
      case 'code_fix': this.deps.chat(this.fixCard(e)); break;
      case 'code_fix_decided': this.decided(e); break;
    }
  }

  private onRun(e: ServerEvent) {
    for (const r of e.rows) this.results.set(r.index, r);
    this.drawResults();
    if (this.picked) void this.freshDetail(this.picked);
  }

  private async freshDetail(picked: Picked) {
    const res = await fetch(this.url(`/campaigns/${picked.campaign}/worlds/${picked.d.index}`), { signal: AbortSignal.timeout(FETCH_MS) });
    if (!res.ok || this.picked !== picked) return;
    picked.d = await res.json();
    this.refresh();
    if (this.fileTab.root.classList.contains('on')) this.pointAt(picked.d.code);
  }

  private drawResults() {
    const order: Record<string, number> = { worse: 0, better: 1, same: 2 };
    const rows = [...this.results.values()].sort((a, b) => order[a.change] - order[b.change] || a.index - b.index);
    this.table.hidden = !rows.length;
    const line = (cells: (string | HTMLElement)[], cls = '') => {
      const row = el('div', `code-row ${cls}`.trim());
      for (const c of cells) row.append(typeof c === 'string' ? el('span', '', c) : c);
      return row;
    };
    const word = (r: { status?: string }) => {
      const s = el('span', '', asRow(r));
      s.dataset.status = String(r.status);
      return s;
    };
    const change = (c: string) => {
      const s = el('span', 'code-change', c === 'better' ? 'Better' : c === 'worse' ? 'Worse' : 'Same');
      s.dataset.change = c;
      return s;
    };
    this.table.replaceChildren(
      line(['World', 'First run', 'Before this run', 'Now', ''], 'code-row-head'),
      ...rows.map(r => {
        const row = line([plain(String(r.name)), word(r.first), word(r.old), word(r.new), change(r.change)]);
        row.title = String(r.new.verdict_reason ?? '');
        return row;
      }),
    );
  }

  private decided(e: ServerEvent) {
    const card = this.cards.get(String(e.fix));
    if (!card) return;
    for (const b of card.querySelectorAll('button')) b.disabled = true;
    card.querySelector('.code-fix-state')!.textContent = e.accepted ? 'Accepted. Your session copy now has this fix. The source file did not change.' : 'Rejected. Your code stays as it was.';
  }

  private cards = new Map<string, HTMLElement>();

  // The AI's fix in the chat: what it did to the numbers, then the diff, then Accept and Reject. A fix that did not help has nothing to accept.
  private fixCard(e: ServerEvent) {
    const card = el('div', 'chat-card code-fix');
    card.dataset.status = String(e.status);
    this.cards.set(String(e.fix), card);
    card.append(el('div', 'chat-card-title', `AI fix for ${asRow({ status: 'failed', verdict: e.group })}`));
    if (e.llm_note) card.append(el('div', 'chat-card-note', String(e.llm_note)));
    const helped = e.status === 'helped';
    card.append(el('div', helped ? 'code-fix-words' : 'code-fix-words code-fix-bad', String(e.words)));
    if (e.sets) {
      const table = el('div', 'code-fix-table');
      const row = (cells: string[], cls = '') => {
        const r = el('div', `code-fix-row ${cls}`.trim());
        for (const c of cells) r.append(el('span', '', c));
        return r;
      };
      table.append(row(['', 'Better', 'Worse', 'Same'], 'head'));
      for (const [key, label] of SET_NAMES) {
        const s = e.sets[key];
        if (s) { const r = row([`${label} (${s.n})`, String(s.better), String(s.worse), String(s.same)]); r.dataset.worse = String(s.worse > 0); table.append(r); }
      }
      card.append(table);
    }
    const flags = (e.flags ?? []) as { line: number; text: string; words: string }[];
    if (flags.length) card.append(el('div', 'code-fix-flag', `Weakens a safety check: ${flags.length} changed ${flags.length === 1 ? 'line touches' : 'lines touch'} the low-pressure, resume, tether or hold checks. Read ${flags.length === 1 ? 'it' : 'them'} before you accept.`));
    if (e.diff) card.append(diffBox(String(e.diff), flags));
    const state = el('div', 'chat-card-note code-fix-state');
    card.append(state);
    if (e.diff && helped) {
      const row = el('div', 'chat-options');
      const decide = (accept: boolean) => async () => {
        for (const b of row.querySelectorAll('button')) b.disabled = true;
        const out = await this.post('/code_fix', { campaign: e.campaign, fix: e.fix, accept });
        if (out.status !== 200) { state.textContent = out.body.words ?? `It did not apply: ${out.body.error ?? out.status}.`; for (const b of row.querySelectorAll('button')) b.disabled = false; }
      };
      const yes = el('button', 'chat-option code-fix-accept', 'Accept');
      const no = el('button', 'chat-option code-fix-reject', 'Reject');
      yes.type = no.type = 'button';
      yes.dataset.keep = no.dataset.keep = '1';
      yes.addEventListener('click', () => void decide(true)());
      no.addEventListener('click', () => void decide(false)());
      row.append(yes, no);
      card.append(row);
    } else if (e.diff) {
      state.textContent = 'Not applied. Your code stays as it was.';
    }
    if (e.sets) card.append(el('div', 'chat-card-note', `Small sample, in this simulation only. The AI saw ${e.held_back_worlds_shown_to_llm} held-back worlds. Only the controller copy changed, never the judge or the world.`));
    return card;
  }
}

function diffBox(diff: string, flags: { text: string }[]) {
  const box = el('div', 'code-diff');
  const flagged = new Set(flags.map(f => f.text));
  for (const raw of diff.split('\n')) {
    if (!raw || raw.startsWith('---') || raw.startsWith('+++')) continue;
    const kind = raw.startsWith('@@') ? 'hunk' : raw[0] === '+' ? 'add' : raw[0] === '-' ? 'del' : 'same';
    const row = el('div', `code-diff-line ${kind}`, raw.startsWith('@@') ? raw.replace(/^@@ -\d+(,\d+)? \+(\d+)(,\d+)? @@.*/, 'Line $2') : raw);
    if ((kind === 'add' || kind === 'del') && flagged.has(raw.slice(1).trim())) {
      row.classList.add('flag');
      row.append(el('span', 'code-diff-tag', 'weakens a safety check'));
    }
    box.append(row);
  }
  return box;
}
