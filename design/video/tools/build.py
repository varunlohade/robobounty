#!/usr/bin/env python3
"""Cuts design/video/draft.mp4 from the captures in _cap/ and the two render clips. Silent. Captions and labels sit in a band under the picture, so they cover no app UI."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIDEO = HERE.parent
ROOT = VIDEO.parent.parent
CAP = VIDEO / "_cap"
WORK = VIDEO / "_work"
BANDS = WORK / "bands"
SEGS = WORK / "segs"
FPS = 24

SIM = "Simulated"
REC = "Recorded run"
RENDER = "Re-render of recorded physics"
LIVE = "Live run, AI replies from a file"
LEDGER = "Local ledger, not on chain"


def manifest():
    return json.loads((CAP / "live" / "manifest.json").read_text())


LIVE_M = manifest()
MARK = {m["name"]: m for m in LIVE_M["marks"]}


def live_at(name, offset=0.0):
    """The last live frame at or before a mark plus an offset."""
    t = MARK[name]["t"] + offset
    best = LIVE_M["frames"][0]
    for f in LIVE_M["frames"]:
        if f["t"] <= t:
            best = f
    return CAP / "live" / best["file"]


def live_range(t0, t1, seconds):
    """Live frames between two times, played evenly in `seconds`. The caption states the speed."""
    frames = [f for f in LIVE_M["frames"] if t0 <= f["t"] <= t1]
    rate = (t1 - t0) / seconds
    out = []
    for a, b in zip(frames, frames[1:] + [None]):
        d = ((b["t"] if b else t1) - a["t"]) / rate
        out.append((CAP / "live" / a["file"], d))
    return out


def rec(name):
    d = CAP / "rec" / name
    return [(d / f["file"], f["d"]) for f in json.loads((d / "frames.json").read_text())]


def still(path, seconds):
    return [(path, seconds)]


def hold(name, seconds):
    frames = rec(name)
    return frames[:-1] + [(frames[-1][0], seconds)] if len(frames) > 1 else [(frames[0][0], seconds)]


def clip(name):
    return {"clip": ROOT / "design/render" / name}


def t(name):
    return MARK[name]["t"]


def x(a, b, seconds):
    return round((t(b) - t(a)) / seconds)


# Each segment: (section, frames or clip, caption, labels). Section times follow docs/DEMO-SCRIPT.md.
def segments():
    return [
        ("open", clip("clip_slip.mp4"), "A window robot on a glass tower, wind near 36 m/s. Real speed. No robot exists: this is a simulator run.", [SIM, REC, RENDER]),
        ("open", clip("clip_slip.mp4"), "Played again. It passes the 0.3 m slide limit 39 s into the run. This world, world_010, slid in 2 of 3 repeats.", [SIM, REC, RENDER]),
        ("open", still("card:title", 7), "This draft is silent. Every shot is the app or a recorded run, and each one says which.", [SIM]),

        ("brief", live_range(t("empty"), t("send") + 0.2, 4.5), "You describe the robot and the place in plain English. Real speed.", [SIM, LIVE]),
        ("brief", still(live_at("question", 1.5), 5), "It asks only what it can't work out. Stored AI replies here, so no AI call ran.", [SIM, LIVE]),
        ("brief", still(live_at("normal_run", 4), 5.5), "It builds the world in the browser and runs the robot once. You check the scene.", [SIM, LIVE]),
        ("brief", hold("chat_brief", 4), "The finished Dubai campaign started from this brief.", [SIM, REC]),
        ("brief", hold("chat_requirements", 5.5), "Seven pass or fail rules, written before any run.", [SIM, REC]),

        ("worlds", still(live_at("review", 3), 8), "You review the plan before it runs. The scenario agent chose 52 worlds in 8 groups.", [SIM, LIVE]),
        ("worlds", live_range(t("filling"), t("map"), 14), f"This session approved only the first 12 worlds. Shown at {x('filling', 'map', 14)}x. Its counts are not the headline numbers.", [SIM, LIVE]),
        ("worlds", hold("map_groups", 8), "The finished campaign, world by world, on the glass each run left behind.", [SIM, REC]),

        ("test", hold("map", 10), "campaign_dubai_final: 31 failed, 13 stopped and held on, 5 flaky, 3 passed. Normal runs: 10 of 10.", [SIM, REC]),
        ("test", hold("report", 7), "We chose these worlds to be harsh. These counts are not a reliability figure.", [SIM, REC]),
        ("test", clip("clip_pass.mp4"), "One of the 3 that passed, a gust world. Real speed.", [SIM, REC, RENDER]),

        ("find", rec("replay_016_start"), "world_016. The robot is a scripted controller we wrote. It breaks the slide rule at 0.6 s. Real speed.", [SIM, REC]),
        ("find", hold("replay_016_end", 5), "Timeline moved to 9:10 of 10:00. The red line is the path it slid. This failure repeated 3 of 3.", [SIM, REC]),
        ("find", rec("replay_033"), "world_033 comes off the glass at 30 s. Shown at 2x. It repeated 3 of 3.", [SIM, REC]),
        ("find", hold("replay_038", 5), "world_038 says it is done. Reported coverage 37%, true coverage 16%. It repeated 3 of 3.", [SIM, REC]),
        ("find", hold("code_108", 7), "The low-pressure guard stops at 1500 Pa. Above fan speed 0.896, the estimate can't read that low.", [SIM, REC]),
        ("find", hold("map", 7), "All 9 detach runs: the estimate read safe, true pressure was under the limit. With true pressure: 8 of 9 still came off.", [SIM, REC]),

        ("fix", hold("fix_top", 12), "The AI fix: one constant, suction while cleaning, 0.85 to 0.9. Plan written first, then 104 fresh worlds.", [SIM, REC]),
        ("fix", hold("fix_top", 12), "Passes 11 to 17. Failures 67 to 60. 0 worse. Normal runs 20 of 20 both ways.", [SIM, REC]),
        ("fix", hold("fix_top", 11), "It removes the guard while cleaning, so we did not apply it. A later live AI try: 0 better.", [SIM, REC]),

        ("bounty", still(live_at("bounty_draft", 3), 5.5), "What is left can go to a bounty. Test units on a local ledger. No money moves and nothing is on chain.", [SIM, LIVE, LEDGER]),
        ("bounty", still(live_at("verdict_pass", 2), 5), "A world the robot passes gets rejected.", [SIM, LIVE, LEDGER]),
        ("bounty", live_range(t("paste_fail"), t("verdict_fail"), 5.4), f"A world from an earlier campaign, picked by a search, goes through the gate. Shown at {x('paste_fail', 'verdict_fail', 5.4)}x.", [SIM, LIVE, LEDGER]),
        ("bounty", still(live_at("verdict_fail", 2), 5.5), "Accepted: 7 of 8 re-runs failed the same way. The gate needs 7.", [SIM, LIVE, LEDGER]),
        ("bounty", live_range(t("dispute"), t("finalize"), 4), f"The 60 s dispute window. Shown at {x('dispute', 'finalize', 4)}x.", [SIM, LIVE, LEDGER]),
        ("bounty", still(live_at("claimed", 2), 4.5), "Finalized and claimed. The contract has 41 local tests and is not deployed.", [SIM, LIVE, LEDGER]),

        ("limits", hold("not_tested", 10), "Not tested: airborne sand, wind by height, sun and glare, real hardware, rain, ice and salt.", [SIM, REC]),
        ("limits", still("card:end", 10), "Hand-built physics, not checked against real hardware. Every number holds in this simulator only.", [SIM]),
    ]


CARDS = {
    "title": "<h1>CrashLab</h1><p>Test a robot in simulated worlds, starting from plain English.</p>",
    "end": "<h1>CrashLab</h1><p>One robot. Hand-built physics. Numbers and sources: README.md and docs/evidence/.</p>",
}


def render_html(segs):
    jobs = []
    for i, (_, _, caption, labels) in enumerate(segs):
        jobs.append({"out": str(BANDS / f"band{i:03d}.png"), "caption": caption, "labels": labels})
    (WORK / "bands.json").write_text(json.dumps({"bands": jobs, "cards": {k: {"html": v, "out": str(BANDS / f"card_{k}.jpg")} for k, v in CARDS.items()}}))
    subprocess.check_call(["nice", "-n", "15", "node", str(HERE / "render_bands.mjs"), str(WORK / "bands.json")])


def encode(i, seg):
    _, media, _, _ = seg
    out = SEGS / f"s{i:03d}.mp4"
    band = BANDS / f"band{i:03d}.png"
    base = ["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error"]
    tail = ["-r", str(FPS), "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", str(out)]
    if isinstance(media, dict):
        cmd = base + ["-i", str(media["clip"]), "-i", str(band), "-filter_complex", "[0:v][1:v]overlay=0:960,format=yuv420p"] + tail
    else:
        lst = WORK / f"s{i:03d}.txt"
        rows = []
        for path, d in media:
            path = BANDS / f"card_{path[5:]}.jpg" if isinstance(path, str) else path
            rows.append(f"file '{path}'\nduration {d:.5f}")
        rows.append(f"file '{path}'")
        lst.write_text("\n".join(rows) + "\n")
        cmd = base + ["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(band), "-filter_complex",
                      "[0:v]scale=1920:960,pad=1920:1080:0:0:black[a];[a][1:v]overlay=0:960,format=yuv420p"] + tail
    subprocess.check_call(cmd)
    return out


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def main():
    for d in (BANDS, SEGS):
        d.mkdir(parents=True, exist_ok=True)
    segs = segments()
    render_html(segs)
    only = {int(a) for a in sys.argv[1:]}
    paths, totals, at = [], {}, 0.0
    timeline = []
    for i, seg in enumerate(segs):
        p = SEGS / f"s{i:03d}.mp4"
        if not only or i in only or not p.exists():
            p = encode(i, seg)
        d = duration(p)
        totals[seg[0]] = totals.get(seg[0], 0) + d
        timeline.append({"i": i, "at": round(at, 2), "d": round(d, 2), "section": seg[0], "caption": seg[2], "labels": seg[3]})
        at += d
        paths.append(p)
    (WORK / "concat.txt").write_text("".join(f"file '{p}'\n" for p in paths))
    out = VIDEO / "draft.mp4"
    subprocess.check_call(["nice", "-n", "15", "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(WORK / "concat.txt"), "-c", "copy", "-an", "-movflags", "+faststart", str(out)])
    (WORK / "timeline.json").write_text(json.dumps(timeline, indent=1))
    print({k: round(v, 1) for k, v in totals.items()}, "total", round(at, 1), "s", round(out.stat().st_size / 1e6, 1), "MB")


main()
