// A stand-in for the run server, shaped by docs/LAB-EVENTS.md, for checks that need no physics. Its worlds and verdicts are invented. Replays come from the inspection pack's real recorded files.
// node src/lab/tools/fake_lab_server.mjs --port N [--procs 6] [--speed 4] [--count 50]
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { gunzipSync } from 'node:zlib';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const PORT = Number(arg('port', 5197));
const PROCS = Number(arg('procs', 6));
const SPEED = Number(arg('speed', 4));
const COUNT = Number(arg('count', 50));
const OUT = join(ROOT, 'policy/packs/inspection/out');
const RESULTS = JSON.parse(readFileSync(join(OUT, 'results.json'), 'utf8')).worlds;
const NOTE = 'Simulated. Fake test server: these verdicts are invented for a page check.';
const ROUTE = [[0, 0], [5, 0], [5, 4], [11, 4]];
const AREA = { kind: 'area', x0: -1.2, x1: 1.2, z0: 40, z1: 43 };
const GROUPS = [['Things on the walkway', 'low_pipe'], ['Wet and slippery floor', 'wet_floor'], ['Steep crossovers', 'steep_crossover'], ['Heavy payload', 'payload_35kg'], ['Small clutter', 'conduit_4cm'], ['Plant as built', 'plant'], ['Clear obstacles', 'clear_cabinet'], ['Light payload', 'payload_10kg'], ['Leak beside the path', 'leak_walkway'], ['Low gravity', 'gravity_3_71'], ['Valve on the route', 'valve']];


const worlds = (pack) => Array.from({ length: COUNT }, (_, index) => {
  const [group, base] = GROUPS[index % GROUPS.length];
  const seeded = (index * 37) % 11;
  return {
    index, name: `${base}_${index}`, group, base, reason: `Reasoned guess: ${group.toLowerCase()} may stop the robot on this route, case ${index}.`,
    held_back: (index + 1) % 5 === 0, seed: 3100 + index, changes: [`add_object ${base} at x ${(seeded * 0.4 + 1).toFixed(1)} m`],
    verdict: RESULTS[base].verdict, verdict_reason: RESULTS[base].reason, numbers: RESULTS[base], pack,
    sticks: index === 7 ? 'stays' : index === 13 ? 'resumes' : null, span: 8 + seeded,
  };
});
const along = (points, k) => {
  const legs = points.slice(1).map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let left = k * legs.reduce((a, b) => a + b, 0);
  for (let i = 0; i < legs.length; i++) {
    if (left <= legs[i]) { const f = left / legs[i]; return [points[i][0] + (points[i + 1][0] - points[i][0]) * f, points[i][1] + (points[i + 1][1] - points[i][1]) * f]; }
    left -= legs[i];
  }
  return points.at(-1);
};

const sessions = new Map();
const cors = (req, res) => {
  const origin = req.headers.origin ?? '*';
  res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Vary', 'Origin');
};
const json = (res, code, body) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
const emit = (s, event, stored = true) => {
  let line;
  if (stored) { s.events.push(event); line = `id: ${s.events.length - 1}\ndata: ${JSON.stringify(event)}\n\n`; } else line = `data: ${JSON.stringify(event)}\n\n`;
  for (const client of s.clients) client.write(line);
};
const poseWorld = pack => {
  const replay = JSON.parse(gunzipSync(readFileSync(join(OUT, 'plant.replay.json.gz'))).toString('utf8'));
  return { type: 'pose_world', pack, hash: 'fakehash', world: {}, solids: replay.solids, scenery: replay.scenery, route: replay.route, floor_friction: replay.floor_friction, note: NOTE };
};

function gridOf(s, now) {
  const c = s.campaign;
  const elapsed = ((now - c.t0) / 1000) * SPEED;
  const counts = { queued: 0, running: 0, passed: 0, failed: 0, stuck: 0, held: 0 };
  const rows = c.worlds.map(w => {
    const outline = w.pack === 'window' ? AREA : { kind: 'route', points: ROUTE };
    const row = { index: w.index, name: w.name, group: w.group, reason: w.reason, held_back: w.held_back, status: 'queued', t: null, t_limit: null, x: null, y: null, outline, verdict: null, verdict_reason: null };
    if (w.held_back) { row.status = 'held'; counts.held++; return row; }
    const started = w.start ?? Infinity;
    if (elapsed < started) { counts.queued++; return row; }
    let k = (elapsed - started) / w.span;
    let status = 'running';
    if (w.sticks === 'stays' && k > 0.4) { k = 0.4; status = 'stuck'; }
    if (w.sticks === 'resumes') { if (k > 0.3 && k <= 0.6) { k = 0.3; status = 'stuck'; } else if (k > 0.6) k -= 0.3; }
    const ended = k >= 1;
    k = Math.min(1, k);
    const stop = w.verdict === 'passed' ? 1 : 0.55;
    const p = along(ROUTE, Math.min(k, stop));
    row.t = Number((k * 30).toFixed(1)); row.t_limit = 30;
    if (w.pack === 'window') { row.x = -1 + 2 * ((k * 5) % 1); row.y = 40.3 + 2.4 * k; } else { row.x = Number((p[0] + Math.sin(k * 40) * 0.08).toFixed(3)); row.y = Number((p[1] + Math.cos(k * 31) * 0.08).toFixed(3)); }
    if (ended && status === 'running') {
      status = w.index === 3 ? 'held' : w.verdict === 'passed' ? 'passed' : 'failed';
      row.verdict = w.index === 3 ? 'wind_hold' : w.verdict; row.verdict_reason = w.index === 3 ? 'The robot held itself in place until the wind fell.' : w.verdict_reason;
    }
    if (status === 'stuck') { row.verdict_reason = 'No progress for 30 s while the run is alive.'; }
    row.status = status;
    counts[status]++;
    return row;
  });
  const running = counts.queued + counts.running > 0 || c.worlds.some(w => w.sticks === 'stays' && !c.ended);
  return { type: 'grid', campaign: c.id, pack: s.pack, running, elapsed_s: Number((elapsed / SPEED).toFixed(1)), max_procs: PROCS, counts, rows };
}

function startCampaign(s) {
  const list = s.scenarios;
  const wl = worlds(s.pack);
  // A simple queue: the next world starts when a slot frees.
  const slots = Array(PROCS).fill(0);
  for (const w of wl) {
    if (w.held_back) continue;
    const i = slots.indexOf(Math.min(...slots));
    w.start = slots[i];
    slots[i] += w.span + (w.sticks === 'resumes' ? w.span * 0.3 : 0);
  }
  const end = Math.max(...slots);
  s.campaign = { id: list.campaign, worlds: wl, t0: Date.now(), ended: false };
  s.timer = setInterval(() => {
    const now = Date.now();
    const g = gridOf(s, now);
    emit(s, g, false);
    if (((now - s.campaign.t0) / 1000) * SPEED > end + 2) {
      clearInterval(s.timer);
      s.campaign.ended = true;
      const final = gridOf(s, now);
      s.campaign.final = final;
      emit(s, final, false);
      emit(s, { type: 'campaign_done', campaign: list.campaign, counts: final.counts, wall_s: final.elapsed_s, max_procs: PROCS, label: 'sim fake', note: NOTE });
      emit(s, { type: 'text', text: `Done. ${final.counts.passed} passed, ${final.counts.failed} failed.` });
      emit(s, { type: 'idle' });
    }
  }, 1000);
}

const server = createServer((req, res) => {
  cors(req, res);
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
  const url = new URL(req.url, 'http://x');
  const parts = url.pathname.split('/').filter(Boolean);
  let raw = '';
  req.on('data', d => { raw += d; });
  req.on('end', () => {
    const body = raw ? JSON.parse(raw) : {};
    if (url.pathname === '/api/health') return json(res, 200, { sim_sha: 'fake', llm: 'none (fake server)', max_procs: PROCS });
    if (url.pathname === '/api/packs') return json(res, 200, { packs: [
      { name: 'window', label: 'Window cleaning robot', robot: 'suction_window_cleaner', backend: 'mujoco', note: NOTE, viewer: 'trial', max_procs: PROCS },
      { name: 'inspection', label: 'Inspection robot', robot: 'anymal_c', backend: 'newton', note: NOTE, viewer: 'poses', max_procs: PROCS },
    ], import: { available: false, note: 'Importing a robot is not built yet.' } });
    if (url.pathname === '/api/sessions' && req.method === 'POST') {
      const pack = body.pack ?? 'window';
      const id = `fake${sessions.size}`;
      const s = { id, pack, events: [], clients: new Set(), campaign: null, scenarios: null };
      sessions.set(id, s);
      if (pack === 'inspection') s.events.push(poseWorld(pack));
      return json(res, 201, { id, pack });
    }
    const s = sessions.get(parts[2]);
    if (!s) return json(res, 404, { error: 'no_session' });
    const rest = parts.slice(3).join('/');
    if (rest === 'state') return json(res, 200, { phase: 'lab', busy: false, engine: s.pack === 'window' ? 'v5' : 'pack', pack: s.pack });
    if (rest === 'events') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
      const after = Number(url.searchParams.get('after') ?? -1);
      s.events.forEach((e, i) => { if (i > after) res.write(`id: ${i}\ndata: ${JSON.stringify(e)}\n\n`); });
      s.clients.add(res);
      res.on('close', () => s.clients.delete(res));
      return undefined;
    }
    if (rest === 'fixed') return json(res, 200, {});
    if (rest === 'message') {
      emit(s, { type: 'user', text: body.text });
      res.writeHead(202); res.end('{}');
      if (/scenario|test case/i.test(body.text)) act(s, 'list_scenarios');
      else if (/^(run|run it|run all|go)$/i.test(body.text.trim())) act(s, 'run_campaign');
      else if (s.pack === 'inspection') {
        emit(s, { type: 'pose_trial', label: 'Normal run', passed: true, verdict: 'passed', reason: RESULTS.plant.reason, url: `/api/sessions/${s.id}/pose_runs/plant/replay` });
        emit(s, { type: 'idle' });
      } else emit(s, { type: 'idle' });
      return undefined;
    }
    if (rest === 'action') { res.writeHead(202); res.end('{}'); act(s, body.action); return undefined; }
    if (rest === 'pose_runs/plant/replay') return replayFile(res, 'plant');
    if (parts[3] === 'campaigns') {
      const tail = parts.slice(5).join('/');
      if (tail === 'grid') return s.campaign ? json(res, 200, s.campaign.final ?? gridOf(s, Date.now())) : json(res, 404, { error: 'no_campaign' });
      if (tail === 'scenarios') return json(res, 200, s.scenarios);
      const w = s.campaign?.worlds[Number(parts[6])];
      if (!w) return json(res, 404, { error: 'no_world' });
      const row = gridOf(s, Date.now()).rows[w.index];
      const ended = row.verdict !== null;
      if (parts[7] === 'replay') return ended ? json(res, 200, { kind: 'poses', url: `/api/sessions/${s.id}/campaigns/${parts[4]}/worlds/${w.index}/poses` }) : json(res, 404, { error: 'no_replay' });
      if (parts[7] === 'poses') return replayFile(res, ended && row.verdict !== 'passed' ? w.base : 'plant');
      const { fell_t_s, reason, verdict, passed, ...numbers } = w.numbers;
      void reason; void verdict; void passed;
      return json(res, 200, {
        index: w.index, name: w.name, group: w.group, reason: w.reason, status: row.status, held_back: w.held_back, verdict: row.verdict, verdict_reason: row.verdict_reason,
        numbers: { deviation_max_m: numbers.deviation_max_m, min_clearance_m: numbers.min_clearance_m, foot_slip_mps: numbers.foot_slip_mps, waypoints_reached: numbers.waypoints_reached },
        events: fell_t_s != null ? [{ name: 'fell', t: fell_t_s, value: 1 }] : [],
        log: [`start ${w.name} seed ${w.seed}`, `t ${row.t ?? 0} s, x ${row.x ?? 0}, y ${row.y ?? 0}`, `status ${row.status}`], code: { file: 'policy/packs/inspection/controller.py', line: 42, why: 'RouteFollower was active.', traced: false },
        changes: w.changes, world: {}, seed: w.seed, wall_s: 18.2, label: 'sim fake', note: NOTE, replay: ended,
      });
    }
    return json(res, 404, { error: 'not_found' });
  });
});

function replayFile(res, name) {
  res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip' });
  res.end(readFileSync(join(OUT, `${name}.replay.json.gz`)));
}

function act(s, action) {
  if (action === 'list_scenarios') {
    const wl = worlds(s.pack);
    const event = { type: 'scenarios', campaign: `c${(s.nCampaign = (s.nCampaign ?? 0) + 1)}`, pack: s.pack, count: wl.length, to_run: wl.filter(w => !w.held_back).length, held_back: wl.filter(w => w.held_back).length,
      count_reason: 'Fake server: a fixed count for a page check.', note: 'Reasons are the AI\'s reasoned guesses, not evidence that these cases occur. Results are simulated.',
      groups: GROUPS.map(([name]) => ({ name, reason: `Reasoned guess: ${name.toLowerCase()} may matter here.`, count: Math.round(COUNT / GROUPS.length) })),
      worlds: wl.map(w => ({ index: w.index, name: w.name, group: w.group, reason: w.reason, held_back: w.held_back, seed: w.seed, changes: w.changes })),
      not_tested: [{ factor: 'Airborne dust', reason: 'The picture shows it, but the physics has no such force.', source: 'code' }, { factor: 'Gas leaks', reason: 'The robot carries no sensor model for it.', source: 'agent' }, { factor: 'A human walking by', reason: 'No moving objects in this world.', source: 'agent' }],
      dropped: { 'refused:out_of_range': 2, not_belonging: 1 }, rejection: null };
    s.scenarios = event;
    emit(s, event);
    emit(s, { type: 'idle' });
  } else if (action === 'run_campaign') startCampaign(s);
}

server.listen(PORT, '127.0.0.1', () => console.log(`fake lab server on ${PORT}`));

