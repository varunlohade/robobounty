"""Writes the six screens from the stored campaign files. Numbers come from docs/evidence, the frames from ../assets."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = OUT.parents[2]
EV = REPO / "docs" / "evidence"

results = [json.loads(l) for l in open(EV / "results.jsonl")]
diag = json.load(open(EV / "diagnosis.json"))
fix = json.load(open(EV / "retest_report.json"))
insp = json.load(open(REPO / "policy/packs/inspection/out/results.json"))
varied = [r for r in results if r["kind"] == "varied"]
controls = [r for r in results if r["kind"] == "control"]
repro = {p["trial"]: p for p in diag["reproduce"]["per_trial"]}
flaky = {p["trial"] for p in diag["reproduce"]["flaky"]}
lead = {p["trial"]: p for p in diag["pressure_lead"]["per_trial"]}
assert len(varied) == 52 and sum(r["passed"] for r in varied) == 3

LINES = {"slip_distance": "controller.py:240", "detach": "controller.py:250", "false_done": "controller.py:261"}
for t in diag["failure_types"]:
    LINES[t["type"]] = t["code_line"].split("/")[-1] if t.get("code_line") else ""
NAMES = {"slip_distance": "Slip distance", "detach": "Detach", "false_done": "False done", "time_limit": "Time limit", "stalled": "Stalled", "wind_hold": "Wind hold", "battery_stop": "Battery stop", "pass": "Passed"}
CLS = {"slip_distance": "c-slip", "detach": "c-detach", "false_done": "c-done", "time_limit": "c-limit", "stalled": "c-limit", "wind_hold": "c-hold", "battery_stop": "c-hold", "pass": "c-pass"}


def kind(r):
    if r["passed"]:
        return "pass"
    if r["outcome"] in ("wind_hold", "battery_stop"):
        return r["outcome"]
    return r["failure"] or r["outcome"]


def reading(r):
    k = kind(r)
    if k == "detach":
        return f'{r["min_pressure_pa"]:.1f} Pa lowest pressure'
    if k == "slip_distance":
        return f'{r["slip_m"]:.2f} m slide'
    if k == "false_done":
        return f'reported {r["reported_coverage"]:.2f}, true {r["coverage"]:.2f}'
    if k == "wind_hold":
        return f'held at {r["hold_mean_wind_ms"]:.1f} m/s wind'
    if k == "battery_stop":
        return f'stopped with {r["coverage"]*100:.0f}% cleaned'
    return f'{r["coverage"]*100:.0f}% cleaned'


def world_row(r):
    k = kind(r)
    rep = repro.get(r["trial"])
    return {"id": r["trial"], "group": r["group"], "kind": k, "name": NAMES[k], "cls": CLS[k], "at": r["first_t"], "reading": reading(r), "line": LINES.get(k, ""),
            "repeat": (f'{rep["same_failure_runs"]} of {rep["of"]}' if rep else "not re-run"), "flaky": r["trial"] in flaky,
            "wind": r["world"]["steady_wind_ms"], "gust": r["world"]["gust_speed_ms"], "wet": r["world"]["wetness"], "minp": r["min_pressure_pa"], "slip": r["slip_m"], "cov": r["coverage"]}


ROWS = [world_row(r) for r in varied]
GROUPS = []
for r in ROWS:
    if r["group"] not in GROUPS:
        GROUPS.append(r["group"])
GROUPS.sort(key=lambda g: (sum(x["kind"] == "pass" for x in ROWS if x["group"] == g) * -1, g))

ICONS = {
 "home": '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 "box": '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
 "target": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
 "chart": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
 "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
 "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
 "ok": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
 "x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
 "hold": '<circle cx="12" cy="12" r="10"/><line x1="10" x2="10" y1="15" y2="9"/><line x1="14" x2="14" y1="15" y2="9"/>',
 "circle": '<circle cx="12" cy="12" r="10"/>',
 "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
 "eyeoff": '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
 "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
 "pause": '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
 "replay": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
 "down": '<path d="m6 9 6 6 6-6"/>', "up": '<path d="m18 15-6-6-6 6"/>',
 "open": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
 "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
 "loader": '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
 "check": '<path d="M20 6 9 17l-5-5"/>',
 "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
 "user": '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
 "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
 "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
 "code": '<path d="M10 12.5 8 15l2 2.5"/><path d="m14 12.5 2 2.5-2 2.5"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/>',
 "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
 "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
 "skip-b": '<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" x2="5" y1="19" y2="5"/>',
 "skip-f": '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/>',
 "doc": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/>',
}


def ic(name, cls=""):
    return f'<svg class="i {cls}" viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


def page(name, title, body):
    (OUT / f"{name}.html").write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="site.css"></head><body>{body}<script src="site.js"></script></body></html>\n')


def shell(cur, main, status_right=""):
    items = [("home", "Home", "home", ""), ("crashlab", "CrashLab", "box", ""), ("bounties", "Bounties", "target", "8"), ("data", "Data", "chart", ""), ("providers", "Providers", "layers", "")]
    nav = "".join(f'<a class="item" href="{h}.html"{" aria-current=page" if h == cur else ""}>{ic(i)}<span>{t}</span>{f"<span class=n>{n}</span>" if n else ""}</a>' for h, t, i, n in items)
    return f'''<div class="app"><nav class="nav" aria-label="Main">
<a class="brand" href="home.html">CrashLab</a>
<button class="find" data-find>{ic("search")}<span>Search</span><kbd>/</kbd></button>
{nav}
<div class="who"><span class="ok">{ic("ok","i16")}</span><span class="name">Verified human<small>0x2f8a…c41e</small></span><button aria-label="Sign out" title="Sign out" onclick="location.href='login.html'">{ic("logout")}</button></div>
</nav><main class="main">{main}</main>
<footer class="status"><span>Simulated. Hand-built physics, not checked against real hardware.</span><span class="r">{status_right}</span></footer></div>'''


def cells(p, h, f, cls=""):
    return f'<div class="cells {cls}" role="img" aria-label="{p} passed, {h} safe holds, {f} failed">' + '<span class="c-pass"></span>' * p + '<span class="c-hold"></span>' * h + '<span class="c-fail"></span>' * f + "</div>"


def bar(p, h, f):
    t = p + h + f
    seg = lambda n, c: f'<span class="{c}" style="width:{n / t * 100:.2f}%"></span>' if n else ""
    return f'<div class="bar" role="img" aria-label="{p} passed, {h} safe holds, {f} failed">{seg(p,"c-pass")}{seg(h,"c-hold")}{seg(f,"c-fail")}</div>'


# ---------- login
n, path = (HERE / "qr.svgpath").read_text().split("\n", 1)
qr = f'<svg viewBox="0 0 {n} {n}" shape-rendering="crispEdges" aria-label="Code to scan with World App"><path d="{path}" fill="#0B0C0E"/></svg>'
page("login", "CrashLab sign in", f'''<div class="login" id="login">
<div class="side">
<a class="brand">CrashLab</a>
<div class="body">
<h1>Sign in to CrashLab</h1>
<p class="proof">World ID proves you are one unique human. It shares no name, email or face.</p>
<div class="go">
<button class="btn pri" id="wid"><span id="wid-i">{ic("scan","i16")}</span><span id="wid-t">Sign in with World ID</span></button>
<button class="btn bare" id="wid-c" hidden>Cancel</button>
</div>
<div class="verify" aria-live="polite">
<div class="qr">{qr}</div>
<ol class="steps">
<li class="done" id="s1">{ic("check")}<span>Request created</span></li>
<li class="now" id="s2"><span id="s2i">{ic("loader","spin")}</span><span>Scan the code with World App<small>Or open this page on your phone. The request ends in 4:58.</small></span></li>
<li id="s3"><span id="s3i">{ic("circle")}</span><span>Check the proof</span></li>
</ol>
</div>
</div>
<p class="foot">Simulated. Hand-built physics, not checked against real hardware.</p>
</div>
<div class="picture frame"><img src="frames/login-snow.jpg" alt="Window cleaning robot on wet tower glass in snow, simulated"><span class="frame-note">Simulated. Replay of a recorded run.</span></div>
</div>''')

# ---------- home
runs = [
    ("Window batch", "Window cleaning robot", "dubai_tower.world", 33, 2, 4, 27, "2 passed, 27 failed, 4 safe holds"),
    ("Inspection batch", "Plant inspection robot", "inspection_plant.world", 34, 16, 0, 18, "16 passed, 18 failed"),
    ("Fix retest, patched", "Window cleaning robot", "2 new seed sets", 104, 17, 27, 60, "17 passed, 60 failed, 27 safe holds"),
    ("Fix retest, baseline", "Window cleaning robot", "2 new seed sets", 104, 11, 26, 67, "11 passed, 67 failed, 26 safe holds"),
    ("campaign_dubai_final", "Window cleaning robot", "8 groups", 52, 3, 13, 36, "3 passed, 36 failed, 13 safe holds"),
    ("Control worlds", "Window cleaning robot", "Nominal", 10, 10, 0, 0, "10 passed"),
]
assert fix["fresh"]["B"]["pass"] == 17 and fix["fresh"]["A"]["fail"] == 67
rows = "".join(f'<tr class="row" tabindex="0" data-href="data.html"><td><b style="font-weight:500">{a}</b></td><td class="t2">{b.replace(" robot","")}</td><td class="num">{n}</td><td>{bar(p,h,f)}</td><td class="t2">{t}</td></tr>' for a, b, _, n, p, h, f, t in runs)
home_main = f'''<header class="head"><h1>Home</h1><div class="r"><button class="btn bare">{ic("upload")}Import robot file<span class="t4 small">Later</span></button></div></header>
<section class="hero">
<div class="vis"><a class="frame" href="crashlab.html" aria-label="Open this run in CrashLab"><img src="frames/tower-wind.jpg" alt="Window cleaning robot on wet glass in strong wind, simulated"><span class="frame-note">Simulated. Replay of a recorded run.</span></a>
<div class="scrub"><button aria-label="Pause">{ic("pause")}</button><span class="track"><b style="width:3%"></b><u style="left:3%"></u></span><span class="small">0:17 / 10:00</span><span class="small t3">8x</span></div></div>
<div class="info">
<h2>Latest batch: window cleaning robot</h2>
<p class="t3">Replay shown: <code>dubai_tower.world</code></p>
<div class="nums"><div><b>33</b><span>Worlds run</span></div><div><b>2</b><span>Passed</span></div><div class="f"><b>27</b><span>Failed</span></div><div><b>4</b><span>Safe holds</span></div></div>
{cells(2,4,27)}
<p class="why">In this replay, wind of 20.9 m/s is above the robot's 10 m/s limit. It holds still and cleans 0.7%.</p>
<div class="acts"><a class="btn pri lg" href="crashlab.html">Open CrashLab</a><a class="btn sec lg" href="data.html">See the 33 worlds</a></div>
</div></section>
<div class="under">
<section><div class="sect"><h2>Recent runs</h2><div class="r"><a class="btn bare" href="data.html">All data</a></div></div>
<table><thead><tr><th>Run</th><th>Robot</th><th class="num">Worlds</th><th>Outcome</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table></section>
<section><div class="sect"><h2>Open work</h2><div class="r t3 small">4</div></div>
<ul class="work">
<li><span class="tag bad">{ic("alert")}</span><span>Decide on detach: 9 worlds<p>The robot was already at full suction in 5 of 9. The controller has no more force to command.</p></span><span class="t3 small">Critical</span></li>
<li><span class="tag hold">{ic("code")}</span><span>Review patch: suction 0.85 to 0.9<p>7 better, 0 worse on 104 new worlds. It also removes the low-pressure guard. Not applied.</p></span><span class="t3 small">High</span></li>
<li onclick="location.href='bounties.html'"><span class="t2">{ic("target")}</span><span>Check a fix on Detach on turns<p>Hidden worlds are running: 7 of 12. <span class="sample">Sample</span></p></span><span class="t3 small"></span></li>
<li><span class="t2">{ic("eyeoff")}</span><span>Send 10 untested factors to a bounty<p>Safety tether, sensor faults, pump faults and 7 more. No function can model them yet.</p></span><span class="t3 small"></span></li>
</ul></section>
</div>'''
page("home", "CrashLab home", shell("home", home_main, 'Frame 359 of 12000<span>LLM: claude headless</span><span class="mono">sim highrise5 09ab2e5a5efa</span>'))

# ---------- crashlab
lab_main = f'''<header class="head"><h1>CrashLab</h1><p>Say the job. The AI builds the world, lists what could go wrong and runs it all.</p></header>
<div class="lab">
<aside>
<div class="sect"><h2>Choose a robot</h2></div>
<button class="robot" aria-pressed="true" data-robot="window"><span class="thumb"><img src="frames/tower-rain.jpg" alt="" style="object-position:85% 50%"></span><span><b>Window cleaning</b><small>Climbs tower glass on suction, with a scripted controller.</small><small class="m">Last batch: 33 run, 2 passed</small></span></button>
<button class="robot" aria-pressed="false" data-robot="plant"><span class="thumb"><img src="frames/plant-walk.jpg" alt=""></span><span><b>Plant inspection</b><small>ANYmal C walks a plant route on an upstream policy.</small><small class="m">Last batch: 34 run, 16 passed</small></span></button>
<div class="sect" style="margin-top:12px"><h2>Recent worlds</h2><div class="r t3 small" id="wcount">3</div></div>
<ul class="worlds" id="worlds"></ul>
<button class="robot" disabled style="border-top:1px solid var(--line);grid-template-columns:14px 1fr;align-items:center;margin-top:auto">{ic("upload")}<span>Import a robot file<small class="m">Coming later</small></span></button>
</aside>
<div class="stage">
<div class="bar2"><div><h2 id="st-t">Window cleaning robot</h2><p class="t3 small"><code id="st-w">dubai_tower.world</code></p></div><div class="r"><span class="t3 small" id="st-n">Opens the tool in this tab</span><a class="btn pri lg" id="open" href="../../../lab.html">Open CrashLab{ic("open")}</a></div></div>
<div class="shot"><div class="win" id="win"><img id="shot" src="frames/full-lab-3.jpg" alt="The CrashLab tool: chat on the left, the simulated run on the right"></div></div>
<div class="flow" id="flow"></div>
</div></div>'''
page("crashlab", "CrashLab", shell("crashlab", lab_main, '<span>LLM: claude headless</span><span class="mono">sim highrise5 09ab2e5a5efa</span>'))

# ---------- bounties
def pub(ids):
    out = []
    for t in ids:
        r = next(x for x in varied if x["trial"] == t)
        row = {"id": t, "at": f'{r["first_t"]:.1f} s' if r["first_t"] is not None else "", "reading": reading(r)}
        if t in lead:
            row["reading"] = f'{lead[t]["true_pa"]:.1f} Pa true, {lead[t]["estimate_pa"]:.0f} Pa estimated'
        row["repeat"] = f'{repro[t]["same_failure_runs"]} of {repro[t]["of"]}' if t in repro else ""
        out.append(row)
    return out


assert all(lead[t]["phase"] == "turn" for t in ("t0033", "t0034", "t0037", "t0039"))
lp = insp["worlds"]["low_pipe"]
dt = insp["worlds"]["dropped_tray"]
wf = insp["worlds"]["wet_floor"]
lc = insp["worlds"]["low_crossover"]
REQ = {r["id"]: r["text"] for r in json.load(open(EV / "requirements.json"))["requirements"]}
BOUNTIES = [
 {"id": 1, "title": "Detach on turns at narrow edges", "robot": "Window", "sev": "Critical", "req": "R1", "text": REQ["R1"], "line": "controller.py:250", "pay": 100, "status": "reviewing", "hidden": 12, "done": 7, "worlds": pub(["t0033", "t0034", "t0037", "t0039"]), "frame": "frames/tower-wind.jpg", "file": "turn_seal.patch", "stage": 2, "subs": [["turn_seal.patch", "Hidden worlds running, 7 of 12 so far", "loader", "live"], ["retreat_on_turn.patch", "Stopped. 5 of 12 hidden worlds passed", "x", "bad"]]},
 {"id": 2, "title": "Slip on wet glass during a clean pass", "robot": "Window", "sev": "High", "req": "R3", "text": REQ["R3"], "line": "controller.py:240", "pay": 60, "status": "open", "hidden": 12, "done": 0, "worlds": pub(["t0026", "t0023", "t0027", "t0022"]), "frame": "frames/tower-rain.jpg", "file": None, "stage": -1},
 {"id": 3, "title": "Slip when dust reaches the seal", "robot": "Window", "sev": "High", "req": "R3", "text": REQ["R3"], "line": "controller.py:193", "pay": 60, "status": "open", "hidden": 12, "done": 0, "worlds": pub(["t0016", "t0017", "t0019", "t0020"]), "frame": "frames/tower-snow.jpg", "file": None, "stage": -1},
 {"id": 4, "title": "Robot reports done on dirty glass", "robot": "Window", "sev": "High", "req": "R4", "text": REQ["R4"], "line": "controller.py:261", "pay": 40, "status": "open", "hidden": 8, "done": 0, "worlds": pub(["t0030", "t0035", "t0038"]), "frame": "frames/tower-acunit.jpg", "file": None, "stage": -1},
 {"id": 5, "title": "Falls over a low pipe on the walkway", "robot": "Inspection", "sev": "High", "req": "Route", "text": "The robot finishes the route without a fall.", "line": "controller.py:42", "pay": 40, "status": "open", "hidden": 8, "done": 0,
  "worlds": [{"id": "low_pipe", "at": f'{lp["fell_t_s"]:.1f} s', "reading": f'{lp["waypoints_reached"]} of 3 waypoints', "repeat": ""}, {"id": "dropped_tray", "at": f'{dt["fell_t_s"]:.1f} s', "reading": f'{dt["waypoints_reached"]} of 3 waypoints', "repeat": ""}], "frame": "frames/plant-lowpipe.jpg", "file": None, "stage": -1},
 {"id": 7, "title": "Slip in gusts over 34 m/s", "robot": "Window", "sev": "High", "req": "R3", "text": REQ["R3"], "line": "controller.py:240", "pay": 60, "status": "open", "hidden": 12, "done": 0, "worlds": pub(["t0008", "t0010"]), "frame": "frames/tower-rain.jpg", "file": None, "stage": -1},
 {"id": 8, "title": "Detach at once with weak suction", "robot": "Window", "sev": "Critical", "req": "R1", "text": REQ["R1"], "line": "controller.py:250", "pay": 80, "status": "open", "hidden": 12, "done": 0, "worlds": pub(["t0048", "t0049"]), "frame": "frames/tower-snow.jpg", "file": None, "stage": -1},
 {"id": 9, "title": "Falls on a wet floor", "robot": "Inspection", "sev": "High", "req": "Route", "text": "The robot finishes the route without a fall.", "line": "controller.py:42", "pay": 40, "status": "open", "hidden": 8, "done": 0, "worlds": [{"id": "wet_floor", "at": f'{wf["fell_t_s"]:.1f} s', "reading": f'{wf["waypoints_reached"]} of 3 waypoints', "repeat": ""}], "frame": "frames/plant-lowpipe.jpg", "file": None, "stage": -1},
 {"id": 10, "title": "Stuck at a low crossover", "robot": "Inspection", "sev": "Medium", "req": "Route", "text": "The robot keeps making progress along the route.", "line": "controller.py:42", "pay": 30, "status": "open", "hidden": 8, "done": 0, "worlds": [{"id": "low_crossover", "at": f'{lc["stuck_t_s"]:.1f} s', "reading": f'{lc["waypoints_reached"]} of 3 waypoints', "repeat": ""}], "frame": "frames/plant-lowpipe.jpg", "file": None, "stage": -1},
 {"id": 6, "title": "Stops on the glass with no reason", "robot": "Window", "sev": "High", "req": "R7", "text": REQ["R7"], "line": "controller.py:213", "pay": 20, "status": "paid", "hidden": 8, "done": 8, "worlds": pub(["t0041"]), "frame": "frames/tower-rain.jpg", "file": "stall_reason.patch", "stage": 4},
]
POSTED = sum(b["pay"] for b in BOUNTIES)
HELD = sum(b["pay"] for b in BOUNTIES if b["status"] == "reviewing")
PAID = sum(b["pay"] for b in BOUNTIES if b["status"] == "paid")
assert sum(b["status"] == "open" for b in BOUNTIES) == 8
bounty_main = f'''<div class="bty">
<section class="list">
<header class="head"><h1>Bounties</h1><div class="r"><span class="sample">Sample pay and submissions</span></div></header>
<div class="filters">
<div class="seg" id="st" role="group" aria-label="Status"></div>
<button class="pick" id="rb">Any robot{ic("down","i12")}</button>
<label class="field">{ic("search")}<input id="q" placeholder="Search" aria-label="Search bounties"></label>
</div>
<div style="flex:1;min-height:0;overflow:hidden"><table id="bt"><thead><tr><th>Bounty</th><th style="width:124px">Worlds</th><th class="sort on num" id="sortpay" style="width:76px">Pay<span class="ar" id="ar">{ic("down","i12")}</span></th><th style="width:124px">Status</th></tr></thead><tbody></tbody></table></div>
<div class="ledger"><div class="lh"><h2>Ledger</h2><span class="warnline">{ic("alert","i12")}Local ledger. Not on chain.</span><span class="sample">Sample</span></div><div class="lnums"><div><b>{POSTED}</b><span>Posted</span></div><div><b>{HELD}</b><span>Held while checking</span></div><div><b>{PAID}</b><span>Paid</span></div><div><b>{POSTED-HELD-PAID}</b><span>Left</span></div></div><p>Test units. Failing worlds come from recorded runs. Pay moves only when every hidden world passes.</p></div>
</section>
<section class="detail" id="detail"><div class="in" id="d-in"></div></section>
</div>'''
page("bounties", "CrashLab bounties", shell("bounties", bounty_main, '<span class="warn">Local ledger. Not on chain.</span><span class="mono">spec 0x680f51…64dc</span>'))

# ---------- data
map_html = ""
for g in GROUPS:
    cs = "".join(f'<i class="{r["cls"]}" data-w="{r["id"]}" tabindex="0" aria-label="{r["id"]}: {r["name"]}"></i>' for r in ROWS if r["group"] == g)
    map_html += f'<span class="g">{g}</span><span class="rowc">{cs}</span>'

fail_types = [("slip_distance", "Slip distance", "R3", "c-slip", "controller.py:240"), ("detach", "Detach", "R1", "c-detach", "controller.py:250"), ("false_done", "False done", "R4", "c-done", "controller.py:261"), ("time_limit", "Time limit", "R6", "c-limit", ""), ("stalled", "Stalled", "R7", "c-limit", "controller.py:213")]
SCALE = 100 / 20
ty_html = ""
for k, nm, req, cls, ln in fail_types:
    all_ = [r for r in ROWS if r["kind"] == k]
    fl = sum(r["flaky"] for r in all_)
    firm = len(all_) - fl
    ty_html += f'<div class="t"><span>{nm}<span class="t3 small"> {req}</span></span><span>{len(all_)}{f" <span class=\"t3 small\">{fl} flaky</span>" if fl else ""}</span><div class="tb"><span class="{cls}" style="width:{firm*SCALE:.1f}%"></span>' + (f'<span class="c-hide" style="width:{fl*SCALE:.1f}%"></span>' if fl else "") + "</div></div>"


def axis(rows, field, lo, hi):
    """One tick per world on the factor's axis. Tall means it failed; short means it passed or held."""
    w, parts = 420, ['<line x1="0" x2="420" y1="18" y2="18" stroke="rgba(255,255,255,.12)"/>']
    for r, val in rows:
        x = (val - lo) / (hi - lo) * w
        k = kind(r)
        colour = {"pass": "#C9CED6", "wind_hold": "#A3A9B3", "battery_stop": "#A3A9B3", "slip_distance": "#D3A017", "detach": "#14A39A", "false_done": "#9A78F0"}.get(k, "#E2574C")
        y, h = (10, 8) if k in ("pass", "wind_hold", "battery_stop") else (2, 16)
        if r["trial"] in flaky:
            parts.append(f'<rect x="{x-1:.1f}" y="{y+.5}" width="2.5" height="{h-1}" fill="none" stroke="{colour}" stroke-width="1"/>')
        else:
            parts.append(f'<rect x="{x-1:.1f}" y="{y}" width="2.5" height="{h}" fill="{colour}"/>')
    for t in (lo, (lo + hi) / 2, hi):
        x = (t - lo) / (hi - lo) * w
        parts.append(f'<text x="{x:.0f}" y="28" fill="#737A85" font-size="10" text-anchor="{"start" if t == lo else "end" if t == hi else "middle"}">{t:g}</text>')
    return f'<svg viewBox="0 0 420 30" style="height:30px">{"".join(parts)}</svg>'


def group(g):
    return [r for r in varied if r["group"] == g]


gust_rows = [(r, r["world"]["gust_speed_ms"]) for r in group("Strong gusts on high facade") + controls]
wet_rows = [(r, r["world"]["wetness"]) for r in group("Wet humid low friction glass") + group("Dry high friction glass") + controls]
wind_rows = [(r, r["world"]["steady_wind_ms"]) for r in group("High steady wind") + controls]
edge_rows = [(r, r["world"]["edge_margin_m"]) for r in group("Weird edges and joints") + controls]
bnd = [
 ("Gust speed, m/s", "passes to 26.6, repeat failures from 34.9", axis(gust_rows, "gust", 0, 50)),
 ("Wetness, 0 to 1", "passes at 0.20, fails from 0.63", axis(wet_rows, "wet", 0, 1)),
 ("Steady wind, m/s", "passes at 2, holds from 11.1", axis(wind_rows, "wind", 0, 25)),
 ("Edge margin, m", "passes at 1.0, fails from 0.58", axis(edge_rows, "edge", 0, 1.2)),
]
bnd_html = "".join(f'<div class="b"><div class="top"><span>{a}</span><span>{b}</span></div>{c}</div>' for a, b, c in bnd)

camp = [
 ("window", "Window batch", "Window", 33, 2, 4, 27),
 ("inspection", "Inspection batch", "Inspection", 34, 16, 0, 18),
 ("final", "campaign_dubai_final", "Window", 52, 3, 13, 36),
 ("retest", "Fix retest, patched", "Window", 104, 17, 27, 60),
]
camp_rows = "".join(f'<tr class="row" tabindex="0" data-camp="{k}" aria-selected="{"true" if k=="final" else "false"}"><td>{a}</td><td class="t2">{b}</td><td class="num">{n}</td><td class="num">{p}</td><td class="num">{f}</td><td class="num">{h}</td><td>{bar(p,h,f)}</td></tr>' for k, a, b, n, p, h, f in camp)
data_main = f'''<header class="head"><h1>Data</h1><p>Campaign results. All simulated.</p><div class="r"><button class="btn sec">{ic("doc")}Export results</button></div></header>
<div class="dgrid">
<table class="camp"><thead><tr><th>Campaign</th><th>Robot</th><th class="num">Worlds run</th><th class="num">Passed</th><th class="num">Failed</th><th class="num">Safe holds</th><th>Outcome</th></tr></thead><tbody>{camp_rows}</tbody></table>
<div class="charts" id="charts">
<div><div class="chart-h"><h2>campaign_dubai_final, 52 worlds</h2><span class="t3 small">One square, one world</span></div>
<div class="map" id="map">{map_html}</div>
<div class="legend"><span><i class="c-pass"></i>Passed</span><span><i class="c-hold"></i>Safe hold</span><span><i class="c-slip"></i>Slip</span><span><i class="c-detach"></i>Detach</span><span><i class="c-done"></i>False done</span><span><i class="c-limit"></i>Time or stall</span></div></div>
<div><div class="chart-h"><h2>Failure types</h2><span class="t3 small">36 failed worlds</span></div><div class="types">{ty_html}</div>
<p class="note" style="margin-top:12px">5 failures did not repeat in 3 re-runs. They stay flaky and leave the type counts in the diagnosis.</p></div>
<div><div class="chart-h"><h2>Boundary values</h2><span class="t3 small">Tall tick failed, short tick passed or held</span></div><div class="bnd">{bnd_html}</div></div>
</div>
<section class="lib"><div class="sect"><h2>Failure library</h2><span class="t3 small" id="libn"></span><div class="r"><div class="seg" id="libk"></div><label class="field" style="width:256px">{ic("search")}<input id="libq" placeholder="Search worlds, types, code lines" aria-label="Search the failure library"><span class="count" id="libc"></span></label></div></div>
<div class="scroll"><table id="lib"><thead><tr><th class="sort" data-s="id">World</th><th class="sort" data-s="group">Group</th><th class="sort" data-s="name">Outcome</th><th class="sort num" data-s="at">Fails at, s</th><th>Reading</th><th>Re-runs</th><th>Code line</th><th></th></tr></thead><tbody></tbody></table></div></section>
</div><div class="tip" id="tip"></div>'''
page("data", "CrashLab data", shell("data", data_main, 'Requirements written before the campaign<span class="mono">sim 0e36d3bf97fe</span>'))

# ---------- providers
PROV = [
 ("Simulation engines", [
  {"k": "mujoco", "name": "MuJoCo", "sub": "DeepMind, open source", "gives": "Physics for both robots", "state": "In use", "s": "ok", "ver": "3.8.1"},
  {"k": "newton", "name": "Newton", "sub": "Open source", "gives": "Walking comparison, 7 worlds", "state": "Lab only", "s": "hold", "ver": "f85fa21e6f4e"},
  {"k": "blender", "name": "Blender", "sub": "Open source, renderer", "gives": "Re-renders recorded physics", "state": "In use", "s": "ok", "ver": "render only"},
 ]),
 ("Robots and controllers", [
  {"k": "window", "name": "High-rise window robot", "sub": "Hand-built model", "gives": "Scripted Python controller", "state": "In use", "s": "ok", "ver": "85e7220d4a09"},
  {"k": "anymal", "name": "ANYmal C", "sub": "Upstream policy, route follower ours", "gives": "Trained walking policy, ONNX", "state": "In use", "s": "ok", "ver": "b1c89c64f172"},
 ]),
 ("AI models", [
  {"k": "claude", "name": "Claude", "sub": "Through Claude Code, headless", "gives": "World edits, scenarios, fix tries", "state": "In use", "s": "ok", "ver": "claude-opus-5-5"},
 ]),
 ("Identity and pay", [
  {"k": "world", "name": "World ID", "sub": "Proof of one human", "gives": "Caps submissions per person", "state": "Not connected", "s": "quiet", "ver": "cap 5"},
  {"k": "contract", "name": "FailureBounty contract", "sub": "Ours, not audited", "gives": "Pays only on a pass", "state": "Local test EVM", "s": "hold", "ver": "41 tests pass"},
 ]),
]
pr = ""
for title, ents in PROV:
    rs = "".join(f'<tr class="row" tabindex="0" data-p="{e["k"]}" aria-selected="{"true" if e["k"]=="window" else "false"}"><td><span class="nm">{e["name"]}</span><span class="nm-s">{e["sub"]}</span></td><td class="t2">{e["gives"]}</td><td><code class="t3">{e["ver"]}</code></td><td><span class="tag {e["s"]}">{ic({"ok":"ok","hold":"hold","quiet":"circle"}[e["s"]])}{e["state"]}</span></td></tr>' for e in ents)
    pr += f'<div class="kind"><h2>{title}</h2><table><colgroup><col style="width:222px"><col style="width:214px"><col style="width:128px"><col></colgroup><tbody>{rs}</tbody></table></div>'
pr += f'''<div class="kind"><h2>Testers</h2><div class="empty"><div><p>No testers yet.</p><small>A tester submits a world that breaks a robot. Names appear here after the gate accepts one.</small></div></div></div>
<div class="kind"><h2>Fix authors</h2><div class="empty"><div><p>No fix authors yet.</p><small>Names appear here when a fix passes all its hidden worlds. This list holds no sample rows.</small></div><a class="btn sec" href="bounties.html">See open bounties</a></div></div>'''
prov_main = f'''<header class="head"><h1>Providers</h1><p>Who provides what in this product. Real entries only.</p></header>
<div class="prov"><section style="overflow:hidden auto">{pr}</section><section class="pdetail" id="pd"></section></div>'''
page("providers", "CrashLab providers", shell("providers", prov_main, '<span>LLM: claude headless</span>'))

(OUT / "data.js").write_text("window.WORLDS=" + json.dumps(ROWS) + ";\nwindow.BOUNTIES=" + json.dumps(BOUNTIES) + ";\nwindow.ICONS=" + json.dumps(ICONS) + ";\n")
for f in ["home", "crashlab", "bounties", "data", "providers", "login"]:
    p = OUT / f"{f}.html"
    p.write_text(p.read_text().replace('<script src="site.js">', '<script src="data.js"></script><script src="site.js">'))
print("built")
