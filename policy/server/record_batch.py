"""Records one batch per robot into policy/runs/demo, for server.py --recorded policy/runs/demo. It starts a real server on its own port with the stored AI replies, and runs each real campaign. Results are simulated.

policy/.venv/bin/python policy/server/record_batch.py [--out DIR] [--pack window] [--limit N]
"""
import argparse
import gzip
import json
import shutil
import socket
import subprocess
import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import site_auth
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pack_campaign
import pack_job
import recorded_batch

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs" / "server"
ORIGIN = "http://localhost:5199"
EXPORT_THREADS = 6
POLL_S = 1.0


def call(port, method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers={"Origin": ORIGIN, "Content-Type": "application/json", "Authorization": f"Bearer {site_auth.local_token()}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def wait_idle(sid, count):
    path = RUNS / sid / "events.jsonl"
    while not path.exists() or sum(json.loads(line)["type"] == "idle" for line in path.read_text().splitlines()) < count:
        time.sleep(0.3)


def write_gz(path, value):
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(value, separators=(",", ":")).encode())


def record(port, pack, out, limit):
    status, reply = call(port, "POST", "/api/sessions", {"pack": pack})
    assert status == 201, status
    sid = reply["id"]
    session = RUNS / sid
    idles = 1 if pack == "inspection" else 0
    if idles:
        wait_idle(sid, idles)
    status, _ = call(port, "POST", f"/api/sessions/{sid}/action", {"action": "list_scenarios", "value": ""})
    assert status == 202, status
    wait_idle(sid, idles + 1)
    status, _ = call(port, "POST", f"/api/sessions/{sid}/action", {"action": "run_campaign"})
    assert status == 202, status
    timeline = []
    while True:
        status, grid = call(port, "GET", f"/api/sessions/{sid}/campaigns/c1/grid")
        if status == 200:
            timeline.append(grid)
            if not grid["running"] and (session / "campaigns" / "c1" / "grid.json").exists() and sum(json.loads(line)["type"] == "campaign_done" for line in (session / "events.jsonl").read_text().splitlines()):
                break
        time.sleep(POLL_S)
    folder = session / "campaigns" / "c1"
    plan = pack_campaign.read_json(folder / "scenarios.json")
    final = pack_campaign.read_json(folder / "grid.json")
    timeline.append(final)
    ran = [r["index"] for r in final["rows"] if (folder / f"w{r['index']:03d}" / "job_result.json").exists()]
    with ThreadPoolExecutor(EXPORT_THREADS) as pool:
        replies = list(pool.map(lambda i: call(port, "GET", f"/api/sessions/{sid}/campaigns/c1/worlds/{i}/replay"), ran))
    ok = [i for i, (code, _) in zip(ran, replies) if code == 200]
    print(f"{pack}: {final['counts']}, {final['elapsed_s']} s, {len(ok)} of {len(ran)} replays", flush=True)
    target = out / pack
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for index in ran:
        source, run = folder / f"w{index:03d}", target / f"w{index:03d}"
        run.mkdir()
        shutil.copyfile(source / "job_result.json", run / "job_result.json")
        (run / "job.log").write_text("\n".join(pack_campaign.tail(source / "job.log")) + "\n")
        if (source / "film.jpg").exists():
            shutil.copyfile(source / "film.jpg", run / "film.jpg")
        if pack == "inspection":
            if index in ok:
                shutil.copyfile(source / "replay.json.gz", run / "replay.json.gz")
        elif index in ok:
            (run / "export").mkdir()
            for path in (session / "exports" / f"c1-{index:03d}").iterdir():
                with gzip.GzipFile(run / "export" / f"{path.name}.gz", "wb", mtime=0) as f:
                    f.write(path.read_bytes())
    events = [json.loads(line) for line in (session / "events.jsonl").read_text().splitlines()]
    opening = [e for e in events if e["type"] in ("world", "pose_world")][:1]
    results = [pack_campaign.read_json(folder / f"w{i:03d}" / "job_result.json") for i in ran]
    label = next(r["label"] for r in results if r)
    opening.append({"type": "sim", "label": f"{recorded_batch.LABEL}, {label}"})
    (target / "opening.json").write_text(json.dumps(opening))
    plan.pop("llm_reply", None)
    write_gz(target / "scenarios.json.gz", plan)
    keep = ("index", "status", "t", "x", "y", "verdict", "verdict_reason")
    write_gz(target / "timeline.json.gz", [{"running": g["running"], "elapsed_s": g["elapsed_s"], "max_procs": g["max_procs"], "label": label, "rows": [{k: r[k] for k in keep} for r in g["rows"]]} for g in timeline])
    return final["counts"]


def store_fix(report_path, out):
    """Keeps one real AI fix's report beside the batch, for the recorded demo. It must name the same worlds and verdicts as the batch's window timeline, or it would describe other runs."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    if report.get("llm", {}).get("error") or report["llm"].get("seconds") is None:
        raise SystemExit("This report did not come from a real AI call.")
    rows = {r["index"]: r for r in recorded_batch._read_gz(out / report["pack"] / "timeline.json.gz")[-1]["rows"]}
    for pair in report["pairs"]:
        if pair["set"] != "held_back" and rows[pair["index"]]["verdict"] != pair["old"]["verdict"]:
            raise SystemExit(f"World {pair['index']} differs from the batch.")
    keep = ("group", "status", "words", "diff", "flags", "sets", "validation", "limits", "held_back_worlds_shown_to_llm", "proof_wall_s", "llm", "base_sha256", "patched_sha256")
    stored = {k: report.get(k) for k in keep}
    stored["source"] = f"A real AI edit, tested in the sandbox on these same worlds in an earlier campaign, {time.strftime('%Y-%m-%d', time.localtime(report_path.stat().st_mtime))}."
    (out / report["pack"] / recorded_batch.STORED_FIX).write_text(json.dumps(stored, indent=1) + "\n")
    print(stored["status"], stored["sets"]["held_back"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "runs" / "demo"))
    ap.add_argument("--pack", choices=sorted(pack_job.PACKS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stored-fix", help="a real AI fix's report.json to keep beside the batch. Nothing else is recorded.")
    a = ap.parse_args()
    if a.stored_fix:
        return store_fix(a.stored_fix, Path(a.out))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    argv = [sys.executable, str(HERE / "server.py"), "--port", str(port), "--recorded", str(HERE / "fixtures")]
    if a.limit:
        argv += ["--scenario-limit", str(a.limit)]
    server = subprocess.Popen(argv, stdout=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                if call(port, "GET", "/api/health", timeout=2)[0] == 200:
                    break
            except OSError:
                time.sleep(0.2)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for pack in [a.pack] if a.pack else sorted(pack_job.PACKS):
            record(port, pack, out, a.limit)
        (out / recorded_batch.MARKER).write_text(json.dumps({"format": "recorded-batch/1", "note": "Simulated. Recorded from real campaigns by record_batch.py, with stored AI replies. See docs/LAB-EVENTS.md.", "packs": sorted(p.name for p in out.iterdir() if p.is_dir())}, indent=1) + "\n")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
