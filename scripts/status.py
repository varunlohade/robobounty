#!/usr/bin/env python3
"""Live status page for the build. It opens from disk and reloads itself every 15 s.

  python3 scripts/status.py set hull running "Hull robot" "Rendering the film"
  python3 scripts/status.py done hull "Film finished"
  python3 scripts/status.py need world "World ID action name and environment"
  python3 scripts/status.py clear world
  python3 scripts/status.py show "Login options" design/x.png   # adds a picture or video to the page
  python3 scripts/status.py watch        # rebuilds the page every 15 s
  python3 scripts/status.py build        # rebuilds it once

Hand-written lines live in status/state.json. Commits and running jobs are read from the machine,
so the page shows them even when nobody updates it. It only reads: it stops nothing.
"""
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "status"
STATE = OUT / "state.json"
PAGE = OUT / "index.html"
DEADLINE = datetime(2026, 11, 7, 9, 0)
JOBS = {
    "check_e2e": "Full flow test", "check_security": "Attack tests", "check_board": "Bounty board check",
    "check_testing": "Engine tools test", "check_grid": "Grid check", "check_lab": "Chat check", "check_code": "Code tab check",
    "check_hang": "Hang recovery check", "check_site": "Website check", "check_pack": "Robot check",
    "Blender": "Blender render", "run_trial": "Simulation run", "supervise.py": "Run server", "site_data.py": "Website data server",
    "board_server.py": "Bounty server", "vite": "Web server",
}


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"work": {}, "needs": {}}


def save(state):
    OUT.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE)


def now():
    return datetime.now().strftime("%H:%M")


def update(key, status, title=None, note=""):
    """The one function to call. status is running, waiting, done or failed."""
    state = load()
    old = state["work"].get(key, {})
    state["work"][key] = {"title": title or old.get("title", key), "status": status, "note": note or old.get("note", ""), "at": now()}
    save(state)
    build()


def need(key, text):
    state = load()
    state["needs"][key] = text
    save(state)
    build()


def show(title, path):
    state = load()
    state.setdefault("shows", [])
    state["shows"] = [x for x in state["shows"] if x["path"] != str(path)]
    state["shows"].insert(0, {"title": title, "path": str(path), "at": now()})
    state["shows"] = state["shows"][:24]
    save(state)
    build()


def clear(key):
    state = load()
    state["needs"].pop(key, None)
    state["work"].pop(key, None)
    save(state)
    build()


def sh(*cmd):
    try:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def running():
    rows = {}
    for line in sh("ps", "-eo", "etime=,command=").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or "status.py" in parts[1]:
            continue
        for key, label in JOBS.items():
            if key in parts[1] and "grep" not in parts[1]:
                rows.setdefault(label, parts[0])
    return sorted(rows.items())


def commits():
    rows = []
    for line in sh("git", "log", "-10", "--format=%h%x09%cd%x09%s", "--date=format:%H:%M").splitlines():
        rows.append(line.split("\t", 2))
    return rows


def pushed():
    ahead = sh("git", "rev-list", "--count", "origin/main..main").strip() or "?"
    return "Everything committed is on GitHub" if ahead == "0" else f"{ahead} commits not on GitHub yet"


CSS = """
:root{--bg:#0B0C0E;--panel:#111317;--line:rgba(255,255,255,.08);--text:#ECEEF1;--dim:#A3A9B3;--green:#5CC186;--red:#F27B73;--amber:#E3B04F;--blue:#7DA7FF}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/20px -apple-system,Inter,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px}h1{font-size:20px;font-weight:500;margin:0}h2{font-size:13px;font-weight:500;color:var(--dim);margin:28px 0 8px}
.top{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:baseline}.dim{color:var(--dim)}
.row{display:grid;grid-template-columns:88px 1fr auto;gap:12px;padding:10px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
.row b{font-weight:500}.st{font-size:12px}.running{color:var(--blue)}.waiting{color:var(--amber)}.done{color:var(--green)}.failed{color:var(--red)}
.need{padding:10px 12px;background:#2a2212;color:var(--amber);border-bottom:1px solid var(--line)}.need b{font-weight:500;color:var(--text)}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}figure{margin:0;background:var(--panel);padding:8px}figure img,figure video{width:100%;display:block}figcaption{font-size:12px;padding-top:6px}
code{font:12px ui-monospace,Menlo,monospace;color:var(--dim)}
.c{display:grid;grid-template-columns:70px 50px 1fr;gap:8px;padding:6px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
@media(max-width:560px){.row{grid-template-columns:70px 1fr}.row .dim:last-child{grid-column:2}.c{grid-template-columns:50px 1fr}.c code{display:none}}
"""
ORDER = {"failed": 0, "running": 1, "waiting": 2, "done": 3}


def build():
    e = html.escape
    state = load()
    left = DEADLINE - datetime.now()
    hours = max(0, left.total_seconds()) / 3600
    work = sorted(state["work"].items(), key=lambda kv: (ORDER.get(kv[1]["status"], 9), kv[1]["title"]))
    parts = [f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<meta http-equiv="refresh" content="30"><title>CrashLab Status</title><style>{CSS}</style><main>',
             f'<div class="top"><h1>CrashLab build</h1><span class="dim">{now()} now. {hours:.1f} hours to the 09:00 deadline. Reloads every 30 s.</span></div>']
    if state["needs"]:
        parts.append("<h2>Needs you</h2>")
        parts += [f'<div class="need"><b>{e(k)}:</b> {e(v)}</div>' for k, v in state["needs"].items()]
    if state.get("shows"):
        parts.append("<h2>Latest to look at</h2><div class=\"g\">")
        for x in state["shows"]:
            src = "file://" + str((ROOT / x["path"]).resolve())
            tag = f'<video src="{e(src)}" controls muted loop playsinline></video>' if x["path"].endswith(".mp4") else f'<a href="{e(src)}" target="_blank"><img src="{e(src)}" loading="lazy"></a>'
            parts.append(f'<figure>{tag}<figcaption>{e(x["title"])} <span class="dim">{e(x["at"])}</span></figcaption></figure>')
        parts.append("</div>")
    parts.append("<h2>Builders</h2>")
    for _, w in work:
        parts.append(f'<div class="row"><span class="st {e(w["status"])}">{e(w["status"].capitalize())}</span><span><b>{e(w["title"])}</b><br><span class="dim">{e(w["note"])}</span></span><span class="dim">{e(w["at"])}</span></div>')
    jobs = running()
    parts.append("<h2>Running on this Mac now, read from the machine</h2>")
    parts += [f'<div class="row"><span class="st running">Running</span><span>{e(n)}</span><span class="dim">{e(t)}</span></div>' for n, t in jobs] or ['<div class="row"><span class="dim">None</span></div>']
    parts.append(f'<h2>Latest commits. {e(pushed())}</h2>')
    parts += [f'<div class="c"><code>{e(c[0])}</code><span class="dim">{e(c[1])}</span><span>{e(c[2][:100])}</span></div>' for c in commits() if len(c) == 3]
    parts.append("</main>")
    OUT.mkdir(exist_ok=True)
    tmp = PAGE.with_suffix(".tmp")
    tmp.write_text("".join(parts))
    tmp.replace(PAGE)


def main():
    a = sys.argv[1:] or ["build"]
    if a[0] == "set":
        update(a[1], a[2], a[3] if len(a) > 3 else None, a[4] if len(a) > 4 else "")
    elif a[0] == "done":
        update(a[1], "done", None, a[2] if len(a) > 2 else "")
    elif a[0] == "need":
        need(a[1], a[2])
    elif a[0] == "show":
        show(a[1], a[2])
    elif a[0] == "clear":
        clear(a[1])
    elif a[0] == "watch":
        while True:
            build()
            time.sleep(15)
    else:
        build()
    if a[0] != "watch":
        print(PAGE)


if __name__ == "__main__":
    main()
