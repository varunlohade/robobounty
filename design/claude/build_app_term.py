#!/usr/bin/env python3
"""Builds app-3-term.html: app-3-dark with a terminal-style agent log on the left. Output is static HTML and SVG."""
import random
import zlib
from pathlib import Path

OUT = Path(__file__).parent

INK = "#FFFFFF"
TXT2 = "#D2D2D2"
TXT3 = "#ABABAB"
HAIR = "#404040"
ACC = "#FFFFFF"
FAIL = "#FF5247"
GLASS = "#0B0B0B"
GLINE = "#333333"
LANE = "#3A3A3A"
FILM = "#404040"
SPECK = "#5E5E5E"
SPAN = "#1C1C1C"
MULL = "#BDBDBD"
CITY = "#262626"
CITY2 = "#3A3A3A"

CHAT_W = 400
RIGHT_W = 1440 - CHAT_W
BAR_H = 64
STATUS_H = 24
CHAPTER_H = 54
PANE_H = 900 - BAR_H - STATUS_H - CHAPTER_H
SERIF = 'Palatino, "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif'

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:1440px;height:900px;background:#000;overflow:hidden}}
body{{position:relative;color:{INK};font:400 16px/24px -apple-system,"SF Pro Text","Helvetica Neue",Arial,sans-serif;
 -webkit-font-smoothing:auto;font-variant-numeric:tabular-nums lining-nums}}
.a{{position:absolute}}
.serif{{font-family:{SERIF}}}
code,.code{{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:13px}}
.small{{font-size:14px;line-height:20px;color:{TXT3}}}
.t2{{color:{TXT2}}}
.fail{{color:{FAIL}}}

/* window bar */
.bar{{position:absolute;left:0;top:0;width:1440px;height:{BAR_H}px;background:#000;z-index:5}}
.title{{position:absolute;left:0;top:0;width:1440px;height:30px;border-bottom:1px solid #2A2A2A;text-align:center;line-height:29px;font-size:13px;color:{TXT2}}}
.lights{{position:absolute;left:12px;top:9px;display:flex;gap:7px}}
.lights i{{display:block;width:11px;height:11px;border-radius:50%;background:#4A4A4A}}
.brand{{position:absolute;left:76px;top:0;line-height:29px;font-family:{SERIF};font-size:15px;color:#FFF}}
.lhead{{position:absolute;left:0;top:30px;width:{CHAT_W}px;height:34px;border-bottom:1px solid #2A2A2A;display:flex;align-items:center;justify-content:space-between;padding:0 12px 0 14px;font-size:13px;color:#FFF;font-weight:500}}
.tabs{{position:absolute;left:{CHAT_W + 1}px;top:30px;width:{RIGHT_W - 1}px;height:34px;display:flex;background:#111;border-bottom:1px solid #2A2A2A;font-size:13px;color:{TXT3}}}
.tabs span{{line-height:33px;height:34px;display:flex;align-items:center;gap:8px;padding:0 14px;border-right:1px solid #2A2A2A}}
.tabs .on{{color:#FFF;background:#000}}
.status{{position:absolute;left:0;top:{900 - STATUS_H}px;width:1440px;height:{STATUS_H}px;background:#111;border-top:1px solid #2A2A2A;display:flex;gap:18px;align-items:center;padding:0 14px;font-size:13px;color:{TXT2};z-index:5;white-space:nowrap}}
.status .r{{margin-left:auto}}
.pb{{position:absolute;display:flex;align-items:center;gap:12px;padding:0 14px;background:#000;border-top:1px solid #2A2A2A;font-size:13px;color:{TXT2};white-space:nowrap;z-index:3}}
.pb .tr{{flex:1;position:relative;height:12px}}
.div{{position:absolute;left:{CHAT_W}px;top:{BAR_H}px;width:1px;height:{PANE_H}px;background:{HAIR};z-index:1}}

/* chat */
.chat{{position:absolute;left:0;top:{BAR_H}px;width:{CHAT_W}px;height:{PANE_H}px}}
.m{{position:absolute;left:32px;width:{CHAT_W - 64}px}}
.you{{font-family:{SERIF};color:{INK}}}
.who{{font-size:14px;line-height:20px;color:{TXT3}}}
.btn{{display:inline-flex;align-items:center;height:36px;padding:0 14px;border-radius:6px;font-size:14px;font-weight:500;white-space:nowrap}}
.pri{{background:{ACC};color:#000}}
.sec{{border:1px solid {INK};color:{INK}}}
.lnk{{color:{INK};font-size:14px;font-weight:500;border-bottom:1px solid {INK};line-height:20px;white-space:nowrap}}
.composer{{position:absolute;left:20px;width:{CHAT_W - 40}px;top:{PANE_H - 92}px;height:76px;border:1px solid #8A8A8A;border-radius:10px;background:#000}}
.composer .ph{{position:absolute;left:14px;top:10px;font-family:{SERIF};font-size:17px;color:{TXT3}}}
.composer .ctx{{position:absolute;left:14px;bottom:9px;font-size:13px;color:{TXT3}}}
.composer .go{{position:absolute;right:9px;bottom:9px;width:28px;height:28px;border-radius:6px;background:{INK}}}
.rule{{position:absolute;height:1px;background:{HAIR}}}
.row{{display:flex;justify-content:space-between;border-top:1px solid {HAIR}}}
.chap{{position:absolute;left:0;top:{900 - STATUS_H - CHAPTER_H}px;width:1440px;height:{CHAPTER_H}px;background:#000;border-top:1px solid #2A2A2A;z-index:5}}
.chap .tk{{position:absolute;top:14px;width:1px;height:9px;background:#8A8A8A}}
.chap .lb{{position:absolute;top:26px;font-size:14px;line-height:20px;color:#ABABAB;white-space:nowrap}}
.tm{{position:absolute;left:0;top:{BAR_H}px;width:{CHAT_W}px;height:{PANE_H}px;font:400 13px/19px "SF Mono",ui-monospace,Menlo,monospace;color:#E6E6E6;overflow:hidden}}
.tm *{{font-family:"SF Mono",ui-monospace,Menlo,monospace}}
.tlog{{position:absolute;left:14px;right:14px;top:0;bottom:90px;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;gap:9px}}
.tlog>*{{flex:none}}
.tool{{background:#171717;border-left:2px solid #8A8A8A;padding:6px 8px 7px 9px;color:#BDBDBD;word-break:break-all}}
.tool b{{display:flex;justify-content:space-between;color:#FFF;font-weight:600;word-break:normal}}
.tool b i{{font-style:normal;font-weight:400;color:#ABABAB}}
.you2{{background:#EDEDED;color:#000;padding:6px 9px;font-weight:500}}
.tcard{{border:1px solid #6A6A6A;padding:8px 9px}}
.tcard h4{{font-weight:600;color:#FFF;font-size:13px;line-height:19px}}
.tb{{display:inline-block;height:26px;line-height:24px;padding:0 9px;border:1px solid #8A8A8A;color:#FFF;font-size:13px;white-space:nowrap}}
.tb.w{{background:#FFF;border-color:#FFF;color:#000;font-weight:500}}
.tdf{{border:1px solid #4A4A4A}}
.tdf .h{{height:28px;display:flex;align-items:center;justify-content:space-between;padding:0 3px 0 9px;background:#171717;border-bottom:1px solid #333;color:#D2D2D2;white-space:nowrap}}
.tdf .l{{height:20px;line-height:20px;padding-left:8px;white-space:pre;color:#ABABAB}}
.tdf .l.ad{{background:#2A2A2A;color:#FFF}}
.tdf .l.d{{color:{FAIL}}}
.tbot{{position:absolute;left:14px;right:14px;bottom:6px;height:78px}}
.wk{{display:flex;align-items:center;gap:8px;color:#ABABAB;height:19px;white-space:nowrap}}
.wk u{{flex:1;height:1px;background:#4A4A4A;display:block}}
.cur{{height:25px;display:flex;align-items:center;gap:8px;color:#FFF;border-bottom:1px solid #4A4A4A}}
.cur i{{display:block;width:8px;height:15px;background:#FFF}}
/* side panel: compact editor-style chat */
.sp{{position:absolute;left:0;top:{BAR_H}px;width:{CHAT_W}px;height:{PANE_H}px;font-size:14px;line-height:20px;color:{TXT2}}}
.flow{{position:absolute;left:14px;right:14px;top:10px}}
.ub{{background:#1E1E1E;border:1px solid #2E2E2E;border-radius:6px;padding:6px 10px;color:#FFF;margin-bottom:8px}}
.st{{height:24px;display:flex;align-items:center;gap:6px;font-size:13px;color:{TXT3};white-space:nowrap}}
.st b{{font-weight:500;color:{TXT2}}}
.st em{{font-style:normal;margin-left:auto}}
.p{{margin:6px 0 8px}}
.dff{{border:1px solid #363636;border-radius:6px;overflow:hidden;background:#0D0D0D}}
.dfh{{height:28px;padding:0 4px 0 10px;display:flex;align-items:center;gap:8px;background:#161616;border-bottom:1px solid #2A2A2A;font-size:13px;color:{TXT3}}}
.dfh code{{font-size:12px;color:{TXT2}}}
.dfh .sp2{{margin-left:auto;display:flex;gap:4px}}
.b{{height:20px;line-height:18px;padding:0 8px;border-radius:4px;font-size:12px;font-weight:500;border:1px solid #6A6A6A;color:{INK};white-space:nowrap;display:inline-block}}
.b.w{{background:{INK};border-color:{INK};color:#000}}
.b2{{height:28px;line-height:26px;padding:0 10px;border-radius:5px;font-size:13px;font-weight:500;border:1px solid #6A6A6A;color:{INK};white-space:nowrap;display:inline-block}}
.b2.w{{background:{INK};border-color:{INK};color:#000}}
.ln{{height:20px;line-height:20px;font-family:"SF Mono",ui-monospace,Menlo,monospace;font-size:12px;color:{TXT3};white-space:pre;padding-left:8px}}
.ln.add{{background:#262626;color:#FFF}}
.ln.bad{{color:{FAIL}}}
.crd{{border:1px solid #4A4A4A;border-radius:7px;background:#111;padding:9px 10px}}
.crd h4{{font-size:14px;line-height:20px;font-weight:600;color:#FFF}}
.nt{{font-size:13px;line-height:18px;color:{TXT2}}}
.inp{{position:absolute;left:10px;right:10px;bottom:10px;height:84px;border:1px solid #4A4A4A;border-radius:12px;background:#141414}}
.inp .ph{{position:absolute;left:12px;top:9px;font-size:14px;color:{TXT3}}}
.inp .ag{{position:absolute;left:8px;bottom:8px;height:24px;padding:0 8px;border-radius:6px;background:#262626;font-size:13px;line-height:24px;color:{TXT2};display:flex;align-items:center;gap:5px}}
.inp .ctx{{position:absolute;left:88px;bottom:8px;line-height:24px;font-size:13px;color:{TXT3};white-space:nowrap}}
.inp .go{{position:absolute;right:8px;bottom:8px;width:26px;height:26px;border-radius:50%;background:{INK}}}
"""

def page(title, body):
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>\n'

def bar(tabs, active, status):
    x = '<svg width="8" height="8" viewBox="0 0 8 8"><path d="M1 1L7 7M7 1L1 7" stroke="#ABABAB" stroke-width="1"/></svg>'
    t = "".join(f'<span class="on">{n} {x}</span>' if n == active else f'<span>{n}</span>' for n in tabs)
    plus = '<svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1V11M1 6H11" stroke="#ABABAB" stroke-width="1.2"/></svg>'
    return f'''<div class="bar"><div class="title">Window robot, Dubai towers</div><div class="lights"><i></i><i></i><i></i></div><div class="brand">CrashLab</div>
<div class="lhead"><span>Chat</span>{plus}</div><div class="tabs">{t}</div></div><div class="div"></div>
<div class="status"><span>Simulated</span><span>Sample data</span><span>Hand-built physics, not checked against real hardware</span><span class="r">{status}</span></div>'''

def playback(left, top, width, height, now, total, marks=()):
    """Standard transport: back, play, forward, scrubber, time, speed."""
    ic = lambda p: f'<svg width="14" height="14" viewBox="0 0 14 14" style="flex:none"><path d="{p}" fill="#FFF"/></svg>'
    back = ic("M2 2H4V12H2ZM12 2V12L5 7Z")
    play = ic("M3 1.5V12.5L12 7Z")
    fwd = ic("M10 2H12V12H10ZM2 2V12L9 7Z")
    f = now / total * 100
    ms = "".join(f'<i style="position:absolute;left:{t / total * 100:.1f}%;top:1px;width:2px;height:10px;background:{c}"></i>' for t, c in marks)
    def clock(v):
        return f"{v // 60}:{v % 60:02d}"
    return f'''<div class="pb" style="left:{left}px;top:{top}px;width:{width}px;height:{height}px">{back}{play}{fwd}
<div class="tr"><i style="position:absolute;left:0;right:0;top:5px;height:2px;background:#404040"></i><i style="position:absolute;left:0;width:{f:.1f}%;top:5px;height:2px;background:#FFF"></i>{ms}<i style="position:absolute;left:{f:.1f}%;top:1px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:#FFF"></i></div>
<span>{clock(now)} / {clock(total)}</span><span>1x</span></div>'''

CHEV_R = '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M3.5 1.5L7 5L3.5 8.5" fill="none" stroke="#ABABAB" stroke-width="1.3"/></svg>'
CHEV_D = '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M1.5 3.5L5 7L8.5 3.5" fill="none" stroke="#ABABAB" stroke-width="1.3"/></svg>'

def step(label, meta="", opened=False):
    return f'<div class="st">{CHEV_D if opened else CHEV_R}<b>{label}</b><em>{meta}</em></div>'

def chapters(active):
    names = ["Brief", "Worlds", "Test", "Find", "Fix", "Bounty"]
    x0, x1 = 64, 1280
    step_x = (x1 - x0) / (len(names) - 1)
    at = names.index(active)
    o = '<div class="chap">'
    o += '<svg class="a" style="left:22px;top:15px" width="18" height="20" viewBox="0 0 18 20"><path d="M3 2V18L16 10Z" fill="#FFF"/></svg>'
    o += f'<div class="a" style="left:{x0}px;top:18px;width:{x1 - x0}px;height:2px;background:#404040"></div>'
    o += f'<div class="a" style="left:{x0}px;top:18px;width:{step_x * at:.0f}px;height:2px;background:#FFF"></div>'
    for i, n in enumerate(names):
        x = x0 + i * step_x
        on = n == active
        col = "#FFF" if i <= at else "#ABABAB"
        o += f'<div class="tk" style="left:{x:.0f}px;background:{col}"></div>'
        o += f'<div class="lb" style="left:{x:.0f}px;color:{col};font-weight:{600 if on else 400}">{n}</div>'
    o += f'<div class="a" style="right:24px;top:14px;font-size:14px;line-height:24px;color:#D2D2D2;white-space:nowrap">Step {at + 1} of {len(names)}</div></div>'
    return o

def composer(ph, ctx):
    arrow = '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M13 19V8M8.5 12.5L13 8L17.5 12.5" fill="none" stroke="#000" stroke-width="1.7"/></svg>'
    chev = '<svg width="8" height="8" viewBox="0 0 10 10"><path d="M1.5 3.5L5 7L8.5 3.5" fill="none" stroke="#D2D2D2" stroke-width="1.5"/></svg>'
    return f'<div class="inp"><div class="ph">{ph}</div><div class="ag">Agent {chev}</div><div class="ctx">{ctx}</div><div class="go">{arrow}</div></div>'

def diff_box(fname, stat, lines, accept=True):
    btn = '<span class="sp2"><span class="b">Reject</span><span class="b w">Accept</span></span>' if accept else ""
    return f'<div class="dff"><div class="dfh"><code>{fname}</code><span>{stat}</span>{btn}</div>{"".join(lines)}</div>'

def model_note():
    return (f'<div class="nt" style="white-space:nowrap"><span style="color:{INK};font-weight:500">Included in this model:</span> wind, suction, grip, water</div>'
            f'<div class="nt" style="white-space:nowrap"><span style="color:{INK};font-weight:500">Outside this model:</span> sand, heat, real hardware</div>')

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
    inner = "#000"
    o = f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{s * .07:.1f}" fill="{color}"/>'
    # tracks with cleats
    for tx in (x + s * .05, x + s - s * .05 - tr):
        o += f'<rect x="{tx:.1f}" y="{y + s * .06:.1f}" width="{tr:.1f}" height="{s * .88:.1f}" fill="#7A7A7A"/>'
        n = 7
        for i in range(n):
            cy = y + s * .1 + i * (s * .8 / (n - 1))
            o += f'<rect x="{tx:.1f}" y="{cy - .5:.1f}" width="{tr:.1f}" height="1" fill="#000"/>'
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
        o += f'<rect x="{ox}" y="{fy + ph + sp - 2}" width="{W - ox}" height="2" fill="#3A3A3A"/>'
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
    H = PANE_H - 40

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
    air = wind_lines(36, fx - 14, 480, 556, 3)
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

    rows_chat = [("Wind", ""), ("Suction", ""), ("Grip", "")]
    y_lines = [f'<div class="ln add">+ {t}</div>' for t in ["pane_m: [2.4, 3.2]", "floor: 62          # 248 m up", "robot_m: 0.48      # square, one tether", "wind_ms: 11        # gusts to 15", "hold_kpa: 1.2", "track_friction: 0.62"]]
    chat = f'''<div class="sp"><div class="flow">
<div class="ub">I&rsquo;m building a window-cleaning robot for towers in Dubai.</div>
{step("Read robot model", "1 file")}
{step("Built world", "2 files", True)}
<div class="p">I set up one bay of a tower with your robot on the glass.</div>
{diff_box("world/tower.yaml", "+42", y_lines)}
<div style="height:6px"></div>
{step("Started live run")}
<div class="p">It is running on the right now. Tell me if the height or the glass is wrong.</div>
<div style="margin:10px 0 14px;display:flex;gap:8px"><span class="b2 w">Test it once</span><span class="b2">Open the code</span></div>
{model_note()}
</div>{composer("Change the robot or the world", "tower.yaml")}</div>'''
    # shared rows: the setting in the chat runs on into the live reading
    y0 = 262
    shared = ""
    live = {
        "Wind": ("11.2", "m/s", spark([9.8, 10.4, 10.1, 11.6, 12.9, 11.8, 10.9, 11.4, 12.2, 11.2, 10.6, 11.2], 96, 22)),
        "Suction": ("2.4", "kPa", spark([2.5, 2.48, 2.5, 2.42, 2.33, 2.4, 2.44, 2.42, 2.36, 2.38, 2.42, 2.4], 96, 22)),
        "Grip": ("0.62", "&mu;", spark([.63, .63, .62, .62, .64, .63, .61, .62, .63, .62, .62, .62], 96, 22, lo=.5, hi=.7)),
    }
    rule_end = CHAT_W + fx - 2
    y0 = 394
    for i, (k, v) in enumerate(rows_chat):
        y = y0 + i * ROW_H
        shared += f'<div class="a" style="left:{CHAT_W}px;top:{y}px;height:1px;width:{rule_end - CHAT_W}px;background:{HAIR};z-index:2"></div>'
        val, unit, sp = live[k]
        shared += f'<div class="a small" style="left:{CHAT_W + 28}px;top:{y + 13}px;color:{TXT2}">{k}</div>'
        shared += f'<div class="a serif" style="left:{CHAT_W + 92}px;top:{y + 7}px;font-size:24px;line-height:30px;white-space:nowrap">{val}<span style="font-family:-apple-system,sans-serif;font-size:14px;color:{TXT3};margin-left:5px">{unit}</span></div>'
        shared += f'<div class="a" style="left:{CHAT_W + 198}px;top:{y + 11}px">{sp}</div>'
    last = y0 + 3 * ROW_H
    shared += f'<div class="a" style="left:{CHAT_W}px;top:{last}px;height:1px;width:{rule_end - CHAT_W}px;background:{HAIR};z-index:2"></div>'
    label_y = y0 - 26
    shared += f'<div class="a small" style="left:{CHAT_W + 28}px;top:{label_y}px;color:{TXT2}">Live, 0:42 into the run</div>'

    after = ''

    right = f'<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{svg}</div>'
    fine = ''
    pb = playback(CHAT_W + 1, BAR_H + H, RIGHT_W - 1, 40, 42, 372)
    body = bar(["World", "tower.yaml"], "World", "Floor 62, 248 m") + pb + right + chat + shared + after + fine
    (OUT / "app-1-dark.html").write_text(page("World set up", body))

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
        o += specks(rng, 0, 0, w, h, n, color="#C4C4C4")
    elif group == "wind":
        n = 1 + int(5 * level)
        for i in range(n):
            y = h * (i + .6) / (n + .2)
            a = rng.random() * 12
            b = w - rng.random() * 14
            o += f'<path d="M{a:.0f} {y:.1f}H{b:.0f}" stroke="#D0D0D0" stroke-width="1"/>'
    elif group == "humidity":
        n = int(5 + 34 * level)
        for _ in range(n):
            cx, cy = rng.random() * w, rng.random() * h
            o += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rng.choice([.9, 1.2, 1.6])}" fill="#D0D0D0"/>'
    elif group == "friction":
        n = 2 + int(8 * level)
        for i in range(n):
            x = (i + .5) * (w + h) / n
            o += f'<path d="M{x:.0f} 0L{x - h:.0f} {h}" stroke="#A8A8A8" stroke-width="1"/>'
    elif group == "heat":
        n = 2 + int(7 * level)
        for i in range(n):
            x = (i + .5) * w / n
            y = 8 + rng.random() * 22
            o += f'<path d="M{x:.0f} {y:.0f}v12" stroke="#C4C4C4" stroke-width="1"/>'
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
    nt = key in ("sand", "heat")
    if nt:
        chg = "Not tested yet"
    nt_style = f"color:{INK};font-weight:500" if nt else ""
    wc = TXT3 if nt else INK
    rows = "".join(f'<div style="height:27px;line-height:27px;white-space:nowrap;color:{wc}">{w}</div>' for w in worlds)
    return f'''<div style="margin-bottom:20px"><div style="display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid {HAIR};padding-bottom:5px">
<span class="serif" style="font-size:21px;line-height:26px">{name}</span><span class="serif" style="font-size:21px;line-height:26px">{len(worlds)}</span></div>
<div class="small" style="margin:5px 0 2px;white-space:nowrap;{nt_style}">{chg}</div>{rows}</div>'''

def app2():
    H = PANE_H
    strip_h = 130
    sim_h = 96
    # the first test at half scale: one clean pane among dusty ones
    def state(c, f):
        return (5, 0) if c == 1 else "film"
    fx = 352
    s = facade(fx, 0, 6, 1, state, RIGHT_W, sim_h, pw=120, ph=96, sp=40, speck_n=50, mw=2)
    rx = fx + 120 + 96
    ry = 8
    rob = f'<path d="M{rx + 12} {ry}V0" stroke="{INK}" stroke-width="1"/>' + robot(rx, ry, 24)
    svg = f'<svg class="a" style="left:0;top:0" width="{RIGHT_W}" height="{sim_h}" viewBox="0 0 {RIGHT_W} {sim_h}">{s}{rob}</svg>'
    summary = f'''<div class="a" style="left:32px;top:12px;width:310px">
<div class="serif" style="font-size:24px;line-height:30px;color:#FFF">First test held</div>
<div style="margin-top:4px;white-space:nowrap">Lowest suction 2.1 kPa, limit 1.2.</div></div>'''
    left_col = group_block("sand") + group_block("heat")
    mid_col = group_block("wind") + group_block("friction")
    right_col = group_block("humidity") + group_block("mullion")
    lst = f'''<div class="a" style="left:32px;top:{strip_h + 14}px;width:{RIGHT_W - 64}px;display:flex;justify-content:space-between;align-items:baseline">
<div class="serif" style="font-size:30px;line-height:38px">The 40 worlds</div>
<div class="t2">Same robot, same code in each. Physics changes, not the script.</div></div>
<div class="a" style="left:32px;top:{strip_h + 66}px;width:{RIGHT_W - 64}px;display:grid;grid-template-columns:1fr 1fr 1fr;column-gap:34px">
<div>{left_col}<div style="margin-top:4px">{model_note()}</div></div><div>{mid_col}</div><div>{right_col}</div></div>'''
    right = f'''<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{svg}{summary}{lst}</div>''' + playback(CHAT_W + 1, BAR_H + sim_h, RIGHT_W - 1, 34, 372, 372) + f'<div class="a" style="left:{CHAT_W + 1}px;top:{BAR_H + strip_h}px;width:{RIGHT_W - 1}px;height:1px;background:#2A2A2A;z-index:3"></div>'

    not_tested = ["Sand wearing the seal over months", "Bird strike on the robot", "Tether snag on a maintenance cradle", "Sensor drift on real hardware"]
    nt = "".join(f'<div style="height:22px;line-height:22px;font-size:13px;white-space:nowrap;color:{TXT2}">{x}</div>' for x in not_tested)
    chat = f'''<div class="sp"><div class="flow">
<div class="ub">Test it once and let me watch.</div>
{step("Ran 1 test", "Simulated")}
<div class="p">It held for the whole pane. Next I worked out what could go wrong here.</div>
<div class="crd" style="margin:10px 0"><h4 style="font-size:15px">Test this on 40 worlds</h4>
<div class="nt" style="margin-top:1px">28 ready. 12 not tested yet: sand and heat.</div>
<div style="margin-top:8px;display:flex;gap:6px"><span class="b2 w">Run the 28 ready</span><span class="b2">See the 40 worlds</span></div></div>
{step("Scenario agent: why 40", "1 step", True)}
<div class="p" style="margin-top:2px">I read this chat and your robot&rsquo;s limits. Six risks came up for this height in Dubai. I raised each one until one more level changed nothing in a quick check. That came to 40.</div>
{step("Read physics assumptions", "PARAMETERS.md")}
<div class="crd" style="margin-top:10px"><h4>Not tested</h4><div class="nt" style="color:{TXT3};margin-bottom:4px">I can&rsquo;t model these, so they get no pass.</div>{nt}
<div style="margin-top:8px;display:flex;align-items:center;gap:10px"><span class="b2">Send to a bounty</span><span class="nt" style="color:{TXT3}">Pays per new valid failure</span></div></div>
</div>{composer("Change the robot or the world", "This tower, this robot")}</div>'''
    card = why = nt_block = ""
    body = bar(["World", "40 worlds", "tower.yaml"], "40 worlds", "40 worlds, 28 ready, 12 not tested yet") + right + chat + card + why + nt_block
    (OUT / "app-2-dark.html").write_text(page("Forty worlds", body))

# ---------- app 3 ----------

FAILS = {"sand": set(), "wind": {7, 8}, "humidity": {5}, "friction": {5}, "mullion": {5, 6}, "heat": set()}
NOT_TESTED = {"sand", "heat"}
ORDER = ["heat", "sand", "humidity", "friction", "mullion", "wind"]

def replay_svg(W, H):
    """One pane at the moment the robot lost grip."""
    def state(c, f):
        if f == 0 and c == 0:
            return "clean"
        if f == 0 and c == 1:
            return (2, .42)
        return "film"
    fx = -150
    oy = -80
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
    s += f'<text x="{p3 + 14}" y="22" {label} fill="{INK}">Gust 25 m/s</text>'
    for i in range(3):
        y = 32 + i * 11
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
    H = PANE_H
    head = f'''<div class="a" style="left:32px;top:14px;width:{RIGHT_W - 64}px;display:flex;justify-content:space-between;align-items:baseline">
<div class="serif" style="font-size:30px;line-height:38px">6 of 28 tested worlds failed</div>
<div class="t2">Simulated. Sample data. Worlds get harder to the right.</div></div>'''
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
        if key in NOT_TESTED:
            rows += f'<div class="a" style="right:32px;top:{y}px;line-height:{th}px;font-size:14px;font-weight:500;white-space:nowrap">Not tested yet</div>'
        for i in range(n):
            level = (i + 1) / n
            st = "fail" if i in FAILS[key] else "pass"
            is_open = key == "wind" and i == 7
            if is_open:
                st = "open"
                open_x, open_y = 32 + lab_w + i * (tw + gap), y
            x = 32 + lab_w + i * (tw + gap)
            if key in NOT_TESTED:
                rows += f'<svg class="a" style="left:{x}px;top:{y}px" width="{tw}" height="{th}"><rect x=".5" y=".5" width="{tw - 1}" height="{th - 1}" fill="none" stroke="#8A8A8A" stroke-dasharray="3 3"/></svg>'
                continue
            ring = f"box-shadow:inset 0 0 0 1px {HAIR}" if st == "pass" else f"box-shadow:inset 0 0 0 2px {FAIL}"
            cover = f'<div class="a" style="left:0;top:0;width:{tw}px;height:{th}px;{ring}"></div>'
            extra = f'<div class="a" style="left:0;top:{th - 4}px;width:{tw}px;height:4px;background:{FAIL}"></div>' if is_open else ""
            rows += f'<div class="a" style="left:{x}px;top:{y}px;width:{tw}px;height:{th}px">{tile(key, level, st, tw, th)}{cover}{extra}</div>'
        cx = 32 + lab_w + 9 * (tw + gap) + 2
        col = FAIL if f_n else TXT3
        if key not in NOT_TESTED:
            rows += f'<div class="a" style="left:{cx}px;top:{y}px;line-height:{th}px;font-size:14px;color:{col};white-space:nowrap">{f_n} of {n}</div>'
    grid_bottom = grid_top + 6 * (th + gap) - gap

    low_top = grid_bottom + 16
    rep_x = 450
    rep_w = RIGHT_W - rep_x - 32
    rep_h = H - low_top - 44
    leader = ''
    replay = f'''<div class="a" style="left:{rep_x}px;top:{low_top}px;width:{rep_w}px;height:{rep_h}px;overflow:hidden">{replay_svg(rep_w, rep_h)}<div class="a" style="left:0;top:0;width:{rep_w}px;height:{rep_h}px;box-shadow:inset 0 0 0 1px {INK}"></div></div>'''
    sc_y = low_top + rep_h
    scrub = ""
    pb = playback(CHAT_W + rep_x, BAR_H + sc_y, rep_w, 38, 252, 254, [(247, "#FFF"), (251, FAIL), (252, FAIL)])

    tl_w = rep_x - 32 - 22
    tl_top = low_top
    events = [
        ("2:41", "Steady wind. Suction holds at 2.4 kPa.", INK),
        ("4:07", "25 m/s gust. Fan adds 2% a tick.", INK),
        ("4:09", "The seal lifts while crossing a mullion.", INK),
        ("4:11", "Suction falls to 0.9 kPa. The limit is 1.2.", FAIL),
        ("4:12", "Grip lost. It slides 1.4 m.", FAIL),
        ("4:14", "The tether holds. The run ends.", INK),
    ]
    evs = ""
    ey = tl_top + 62
    EH = 46
    ev_ys = {}
    for i, (t, txt, c) in enumerate(events):
        y = ey + i * EH
        ev_ys[t] = y
        evs += f'<div class="a" style="left:32px;top:{y}px;width:{tl_w}px;height:1px;background:{HAIR}"></div>'
        evs += f'<div class="a" style="left:32px;top:{y + 11}px;width:44px;color:{c}">{t}</div>'
        evs += f'<div class="a" style="left:78px;top:{y + 11}px;width:{tl_w - 46}px;color:{c};white-space:nowrap">{txt}</div>'
        if t == "4:07":
            evs += f'<div class="a code" style="right:{RIGHT_W - 32 - tl_w}px;top:{y + 12}px;font-size:12px;color:#FFF;text-decoration:underline">suction.py:88</div>'
    evs += f'<div class="a" style="left:32px;top:{ey + len(events) * EH}px;width:{tl_w}px;height:1px;background:{HAIR}"></div>'
    tl_head = f'''<div class="a" style="left:32px;top:{tl_top}px;width:{tl_w}px"><div class="serif" style="font-size:21px;line-height:26px">High-floor wind, world 8</div><div class="t2" style="white-space:nowrap">Gust from 15 to 25 m/s in 2 s</div></div>
<div class="a" style="right:{RIGHT_W - 32 - tl_w}px;top:{tl_top + 26}px"><span class="b2">Replay the recorded run</span></div>'''

    right = f'<div class="a" style="left:{CHAT_W}px;top:{BAR_H}px;width:{RIGHT_W}px;height:{H}px;overflow:hidden">{head}{rows}{leader}{replay}{scrub}{tl_head}{evs}</div>'

    counts = [("3", "Seal peels in a gust", "2 wind, 1 mullion"),
              ("2", "Tracks slip on wet glass", "1 humidity, 1 friction"),
              ("1", "Seal catches on a raised lip", "1 mullion")]
    ctab = ""
    for n, a, b in counts:
        ctab += f'''<div style="display:flex;height:26px;align-items:center;font-size:14px;white-space:nowrap"><span style="width:20px;color:{FAIL};font-weight:600">{n}</span><span style="color:#FFF">{a}</span><span class="nt" style="margin-left:auto;color:{TXT3}">{b}</span></div>'''
    lines = ['<div class="ln"> 87  error = target_kpa - suction_kpa</div>',
             '<div class="ln bad">-88  fan += 0.02 * error</div>',
             '<div class="ln add">+88  fan += 0.02 * error + gust_feedforward(wind)</div>',
             '<div class="ln"> 89  fan = min(fan, FAN_MAX)</div>']
    chat = f'''<div class="tm"><div class="tlog">
<div class="tool"><b>build_world <i>ok</i></b>{{"world":"tower_bay","steady_wind_ms":11,"suction_pa":2400}}</div>
<div class="tcard"><h4>Test this on 40 worlds</h4><div style="color:#D2D2D2">28 ready. 12 not tested yet.</div>
<div style="margin-top:6px;display:flex;gap:6px"><span class="tb">See the 40 worlds</span></div></div>
<div class="tool"><b>run_trials <i>sample data</i></b>{{"n":28,"passed":22,"failed":6}}
<div style="height:5px"></div>{{"trial":"wind_08","passed":false,"failure":"detach","min_pressure_pa":900,"slip_m":1.4,"coverage":0.42}}</div>
<div class="you2">&gt; why did they fail?</div>
<div style="color:#FFF">3 of 6: a gust peels the seal. The fan adds only 2% per tick, too slow to hold suction.</div>
<div class="tdf"><div class="h"><span>control/suction.py +1 &minus;1</span><span style="display:flex;gap:3px"><span class="b">Reject</span><span class="b w">Accept</span></span></div>
<div class="l"> 87  error = target_kpa - suction_kpa</div><div class="l d">-88  fan += 0.02 * error</div><div class="l ad">+88  fan += 0.02 * error + gust_ff(wind)</div><div class="l"> 89  fan = min(fan, FAN_MAX)</div></div>
<div style="display:flex;align-items:center;gap:10px"><span class="tb w">Try a fix</span><span style="color:#D2D2D2;white-space:nowrap">reruns the 6 failed</span></div>
<div class="tcard"><div style="display:flex;justify-content:space-between;align-items:center"><h4>Bounty on 4 gaps</h4><span class="tb">Send to a bounty</span></div><div style="color:#D2D2D2;margin-top:4px;white-space:nowrap">6 sent in, 2 new valid failures (sample)</div></div>
<div style="color:#D2D2D2"><span style="color:#FFF">Included in this model:</span> wind, suction, grip, water<br><span style="color:#FFF">Outside this model:</span> sand, heat, real hardware</div>
</div><div class="tbot"><div class="wk"><span>replaying wind_08</span><u></u></div><div class="cur">&gt; <i></i></div>
<div style="margin-top:6px;display:flex;justify-content:space-between;color:#ABABAB;white-space:nowrap"><span>~/towers/window-robot</span><span>context 18% (sample)</span></div></div></div>'''
    cc = red = actions = b_block = ""
    (OUT / "app-3-term.html").write_text(page("Forty results", bar(["World", "40 worlds", "suction.py"], "40 worlds", "6 failed, 22 held, 12 not tested yet") + chapters("Find") + right + pb + chat + cc + red + actions + b_block))
    return ev_ys

if __name__ == "__main__":
    print(app3())
