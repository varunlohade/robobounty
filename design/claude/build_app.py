#!/usr/bin/env python3
"""Builds app-1.html, app-2.html and app-3.html. Output is static HTML and SVG."""
import random
import zlib
from pathlib import Path

OUT = Path(__file__).parent

INK = "#15171A"
TXT2 = "#50545A"
TXT3 = "#6C7076"
HAIR = "#DFE0E2"
ACC = "#123C2F"
FAIL = "#A61E1A"
GLASS = "#EDF2F4"
GLINE = "#D5DEE2"
LANE = "#C8D3D8"
FILM = "#D3CEC3"
SPECK = "#BDB5A5"
SPAN = "#E4E5E6"
MULL = "#2B2E33"
CITY = "#E6E7E9"
CITY2 = "#D6D8DB"

CHAT_W = 450
RIGHT_W = 1440 - CHAT_W
BAR_H = 44
SERIF = 'Palatino, "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif'

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1440px;height:900px;background:#fff;overflow:hidden}}
body{{position:relative;color:{INK};font:400 16px/24px -apple-system,"SF Pro Text","Helvetica Neue",Arial,sans-serif;
 -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums lining-nums}}
.a{{position:absolute}}
.serif{{font-family:{SERIF}}}
code,.code{{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:13px}}
.small{{font-size:13px;line-height:18px;color:{TXT3}}}
.t2{{color:{TXT2}}}
.fail{{color:{FAIL}}}

/* window bar */
.bar{{position:absolute;left:0;top:0;width:1440px;height:{BAR_H}px;border-bottom:1px solid {HAIR};background:#fff;z-index:5}}
.lights{{position:absolute;left:16px;top:16px;display:flex;gap:8px}}
.lights i{{display:block;width:12px;height:12px;border-radius:50%;background:#DCDDDF}}
.brand{{position:absolute;left:84px;top:0;line-height:43px;font-family:{SERIF};font-size:18px}}
.proj{{position:absolute;left:176px;top:0;line-height:44px;font-size:14px;color:{TXT3}}}
.tabs{{position:absolute;left:{CHAT_W + 32}px;top:0;height:44px;display:flex;gap:24px;font-size:14px;color:{TXT2}}}
.tabs span{{line-height:44px;height:44px;display:block}}
.tabs .on{{color:{INK};font-weight:500;box-shadow:inset 0 -2px 0 {ACC}}}
.barR{{position:absolute;right:24px;top:0;line-height:44px;font-size:13px;color:{TXT3};display:flex;gap:18px;align-items:center}}
.div{{position:absolute;left:{CHAT_W}px;top:{BAR_H}px;width:1px;height:{900 - BAR_H}px;background:{HAIR};z-index:1}}

/* chat */
.chat{{position:absolute;left:0;top:{BAR_H}px;width:{CHAT_W}px;height:{900 - BAR_H}px}}
.m{{position:absolute;left:32px;width:{CHAT_W - 64}px}}
.you{{font-family:{SERIF};color:{INK}}}
.who{{font-size:13px;line-height:18px;color:{TXT3}}}
.btn{{display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:6px;font-size:14px;font-weight:500;white-space:nowrap}}
.pri{{background:{ACC};color:#fff}}
.sec{{border:1px solid {INK};color:{INK}}}
.lnk{{color:{INK};font-size:14px;font-weight:500;border-bottom:1px solid {INK};line-height:20px;white-space:nowrap}}
.composer{{position:absolute;left:20px;width:{CHAT_W - 40}px;top:{900 - BAR_H - 92}px;height:76px;border:1px solid #CFD0D3;border-radius:10px;background:#fff}}
.composer .ph{{position:absolute;left:14px;top:10px;font-family:{SERIF};font-size:17px;color:{TXT3}}}
.composer .ctx{{position:absolute;left:14px;bottom:9px;font-size:13px;color:{TXT3}}}
.composer .go{{position:absolute;right:9px;bottom:9px;width:28px;height:28px;border-radius:6px;background:{INK}}}
.rule{{position:absolute;height:1px;background:{HAIR}}}
.row{{display:flex;justify-content:space-between;border-top:1px solid {HAIR}}}
"""

def page(title, body):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>\n'

def bar(tabs, active):
    t = "".join(f'<span class="{"on" if x == active else ""}">{x}</span>' for x in tabs)
    return f'''<div class="bar"><div class="lights"><i></i><i></i><i></i></div><div class="brand">CrashLab</div>
<div class="proj">Window robot, Dubai towers</div><div class="tabs">{t}</div>
<div class="barR"><span>Simulated</span><span>Sample data</span></div></div><div class="div"></div>'''

def composer(ph, ctx):
    arrow = '<svg width="28" height="28" viewBox="0 0 28 28"><path d="M14 20V9M9.5 13L14 8.5L18.5 13" fill="none" stroke="#fff" stroke-width="1.6"/></svg>'
    return f'<div class="composer"><div class="ph">{ph}</div><div class="ctx">{ctx}</div><div class="go">{arrow}</div></div>'

# ---------- drawing ----------

def specks(rng, x, y, w, h, n, color=SPECK):
    out = []
    for _ in range(n):
        px, py = x + rng.random() * w, y + rng.random() * h
        s = rng.choice([1, 1, 1.5, 2])
        out.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{s}" height="{s}" fill="{color}"/>')
    return "".join(out)

def glass_marks(x, y, w, h):
    """Drafting sign for glass: two short parallel diagonals in a corner."""
    a = f'<path d="M{x + w * .58:.1f} {y + h * .30:.1f}L{x + w * .80:.1f} {y + h * .08:.1f}" stroke="{GLINE}" stroke-width="1.5"/>'
    b = f'<path d="M{x + w * .66:.1f} {y + h * .34:.1f}L{x + w * .88:.1f} {y + h * .12:.1f}" stroke="{GLINE}" stroke-width="1.5"/>'
    return a + b

def robot(x, y, s=48, color=INK):
    """Flat square suction robot, seen from outside the glass."""
    tr = s * .16
    inner = "#fff"
    o = f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{s * .07:.1f}" fill="{color}"/>'
    # tracks with cleats
    for tx in (x + s * .05, x + s - s * .05 - tr):
        o += f'<rect x="{tx:.1f}" y="{y + s * .06:.1f}" width="{tr:.1f}" height="{s * .88:.1f}" fill="#54585E"/>'
        n = 7
        for i in range(n):
            cy = y + s * .1 + i * (s * .8 / (n - 1))
            o += f'<rect x="{tx:.1f}" y="{cy - .5:.1f}" width="{tr:.1f}" height="1" fill="{color}"/>'
    # suction ring and tether point
    cx, cy = x + s / 2, y + s / 2
    o += f'<circle cx="{cx}" cy="{cy}" r="{s * .2:.1f}" fill="none" stroke="{inner}" stroke-width="{max(1, s * .03):.1f}"/>'
    o += f'<circle cx="{cx}" cy="{cy}" r="{s * .08:.1f}" fill="{inner}"/>'
    return o

def facade(ox, oy, cols, floors, cell_state, W, H, seed=7, pw=240, ph=320, sp=80, speck_n=170, mw=3):
    """cell_state(col, floor) -> 'clean' | 'film' | int (lanes cleaned, 0-5)."""
    rng = random.Random(seed)
    o = ""
    for f in range(floors):
        fy = oy + f * (ph + sp)
        for c in range(cols):
            x, y = ox + c * pw, fy
            st = cell_state(c, f)
            if st == "clean":
                o += f'<rect x="{x}" y="{y}" width="{pw}" height="{ph}" fill="{GLASS}"/>' + glass_marks(x, y, pw, ph)
            else:
                o += f'<rect x="{x}" y="{y}" width="{pw}" height="{ph}" fill="{FILM}"/>' + specks(rng, x, y, pw, ph, speck_n)
                if isinstance(st, tuple):
                    lanes, frac = st
                    lw = pw / 5
                    if lanes:
                        o += f'<rect x="{x}" y="{y}" width="{lw * lanes}" height="{ph}" fill="{GLASS}"/>'
                    if frac:
                        lane_h = ph * frac
                        # odd lanes run up from the bottom, even lanes run down from the top
                        ly = y if lanes % 2 == 0 else y + ph - lane_h
                        o += f'<rect x="{x + lw * lanes}" y="{ly}" width="{lw}" height="{lane_h}" fill="{GLASS}"/>'
                    # lane edges: each one stops short at the end where the robot turned
                    for i in range(1, lanes + (1 if frac else 0)):
                        lx = x + lw * i
                        gap = lw * .55
                        if i % 2 == 1:   # lanes i-1 and i join at the bottom
                            o += f'<path d="M{lx} {y}V{y + ph - gap}" stroke="{LANE}" stroke-width="1"/>'
                        else:            # lanes i-1 and i join at the top
                            o += f'<path d="M{lx} {y + gap}V{y + ph}" stroke="{LANE}" stroke-width="1"/>'
        # spandrel band under the floor's vision glass
        o += f'<rect x="{ox}" y="{fy + ph}" width="{W - ox}" height="{sp}" fill="{SPAN}"/>'
        o += f'<rect x="{ox}" y="{fy + ph + sp - 2}" width="{W - ox}" height="2" fill="#C6C8CB"/>'
    # mullions
    for c in range(cols + 1):
        x = ox + c * pw
        o += f'<rect x="{x - mw / 2}" y="0" width="{mw}" height="{H}" fill="{MULL}"/>'
    for f in range(floors):
        fy = oy + f * (ph + sp)
        o += f'<rect x="{ox}" y="{fy - mw / 2}" width="{W - ox}" height="{mw}" fill="{MULL}"/>'
        o += f'<rect x="{ox}" y="{fy + ph - mw / 2}" width="{W - ox}" height="{mw}" fill="{MULL}"/>'
    return o

def city(x0, x1, base, seed=3, scale=1.0, color=CITY):
    rng = random.Random(seed)
    o = ""
    x = x0
    while x < x1:
        w = rng.choice([10, 14, 18, 22, 26]) * scale
        h = rng.choice([14, 20, 26, 34, 48, 62, 40, 22]) * scale
        w = min(w, x1 - x)
        o += f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{color}"/>'
        x += w + rng.choice([0, 3, 6, 10]) * scale
    return o

def wind_lines(x0, x1, y0, y1, n, seed=11, color="#B4B8BD"):
    rng = random.Random(seed)
    o = ""
    for i in range(n):
        y = y0 + (y1 - y0) * (i + .5) / n
        a = x0 + rng.random() * 60
        b = x1 - rng.random() * 70
        o += f'<path d="M{a:.0f} {y:.0f}H{b:.0f}" stroke="{color}" stroke-width="1"/>'
        o += f'<path d="M{b - 6:.0f} {y - 3:.0f}L{b:.0f} {y:.0f}L{b - 6:.0f} {y + 3:.0f}" fill="none" stroke="{color}" stroke-width="1"/>'
    return o

def spark(points, w, h, color=INK, limit=None, lo=None, hi=None):
    lo = min(points) if lo is None else lo
    hi = max(points) if hi is None else hi
    def yy(v):
        return h - 1 - (v - lo) / (hi - lo) * (h - 2)
    d = "M" + "L".join(f"{i * w / (len(points) - 1):.1f} {yy(v):.1f}" for i, v in enumerate(points))
    o = f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block">'
    if limit is not None:
        o += f'<path d="M0 {yy(limit):.1f}H{w}" stroke="#9EA2A7" stroke-width="1" stroke-dasharray="2 3"/>'
    o += f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.25"/></svg>'
    return o

# ---------- app 1 ----------

def app1():
    ROW_H = 44
    fx = 346  # facade start inside the right pane
    H = 900 - BAR_H

    def state(c, f):
        if f == 0:
            return "clean"
        if f == 1:
            return ["clean", (3, .62), "film"][min(c, 2)]
        return "film"

    oy = -160
    s = facade(fx, oy, 3, 3, state, RIGHT_W, H)
    pane_x = fx + 240
    pane_y = oy + 400
    lane = 48
    # robot climbs lane 4 (index 3), which runs up from the bottom
    rx = pane_x + 3 * lane
    ry = pane_y + 320 - 320 * .62 - 24
    s += f'<path d="M{rx + 24} {ry}V0" stroke="{INK}" stroke-width="1.25"/>'
    s += robot(rx, ry)

    # air: wind and the city far below
    base = H - 66
    air = wind_lines(36, fx - 14, 500, 660, 5)
    air += city(0, fx - 2, base, seed=5, scale=1.25, color=CITY)
    air += city(0, fx - 2, base, seed=9, scale=.7, color=CITY2)
    air += f'<path d="M0 {base}H{fx - 2}" stroke="{INK}" stroke-width="1"/>'

    # notes on the drawing, set straight on the surface they name
    note = f'font-family="-apple-system,Helvetica Neue,Arial,sans-serif" font-size="13" fill="{INK}"'
    notes = f'<text x="{rx + 34}" y="60" {note}>Tether</text>'
    notes += f'<text x="{pane_x + 14}" y="{pane_y + 300}" {note}>Clean path</text>'
    notes += f'<text x="{pane_x + 254}" y="{pane_y + 300}" {note}>Dust film</text>'
    # floor marks, on the spandrels
    for name, y in (("Floor 63, 252 m", oy + 320 + 80), ("Floor 61, 244 m", oy + 800 + 320 + 80)):
        pass
    notes += f'<text x="{fx + 14}" y="{oy + 320 + 46}" {note}>Floor 62, 248 m</text>'
    notes += f'<text x="{fx + 14}" y="{oy + 720 + 46}" {note}>Floor 61, 244 m</text>'
    # 1 m bar, drawn at glass scale on the spandrel
    sb = pane_x + 256
    sy = oy + 720 + 40
    notes += f'<path d="M{sb} {sy}H{sb + 100}M{sb} {sy - 4}V{sy + 4}M{sb + 100} {sy - 4}V{sy + 4}" stroke="{INK}" stroke-width="1" fill="none"/><text x="{sb + 108}" y="{sy + 4.5}" {note}>1 m</text>'

    svg = f'<svg class="a" style="left:0;top:0" width="{RIGHT_W}" height="{H}" viewBox="0 0 {RIGHT_W} {H}">{air}{s}{notes}</svg>'

    rows_chat = [
        ("Tower", "Curtain wall, panes 2.4 by 3.2 m"),
        ("Height", "Floor 62, 248 m up"),
        ("Robot", "0.48 m square, tracks, one tether"),
        ("Wind", "11 m/s, gusts to 15"),
        ("Suction", "Holds above 11 kPa"),
        ("Grip", "Track friction 0.62, light dust"),
    ]
    chat = f'''<div class="chat">
<div class="m you" style="top:26px;font-size:27px;line-height:36px">I&rsquo;m building a window-cleaning robot for towers in Dubai.</div>
<div class="m" style="top:118px">I set up one bay of a tower with your robot on the glass. It is running on the right now. Tell me if the height or the glass is wrong.</div>
</div>'''
    # shared rows: the setting in the chat runs on into the live reading
    y0 = 262
    shared = ""
    live = {
        "Wind": ("11.2", "m/s", spark([9.8, 10.4, 10.1, 11.6, 12.9, 11.8, 10.9, 11.4, 12.2, 11.2, 10.6, 11.2], 96, 22)),
        "Suction": ("18.4", "kPa", spark([18.9, 18.8, 18.9, 18.5, 18.1, 18.4, 18.6, 18.5, 18.2, 18.3, 18.5, 18.4], 96, 22)),
        "Grip": ("0.62", "&mu;", spark([.63, .63, .62, .62, .64, .63, .61, .62, .63, .62, .62, .62], 96, 22, lo=.5, hi=.7)),
    }
    rule_end = CHAT_W + fx - 2
    for i, (k, v) in enumerate(rows_chat):
        y = y0 + i * ROW_H
        crossing = k in live
        width = (rule_end - 32) if crossing else CHAT_W - 64
        shared += f'<div class="a" style="left:32px;top:{y}px;height:1px;width:{width}px;background:{HAIR};z-index:2"></div>'
        shared += f'<div class="a small" style="left:32px;top:{y + 13}px;color:{TXT2};width:70px">{k}</div>'
        shared += f'<div class="a" style="left:96px;top:{y + 10}px;width:330px;white-space:nowrap">{v}</div>'
        if crossing:
            val, unit, sp = live[k]
            shared += f'<div class="a serif" style="left:{CHAT_W + 28}px;top:{y + 7}px;font-size:24px;line-height:30px;white-space:nowrap">{val}<span style="font-family:-apple-system,sans-serif;font-size:13px;color:{TXT3};margin-left:5px">{unit}</span></div>'
            shared += f'<div class="a" style="left:{CHAT_W + 28 + 118}px;top:{y + 11}px">{sp}</div>'
    last = y0 + len(rows_chat) * ROW_H
    shared += f'<div class="a" style="left:32px;top:{last}px;height:1px;width:{rule_end - 32}px;background:{HAIR};z-index:2"></div>'
    label_y = y0 + 3 * ROW_H - 26
    shared += f'<div class="a small" style="left:{CHAT_W + 28}px;top:{label_y}px;color:{TXT2}">Live, 0:42 into the run</div>'

    after = f'''<div class="a" style="left:32px;top:{last + 14}px;width:{CHAT_W - 64}px"><span class="code t2">world/tower.yaml</span> <span class="small">+42</span> &nbsp; <span class="code t2">world/weather.yaml</span> <span class="small">+18</span></div>
<div class="a" style="left:32px;top:{last + 56}px;display:flex;gap:18px;align-items:center"><span class="btn pri">Test it once</span><span class="lnk">Open the code</span></div>'''

    right = f'<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{svg}</div>'
    fine = f'<div class="a small" style="left:{CHAT_W + 28}px;top:{BAR_H + base + 12}px;width:290px">Hand-built physics, not checked against real hardware.</div>'
    body = bar(["World", "Code"], "World") + right + chat + shared + after + fine + f'<div class="chat" style="pointer-events:none">{composer("Change the robot or the world", "This tower, this robot")}</div>'
    (OUT / "app-1.html").write_text(page("World set up", body))

# ---------- tiles ----------

def tile(group, level, status="pass", w=76, h=52, seed=0):
    rng = random.Random(zlib.crc32(f"{group}{round(level * 100)}{seed}".encode()))
    mx = w // 2  # mullion
    pane_l = f'<rect x="0" y="0" width="{mx}" height="{h}" fill="{GLASS}"/>'
    film = f'<rect x="{mx}" y="0" width="{w - mx}" height="{h}" fill="{FILM}"/>'
    o = film + pane_l
    lane = (w - mx) / 5
    color = FAIL
    stop = {"pass": 5, "fail": 2, "open": 2}[status]
    # cleaned lanes on the right pane
    if status == "pass":
        o += f'<rect x="{mx}" y="0" width="{lane * 3}" height="{h}" fill="{GLASS}"/>'
        rob = f'<rect x="{mx + lane * 3}" y="{h * .3:.0f}" width="{lane:.1f}" height="{lane:.1f}" fill="{INK}"/>'
    else:
        o += f'<rect x="{mx}" y="0" width="{lane * 2}" height="{h}" fill="{GLASS}"/>'
        o += f'<rect x="{mx + lane * 2}" y="0" width="{lane}" height="{h * .32:.0f}" fill="{GLASS}"/>'
        fx_ = mx + lane * 2.5
        o += f'<path d="M{fx_} {h * .32:.0f}V{h * .78:.0f}" stroke="{color}" stroke-width="1.5"/>'
        rob = f'<rect x="{mx + lane * 2}" y="{h * .78:.0f}" width="{lane:.1f}" height="{lane:.1f}" fill="{color}"/>'
    # the condition, stronger with level
    if group == "sand":
        n = int(16 + 90 * level)
        o += specks(rng, 0, 0, w, h, n, color="#A89C82")
    elif group == "wind":
        n = 1 + int(5 * level)
        for i in range(n):
            y = h * (i + .6) / (n + .2)
            a = rng.random() * 12
            b = w - rng.random() * 14
            o += f'<path d="M{a:.0f} {y:.1f}H{b:.0f}" stroke="#7C8187" stroke-width="1"/>'
    elif group == "humidity":
        n = int(5 + 34 * level)
        for _ in range(n):
            cx, cy = rng.random() * w, rng.random() * h
            o += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rng.choice([.9, 1.2, 1.6])}" fill="#8FA7B3"/>'
    elif group == "friction":
        n = 2 + int(8 * level)
        for i in range(n):
            x = (i + .5) * (w + h) / n
            o += f'<path d="M{x:.0f} 0L{x - h:.0f} {h}" stroke="#A9B6BC" stroke-width="1"/>'
    elif group == "heat":
        n = 2 + int(7 * level)
        for i in range(n):
            x = (i + .5) * w / n
            y = 8 + rng.random() * 22
            o += f'<path d="M{x:.0f} {y:.0f}v12" stroke="#A89C82" stroke-width="1"/>'
    # mullion
    if group == "mullion":
        t = 2 + 6 * level
        off = 3 * level
        o += f'<rect x="{mx - t / 2:.1f}" y="0" width="{t:.1f}" height="{h * .5:.0f}" fill="{MULL}"/>'
        o += f'<rect x="{mx - t / 2 + off:.1f}" y="{h * .5:.0f}" width="{t:.1f}" height="{h * .5 + 1:.0f}" fill="{MULL}"/>'
    else:
        o += f'<rect x="{mx - 1}" y="0" width="2" height="{h}" fill="{MULL}"/>'
    o += rob
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block">{o}</svg>'

# ---------- app 2 ----------

GROUPS = {
    "sand": ("Sandstorm", "Adds seal leak, friction, sensor noise", [
        "Light dust on the seal, 8 m/s wind", "Dust on the seal, 12 m/s wind", "Dust on the seal, 15 m/s wind",
        "Dust on the seal, 18 m/s wind", "Heavy dust on the seal, 18 m/s", "Dust on the camera, 14 m/s wind",
        "Dust on wet glass, 10 m/s wind", "Full storm front, 24 m/s wind"]),
    "wind": ("High-floor wind", "Adds side load and peel at the seal", [
        "Steady 14 m/s on floor 40", "Steady 18 m/s on floor 62", "Steady 22 m/s on floor 80",
        "Updraft along the face, 9 m/s", "Gust hits during a turn", "Gust hits at a pane edge",
        "Side wind pulls the tether taut", "Gust from 15 to 25 m/s in 2 s", "Corner vortex at the tower edge"]),
    "humidity": ("Humidity", "Adds a water film under the tracks", [
        "Salt haze off the Gulf", "Evening fog on cool glass", "Drying streaks, patchy grip",
        "Wash water left by the robot", "Wet lower half of the pane", "Dawn condensation, 90% humidity"]),
    "friction": ("Low friction", "Lowers the track grip coefficient", [
        "Worn tracks on clean glass", "Grip 0.40, fresh coating", "Grip 0.30, soap film",
        "Worn tracks on wet glass", "Grip 0.25, soap and dew", "Grip 0.20, oily residue"]),
    "mullion": ("Odd mullion edges", "Changes seal contact at each crossing", [
        "Crooked joint, 3 degree skew", "Sunken joint, 12 mm gap", "Silicone bead across the seal",
        "Panes out of plane by 8 mm", "Raised mullion, 18 mm lip", "Raised mullion, 30 mm lip",
        "Fin across the path, 40 mm"]),
    "heat": ("Heat", "Lowers air density and battery output", [
        "45 &deg;C, thin air, less suction", "50 &deg;C, battery output drops",
        "Glass at 70 &deg;C in full sun", "Seal goes soft at 60 &deg;C"]),
}

def group_block(key):
    name, chg, worlds = GROUPS[key]
    rows = "".join(f'<div style="height:27px;line-height:27px;white-space:nowrap">{w}</div>' for w in worlds)
    return f'''<div style="margin-bottom:20px"><div style="display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid {HAIR};padding-bottom:5px">
<span class="serif" style="font-size:21px;line-height:26px">{name}</span><span class="serif" style="font-size:21px;line-height:26px">{len(worlds)}</span></div>
<div class="small" style="margin:6px 0 3px;white-space:nowrap">{chg}</div>{rows}</div>'''

def app2():
    H = 900 - BAR_H
    strip_h = 168
    # the first test at half scale: one clean pane among dusty ones
    def state(c, f):
        return (5, 0) if c == 1 else "film"
    fx = 352
    s = facade(fx, 0, 6, 1, state, RIGHT_W, strip_h, pw=120, ph=168, sp=40, speck_n=80, mw=2)
    rx = fx + 120 + 96
    ry = 16
    rob = f'<path d="M{rx + 12} {ry}V0" stroke="{INK}" stroke-width="1"/>' + robot(rx, ry, 24)
    svg = f'<svg class="a" style="left:0;top:0" width="{RIGHT_W}" height="{strip_h}" viewBox="0 0 {RIGHT_W} {strip_h}">{s}{rob}</svg>'
    summary = f'''<div class="a" style="left:32px;top:18px;width:300px">
<div class="serif" style="font-size:24px;line-height:30px">First test held</div>
<div style="margin-top:6px">One pane in 6 min 12 s.</div>
<div>Lowest suction 16.2 kPa, limit 11.</div>
<div style="margin-top:12px"><span class="lnk">Replay the recorded run</span></div></div>'''
    left_col = group_block("sand") + group_block("heat")
    mid_col = group_block("wind") + group_block("friction")
    right_col = group_block("humidity") + group_block("mullion")
    lst = f'''<div class="a" style="left:32px;top:{strip_h + 14}px;width:{RIGHT_W - 64}px;display:flex;justify-content:space-between;align-items:baseline">
<div class="serif" style="font-size:30px;line-height:38px">The 40 worlds</div>
<div class="t2">Same robot, same code in each. Physics changes, not the script.</div></div>
<div class="a" style="left:32px;top:{strip_h + 66}px;width:{RIGHT_W - 64}px;display:grid;grid-template-columns:1fr 1fr 1fr;column-gap:34px">
<div>{left_col}<div class="small" style="margin-top:6px;width:280px">Weather effects are simplified models. Hand-built physics, not checked against real hardware.</div></div><div>{mid_col}</div><div>{right_col}</div></div>'''
    right = f'''<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{svg}{summary}{lst}</div>'''

    not_tested = ["Sand wearing the seal over months", "Bird strike on the robot", "Tether snag on a maintenance cradle", "Sensor drift on real hardware"]
    nt = "".join(f'<div style="border-top:1px solid {HAIR};height:31px;line-height:30px;white-space:nowrap">{x}</div>' for x in not_tested)
    chat = f'''<div class="chat">
<div class="m you" style="top:20px;font-size:22px;line-height:30px">Test it once and let me watch.</div>
<div class="m" style="top:58px">It held for the whole pane. Next I worked out what could go wrong for this robot here.</div>
</div>'''
    # the card sits on the same line as the top of the list and opens into it
    cy = BAR_H + strip_h
    ch = 136
    card = f'''<div class="a" style="left:20px;top:{cy}px;width:{CHAT_W - 20 + 1}px;height:{ch}px;background:#fff;border:1px solid {INK};border-right:0;border-radius:8px 0 0 8px;z-index:3">
<div class="serif" style="position:absolute;left:11px;top:12px;font-size:27px;line-height:34px">Test this on 40 worlds</div>
<div class="t2" style="position:absolute;left:11px;top:46px;white-space:nowrap">About 3 minutes on this Mac.</div>
<div style="position:absolute;left:11px;top:84px;display:flex;gap:10px"><span class="btn pri">Run the 40 worlds</span><span class="btn sec">See the 40 worlds</span></div></div>
<div class="a" style="left:{CHAT_W}px;top:{cy}px;width:{RIGHT_W}px;height:1px;background:{INK};z-index:3"></div>'''
    why_top = cy + ch + 16
    why = f'''<div class="m" style="top:{why_top}px"><div class="who">Why 40, from the scenario agent</div>
<div style="margin-top:2px">I read this chat and your robot&rsquo;s limits. Six risks came up for this height in Dubai. I raised each one until one more level changed nothing in a quick check. That came to 40.</div></div>'''
    ntop = why_top + 18 + 2 + 96 + 18
    nt_block = f'''<div class="m" style="top:{ntop}px">
<div style="display:flex;justify-content:space-between;align-items:baseline"><span class="serif" style="font-size:21px;line-height:26px">Not tested</span><span class="small">I can&rsquo;t model these, so no pass</span></div>
<div style="margin-top:6px">{nt}<div style="border-top:1px solid {HAIR}"></div></div>
<div style="margin-top:12px;display:flex;align-items:center;gap:14px"><span class="btn sec">Send to a bounty</span><span class="small" style="white-space:nowrap">Pays per new valid failure</span></div></div>'''
    body = bar(["World", "40 worlds", "Code"], "40 worlds") + right + chat + card + why + nt_block + f'<div class="chat" style="pointer-events:none">{composer("Change the robot or the world", "This tower, this robot")}</div>'
    (OUT / "app-2.html").write_text(page("Forty worlds", body))

# ---------- app 3 ----------

FAILS = {"sand": {3, 4, 5, 6, 7}, "wind": {7, 8}, "humidity": {5}, "friction": {5}, "mullion": {5, 6}, "heat": set()}
ORDER = ["heat", "humidity", "friction", "wind", "mullion", "sand"]

def replay_svg(W, H):
    """One pane at the moment the robot lost grip."""
    def state(c, f):
        if f == 0 and c == 0:
            return "clean"
        if f == 0 and c == 1:
            return (2, .42)
        return "film"
    fx = -150
    oy = -40
    s = facade(fx, oy, 3, 2, state, W, H, seed=21, speck_n=260)
    p = fx + 240
    lane = 48
    top_rx = p + 2 * lane
    stop_y = oy + 320 * .42
    drop_y = oy + 320 + 80 - 66
    p3 = p + 240
    label = 'font-family="-apple-system,Helvetica Neue,Arial,sans-serif" font-size="13"'
    # where it lost grip
    s += f'<rect x="{top_rx}" y="{stop_y - 4}" width="48" height="48" fill="none" stroke="{INK}" stroke-width="1" stroke-dasharray="3 3"/>'
    # the slide
    s += f'<path d="M{top_rx + 24} {stop_y + 44}V{drop_y}" stroke="{FAIL}" stroke-width="2"/>'
    # the tether, taut, pulled off line by the wind
    s += f'<path d="M{top_rx + 24} {drop_y + 24}L{top_rx - 14} 0" stroke="{INK}" stroke-width="1.25"/>'
    s += robot(top_rx, drop_y, 48, color=FAIL)
    # the gust, on the next pane, blowing toward the robot
    s += f'<text x="{p3 + 14}" y="34" {label} fill="{INK}">Gust 18 m/s</text>'
    for i in range(4):
        y = 50 + i * 14
        a = W - 12 - (i * 37 % 26)
        b = p3 + 14 + (i * 53 % 30)
        s += f'<path d="M{a} {y}H{b}M{b + 6} {y - 3}L{b} {y}L{b + 6} {y + 3}" fill="none" stroke="{INK}" stroke-width="1"/>'
    # notes with leaders across to the dusty pane
    gy = stop_y + 20
    s += f'<path d="M{top_rx + 48} {gy}H{p3 + 10}" stroke="{FAIL}" stroke-width="1"/><text x="{p3 + 14}" y="{gy + 4.5}" {label} fill="{FAIL}" font-weight="500">Grip lost, 4:12</text>'
    ry = drop_y + 24
    s += f'<path d="M{top_rx + 48} {ry}H{p3 + 10}" stroke="{FAIL}" stroke-width="1"/><text x="{p3 + 14}" y="{ry + 4.5}" {label} fill="{FAIL}" font-weight="500">Slid 1.4 m</text>'
    return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" style="display:block">{s}</svg>'

def app3():
    H = 900 - BAR_H
    head = f'''<div class="a" style="left:32px;top:14px;width:{RIGHT_W - 64}px;display:flex;justify-content:space-between;align-items:baseline">
<div class="serif" style="font-size:30px;line-height:38px">11 of 40 worlds failed</div>
<div class="t2">Simulated. In each row, worlds get harder to the right.</div></div>'''
    grid_top = 62
    tw, th, gap = 76, 50, 6
    lab_w = 134
    rows = ""
    open_x = open_y = None
    for ri, key in enumerate(ORDER):
        name, _, worlds = GROUPS[key]
        y = grid_top + ri * (th + gap)
        short = {"mullion": "Mullion edges"}.get(key, name)
        rows += f'<div class="a serif" style="left:32px;top:{y}px;width:{lab_w}px;line-height:{th}px;font-size:17px;white-space:nowrap">{short}</div>'
        n = len(worlds)
        f_n = len(FAILS[key])
        for i in range(n):
            level = (i + 1) / n
            st = "fail" if i in FAILS[key] else "pass"
            is_open = key == "sand" and i == 3
            if is_open:
                st = "open"
                open_x, open_y = 32 + lab_w + i * (tw + gap), y
            x = 32 + lab_w + i * (tw + gap)
            ring = f"box-shadow:inset 0 0 0 1px {HAIR}" if st == "pass" else f"box-shadow:inset 0 0 0 2px {FAIL}"
            cover = f'<div class="a" style="left:0;top:0;width:{tw}px;height:{th}px;{ring}"></div>'
            extra = f'<div class="a" style="left:0;top:{th - 4}px;width:{tw}px;height:4px;background:{FAIL}"></div>' if is_open else ""
            rows += f'<div class="a" style="left:{x}px;top:{y}px;width:{tw}px;height:{th}px">{tile(key, level, st, tw, th)}{cover}{extra}</div>'
        cx = 32 + lab_w + 9 * (tw + gap) + 2
        col = FAIL if f_n else TXT3
        rows += f'<div class="a" style="left:{cx}px;top:{y}px;line-height:{th}px;font-size:14px;color:{col};white-space:nowrap">{f_n} of {n}</div>'
    grid_bottom = grid_top + 6 * (th + gap) - gap

    low_top = grid_bottom + 16
    rep_x = open_x + tw // 2
    rep_w = RIGHT_W - rep_x - 32
    rep_h = H - low_top - 66
    leader = f'<div class="a" style="left:{rep_x}px;top:{open_y + th}px;width:1px;height:{low_top - open_y - th}px;background:{FAIL};z-index:2"></div>'
    replay = f'''<div class="a" style="left:{rep_x}px;top:{low_top}px;width:{rep_w}px;height:{rep_h}px;overflow:hidden">{replay_svg(rep_w, rep_h)}<div class="a" style="left:0;top:0;width:{rep_w}px;height:{rep_h}px;box-shadow:inset 0 0 0 1px {INK}"></div></div>'''
    sc_y = low_top + rep_h + 12
    total = 254.0
    pw = rep_w - 198 - 118
    # the scrubber is the suction trace itself: flat, then under the limit at the end
    th_ = 36
    lo, hi = 6.0, 20.0
    def px(t):
        return t / total * pw
    def py(v):
        return th_ - 1 - (v - lo) / (hi - lo) * (th_ - 2)
    pts = [(0, 18.4), (60, 18.3), (120, 18.0), (161, 17.2), (200, 16.6), (240, 16.0), (247, 14.1), (249, 12.0), (250.2, 11.0)]
    below = [(250.2, 11.0), (251, 9.0), (252, 7.2)]
    d1 = "M" + "L".join(f"{px(t):.1f} {py(v):.1f}" for t, v in pts)
    d2 = "M" + "L".join(f"{px(t):.1f} {py(v):.1f}" for t, v in below)
    tr = f'<svg width="{pw}" height="{th_}" style="display:block" viewBox="0 0 {pw} {th_}">'
    tr += f'<path d="M0 {py(11):.1f}H{pw}" stroke="#9EA2A7" stroke-width="1" stroke-dasharray="2 3"/>'
    tr += f'<path d="{d1}" fill="none" stroke="{INK}" stroke-width="1.25"/><path d="{d2}" fill="none" stroke="{FAIL}" stroke-width="2"/>'
    tr += f'<path d="M{px(252):.1f} 0V{th_}" stroke="{INK}" stroke-width="1"/></svg>'
    scrub = f'''<div class="a" style="left:{rep_x}px;top:{sc_y}px"><span class="btn sec">Replay the recorded run</span></div>
<div class="a" style="left:{rep_x + 198}px;top:{sc_y}px">{tr}</div>
<div class="a small" style="left:{rep_x + 198 + pw + 10}px;top:{sc_y}px;white-space:nowrap;color:{INK}">4:12 of 4:14<br><span style="color:{TXT3}">Suction, limit 11</span></div>'''

    tl_w = rep_x - 32 - 22
    tl_top = low_top
    events = [
        ("2:41", "Dust builds on the seal. Leak reaches 6%.", INK),
        ("4:07", "Gust of 18 m/s. The fan adds only 2% per tick.", INK),
        ("4:09", "The seal lifts while crossing a mullion.", INK),
        ("4:11", "Suction falls to 9.0 kPa. The limit is 11.", FAIL),
        ("4:12", "Grip lost. It slides 1.4 m.", FAIL),
        ("4:14", "The tether holds. The run ends.", INK),
    ]
    evs = ""
    ey = tl_top + 62
    EH = 52
    ev_ys = {}
    for i, (t, txt, c) in enumerate(events):
        y = ey + i * EH
        ev_ys[t] = y
        evs += f'<div class="a" style="left:32px;top:{y}px;width:{tl_w}px;height:1px;background:{HAIR}"></div>'
        evs += f'<div class="a" style="left:32px;top:{y + 14}px;width:44px;color:{c}">{t}</div>'
        evs += f'<div class="a" style="left:78px;top:{y + 14}px;width:{tl_w - 46}px;color:{c};white-space:nowrap">{txt}</div>'
    evs += f'<div class="a" style="left:32px;top:{ey + len(events) * EH}px;width:{tl_w}px;height:1px;background:{HAIR}"></div>'
    tl_head = f'''<div class="a" style="left:32px;top:{tl_top}px;width:{tl_w}px"><div class="serif" style="font-size:21px;line-height:26px">Sandstorm, world 4</div><div class="t2" style="white-space:nowrap">Dust on the seal, 18 m/s wind</div></div>'''

    right = f'<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{head}{rows}{leader}{replay}{scrub}{tl_head}{evs}</div>'

    counts = [("8", "Seal leak in a gust", "5 sandstorm, 2 wind, 1 mullion"),
              ("2", "Tracks slip on wet glass", "1 humidity, 1 low friction"),
              ("1", "Seal catches on a raised lip", "1 mullion")]
    ctab = ""
    for n, a, b in counts:
        ctab += f'''<div style="display:flex;border-top:1px solid {HAIR};height:58px;align-items:center"><div class="serif" style="width:34px;font-size:24px;color:{FAIL}">{n}</div><div style="line-height:21px"><div>{a}</div><div class="small">{b}</div></div></div>'''

    line_h = 22
    link_y = ev_ys["4:07"] + BAR_H + 26   # window y of the red trace, centred on the 4:07 row
    code_top = link_y - 26 - line_h - line_h // 2
    chat = f'''<div class="chat">
<div class="m t2" style="top:14px">All 40 ran in 3 min 20 s.</div>
<div class="m you" style="top:50px;font-size:22px;line-height:30px">Why did they fail?</div>
<div class="m" style="top:88px">11 of 40 failed and 29 held. Heat broke nothing. One cause explains 8 of the 11: dust opens a small leak at the seal, then a gust arrives.</div>
<div class="m" style="top:172px">{ctab}<div style="border-top:1px solid {HAIR}"></div></div>
<div class="m" style="top:{172 + 174 + 16}px">The fan can add only 2% per tick. A gust takes suction down faster than that. Here is the line.</div>
</div>'''
    cc = f'''<div class="a" style="left:32px;top:{code_top}px;width:{CHAT_W - 64}px;z-index:3">
<div style="height:26px;display:flex;justify-content:space-between;align-items:center"><span class="code t2">control/suction.py</span><span class="small">Runs at 4:07 in the replay</span></div>
<div class="code" style="line-height:{line_h}px;color:{TXT2};white-space:pre"><span style="color:{TXT3}"> 87 </span> error = target_kpa - suction_kpa</div>
<div class="code" style="line-height:{line_h}px;color:{INK};white-space:pre;box-shadow:inset 2px 0 0 {FAIL}"><span style="color:{TXT3}"> 88 </span> fan += 0.02 * error</div>
<div class="code" style="line-height:{line_h}px;color:{TXT2};white-space:pre"><span style="color:{TXT3}"> 89 </span> fan = min(fan, FAN_MAX)</div>
</div>'''
    red = f'<div class="a" style="left:{32 + 196}px;top:{link_y}px;width:{CHAT_W + 28 - 228}px;height:1px;background:{FAIL};z-index:4"></div>'
    act_top = code_top + 26 + line_h * 3 + 10
    actions = f'''<div class="a" style="left:32px;top:{act_top}px;display:flex;gap:16px;align-items:center;z-index:3"><span class="btn pri">Try a fix</span><span class="small" style="color:{TXT2};white-space:nowrap">Reruns the 11 failed worlds first</span></div>'''
    b_top = act_top + 36 + 14
    b_block = f'''<div class="a" style="left:32px;top:{b_top}px;width:{CHAT_W - 64}px">
<div style="display:flex;justify-content:space-between;align-items:baseline;border-top:1px solid {HAIR};padding-top:7px"><span class="serif" style="font-size:18px;line-height:24px">Bounty open on 4 gaps</span><span class="small">Sample data</span></div>
<div style="display:flex;justify-content:space-between;margin-top:2px"><span class="small" style="color:{TXT2}">6 worlds sent in</span><span class="small" style="color:{TXT2}">2 new valid failures</span><span class="small" style="color:{TXT2}">$500 paid</span></div></div>'''
    (OUT / "app-3.html").write_text(page("Forty results", bar(["World", "40 worlds", "Code"], "40 worlds") + right + chat + cc + red + actions + b_block + f'<div class="chat" style="pointer-events:none">{composer("Ask about a failure or change the code", "Sandstorm, world 4")}</div>'))
    return code_top, b_top, ev_ys

if __name__ == "__main__":
    app1()
    app2()
    print(app3())
