#!/usr/bin/env python3
"""Puts the rendered tiles into one looping video. Labels come from plan.json, which reads each run's own result. Nothing is animated by the page.

  login_film_compose.py --size 1920x1080 --out public/login/film-1080.mp4 --poster public/login/film-poster.jpg --crf 24
"""
import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "design" / "render" / "login_film"
FPS, LOOP = 30, 210  # Seven seconds. Every tile repeats exactly on this length, so the whole frame does.
COLS, ROWS = 6, 4
DISSOLVE, FADE = 10, 4
# Reading order. The sign-in panel covers the right side, so the left four columns carry the failures and the fixes.
LAYOUT = ["insp-w015", "win-w001", "insp-w046", "fix041", "insp-w032", "win-w009",
          "win-w004", "insp-w019", "code000", "insp-w043", "win-w023", "insp-w045",
          "insp-w021", "fix042", "insp-w016", "win-w007", "insp-w037", "insp-w005",
          "insp-w029", "insp-w040", "win-w020", "insp-w009", "insp-w026", "insp-w035"]
PHASE = {t: (i * 0.618034) % 1 for i, t in enumerate(LAYOUT)}
INK, RED_CHIP, RED, BLUE, GREEN, DIM = (11, 12, 14), (181, 48, 42), (229, 83, 75), (79, 134, 255), (110, 216, 146), (176, 180, 188)
RED_T, GREEN_T, BLUE_T = (255, 152, 145), (110, 216, 146), (145, 184, 255)


class Type:
    def __init__(self, scale, inter, mono):
        self.scale = scale
        self.name = ImageFont.truetype(inter, round(15 * scale))
        self.name.set_variation_by_axes([430])
        self.word = ImageFont.truetype(inter, round(15 * scale))
        self.word.set_variation_by_axes([560])
        self.mono = ImageFont.truetype(mono, round(13 * scale))


def chip(tw, th, ty, lines, bg, border=None):
    """One tile's label layer, RGBA. A solid chip and, for a failure or a fix, a solid border."""
    im = Image.new("RGBA", (tw * 2, th * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = ty.scale
    if border:
        w = round(2 * s) * 2
        d.rectangle((0, 0, tw * 2 - 1, th * 2 - 1), outline=border + (255,), width=w)
    fonts = [(ty.mono if f == "mono" else ty.word if f == "word" else ty.name) for _, _, f in lines]
    # Draw the text at twice the size through a big font, for clean edges.
    px, py, gap = round(8 * s), round(5 * s), round(20 * s)
    width = max(d.textlength(t, font=f) for (t, _, _), f in zip(lines, fonts))
    width = min(width, tw - round(16 * s) - 2 * px)
    x0, y1 = round(8 * s), th - round(8 * s)
    h = 2 * py + gap * len(lines)
    y0 = y1 - h
    small = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ds = ImageDraw.Draw(small)
    if border:
        ds.rectangle((0, 0, tw - 1, th - 1), outline=border + (255,), width=round(2 * s))
    ds.rounded_rectangle((x0, y0, x0 + width + 2 * px, y1), round(4 * s), fill=bg + (255,))
    y = y0 + py
    for (t, col, _), f in zip(lines, fonts):
        while ds.textlength(t, font=f) > width + 0.5 and len(t) > 4:
            t = t[:-2].rstrip() + "…" if not t.endswith("…") else t[:-2].rstrip() + "…"
        ds.text((x0 + px, y + round(1 * s)), t, font=f, fill=col + (255,))
        y += gap
    return np.asarray(small).astype(np.float32) / 255


def states(t, ty, tw, th):
    """Frame ranges in the tile's own loop, each with a label layer."""
    name = t["name"]
    speed = f"  {t['speed']}x" if t["speed"] > 1 else ""
    nm = (name + speed, (238, 239, 241), "name")
    seg = t["segments"]
    if t["kind"] != "fix":
        at = round(seg[0]["verdict_at"] * FPS)
        if t["kind"] == "fail":
            late = chip(tw, th, ty, [(name + speed, (251, 227, 225), "name"), (t["words"], (255, 255, 255), "word")], RED_CHIP, RED)
        else:
            late = chip(tw, th, ty, [nm, (t["words"], GREEN_T, "word")], INK)
        return [(0, chip(tw, th, ty, [nm], INK)), (at, late)]
    n_before = round(seg[0]["seconds"] * seg[0]["fps"])
    at = min(round(seg[0]["verdict_at"] * FPS), n_before - 8)
    fix_at = n_before + 12
    after_at = fix_at + 42
    return [(0, chip(tw, th, ty, [nm, ("Before the fix", DIM, "word")], INK)),
            (at, chip(tw, th, ty, [(name + speed, (251, 227, 225), "name"), (t["words"], (255, 255, 255), "word")], RED_CHIP, RED)),
            (fix_at, chip(tw, th, ty, [(f"{t['who']} applied", BLUE_T, "word"), (f"- {t['minus']}", RED_T, "mono"), (f"+ {t['plus']}", GREEN_T, "mono")], INK, BLUE)),
            (after_at, chip(tw, th, ty, [nm, ("After the fix", DIM, "word")], INK)),
            (LOOP - 30, chip(tw, th, ty, [nm, (t["after_words"], GREEN_T, "word")], INK))]


def load(work, seg, tw, th):
    n = round(seg["seconds"] * seg["fps"])
    d = work / seg["key"] / "jpg"

    def one(i):
        p = d / f"{i:04d}.jpg"
        if not p.exists():
            return None
        return cv2.resize(cv2.imread(str(p)), (tw, th), interpolation=cv2.INTER_AREA)[:, :, ::-1]
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(one, range(n)))
    return [f for f in out if f is not None]


def timeline(t, clips):
    """LOOP frames for one tile: motion, a hold on the last recorded frame, a dissolve back to the first. Each entry is (a, b, u): u of frame b over frame a."""
    tl = []
    if len(clips) == 1:
        c = clips[0]
        for f in range(LOOP):
            i = min(f, len(c) - 1)
            if f >= LOOP - DISSOLVE:
                tl.append((c[i], c[0], (f - (LOOP - DISSOLVE) + 1) / DISSOLVE))
            else:
                tl.append((c[i], None, 0))
        return tl
    a, b = clips
    gap = 30
    for f in range(LOOP):
        if f < len(a) + gap:
            i = min(f, len(a) - 1)
            u = max(0, f - (len(a) + gap - DISSOLVE) + 1) / DISSOLVE
            tl.append((a[i], b[0], u) if u > 0 else (a[i], None, 0))
        else:
            i = min(f - len(a) - gap, len(b) - 1)
            if f >= LOOP - DISSOLVE:
                tl.append((b[i], a[0], (f - (LOOP - DISSOLVE) + 1) / DISSOLVE))
            else:
                tl.append((b[i], None, 0))
    return tl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--out", required=True)
    ap.add_argument("--poster", default=None)
    ap.add_argument("--crf", type=float, default=24)
    ap.add_argument("--work", default=str(OUT / "_work" / "final"))
    ap.add_argument("--inter", default="/tmp/lf/Inter.ttf")
    ap.add_argument("--mono", default="/tmp/lf/Mono.ttf")
    ap.add_argument("--grain", type=float, default=1.5)
    a = ap.parse_args()
    W, H = map(int, a.size.split("x"))
    tw, th = W // COLS, H // ROWS
    sep = max(2, round(2 * H / 1080))
    plan = {t["id"]: t for t in json.loads((OUT / "plan.json").read_text())["tiles"]}
    ty = Type(H / 1080, a.inter, a.mono)
    frame = np.empty((H, W, 3), np.float32)
    tiles = []
    for slot, tid in enumerate(LAYOUT):
        t = plan[tid]
        clips = [load(Path(a.work), s, tw, th) for s in t["segments"]]
        if not all(len(c) == round(s["seconds"] * s["fps"]) for c, s in zip(clips, t["segments"])):
            raise SystemExit(f"{tid}: frames missing, {[len(c) for c in clips]}")
        st = states(t, ty, tw, th)
        tiles.append({"t": t, "tl": timeline(t, clips), "st": st, "phase": round(PHASE[tid] * LOOP), "x": (slot % COLS) * W // COLS, "y": (slot // COLS) * H // ROWS})
        print(tid, "loaded", flush=True)

    def state_at(tile, f):
        now = tile["st"][0]
        for s in tile["st"]:
            if s[0] <= f:
                now = s
        return now
    # Frame 0 is the poster, so the first paint and the video agree: the most failures and fixes in view.
    best, start = -1, 0
    for f in range(LOOP):
        n = 0
        for i, tl in enumerate(tiles):
            s = state_at(tl, (f + tl["phase"]) % LOOP)
            k = tl["st"].index(s)
            weight = 2 if tl["t"]["kind"] == "fix" and k == 2 else 1 if (tl["t"]["kind"] == "fail" and k == 1) or (tl["t"]["kind"] == "fix" and k == 1) else 0
            if i % COLS < 4:
                weight *= 2
            n += weight
        if n > best:
            best, start = n, f
    print("poster frame", start, "score", best)

    rng = np.random.default_rng(7)
    grains = []
    for _ in range(30):  # 30 divides the loop, so the grain repeats with it.
        g = rng.normal(0, 1, (H // 2 + 1, W // 2 + 1)).astype(np.float32)
        g = cv2.resize(g, (W, H), interpolation=cv2.INTER_LINEAR) * 0.7 + rng.normal(0, 0.5, (H, W)).astype(np.float32)
        grains.append(g[..., None] * a.grain)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slower", "-crf", str(a.crf),
                            "-profile:v", "high", "-level", "5.0" if H > 1080 else "4.2", "-pix_fmt", "yuv420p", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-bf", "2", "-x264-params", "open-gop=0:aq-mode=3:deblock=-1,-1:psy-rd=1.0,0.05",
                            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart", "-an", "-map_metadata", "-1", a.out], stdin=subprocess.PIPE)
    for f0 in range(LOOP):
        f = (f0 + start) % LOOP
        frame[:] = np.array(INK, np.float32)
        layers = []
        for tl in tiles:
            lf = (f + tl["phase"]) % LOOP
            a_img, b_img, u = tl["tl"][lf]
            im = a_img.astype(np.float32) if b_img is None else a_img.astype(np.float32) * (1 - u) + b_img.astype(np.float32) * u
            x, y = tl["x"], tl["y"]
            frame[y:y + th - sep, x:x + tw - sep] = im[:th - sep, :tw - sep]
            s = state_at(tl, lf)
            k = tl["st"].index(s)
            mix = min(1.0, (lf - s[0] + 1) / FADE) if k > 0 else 1.0
            if k == 0 and lf < FADE:  # The loop's seam: from the last label back to the first.
                mix = (lf + 1) / FADE
                prev = tl["st"][-1][1]
            else:
                prev = tl["st"][k - 1][1] if k > 0 else tl["st"][0][1]
            layer = s[1] * mix + prev * (1 - mix) if mix < 1 else s[1]
            layers.append((x, y, layer))
        frame += grains[f % len(grains)] * (0.35 + 0.65 * np.clip(frame.mean(axis=2, keepdims=True) / 110, 0, 1))
        for x, y, layer in layers:
            al = layer[:th - sep, :tw - sep, 3:4]
            frame[y:y + th - sep, x:x + tw - sep] = frame[y:y + th - sep, x:x + tw - sep] * (1 - al) + layer[:th - sep, :tw - sep, :3] * 255 * al
        out = np.clip(frame + 0.5, 0, 255).astype(np.uint8)
        enc.stdin.write(out.tobytes())
        if f0 == 0 and a.poster:
            Image.fromarray(out).save(a.poster, quality=84, optimize=True, progressive=True, subsampling="4:2:0")
    enc.stdin.close()
    enc.wait()
    manifest = {"note": "Simulated. Each tile is a window of one recorded run, rendered in Cycles. Words come from that run's result.", "loop_s": LOOP / FPS, "grid": [COLS, ROWS],
                "tiles": [{"slot": i, "run": plan[t]["run"], "robot": plan[t]["robot"], "name": plan[t]["name"], "verdict": plan[t]["verdict"], "words": plan[t]["words"], "speed": plan[t]["speed"], "windows_s": [[round(s["t0"], 2), round(s["t1"], 2)] for s in plan[t]["segments"]], **({"fix": {"who": plan[t]["who"], "minus": plan[t]["minus"], "plus": plan[t]["plus"], "after": plan[t]["after_words"]}} if plan[t]["kind"] == "fix" else {})} for i, t in enumerate(LAYOUT)]}
    (Path(a.out).parent / "film.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(a.out, Path(a.out).stat().st_size / 1e6, "MB")


if __name__ == "__main__":
    main()
