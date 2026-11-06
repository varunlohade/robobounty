// The test run: one light 2D canvas per scenario, driven by the 1 Hz grid event. No WebGL here. A replay opens one view in the same stage and closes it on the way back.
import { el } from '../app/dom.ts';
import type { ServerEvent } from '../app/chat/live.ts';
import { fmtTime } from '../app/world_page.ts';

export type Status = 'queued' | 'running' | 'passed' | 'failed' | 'stuck' | 'held';
type Outline = { kind: 'area'; x0: number; x1: number; z0: number; z1: number } | { kind: 'route'; points: number[][] };
// What this scenario changed, from its world: an object's outline in the outline's axes, or a changed setting.
type Mark = { kind: 'shape'; what: string; name: string; text: string; points: number[][] } | { kind: 'value'; icon: string; text: string };
interface Film { count: number; cols: number; w: number; h: number }
export interface Row {
  index: number; name: string; group: string; reason: string; status: Status; held_back: boolean;
  t: number | null; t_limit: number | null; x: number | null; y: number | null;
  outline: Outline; marks?: Mark[]; frames?: number; film?: Film | null; verdict: string | null; verdict_reason: string | null;
  first?: { status: Status; verdict: string | null; verdict_reason: string | null };
}
export interface Played { page: HTMLElement; start: () => Promise<void>; stop: () => void; jump: (t: number) => void }
interface Deps { base: string; statusRight: HTMLElement; play: (how: ServerEvent) => Promise<Played | null>; openFile?: (d: ServerEvent) => void; openWorld?: (d: ServerEvent) => void }

const GAP = 6;
const PAD = 8;
const FETCH_MS = 15_000;
const MOVE_MS = 1000;
const LIVE_DRAW_MS = 40; // 25 draws a second is enough for a dot that crosses a square in several seconds.
const TRAIL_MAX = 200;
const ZOOM_MS = 950;
const ASPECT_MAX = 1.25;
const OUTLINE_MARGIN = 0.14;

const INK = { text: '#ECEEF1', text2: '#A3A9B3', muted: '#737A85', faint: '#4B515B', line: '#2A2F37', red: '#E5534B', redText: '#F27B73', amberText: '#E3B04F', greenText: '#5CC186' };
const MARK_FILL: Record<string, [string, string]> = { wet_patch: ['rgba(90,170,235,.38)', '#6FB7EE'], dirt_patch: ['rgba(176,140,90,.42)', '#C39C66'] };
const MARK_SOLID: [string, string] = ['rgba(236,238,241,.26)', '#C9CDD3'];
const MARK_MIN_PX = 2;
const FILM_MS = 250; // Each frame of a run's loop.
const FILM_HOLD = 6; // The last frame waits this many steps, so the end of the run reads before the loop restarts.
const FILM_STAGGER_MS = 137; // Squares do not step on the same beat.
const SCRIM = 'rgba(10,12,15,.72)';
const INSET_W = 0.42, INSET_H = 0.48;
const VALUE_ROW = 14;
const VALUE_ROWS_MAX = 2;
const ICON = 10;
const SANS = 'Inter, -apple-system, "Helvetica Neue", Arial, sans-serif';

const VERDICT_WORDS: Record<string, string> = {
  passed: 'Passed', fell: 'Fell', stuck: 'Stuck', timed_out: 'Timed out', off_route: 'Off route', sim_failed: 'Sim failed', sim_diverged: 'Sim failed', process_crashed: 'Crashed', froze: 'Froze',
  detach: 'Came off', tether_load: 'Tether load', slip_distance: 'Slipped', stalled: 'Stalled', time_limit: 'Time limit', coverage: 'Low coverage', false_done: 'False finish', wind_hold: 'Safe hold, wind', battery_stop: 'Safe hold, battery',
};
const COUNT_ROWS: [keyof Counts, string][] = [['running', 'Running'], ['queued', 'Queued'], ['passed', 'Passed'], ['failed', 'Failed'], ['stuck', 'Stuck'], ['safe_hold', 'Safe hold'], ['held', 'Held back']];
type Counts = Record<Status | 'safe_hold', number>;

const plainName = (name: string) => { const s = name.replaceAll('_', ' '); return s.charAt(0).toUpperCase() + s.slice(1); };

export function statusWord(r: Row): string {
  if (r.status === 'held' && r.held_back) return 'Held back';
  if (r.status === 'stuck' && !r.verdict) return 'Stuck';
  if (r.verdict) return VERDICT_WORDS[r.verdict] ?? plainName(r.verdict);
  return { queued: 'Queued', running: 'Running', passed: 'Passed', failed: 'Failed', stuck: 'Stuck', held: 'Safe hold' }[r.status];
}

// One square: a button around a canvas. The button carries focus, hover and the border. The canvas carries the picture.
class Square {
  readonly root = el('button', 'sq');
  private canvas = el('canvas');
  private c = this.canvas.getContext('2d', { alpha: false })!;
  private w = 0; private h = 0; private ratio = 1;
  private fromX = 0; private fromY = 0; private toX = 0; private toY = 0; private movedAt = 0; private placed = false;
  private trail: number[] = [];
  private shortName = ''; private shortFor = 0;
  private shown: HTMLImageElement | null = null; // The newest live frame, or the film sheet.
  private loading = false; private seenFrames = 0; private filmStep = -1;
  private film: Film | null = null;
  row: Row;
  stale = true;

  constructor(row: Row, private base: string) {
    this.row = row;
    this.root.type = 'button';
    this.root.dataset.index = String(row.index);
    this.root.append(this.canvas);
    this.set(row);
  }

  set(row: Row) {
    if (row.x !== null && row.y !== null) {
      if (!this.placed) { this.fromX = this.toX = row.x; this.fromY = this.toY = row.y; this.placed = true; } else if (row.x !== this.toX || row.y !== this.toY) {
        const [x, y] = this.at(performance.now());
        this.fromX = x; this.fromY = y; this.toX = row.x; this.toY = row.y;
        this.movedAt = performance.now();
      }
      this.trail.push(row.x, row.y);
      if (this.trail.length > TRAIL_MAX * 2) this.trail.splice(0, 2);
    }
    if (row.status === 'queued' && this.row.status !== 'queued') { this.trail = []; this.placed = false; }
    if (this.film && !row.film) { this.film = null; this.shown = null; this.seenFrames = 0; } // A re-run with no picture must not keep the old run's picture.
    const stale = row.status !== this.row.status || row.t !== this.row.t || row.x !== this.row.x || row.y !== this.row.y || row.verdict !== this.row.verdict;
    if (stale) this.stale = true;
    this.row = row;
    this.fetchPicture();
    this.root.dataset.status = row.status;
    this.root.dataset.held = String(row.held_back);
    this.root.dataset.marks = String(row.marks?.length ?? 0);
    this.root.setAttribute('aria-label', `${plainName(row.name)}. ${statusWord(row)}.`);
  }

  // At most one image in flight per square. A real frame of this run replaces the last when it has loaded.
  private fetchPicture() {
    const { row } = this;
    if (this.loading || this.film) return;
    const film = row.film ?? null;
    const frames = row.frames ?? 0;
    if (!film && frames <= this.seenFrames) return;
    this.loading = true;
    this.seenFrames = frames;
    const image = new Image();
    image.crossOrigin = 'anonymous';
    image.onload = () => {
      this.loading = false;
      this.shown = image;
      if (film) this.film = film;
      this.stale = true;
      this.root.dataset.picture = film ? 'film' : 'live';
    };
    image.onerror = () => { this.loading = false; };
    image.src = `${this.base}/worlds/${row.index}/${film ? 'film.jpg' : `latest.jpg?n=${frames}`}`;
  }

  /** A film moves to its next frame on its own clock. */
  tick(now: number) {
    if (!this.film) return;
    const step = Math.floor((now + this.row.index * FILM_STAGGER_MS) / FILM_MS);
    if (step !== this.filmStep) { this.filmStep = step; this.stale = true; }
  }

  // The run's real picture, cut to fill the square. Words and the map sit on it.
  private picture() {
    const { c, w, h, shown } = this;
    if (!shown) return false;
    const film = this.film;
    const fw = film?.w ?? shown.naturalWidth, fh = film?.h ?? shown.naturalHeight;
    let sx = 0, sy = 0;
    if (film) {
      const at = Math.min(film.count - 1, ((this.filmStep % (film.count + FILM_HOLD)) + film.count + FILM_HOLD) % (film.count + FILM_HOLD));
      sx = (at % film.cols) * fw; sy = Math.floor(at / film.cols) * fh;
    }
    const scale = Math.max(w / fw, h / fh), cw = w / scale, ch = h / scale;
    c.drawImage(shown, sx + (fw - cw) / 2, sy + (fh - ch) / 2, cw, ch, 0, 0, w, h);
    const { row } = this;
    if (row.status === 'failed' || row.status === 'stuck') { c.fillStyle = 'rgba(229,83,75,.2)'; c.fillRect(0, 0, w, h); }
    else if (row.status === 'held') { c.fillStyle = 'rgba(214,154,45,.14)'; c.fillRect(0, 0, w, h); }
    return true;
  }

  private at(now: number): [number, number] {
    const k = Math.min(1, (now - this.movedAt) / MOVE_MS);
    return [this.fromX + (this.toX - this.fromX) * k, this.fromY + (this.toY - this.fromY) * k];
  }

  size(w: number, h: number) {
    const ratio = Math.min(devicePixelRatio, 2);
    if (w === this.w && h === this.h && ratio === this.ratio) return;
    this.w = w; this.h = h; this.ratio = ratio;
    this.canvas.width = Math.round(w * ratio);
    this.canvas.height = Math.round(h * ratio);
    this.shortFor = 0;
    this.stale = true;
  }

  /** The dot still glides, or a run is alive, so this square redraws on the live clock. */
  get live() {
    return this.row.status === 'running' || performance.now() - this.movedAt < MOVE_MS;
  }

  draw(now: number) {
    const { c, w, h, row } = this;
    if (!w) return;
    this.stale = false;
    c.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
    const red = row.status === 'failed' || row.status === 'stuck';
    const amber = row.status === 'held' && !row.held_back;
    c.fillStyle = red ? '#2A1416' : amber ? '#231C10' : row.status === 'queued' || row.held_back ? '#0E1013' : '#14171B';
    c.fillRect(0, 0, w, h);
    if (row.held_back) this.hatch();

    const pictured = this.picture();
    const lines = this.valueLines();
    const foot = 20;
    const head = Math.max(22, lines ? 20 + lines * VALUE_ROW : 22);
    if (pictured) {
      c.fillStyle = SCRIM;
      c.fillRect(0, 0, w, head);
      c.fillRect(0, h - foot, w, foot);
    }
    const valuesBottom = this.values();
    const top = Math.max(22, valuesBottom + 2);
    if (pictured) {
      // On a picture the plan view shrinks to a corner map, since the camera's view does not line up with it.
      const iw = Math.round(w * INSET_W), ih = Math.round((h - foot - top) * INSET_H), ix = w - iw - 3, iy = h - foot - ih - 3;
      c.fillStyle = SCRIM;
      c.fillRect(ix, iy, iw, ih);
      this.outline(ix, iy + 2, iw, iy + ih - 2, now);
    } else {
      this.outline(0, top, w, h - foot, now);
    }

    c.textBaseline = 'middle';
    c.font = `400 10.5px ${SANS}`;
    if (this.shortFor !== w) { this.shortName = fit(c, plainName(row.name), w - PAD * 2); this.shortFor = w; }
    c.fillStyle = red ? INK.text : row.status === 'queued' || row.held_back ? INK.muted : INK.text2;
    c.textAlign = 'left';
    c.fillText(this.shortName, PAD, 12);

    const word = statusWord(row);
    c.font = `${red ? 500 : 400} 10.5px ${SANS}`;
    c.fillStyle = red ? INK.redText : amber ? INK.amberText : row.status === 'passed' ? INK.greenText : row.status === 'running' ? INK.text : INK.muted;
    let x = PAD;
    x += this.glyph(row, x, h - 11) ? 12 : 0;
    c.fillText(word, x, h - 11);
    const wordEnd = x + c.measureText(word).width;
    c.font = `400 10.5px ${SANS}`;
    const time = row.first && (row.first.verdict !== row.verdict) ? `was ${statusWord({ ...row, ...row.first })}` : row.t === null ? '' : `${Math.round(row.t)} s`;
    if (time && wordEnd + 6 + c.measureText(time).width <= w - PAD) {
      c.textAlign = 'right';
      c.fillStyle = red ? INK.redText : INK.muted;
      c.fillText(time, w - PAD, h - 11);
      c.textAlign = 'left';
    }
    if (row.t !== null && row.t_limit) {
      c.fillStyle = INK.line;
      c.fillRect(0, h - 2, w, 2);
      c.fillStyle = red ? INK.red : row.status === 'running' ? INK.text : INK.muted;
      c.fillRect(0, h - 2, w * Math.min(1, row.t / row.t_limit), 2);
    }
  }

  private markWords() {
    return [...new Map((this.row.marks ?? []).map(m => [m.text, m])).values()];
  }

  private valueLines() {
    const { c, w } = this;
    const words = this.markWords();
    if (!words.length) return 0;
    c.font = `400 10px ${SANS}`;
    let x = PAD, rows = 1;
    for (const m of words) {
      const width = c.measureText(m.text).width + (m.kind === 'value' ? ICON + 3 : ICON);
      if (x > PAD && x + width > w - PAD) {
        if (rows === VALUE_ROWS_MAX) break;
        x = PAD; rows++;
      }
      x += width + 8;
    }
    return rows;
  }

  // One line of small icons and values under the name, from the row's marks. Same words only once: a part brings many rectangles.
  private values() {
    const { c, w, row } = this;
    const words = this.markWords();
    if (!words.length) return 0;
    const dim = row.status === 'queued' || row.held_back;
    c.font = `400 10px ${SANS}`;
    c.textBaseline = 'middle';
    c.textAlign = 'left';
    let x = PAD, y = 26, rows = 1;
    for (const m of words) {
      const hasIcon = m.kind === 'value';
      const width = c.measureText(m.text).width + (hasIcon ? ICON + 3 : ICON);
      if (x > PAD && x + width > w - PAD) {
        if (rows === VALUE_ROWS_MAX) break;
        x = PAD; y += VALUE_ROW; rows++;
      }
      const ink = dim ? INK.muted : this.shown ? INK.text : INK.text2;
      if (m.kind === 'value') { markIcon(c, m.icon, x, y, ink); x += ICON + 3; } else {
        const [fill, edge] = MARK_FILL[m.what] ?? MARK_SOLID;
        c.fillStyle = fill; c.strokeStyle = edge; c.lineWidth = 1;
        c.fillRect(x, y - 3.5, 7, 7); c.strokeRect(x + 0.5, y - 3.5 + 0.5, 6, 6);
        x += ICON;
      }
      c.fillStyle = ink;
      const room = w - PAD - x;
      const text = c.measureText(m.text).width <= room ? m.text : fit(c, m.text, room);
      c.fillText(text, x, y);
      x += c.measureText(text).width + 8;
    }
    return y + 6;
  }

  private hatch() {
    const { c, w, h } = this;
    c.strokeStyle = 'rgba(255,255,255,.035)';
    c.lineWidth = 1;
    c.beginPath();
    for (let i = -h; i < w; i += 7) { c.moveTo(i, h); c.lineTo(i + h, 0); }
    c.stroke();
  }

  // The world's outline, the path the robot took, and the robot.
  private outline(left: number, top: number, w: number, bottom: number, now: number) {
    const { c, row } = this;
    const o = row.outline;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    const take = (x: number, y: number) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); };
    if (o.kind === 'area') { take(o.x0, o.z0); take(o.x1, o.z1); } else for (const [x, y] of o.points) take(x, y);
    if (!Number.isFinite(x0)) return;
    const shapes = (row.marks ?? []).filter((m): m is Extract<Mark, { kind: 'shape' }> => m.kind === 'shape');
    for (const m of shapes) for (const [x, y] of m.points) take(x, y);
    // A robot that leaves the outline stays in the square, with the scale eased to fit it.
    for (let i = 0; i < this.trail.length; i += 2) take(this.trail[i], this.trail[i + 1]);
    const spanX = Math.max(x1 - x0, 0.5), spanY = Math.max(y1 - y0, 0.5);
    const pad = left ? 3 : PAD;
    const aw = w - pad * 2, ah = bottom - top - 4;
    const scale = Math.min(aw / (spanX * (1 + OUTLINE_MARGIN)), ah / (spanY * (1 + OUTLINE_MARGIN)));
    const ox = left + w / 2 - ((x0 + x1) / 2) * scale, oy = top + 2 + ah / 2 + ((y0 + y1) / 2) * scale;
    const px = (x: number) => ox + x * scale, py = (y: number) => oy - y * scale;
    const red = row.status === 'failed' || row.status === 'stuck';
    const dim = row.status === 'queued' || row.held_back;

    c.save();
    c.beginPath();
    c.rect(left, top - 2, w, bottom - top + 4);
    c.clip();
    c.lineWidth = 1;
    c.strokeStyle = dim ? INK.faint : red ? 'rgba(242,123,115,.45)' : INK.muted;
    c.lineJoin = 'round';
    const ink = c.strokeStyle;
    for (const m of shapes) {
      const [fill, edge] = MARK_FILL[m.what] ?? MARK_SOLID;
      c.fillStyle = fill; c.strokeStyle = edge;
      c.beginPath();
      // A thin sill still shows: a shape keeps a width and height of a few pixels.
      const xs = m.points.map(p => px(p[0])), ys = m.points.map(p => py(p[1]));
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      const growX = Math.max(1, MARK_MIN_PX / Math.max(Math.max(...xs) - Math.min(...xs), 0.01)), growY = Math.max(1, MARK_MIN_PX / Math.max(Math.max(...ys) - Math.min(...ys), 0.01));
      xs.forEach((sx, i) => { const qx = cx + (sx - cx) * growX, qy = cy + (ys[i] - cy) * growY; if (i) c.lineTo(qx, qy); else c.moveTo(qx, qy); });
      c.closePath();
      c.fill();
      c.stroke();
    }
    c.strokeStyle = ink;
    c.beginPath();
    if (o.kind === 'area') c.rect(px(o.x0) + 0.5, py(o.z1) + 0.5, (o.x1 - o.x0) * scale, (o.z1 - o.z0) * scale);
    else o.points.forEach(([x, y], i) => { if (i) c.lineTo(px(x), py(y)); else c.moveTo(px(x), py(y)); });
    c.stroke();
    if (o.kind === 'route' && !dim) {
      c.fillStyle = c.strokeStyle;
      for (const [x, y] of o.points) { c.beginPath(); c.arc(px(x), py(y), 1.5, 0, 7); c.fill(); }
    }
    if (this.placed) {
      const [rx, ry] = this.at(now);
      if (this.trail.length >= 2) {
        c.strokeStyle = red ? INK.redText : row.status === 'running' ? INK.text : INK.text2;
        c.lineWidth = 1.25;
        c.beginPath();
        c.moveTo(px(this.trail[0]), py(this.trail[1]));
        for (let i = 2; i < this.trail.length; i += 2) c.lineTo(px(this.trail[i]), py(this.trail[i + 1]));
        c.lineTo(px(rx), py(ry));
        c.stroke();
      }
      const dx = px(rx), dy = py(ry);
      if (row.status === 'running') {
        const k = (now % 1400) / 1400;
        c.strokeStyle = `rgba(236,238,241,${0.5 * (1 - k)})`;
        c.lineWidth = 1;
        c.beginPath(); c.arc(dx, dy, 3 + 6 * k, 0, 7); c.stroke();
      }
      if (red) {
        c.strokeStyle = INK.red;
        c.lineWidth = 2;
        c.beginPath();
        c.moveTo(dx - 4, dy - 4); c.lineTo(dx + 4, dy + 4); c.moveTo(dx + 4, dy - 4); c.lineTo(dx - 4, dy + 4);
        c.stroke();
      } else {
        c.fillStyle = row.status === 'passed' ? INK.greenText : row.status === 'held' ? INK.amberText : INK.text;
        c.beginPath(); c.arc(dx, dy, row.status === 'running' ? 3 : 2.5, 0, 7); c.fill();
      }
    }
    c.restore();
  }

  // A status never rests on colour alone.
  private glyph(row: Row, x: number, y: number): boolean {
    const { c } = this;
    c.lineWidth = 1.25;
    c.lineCap = 'round';
    if (row.status === 'passed') {
      c.strokeStyle = INK.greenText;
      c.beginPath(); c.moveTo(x, y); c.lineTo(x + 3, y + 3); c.lineTo(x + 8, y - 3); c.stroke();
      return true;
    }
    if (row.status === 'failed') {
      c.strokeStyle = INK.redText;
      c.beginPath(); c.moveTo(x, y - 3.5); c.lineTo(x + 7, y + 3.5); c.moveTo(x + 7, y - 3.5); c.lineTo(x, y + 3.5); c.stroke();
      return true;
    }
    if (row.status === 'stuck') {
      c.fillStyle = INK.redText;
      c.fillRect(x, y - 3.5, 2.5, 7); c.fillRect(x + 4.5, y - 3.5, 2.5, 7);
      return true;
    }
    if (row.status === 'held' && !row.held_back) {
      c.strokeStyle = INK.amberText;
      c.beginPath(); c.moveTo(x, y); c.lineTo(x + 7, y); c.stroke();
      return true;
    }
    return false;
  }
}

// A small line icon, 10 px wide, centred on y. It only says which setting the value beside it is.
function markIcon(c: CanvasRenderingContext2D, name: string, x: number, y: number, ink: string) {
  c.save();
  c.translate(x, y - ICON / 2);
  c.strokeStyle = ink; c.fillStyle = ink; c.lineWidth = 1; c.lineCap = 'round'; c.lineJoin = 'round';
  c.beginPath();
  const line = (...p: number[]) => { c.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) c.lineTo(p[i], p[i + 1]); };
  switch (name) {
    case 'wind':
      c.moveTo(0.5, 3.5); c.lineTo(6.5, 3.5); c.arc(6.5, 2, 1.5, Math.PI / 2, -Math.PI / 2, true);
      c.moveTo(0.5, 6); c.lineTo(8, 6); c.arc(8, 7.5, 1.5, -Math.PI / 2, Math.PI / 2);
      break;
    case 'rain':
      line(3, 1, 1, 4.5); line(6, 1, 4, 4.5); line(9, 1, 7, 4.5); line(3, 5.5, 1, 9); line(6, 5.5, 4, 9); line(9, 5.5, 7, 9);
      break;
    case 'leak':
      c.moveTo(5, 0.5); c.lineTo(8, 5.5); c.arc(5, 6.5, 3, -0.32, Math.PI + 0.32); c.closePath();
      break;
    case 'suction':
      line(0.5, 9, 9.5, 9); line(5, 1, 5, 6.5); line(2.8, 4.3, 5, 6.5, 7.2, 4.3);
      break;
    case 'pad':
      line(1, 8, 9, 8); line(2, 5.5, 8, 5.5, 8, 8); line(2, 5.5, 2, 8); line(5, 0.5, 5, 3.5);
      break;
    case 'battery':
      c.rect(0.5, 2.5, 8, 5); line(9.5, 4, 9.5, 6);
      break;
    case 'speed':
      line(1, 2, 4, 5, 1, 8); line(5, 2, 8, 5, 5, 8);
      break;
    case 'dirt':
      for (const [dx, dy] of [[1.5, 2], [5, 1], [8.5, 3], [3, 5.5], [7, 6.5], [1.5, 8.5], [5, 9]]) { c.moveTo(dx + 0.7, dy); c.arc(dx, dy, 0.7, 0, 7); }
      break;
    case 'panes':
      c.rect(0.5, 0.5, 9, 9); line(5, 0.5, 5, 9.5); line(0.5, 5, 9.5, 5);
      break;
    case 'margin':
      c.rect(0.5, 0.5, 9, 9); c.rect(3, 3, 4, 4);
      break;
    case 'corner':
      line(1, 9.5, 1, 1, 9.5, 1);
      break;
    case 'setback':
      line(0.5, 1, 4, 1, 4, 5, 9.5, 5, 9.5, 9.5);
      break;
    case 'heat':
      line(5, 1, 5, 6); c.moveTo(7, 7.5); c.arc(5, 7.5, 2, 0, 7);
      break;
    case 'grip':
      line(0.5, 8, 3, 3, 5.5, 8, 8, 3, 9.5, 6);
      break;
    case 'payload':
      c.rect(1, 3.5, 8, 6); line(3.5, 3.5, 3.5, 1, 6.5, 1, 6.5, 3.5);
      break;
    case 'gravity':
      line(5, 0.5, 5, 7); line(2.5, 4.8, 5, 7.3, 7.5, 4.8); line(1, 9.5, 9, 9.5);
      break;
    case 'route':
      line(1, 8.5, 5, 8.5, 5, 1.5, 9, 1.5);
      break;
    case 'time':
      c.moveTo(9.5, 5); c.arc(5, 5, 4.5, 0, 7); line(5, 2.5, 5, 5, 7, 6);
      break;
    default:
      c.moveTo(6.5, 5); c.arc(5, 5, 1.5, 0, 7);
  }
  c.stroke();
  c.restore();
}

function fit(c: CanvasRenderingContext2D, text: string, width: number) {
  if (c.measureText(text).width <= width) return text;
  let lo = 0, hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (c.measureText(`${text.slice(0, mid)}…`).width <= width) lo = mid; else hi = mid - 1;
  }
  return `${text.slice(0, lo).trimEnd()}…`;
}

export class Grid {
  readonly root = el('div', 'grid-page');
  campaign = '';
  private bar = el('div', 'grid-bar');
  private back = el('button', 'grid-back', 'Back to grid');
  private countsBox = el('div', 'grid-counts');
  private clock = el('span', 'grid-clock');
  private recorded = el('span', 'grid-recorded', 'Recorded run');
  private notTestedBtn = el('button', 'grid-btn', 'Not tested');
  private main = el('div', 'grid-main');
  private stage = el('div', 'grid-stage');
  private board = el('div', 'grid-board');
  private replayHost = el('div', 'grid-replay');
  private rail = el('aside', 'grid-rail');
  private hover = el('div', 'grid-hover');
  private squares = new Map<number, Square>();
  private counts: Partial<Record<keyof Counts, HTMLElement>> = {};
  private observer: ResizeObserver;
  private run = 0;
  private lastLive = 0;
  private selected: number | null = null;
  private playing: Played | null = null;
  private scenarios: ServerEvent | null = null;
  private done_: ServerEvent | null = null;
  private openToken = 0;
  private entered = false;
  private onKey = (e: KeyboardEvent) => {
    if (e.key !== 'Escape' || !this.root.isConnected) return;
    if ((e.target as HTMLElement).closest('.chat')) return;
    this.closeDetail();
  };
  drawMs = 0; drawn = 0;

  constructor(private deps: Deps) {
    this.back.type = 'button';
    this.back.hidden = true;
    this.back.addEventListener('click', () => this.closeDetail());
    for (const [key, label] of COUNT_ROWS) {
      const chip = el('span', 'grid-count');
      chip.dataset.status = key;
      const n = el('b', '', '0');
      chip.append(el('i'), el('span', '', label), n);
      this.counts[key] = n;
      this.countsBox.append(chip);
    }
    this.notTestedBtn.type = 'button';
    this.notTestedBtn.hidden = true;
    this.notTestedBtn.addEventListener('click', () => this.toggleNotTested());
    const end = el('div', 'grid-bar-end');
    this.recorded.hidden = true;
    end.append(this.recorded, this.clock, this.notTestedBtn);
    this.bar.append(this.back, this.countsBox, end);

    this.replayHost.hidden = true;
    this.stage.append(this.board, this.replayHost);
    this.rail.hidden = true;
    this.hover.hidden = true;
    this.main.append(this.stage, this.rail);
    this.root.append(this.bar, this.main, this.hover);

    this.board.addEventListener('pointerover', e => { const s = this.squareAt(e.target); if (s) this.showHover(s); });
    this.board.addEventListener('pointerleave', () => { this.hover.hidden = true; });
    this.board.addEventListener('click', e => { const s = this.squareAt(e.target); if (s) void this.openDetail(s.row.index); });
    this.observer = new ResizeObserver(() => this.layout());
    void document.fonts?.ready.then(() => { for (const s of this.squares.values()) { s.size(0, 0); } this.layout(); });
  }

  private squareAt(target: EventTarget | null) {
    const b = (target as HTMLElement).closest<HTMLElement>('.sq');
    return b ? this.squares.get(Number(b.dataset.index)) : undefined;
  }

  setScenarios(e: ServerEvent) {
    this.scenarios = e;
    const n = (e.not_tested ?? []).length;
    this.notTestedBtn.hidden = false;
    this.notTestedBtn.textContent = `Not tested ${n}`;
  }

  update(e: ServerEvent) {
    this.campaign = String(e.campaign);
    this.recorded.hidden = !e.recorded;
    let added = false;
    for (const row of e.rows as Row[]) {
      const had = this.squares.get(row.index);
      if (had) {
        const changed = had.row.status !== row.status;
        had.set(row);
        if (changed && this.selected === row.index) void this.refreshDetail(row.index);
      } else {
        const s = new Square(row, this.deps.base);
        this.squares.set(row.index, s);
        this.board.append(s.root);
        added = true;
      }
    }
    for (const [key] of COUNT_ROWS) {
      const n = Number(e.counts?.[key] ?? 0);
      this.counts[key]!.textContent = String(n);
      this.counts[key]!.parentElement!.dataset.some = String(n > 0);
    }
    if (!this.done_) this.clock.textContent = e.running ? `${fmtTime(Number(e.elapsed_s))}, ${e.max_procs} at once` : `Finished in ${fmtTime(Number(e.elapsed_s))}`;
    this.root.dataset.running = String(Boolean(e.running));
    this.root.dataset.updates = String(Number(this.root.dataset.updates ?? 0) + 1);
    if (added) this.layout();
  }

  done(e: ServerEvent) {
    this.done_ = e;
    this.clock.textContent = `Finished in ${fmtTime(Number(e.wall_s))}, ${e.max_procs} at once`;
    this.root.dataset.running = 'false';
    this.root.dataset.done = 'true';
  }

  // The most squares that fit the stage, each as near square as the space allows.
  private layout() {
    const W = this.stage.clientWidth - GAP * 2 - 4, H = this.stage.clientHeight - GAP * 2 - 4;
    const n = this.squares.size;
    if (!n || W <= 0 || H <= 0 || this.board.hidden) return;
    let best = { side: 0, cols: 1, cw: 0, ch: 0 };
    for (let cols = 1; cols <= n; cols++) {
      const rows = Math.ceil(n / cols);
      const cw = (W - GAP * (cols - 1)) / cols, ch = (H - GAP * (rows - 1)) / rows;
      const side = Math.min(cw, ch);
      if (side > best.side) best = { side, cols, cw, ch };
    }
    const cw = Math.floor(Math.min(best.cw, best.side * ASPECT_MAX)), ch = Math.floor(Math.min(best.ch, best.side * ASPECT_MAX));
    this.board.style.gridTemplateColumns = `repeat(${best.cols}, ${cw}px)`;
    this.board.style.gridAutoRows = `${ch}px`;
    this.board.style.gap = `${GAP}px`;
    // The border is 1 px on each side of the canvas.
    for (const s of this.squares.values()) s.size(cw - 2, ch - 2);
    this.drawStale(performance.now());
  }

  private drawStale(now: number) {
    if (this.board.hidden) return;
    const t0 = performance.now();
    let any = 0;
    const live = now - this.lastLive >= LIVE_DRAW_MS;
    for (const s of this.squares.values()) {
      s.tick(now);
      if (s.stale || (live && s.live)) { s.draw(now); any++; }
    }
    if (live) this.lastLive = now;
    if (any) { this.drawMs += performance.now() - t0; this.drawn++; }
  }

  private loop() {
    const run = ++this.run;
    const tick = (now: number) => {
      if (run !== this.run) return;
      this.drawStale(now);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /** The grid is on screen. */
  enter() {
    if (this.entered) return;
    this.entered = true;
    this.observer.observe(this.stage);
    addEventListener('keydown', this.onKey);
    this.layout();
    this.loop();
  }

  /** Something else takes the main area. The rows stay, so a return finds them. */
  leave() {
    this.entered = false;
    this.run++;
    this.observer.disconnect();
    removeEventListener('keydown', this.onKey);
    this.closeReplay();
    this.closeRail();
    this.root.remove();
  }

  /** The main window pulls back from the single view, out to the grid. */
  async zoomFrom(outgoing: HTMLElement | null) {
    this.layout();
    this.drawStale(performance.now());
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const target = [...this.squares.values()].find(s => s.row.status === 'running') ?? [...this.squares.values()].find(s => !s.row.held_back) ?? [...this.squares.values()][0];
    if (!outgoing || !target || still) { this.root.dataset.zoom = 'done'; return; }
    const v = outgoing.getBoundingClientRect(), sq = target.root.getBoundingClientRect(), b = this.board.getBoundingClientRect();
    const scale = v.width / sq.width;
    const cx = sq.left + sq.width / 2 - b.left, cy = sq.top + sq.height / 2 - b.top;
    const tx = v.left + v.width / 2 - b.left - scale * cx, ty = v.top + v.height / 2 - b.top - scale * cy;
    const easing = 'cubic-bezier(.3,.05,.15,1)';
    this.root.dataset.zoom = 'moving';
    // The view rides inside the board, on its square, so the two move as one picture.
    Object.assign(outgoing.style, { position: 'absolute', inset: 'auto', left: '0', top: '0', width: `${v.width}px`, height: `${v.height}px`, zIndex: '4', transformOrigin: '0 0', pointerEvents: 'none', transform: `translate(${cx - v.width / (2 * scale)}px, ${cy - v.height / (2 * scale)}px) scale(${1 / scale})` });
    this.board.append(outgoing);
    this.board.style.transformOrigin = '0 0';
    const toBoard = this.board.animate([{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }, { transform: 'none' }], { duration: ZOOM_MS, easing, fill: 'both' });
    this.bar.animate([{ opacity: 0 }, { opacity: 0, offset: 0.5 }, { opacity: 1 }], { duration: ZOOM_MS, fill: 'both' });
    const fromView = outgoing.animate([{ opacity: 1 }, { opacity: 1, offset: 0.5 }, { opacity: 0 }], { duration: ZOOM_MS, fill: 'both' });
    await Promise.all([toBoard.finished, fromView.finished]);
    toBoard.cancel();
    this.root.dataset.zoom = 'done';
    this.layout();
  }

  private showHover(s: Square) {
    const { row } = s;
    this.hover.replaceChildren(el('div', 'grid-hover-name', plainName(row.name)), el('div', 'grid-hover-group', row.group), el('div', 'grid-hover-reason', row.reason));
    const marks = [...new Set((row.marks ?? []).map(m => m.text))];
    if (marks.length) this.hover.append(el('div', 'grid-hover-group', marks.join(', ')));
    if (row.first) this.hover.append(el('div', 'grid-hover-group', `First run: ${statusWord({ ...row, ...row.first })}`));
    if (row.verdict_reason) this.hover.append(el('div', `grid-hover-verdict${row.status === 'failed' || row.status === 'stuck' ? ' bad' : ''}`, row.verdict_reason));
    this.hover.hidden = false;
    const r = s.root.getBoundingClientRect(), box = this.root.getBoundingClientRect(), hw = this.hover.offsetWidth, hh = this.hover.offsetHeight;
    let left = r.right + 8 - box.left;
    if (left + hw > box.width - 8) left = r.left - hw - 8 - box.left;
    const top = Math.max(8, Math.min(box.height - hh - 8, r.top - box.top));
    this.hover.style.left = `${Math.max(8, left)}px`;
    this.hover.style.top = `${top}px`;
  }

  private select(index: number | null) {
    if (this.selected !== null) this.squares.get(this.selected)?.root.classList.remove('picked');
    this.selected = index;
    if (index !== null) this.squares.get(index)?.root.classList.add('picked');
  }

  private async getJson(path: string) {
    const res = await fetch(`${this.deps.base}${path}`, { signal: AbortSignal.timeout(FETCH_MS) });
    return { ok: res.ok, status: res.status, body: await res.json().catch(() => null) };
  }

  private async openDetail(index: number) {
    this.hover.hidden = true;
    this.select(index);
    this.rail.hidden = false;
    this.rail.dataset.mode = 'detail';
    this.back.hidden = false;
    await this.refreshDetail(index);
    this.layout();
  }

  private async refreshDetail(index: number) {
    const token = ++this.openToken;
    const row = this.squares.get(index)?.row;
    if (row) this.fillRail(this.detailHead(row), [el('div', 'grid-rail-note', 'Loading the details')]);
    let detail: ServerEvent | null = null;
    let failure = '';
    try {
      const got = await this.getJson(`/worlds/${index}`);
      if (got.ok) detail = got.body; else failure = `HTTP ${got.status}`;
    } catch (err) { failure = String(err); }
    if (token !== this.openToken || this.selected !== index) return;
    if (!detail) {
      this.fillRail(row ? this.detailHead(row) : [], [el('div', 'grid-rail-note bad', `Could not load the details: ${failure}`)]);
      return;
    }
    this.fillRail(this.detailHead(detail as unknown as Row), this.detailBody(detail));
    this.rail.dataset.index = String(index);
    if (detail.replay && this.playingIndex !== index) void this.playReplay(index);
    else if (!detail.replay && this.playingIndex !== index) this.closeReplay();
  }

  private playingIndex: number | null = null;
  private replayToken = 0;

  private async playReplay(index: number) {
    this.closeReplay();
    const token = this.replayToken;
    this.playingIndex = index;
    const loading = el('div', 'grid-replay-note', 'Loading the replay');
    this.replayHost.replaceChildren(loading);
    this.replayHost.hidden = false;
    this.board.hidden = true;
    let failure = '';
    try {
      const how = await this.getJson(`/worlds/${index}/replay`);
      if (token !== this.replayToken) return;
      if (!how.ok) failure = how.status === 404 ? 'This run left no replay.' : `HTTP ${how.status}`;
      else {
        const played = await this.deps.play(how.body);
        if (token !== this.replayToken) { played?.stop(); return; }
        if (!played) failure = 'The replay did not load.';
        else {
          this.replayHost.replaceChildren(played.page);
          this.playing = played;
          await played.start();
          return;
        }
      }
    } catch (err) { failure = String(err); }
    if (token === this.replayToken) loading.textContent = failure;
  }

  private closeReplay() {
    this.replayToken++;
    this.playing?.stop();
    this.playing = null;
    this.playingIndex = null;
    this.replayHost.replaceChildren();
    this.replayHost.hidden = true;
    if (this.board.hidden) {
      this.board.hidden = false;
      for (const s of this.squares.values()) s.stale = true;
      this.layout();
    }
  }

  private closeRail() {
    this.openToken++;
    this.select(null);
    this.rail.hidden = true;
    delete this.rail.dataset.mode;
    delete this.rail.dataset.index;
    this.back.hidden = true;
  }

  closeDetail() {
    this.closeRail();
    this.closeReplay();
    this.layout();
  }

  private toggleNotTested() {
    if (this.rail.dataset.mode === 'not_tested') { this.closeRail(); this.layout(); return; }
    this.closeReplay();
    this.closeRail();
    const s = this.scenarios;
    const list = (s?.not_tested ?? []) as { factor: string; reason: string; source: string }[];
    const body: HTMLElement[] = [];
    for (const item of list) {
      const row = el('div', 'grid-nt');
      row.append(el('div', 'grid-nt-name', item.factor), el('div', 'grid-nt-reason', item.reason), el('div', 'grid-nt-source', item.source === 'agent' ? 'Named by the agent' : 'Named by the code'));
      body.push(row);
    }
    if (!list.length) body.push(el('div', 'grid-rail-note', 'The list is empty.'));
    const dropped = Object.entries((s?.dropped ?? {}) as Record<string, number>);
    if (dropped.length) body.push(section('Refused by the code', dropped.map(([k, n]) => fact(k.replace(/^refused:/, '').replaceAll('_', ' '), String(n)))));
    if (s?.note) body.push(el('div', 'grid-rail-note', String(s.note)));
    this.rail.hidden = false;
    this.rail.dataset.mode = 'not_tested';
    this.back.hidden = false;
    this.fillRail([el('h3', 'grid-rail-title', 'Not tested')], body);
    this.layout();
  }

  private fillRail(head: HTMLElement[], body: HTMLElement[]) {
    this.rail.replaceChildren(...head, ...body);
    this.rail.scrollTop = 0;
  }

  private detailHead(d: Row): HTMLElement[] {
    const chip = el('div', 'grid-chip');
    chip.dataset.status = d.status;
    chip.dataset.held = String(d.held_back);
    chip.append(el('i'), el('span', '', statusWord(d)));
    return [el('h3', 'grid-rail-title', plainName(d.name)), el('div', 'grid-rail-group', d.group), chip];
  }

  private detailBody(d: ServerEvent): HTMLElement[] {
    const out: HTMLElement[] = [];
    const bad = d.status === 'failed' || d.status === 'stuck';
    if (d.verdict_reason) out.push(section('Judge', [el('div', bad ? 'grid-text bad' : 'grid-text', String(d.verdict_reason))]));
    out.push(section('Why this scenario', [el('div', 'grid-text', String(d.reason))]));
    if (d.held_back) out.push(el('div', 'grid-rail-note', 'Kept back as a fresh set for testing a change. It does not run here.'));
    else if (!d.replay) out.push(el('div', 'grid-rail-note', 'The replay comes when this run ends.'));
    const numbers = Object.entries((d.numbers ?? {}) as Record<string, unknown>);
    if (numbers.length) out.push(section('Numbers', numbers.map(([k, v]) => fact(k.replaceAll('_', ' '), typeof v === 'number' ? String(Number(v.toFixed(3))) : String(v)))));
    if (d.changes?.length) out.push(section('Changes to the world', (d.changes as string[]).map(c => el('div', 'grid-mono', c))));
    if (d.events?.length) {
      out.push(section('Events', (d.events as { name: string; t: number; value?: number }[]).map(ev => {
        const row = el('button', 'grid-event');
        row.type = 'button';
        row.append(el('span', '', `${ev.t} s`), el('span', '', ev.name));
        row.addEventListener('click', () => this.playing?.jump(ev.t));
        return row;
      })));
    }
    const log = (d.log ?? []) as string[];
    const logBox = el('pre', 'grid-log', log.length ? log.join('\n') : 'No log lines yet.');
    out.push(section('Last log lines', [logBox]));
    const file = el('div', 'grid-file');
    const open = el('button', 'grid-btn', 'Open file');
    open.type = 'button';
    open.addEventListener('click', () => this.deps.openFile?.(d));
    const world = el('button', 'grid-btn', 'World file');
    world.type = 'button';
    world.addEventListener('click', () => this.deps.openWorld?.(d));
    file.append(open, world);
    if (d.first) out.push(section('Old and new', [fact('First run', statusWord({ ...d, ...d.first } as unknown as Row)), fact('Latest run', statusWord(d as unknown as Row))]));
    const code = d.code as { file: string; line: number; traced: boolean; why?: string } | null;
    const parts: HTMLElement[] = [];
    if (code) {
      parts.push(el('div', 'grid-mono', `${code.file}:${code.line}`), el('div', 'grid-rail-note', code.traced ? 'Traced line.' : 'Active code at that moment, not a traced line.'));
      if (code.why) parts.push(el('div', 'grid-text', code.why));
    }
    if (parts.length) out.push(section('Code', parts));
    const facts: HTMLElement[] = [];
    if (d.seed !== undefined) facts.push(fact('Seed', String(d.seed)));
    if (d.wall_s != null) facts.push(fact('Wall time', `${Number(d.wall_s).toFixed(1)} s`));
    if (facts.length) out.push(section('Run', facts));
    if (d.note) out.push(el('div', 'grid-rail-note', String(d.note)));
    if (d.label) out.push(el('div', 'grid-mono grid-label', String(d.label)));
    out.push(file);
    return out;
  }
}

function section(title: string, body: HTMLElement[]) {
  const box = el('section', 'grid-section');
  box.append(el('h4', '', title), ...body);
  return box;
}

function fact(name: string, value: string) {
  const row = el('div', 'grid-fact');
  row.append(el('span', '', name), el('span', '', value));
  return row;
}
