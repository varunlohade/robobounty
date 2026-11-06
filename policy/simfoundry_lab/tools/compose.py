"""Builds design/simfoundry/result.mp4 and stills from real outputs in work/. Writes no result that is not on disk."""
import json, subprocess, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LAB = Path(__file__).resolve().parents[1]; WORK = LAB / "work"; ROOT = LAB.parents[1]
OUT = ROOT / "design/simfoundry"; OUT.mkdir(parents=True, exist_ok=True)
W, H, FPS = 1920, 1080, 30
PW, PH = 954, 536
SANS = "/System/Library/Fonts/Supplemental/Arial.ttf"; BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"; MONO = "/System/Library/Fonts/Menlo.ttc"
def font(path, size): return ImageFont.truetype(path, size)
BG = (17, 19, 22); INK = (236, 238, 240); DIM = (150, 156, 164); RED = (240, 96, 84); GREEN = (96, 200, 130); AMBER = (240, 180, 70)

sink = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                         "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT / "result.mp4")], stdin=subprocess.PIPE)
stills = {}

class Clip:
    def __init__(self, path, start=0.0):
        self.c = cv2.VideoCapture(str(path)); self.fps = self.c.get(cv2.CAP_PROP_FPS); self.c.set(cv2.CAP_PROP_POS_MSEC, start * 1000); self.last = None; self.t = 0.0; self.n = 0
    def frame(self):
        target = self.t * self.fps
        while self.n <= target or self.last is None:
            ok, f = self.c.read()
            if not ok: break
            self.last = f; self.n += 1
        self.t += 1 / FPS
        if self.last is None: raise RuntimeError("no frames")
        return cv2.cvtColor(self.last, cv2.COLOR_BGR2RGB)

def fit(rgb):
    h, w = rgb.shape[:2]; s = min(PW / w, PH / h); r = cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    c = np.full((PH, PW, 3), 8, np.uint8); y = (PH - r.shape[0]) // 2; x = (PW - r.shape[1]) // 2; c[y:y + r.shape[0], x:x + r.shape[1]] = r
    return c

def wrap(d, text, f, width):
    out, line = [], ""
    for word in text.split():
        t = f"{line} {word}".strip()
        if d.textlength(t, font=f) > width and line: out.append(line); line = word
        else: line = t
    return out + [line] if line else out

def label(d, x, y, width, head, body, colour):
    d.rectangle([x, y, x + 8, y + 200], fill=colour)
    d.text((x + 20, y), head, font=font(BOLD, 30), fill=colour)
    lines = wrap(d, body, font(SANS, 28), width - 30)
    assert len(lines) <= 4, body
    for i, l in enumerate(lines):
        d.text((x + 20, y + 42 + i * 38), l, font=font(SANS, 28), fill=INK)

def pair(title, status, left, right, seconds, still=None, still_at=0.5):
    n = int(seconds * FPS)
    for i in range(n):
        a = fit(left["clip"].frame()); b = fit(right["clip"].frame())
        img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img)
        d.text((24, 40), title, font=font(BOLD, 40), fill=INK)
        d.text((24, 98), status, font=font(SANS, 29), fill=AMBER)
        img.paste(Image.fromarray(a), (0 + 3, 158)); img.paste(Image.fromarray(b), (W - PW - 3, 158))
        label(d, 12, 716, PW - 30, left["head"], left["body"], left["colour"])
        label(d, W - PW + 6, 716, PW - 30, right["head"], right["body"], right["colour"])
        d.text((24, H - 46), "Simulated panes are simulated. No pane claims to match a real place.", font=font(SANS, 24), fill=DIM)
        arr = np.asarray(img); sink.stdin.write(arr.tobytes())
        if still and i == int(n * still_at): img.save(OUT / f"{still}.png")

def card(lines, seconds, still=None):
    img = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(img); y = 70
    for text, f, colour in lines:
        d.text((70, y), text, font=f, fill=colour); y += int(f.size * 1.42)
    arr = np.asarray(img).tobytes()
    for _ in range(int(seconds * FPS)): sink.stdin.write(arr)
    if still: img.save(OUT / f"{still}.png")

def log_tail(name, pick, limit=7):
    rows = [l.rstrip() for l in (WORK / "logs" / name).read_text(errors="replace").splitlines() if any(p in l for p in pick)]
    return [r.replace(str(LAB), ".")[:112] for r in rows[:limit]]

H1, H2, T, M, MS = font(BOLD, 60), font(BOLD, 40), font(SANS, 34), font(MONO, 27), font(MONO, 23)
FRUITS = LAB / "repo/docs/assets/example_videos/Fruits.mp4"
HULL = ROOT / "design/shell/hull-scan.mp4"
da3 = (WORK / "logs/da3_mps_fruits.log").read_text(errors="replace")
da3_line = next((l for l in da3.splitlines() if l.startswith("inference")), "")

card([("SimFoundry trial on a MacBook (M4 Max, 36 GB, no NVIDIA)", H1, INK), ("", T, INK),
      ("How far it got: stage 1b ran. Stage 2 crashed. Stage 3 cannot start.", H2, AMBER),
      ("No scene was built on this Mac. It needs Linux and an NVIDIA GPU, 16 GiB minimum.", T, INK), ("", T, INK),
      ("Part 1. What this Mac made: frames, then depth with a smaller model outside the pipeline.", T, INK),
      ("Part 2. The real logs at the point it stopped.", T, INK),
      ("Part 3. NVIDIA's own published scene, NOT built here, loaded into MuJoCo and tested.", T, INK),
      (f"{'Part 4. The ship hull render, as far as this Mac goes.' if (WORK / 'hull_da3.npz').exists() else 'Hull render: the input file did not exist when this video was made.'}", T, INK)], 6, "01_summary")

REAL = dict(head="INPUT: REAL FOOTAGE", body="NVIDIA's sample, docs/assets/example_videos/Fruits.mp4, from the SimFoundry repo. Not our footage.", colour=GREEN)
if (WORK / "fruits_da3_depth.mp4").exists():
    pair("Part 1. Built on this Mac", "Stage 1b is the real pipeline. Depth is NOT the pipeline: its stage 2 crashes here.", dict(REAL, clip=Clip(FRUITS)),
         dict(head="BUILT HERE: DEPTH, 15 FRAMES", body=f"Depth Anything 3 BASE on Apple MPS, called directly. SimFoundry uses a larger model. {da3_line.capitalize()}.", colour=AMBER, clip=Clip(WORK / "fruits_da3_depth.mp4")), 9, "02_depth_on_mac")
    pair("Part 1. Built on this Mac", "A point cloud is not a physics scene. It has no objects, no mass and no collision shapes.", dict(REAL, clip=Clip(FRUITS, 9)),
         dict(head="BUILT HERE: POINT CLOUD FROM THAT DEPTH", body="Unprojected from the same DA3 output. Moving the camera shows the 3D shape.", colour=AMBER, clip=Clip(WORK / "fruits_da3_cloud.mp4")), 6, "03_cloud_on_mac")

rows = [("Part 2. Where it stopped: real logs from this Mac", H2, INK), ("", MS, INK),
        ("stage 1b  video to frames     RAN  452 frames, 15 sampled, 21.6 s", M, GREEN),
        ("stage 2   depth               CRASHED, and the code hard-codes device=\"cuda\"", M, RED)]
rows += [("    " + r, MS, DIM) for r in log_tail("stage2_documented.log", ["Starting stage-2", "SIGSEGV", "Aborted at"], 3)]
rows += [("stage 3   find the table      CANNOT START", M, RED)]
rows += [("    " + r, MS, DIM) for r in log_tail("stage3_documented.log", ["ModuleNotFoundError", "import sam3"], 2)]
rows += [("    facebook/sam3 weights: HTTP 401 without an approved Hugging Face account", MS, DIM),
         ("stage 5-8 objects, meshes, poses   NOT RUN. CUDA GPU code, Gemini calls, gated weights", M, DIM),
         ("stage 10-12 compile and physics    NOT RUN. Need the outputs above", M, DIM),
         ("stage 13-14 USD, OmniGibson scene  NOT RUN. Isaac Sim needs an NVIDIA GPU", M, DIM), ("", MS, INK),
         ("Installing on the Mac also failed once: xformers did not build, so it was left out.", T, INK),
         ("Next step: a rented Linux NVIDIA machine. Commands are in policy/simfoundry_lab/GPU.md.", T, AMBER)]
card(rows, 10, "04_where_it_stopped")

rep = json.load(open(WORK / "sim_report.json"))
NOT = "NOT BUILT HERE: NVIDIA'S PUBLISHED SCENE"
pair("Part 3. What a finished scene looks like. NOT built on this Mac.", "NVIDIA's download droid_desk_serve_fruits. Layout, pear and plate differ from this clip. Same source clip: not confirmed.", dict(REAL, clip=Clip(FRUITS)),
     dict(head=NOT, body="Simulated, in MuJoCo with my lighting. NVIDIA says SimFoundry made the objects. The room is a separate phone scan, placed by an operator.", colour=RED, clip=Clip(WORK / "sim_view.mp4")), 9, "05_published_scene", 0.2)
pair("Part 3. Collision shapes and the drop test. NOT built on this Mac.", "1 kg box at 3 s, ANYmal C from our inspection pack at 5 s. A 52 kg robot on a desk is a load test, not a real setup.",
     dict(head="SIMULATED: COLLISION SHAPES ONLY", body="Convex hulls from the USD files: 2 to 32 per object. Start gaps -0.7 to +2.8 mm. Room has no collision shape.", colour=RED, clip=Clip(WORK / "sim_hull.mp4")),
     dict(head="SIMULATED: BOX AND ROBOT DROP", body="Desk is an invisible endless plane, so nothing can fall off. Robot color and friction 0.75 are mine. With that, apple rolled 29 mm and orange 23 mm untouched.", colour=RED, clip=Clip(WORK / "sim_wide.mp4")), 9, "06_drop_test", 0.92)

if (WORK / "hull_da3_depth.mp4").exists():
    pair("Part 4. Ship hull input. THE INPUT IS A RENDER, NOT REAL FOOTAGE.", "Stage 1b ran. Depth used DA3 BASE outside the pipeline. No scene: stage 3 needs SAM3 and one flat table.",
         dict(head="INPUT: OUR OWN RENDER", body="design/shell/hull-scan.mp4. Computer graphics of a parked robot under a hull. Not real footage.", colour=AMBER, clip=Clip(HULL)),
         dict(head="BUILT HERE: DEPTH FROM THE RENDER", body="Depth Anything 3 BASE on Apple MPS, called directly. This is not a simulation scene.", colour=AMBER, clip=Clip(WORK / "hull_da3_depth.mp4")), 12, "07_hull_depth")
    pair("Part 4. Ship hull input. THE INPUT IS A RENDER, NOT REAL FOOTAGE.", "A point cloud has no objects, mass or collision shapes. It proves nothing about real hulls.",
         dict(head="INPUT: OUR OWN RENDER", body="design/shell/hull-scan.mp4. Computer graphics, not real footage.", colour=AMBER, clip=Clip(HULL)),
         dict(head="BUILT HERE: POINT CLOUD FROM THE RENDER", body="Unprojected from the DA3 output above.", colour=AMBER, clip=Clip(WORK / "hull_da3_cloud.mp4")), 8, "08_hull_cloud")

card([("Verdict: needs a rented NVIDIA machine", H1, AMBER), ("", T, INK),
      ("No scene came out of this Mac. The scene in Part 3 is NVIDIA's download.", H2, INK), ("", T, INK),
      ("RTX 4090 24 GB, 300 GB disk, about 5 hours for a first run: about $2 to $5 for the machine.", T, INK),
      ("Also needed: approved Hugging Face access and a Gemini key. Those belong to the owner.", T, INK),
      ("Designed for objects on one flat table. A curved hull is outside that design: untested.", T, INK),
      ("Licenses: required FoundationPose and Any6D are non-commercial. Hunyuan3D excludes EU, UK, South Korea.", T, RED)], 6, "09_verdict")
sink.stdin.close(); sink.wait()
