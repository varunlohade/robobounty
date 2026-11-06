import random, math
from pro_lib import *

# ---------- data
TYPES = {"Suction loss":"--f-suc","Slip distance":"--f-slip","Edge detach":"--f-edge","Tether slack":"--f-teth"}
W = [
 # id, reason, group, status, type, metric
 ("w01","Calm reference, floor 12","Wind","Passed","", "Suction 13.9 kPa"),
 ("w02","Steady wind, 8 m/s","Wind","Held back","", "Not run"),
 ("w03","Dust on seal, light haze","Sand and dust","Flaky","", "1 of 8 repeats"),
 ("w04","Condensation, 92% humidity","Wet and humid","Failed","Slip distance","Slip 0.41 m"),
 ("w05","Gust front, 18 m/s from the side","Wind","Failed","Suction loss","Suction 6.8 kPa"),
 ("w06","Hot facade, 48 °C, thin air","Heat","Failed","Suction loss","Suction 7.4 kPa"),
 ("w07","Water film after rain","Wet and humid","Failed","Slip distance","Slip 0.63 m"),
 ("w08","Mullion edge, 40 mm step","Edges","Failed","Edge detach","Lift 11 mm"),
 ("w09","Corner panel, 60 mm step","Edges","Failed","Edge detach","Lift 19 mm"),
 ("w10","Low friction coating, μ 0.31","Surface","Held back","", "Not run"),
 ("w11","Fine sand film on glass","Sand and dust","Failed","Slip distance","Slip 0.37 m"),
 ("w12","Battery heat, 44 °C","Heat","Passed","", "Suction 12.1 kPa"),
 ("w13","Crosswind at floor 80, 22 m/s","Wind","Failed","Tether slack","Slack 1.4 m"),
 ("w14","Sandstorm: dust on seal, 18 m/s","Sand and dust","Failed","Suction loss","Suction 3.1 kPa"),
 ("w15","Humid night, 88%, no wind","Wet and humid","Held back","", "Not run"),
 ("w16","Wet glass under gusts, 14 m/s","Wet and humid","Failed","Slip distance","Slip 0.52 m"),
 ("w17","Sealant ridge, 12 mm","Edges","Flaky","", "2 of 8 repeats"),
 ("w18","Hot glass after sun, 52 °C","Heat","Failed","Suction loss","Suction 7.1 kPa"),
]
GROUPS = [("Wind",12),("Sand and dust",10),("Wet and humid",11),("Heat",7),("Edges",8),("Surface",4)]
# heat map: mild to harsh. S=suction, L=slip, E=edge, T=tether, P=pass, H=held, F=flaky
HM = {
 "Wind":          "PHHSHTSSTSST",
 "Sand and dust": "FHLSHSLSSX",
 "Wet and humid": "HLHFLLHLLSL",
 "Heat":          "PHSFHSS",
 "Edges":         "HFEHEEEE",
 "Surface":       "PFLH",
}
cnt={}
for v in HM.values():
    for c in v: cnt[c]=cnt.get(c,0)+1
cnt["S"]=cnt.get("S",0)+cnt.pop("X",0)
# must match the given values
assert cnt=={"S":14,"L":9,"E":5,"T":3,"H":13,"F":5,"P":3}, cnt
print(cnt)

def status_badge(s):
    return {"Failed":bdg("Failed","r","x"),"Passed":bdg("Passed","g","check"),"Held back":bdg("Held back","n","lock"),"Flaky":bdg("Flaky","a","shuffle")}[s]

def line_path(fn, t0, t1, x0, x1, y0, y1, v0, v1, n=240):
    pts=[]
    for i in range(n+1):
        t=t0+(t1-t0)*i/n
        v=fn(t)
        pts.append((x0+(x1-x0)*(t-t0)/(t1-t0), y1-(y1-y0)*(v-v0)/(v1-v0)))
    return pth(pts)

# ---------- pro-1
def pro1():
    rnd=random.Random(7)
    c = chat(
      U("Window robot for towers in Dubai. It cleans glass on high floors.")+
      steps([("check","Built world","Floor 62"),("check","Looked at the scene","3 views"),("check","Wrote requirements","6"),("check","Ran 1 test","Passed")])+
      A("The robot finished one normal run. Suction stayed above the 8 kPa hold limit, even in both gusts.","Does the scene look right?")+
      U("Looks right. What could go wrong up there?")+
      steps([("check","Read this conversation"),("check","Worked out what could go wrong","52 worlds")])+
      A("Sandstorms, strong wind at height, wet glass and hard edges all change the physics here. I would test all of them.")+
      f'''<div class="card"><div class="card-h"><span class="t14 m grow">Test this on 52 worlds</span>{bdg("Needs approval","ac")}</div>
      <div class="card-b">{kv("Worlds to run","39")}{kv("Held back to check fixes","13")}{kv("Control runs","10")}{kv("Requirements","6")}{kv("Expected compute",'<span class="smp">Sample</span>&nbsp; 4 min')}</div>
      <div class="card-f"><span class="btn btn-p">Approve and run</span><span class="btn btn-s">See the 52 worlds</span></div>
      <div class="linkrow">{ic("circle-slash")}<span>7 things not tested</span>{ic("chevron-right")}</div></div>''')

    # timeline signals
    def suction(t):
        g = sum(1.6*math.exp(-((t-a)/3.0)**2) for a in (33,93))
        return 14.1-g+0.12*math.sin(t*1.7)+0.08*math.sin(t*4.3)
    def wind(t):
        g = sum(6.0*(1 if a<=t<=a+6 else 0)*min(1,(t-a)/1.2,(a+6-t)/1.2) for a in (30,90))
        return 8+g+0.5*math.sin(t*.9)+0.3*math.sin(t*2.7)
    tw=796; lab=88; pw=tw-lab-12
    X=lambda t: lab+pw*t/120
    ticks=""
    for t in range(0,121,10):
        x=X(t); major=t%30==0
        ticks+=f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{16 if major else 18}" y2="20" stroke="#4B515B"/>'
        if major: ticks+=f'<text x="{x:.1f}" y="12" text-anchor="{"start" if t==0 else "end" if t==120 else "middle"}" class="tx">{t//60}:{t%60:02d}</text>'
    tracks=[("Events",20),("Suction",48),("Wind",76)]
    grid="".join(f'<line x1="0" x2="{tw}" y1="{y+28}" y2="{y+28}" stroke="rgba(255,255,255,.07)"/>' for _,y in tracks)
    labels="".join(f'<text x="12" y="{y+18}" class="lb">{n}</text>' for n,y in tracks)
    sp=line_path(suction,0,120,X(0),X(120),48+4,48+24,12,14.6)
    wp=line_path(wind,0,120,X(0),X(120),76+5,76+24,4,16)
    lim_y=48+24
    # events
    ev=""
    for t,l in [(0,"Start"),(30,"Gust"),(47,"Panel edge"),(90,"Gust"),(112,"Finish")]:
        x=X(t)
        ev+=f'<path d="M{x:.1f} 29 l5 5 -5 5 -5 -5z" fill="#A3A9B3"/>'+(f'<text x="{x-8:.1f}" y="38" text-anchor="end" class="tx">{l}</text>' if l=="Gust" else f'<text x="{x+8:.1f}" y="38" class="tx">{l}</text>')
    t_now=33.4; ph=X(t_now)
    # gust spans on wind
    spans="".join(f'<rect x="{X(a):.1f}" y="77" width="{X(a+6)-X(a):.1f}" height="27" fill="rgba(255,255,255,.05)"/>' for a in (30,90))
    timeline=f'''<svg width="{tw}" height="104" viewBox="0 0 {tw} 104" style="display:block"><style>.tx{{font:400 11px Inter;fill:#737A85;font-feature-settings:"tnum"}}.lb{{font:400 12px Inter;fill:#A3A9B3}}</style>
    {ticks}<line x1="0" x2="{tw}" y1="20" y2="20" stroke="rgba(255,255,255,.07)"/>{grid}{labels}{ev}{spans}
    <path d="{sp}" fill="none" stroke="#C9CED6" stroke-width="1.25"/><path d="{wp}" fill="none" stroke="#C9CED6" stroke-width="1.25"/>
    <line x1="{int(ph)+.5}" x2="{int(ph)+.5}" y1="4" y2="104" stroke="#3E7BFA" stroke-width="1"/><path d="M{ph-5:.1f} 0h10v6l-5 5-5-5z" fill="#3E7BFA"/>
    </svg>'''

    # viewport overlay
    wind_arrows=""
    for (x,y) in [(32,104),(84,232),(28,368),(96,488)]:
        wind_arrows+=f'<path d="M{x} {y} h44 m-6 -4 l6 4 -6 4" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round"/>'
    bx0,by0,bx1,by1=586,300,764,516
    s=14
    br=f'M{bx0} {by0+s}V{by0}H{bx0+s} M{bx1-s} {by0}H{bx1}V{by0+s} M{bx1} {by1-s}V{by1}H{bx1-s} M{bx0+s} {by1}H{bx0}V{by1-s}'
    gizmo='''<g transform="translate(36,588)" stroke-width="1.5" stroke-linecap="round"><line x1="0" y1="0" x2="22" y2="-8" stroke="#E5534B"/><line x1="0" y1="0" x2="0" y2="-24" stroke="#3FA66A"/><line x1="0" y1="0" x2="-14" y2="-12" stroke="#5089FB"/><text x="25" y="-5" font-family="Inter" font-size="11" fill="#E5534B" stroke="none">x</text><text x="-3" y="-27" font-family="Inter" font-size="11" fill="#3FA66A" stroke="none">z</text><text x="-24" y="-13" font-family="Inter" font-size="11" fill="#5089FB" stroke="none">y</text></g>'''
    w=f'''<div class="grow row" style="align-items:stretch;min-height:0">
    <div class="grow" style="display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line)">
      <div class="row gap8" style="height:40px;flex:none;padding:0 8px;border-bottom:1px solid var(--line);position:relative">
        <span class="sel">{ic("video")}Follow robot{ic("chevron-down",12)}</span>
        <span class="seg"><span class="on">Perspective</span><span>Front</span><span>Top</span></span>
        <div class="vr"></div>
        <span class="row gap4"><span class="ib on">{ic("mouse-pointer-2")}</span><span class="ib">{ic("move-3d")}</span><span class="ib">{ic("ruler")}</span></span>
        <div class="vr"></div>
        <span class="row gap4"><span class="ib hov">{ic("wind")}</span><span class="ib">{ic("grid-3x3")}</span><span class="ib">{ic("arrow-down-to-line")}</span></span>
        <span class="grow"></span>
        {bdg("Replay of recorded run","n","history")}
        <span class="ib">{ic("camera")}</span><span class="ib">{ic("maximize")}</span>
      </div>
      <div class="vp grow" style="min-height:0">
        <img src="pro-assets/render-still.jpg" style="height:620px;left:-170px;top:0" alt="Rendered window robot on a glass tower">
        <svg class="overlay" width="796" height="620" viewBox="0 0 796 620">{wind_arrows}<path d="{br}" fill="none" stroke="#7DA7FF" stroke-width="1.5"/>{gizmo}</svg>
        <div class="tooltip" style="left:397px;top:8px">Show wind vectors<kbd>W</kbd></div>
        <span class="vp-tag" style="left:{bx0}px;top:{by0-28}px">Robot, suction 12.6 kPa</span>
        <span class="vp-tag" style="left:12px;top:12px">Wind 14 m/s, gust</span>
        <span class="vp-tag" style="right:12px;bottom:12px">Frame 1002 of 3600</span>
      </div>
      <div style="flex:none;border-top:1px solid var(--line)">
        <div class="tl-bar"><span class="ib">{ic("skip-back")}</span><span class="ib">{ic("chevron-left")}</span><span class="play">{ic("pause")}</span><span class="ib">{ic("chevron-right")}</span><span class="ib">{ic("skip-forward")}</span>
          <span style="margin-left:8px" class="m">0:33.40</span><span class="c3">of 2:00.00</span><span class="grow"></span><span class="smp" style="margin-right:8px">Sample signals</span><span class="sel" style="height:24px;border-radius:4px">1×{ic("chevron-down",12)}</span><span class="ib s">{ic("repeat")}</span><span class="ib s">{ic("zoom-out")}</span><span class="ib s">{ic("zoom-in")}</span></div>
        {timeline}
      </div>
    </div>
    <div style="width:272px;flex:none;overflow:hidden;display:flex;flex-direction:column">
      <div class="ph"><span style="color:var(--t1)">Inspector</span><span class="sp"></span><span class="smp">Sample values</span></div>
      <div class="sec"><div class="sec-h">{ic("chevron-down",12)}World</div>
        {prop("Location","Dubai Marina",ro=1)}{prop("Building","Glass tower",ro=1)}{prop("Floor","62",ro=1)}{prop("Height","248","m",ro=1)}</div>
      <div class="sec"><div class="sec-h">{ic("chevron-down",12)}Weather</div>
        {prop("Wind","8.0","m/s",foc=1)}{prop("Gust","14.0","m/s")}{prop("Direction","20","°")}{prop("Temperature","41","°C")}{prop("Humidity","64","%")}{prop("Dust on seal","0.05")}</div>
      <div class="sec"><div class="sec-h">{ic("chevron-down",12)}Glass</div>
        {prop("Wetness","0.20")}{prop("Friction","0.62","μ")}{prop("Edge step","40","mm")}</div>
      <div class="sec" style="border:0"><div class="sec-h">{ic("chevron-down",12)}Robot</div>
        {prop("Suction","12.6","kPa",ro=1)}{prop("Hold limit","8.0","kPa")}{prop("Pump duty","72","%",ro=1)}{prop("Mass","6.4","kg")}{prop("Tether","12.0","m")}</div>
      <div class="sec" style="border-top:1px solid var(--line)"><div class="sec-h">{ic("chevron-right",12)}<span class="grow">Requirements</span><span class="c3" style="font-weight:400">6</span></div><div class="sec-h">{ic("chevron-right",12)}<span class="grow">Not tested</span><span class="c3" style="font-weight:400">7</span></div></div>
    </div></div>'''
    return shell("CrashLab: World","World",c,w)

def prop(k,v,u="",ro=0,foc=0):
    cl="val"+(" ro" if ro else "")+(" foc" if foc else "")
    return f'<div class="prop"><span>{k}</span><div class="{cl}"><span>{v}</span><i>{u}</i></div></div>'

# ---------- pro-2
def pro2():
    c=chat(
      steps([("check","Campaign approved","52 worlds")])+U("Run it, and tell me what broke.")+
      steps([("check","Ran 39 worlds","2 min 16 s"),("check","Ran controls","10 of 10"),("check","Re-ran each failure","8 times each"),("check","Grouped failures","4 types"),("loader","Trying a fix","Running","run")])+
      A("31 worlds failed, and four failure types explain all of them. Suction loss is the largest, with 14 worlds.","Controls passed 10 of 10, so the test setup holds. I excluded 5 flaky worlds because the failure did not repeat.")+
      f'''<div class="card"><div class="card-h"><span class="t14 m grow">Worst failure</span>{bdg("Failed","r","x")}</div>
      <div class="card-b">{kv("World","w14")}{kv("Cause","Suction loss")}{kv("Lowest suction","3.1 kPa")}{kv("Code line",'<span class="mono">controller.py:63</span>')}</div>
      <div class="card-f"><span class="btn btn-p">Open replay</span><span class="btn btn-s">Show in table</span></div></div>'''+
      f'''<div class="card"><div class="card-h"><span class="t14 m grow">7 things not tested</span></div>
      <div class="card-b c2">The code cannot model these, so none of them count as a pass. You can send them to a bounty.</div>
      <div class="card-f"><span class="btn btn-s">Send to a bounty</span><span class="btn btn-g">See the list</span></div></div>''',
      chips=("Test run",))
    # pipeline
    pl=[("Queued","52","d"),("Running","39 worlds","d"),("Reproducing","31 of 31","d"),("Diagnosing","4 types","d"),("Fixing","Fix 1","a"),("Validating","","p"),("Report","","p")]
    ps=""
    for i,(n,m,s) in enumerate(pl):
        icon={"d":f'<span style="color:var(--grn-t)">{ic("circle-check")}</span>',"a":f'<span style="color:var(--ac-t)">{ic("loader")}</span>',"p":f'<span style="color:var(--t4)">{ic("circle")}</span>'}[s]
        col={"d":"var(--t2)","a":"var(--t1)","p":"var(--t3)"}[s]
        ps+=f'<div class="row gap8 nowrap">{icon}<span style="color:{col}" class="{"m" if s=="a" else ""}">{n}</span><span class="t12 c3">{m}</span></div>'
        if i<len(pl)-1: ps+=f'<div class="grow" style="height:1px;background:var(--line2);min-width:8px"></div>'
    # stats
    tot=52
    stats=[("Worlds","52",""),("Failed","31",""),("Held back","13",""),("Flaky, excluded","5",""),("Passed","3",""),("Controls","10/10","")]
    st=""
    for i,(k,v,_) in enumerate(stats):
        st+=f'<div style="padding:0 16px;{"border-left:1px solid var(--line);" if i else "padding-left:12px;"}"><div class="t12 c2">{k}</div><div class="t20 m" style="margin-top:0">{v}</div></div>'
    segs=[(31,"var(--red)"),(13,"#3A3F48"),(5,"var(--amb)"),(3,"#C9CED6")]
    bar="".join(f'<div style="flex:{a};background:{b};height:4px;border-radius:2px"></div>' for a,b in segs)
    # table
    rows=""
    for r in W:
        sw=f'<span class="row gap8"><span class="sw" style="background:var({TYPES[r[4]]})"></span>{r[4]}</span>' if r[4] else '<span style="color:var(--t4)">None</span>'
        cls=" class=sel-r" if r[0]=="w14" else (" class=hov-r" if r[0]=="w08" else "")
        rows+=f'<tr{cls}><td class="p">{r[0]}</td><td class="p">{r[1]}</td><td>{r[2]}</td><td>{status_badge(r[3])}</td><td>{sw}</td><td class="num">{r[5]}</td></tr>'
    table=f'''<table class="tbl"><colgroup><col style="width:64px"><col><col style="width:112px"><col style="width:104px"><col style="width:116px"><col style="width:128px"></colgroup>
    <thead><tr><th class="sorted"><span class="row">World{ic("arrow-up",12)}</span></th><th>Reason</th><th>Group</th><th>Status</th><th>Failure type</th><th class="num">Key metric</th></tr></thead><tbody>{rows}</tbody></table>'''
    # heat map
    colors={"S":"#E2574C","X":"#E2574C","L":"#D3A017","E":"#14A39A","T":"#9A78F0","P":"#C9CED6","H":"#2A2F37"}
    cell=15;g=2;lw=92;px=12;rh=24
    hm=""
    y=0
    for gname,_ in GROUPS:
        s=HM[gname]
        hm+=f'<text x="0" y="{y+16}" font-family="Inter" font-size="12" fill="#A3A9B3">{gname}</text>'
        for i,ch in enumerate(s):
            x=lw+i*(cell+g)
            if ch=="F":
                hm+=f'<rect x="{x}" y="{y}" width="{cell}" height="{rh}" rx="2" fill="#2A2F37"/><path d="M{x+4} {y+16} L{x+11} {y+8}" stroke="#D69A2D" stroke-width="1.5" stroke-linecap="round"/>'
            else:
                hm+=f'<rect x="{x}" y="{y}" width="{cell}" height="{rh}" rx="2" fill="{colors[ch]}"/>'
            if gname=="Sand and dust" and ch=="X":
                hm+=f'<rect x="{x-1.5}" y="{y-1.5}" width="{cell+3}" height="{rh+3}" rx="3" fill="none" stroke="#ECEEF1" stroke-width="1.5"/>'
        y+=rh+g
    hmh=y-g
    def lg(col,t,flaky=False):
        return f'<span class="row gap4 nowrap"><span class="sw" style="background:{col}"></span>{t}</span>'
    types=[("Suction loss",14,"High","w14","controller.py:63"),("Slip distance",9,"High","w07","controller.py:112"),("Edge detach",5,"Medium","w09","planner.py:48"),("Tether slack",3,"Low","w13","winch.py:27")]
    tr=""
    for n,cn,sev,wo,li in types:
        tr+=f'<div style="padding:8px 12px;border-bottom:1px solid var(--line)"><div class="row gap8"><span class="sw" style="background:var({TYPES[n]})"></span><span class="grow">{n}</span><span class="m">{cn}</span></div><div class="row t12 c3" style="padding-left:16px;margin-top:0"><span class="grow">{sev}, worst {wo}</span><span class="mono" style="font-size:11px;color:var(--t3)">{li}</span></div></div>'
    w=f'''
    <div class="row gap8" style="height:44px;flex:none;padding:0 12px;border-bottom:1px solid var(--line)">{ps}</div>
    <div class="row" style="height:64px;flex:none;border-bottom:1px solid var(--line);position:relative">{st}<div class="grow"></div>
      <div style="width:256px;margin-right:12px"><div class="row t12 c3" style="justify-content:space-between;margin-bottom:4px"><span>Share of 52 worlds</span><span>60% failed</span></div><div class="row" style="gap:2px">{bar}</div></div></div>
    <div class="row gap8" style="height:44px;flex:none;padding:0 12px;border-bottom:1px solid var(--line)">
      <div class="inp focus" style="width:208px">{ic("search")}<span class="caret" style="margin:0 -7px 0 0"></span><span class="c3">Filter worlds</span></div>
      <span class="seg"><span class="on">All <b>52</b></span><span>Failed <b>31</b></span><span>Held <b>13</b></span><span>Flaky <b>5</b></span><span>Passed <b>3</b></span></span>
      <span class="sel"><span class="lb">Group</span>All{ic("chevron-down",12)}</span><span class="sel"><span class="lb">Type</span>All{ic("chevron-down",12)}</span>
      <span class="grow"></span><span class="btn btn-g">{ic("download")}Export</span>
    </div>
    <div class="grow row" style="align-items:stretch;min-height:0">
      <div class="grow" style="min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--line);overflow:hidden">{table}
        <div class="grow"></div><div class="row t12 c3" style="height:32px;flex:none;padding:0 12px;justify-content:space-between;background:var(--panel);border-top:1px solid var(--line);margin-top:-1px"><span>1 to 18 of 52 worlds. Reasons and metrics are sample.</span><span class="row gap4"><span class="ib s" style="color:var(--t4)">{ic("chevron-left")}</span><span class="ib s">{ic("chevron-right")}</span></span></div></div>
      <div style="width:320px;flex:none;display:flex;flex-direction:column;overflow:hidden">
        <div class="ph"><span style="color:var(--t1)">World map</span><span class="sp"></span><span class="smp">Sample layout</span></div>
        <div style="padding:12px 12px 8px"><div class="row t11 c3" style="padding-left:92px;width:296px;justify-content:space-between;margin-bottom:4px"><span>Mild</span><span>Harsh</span></div>
        <svg width="296" height="{hmh+4}" viewBox="0 -2 296 {hmh+4}">{hm}</svg>
        <div class="t12 c2" style="display:flex;flex-wrap:wrap;gap:4px 12px;margin-top:12px">{lg("#C9CED6","Passed")}{lg("#2A2F37","Held back")}<span class="row gap4 nowrap"><svg width="8" height="8" viewBox="0 0 8 8"><rect width="8" height="8" rx="2" fill="#2A2F37"/><path d="M2 6 6 2" stroke="#D69A2D" stroke-width="1.25"/></svg>Flaky</span><span class="c3">Colour shows failure type</span></div></div>
        <div class="ph" style="border-top:1px solid var(--line)"><span style="color:var(--t1)">Failure types</span><span class="sp"></span><span class="c3" style="font-weight:400">31 worlds</span></div>
        {tr}
        <div class="grow"></div>
        <div style="padding:8px 12px;border-top:1px solid var(--line)"><div class="row gap8" style="height:24px">{ic("shuffle",14,"c3")}<span class="grow c2">5 flaky worlds excluded</span>{ic("chevron-right",14,"c3")}</div><div class="row gap8" style="height:24px">{ic("circle-slash",14,"c3")}<span class="grow c2">7 things not tested</span>{ic("chevron-right",14,"c3")}</div></div>
      </div>
    </div>'''
    return shell("CrashLab: Test run","Test run",c,w)

# ---------- pro-3
def pro3():
    c=chat(
      steps([("check","Test run finished","31 failed")])+U("Why did it fall in the sandstorm world?")+
      steps([("check","Opened replay of w14"),("check","Re-ran the failure","8 of 8"),("check","Traced it to code",'<span class="mono">controller.py:63</span>'),("check","Tried a fix on fresh worlds","104")])+
      A("Dust raises the leak reading. The guard then stops the pump, and suction falls under the hold limit 2.5 s later.","Keeping the pump on a low duty helps. It also removes the guard, so you should decide.")+
      f'''<div class="card"><div class="card-h"><span class="t14 m grow">Fix for suction loss</span>{bdg("Not applied","n")}</div>
      <div class="card-b">{kv("Passes on 104 fresh worlds",'<span class="m">11 to 17</span>')}{kv("Worse","0")}{kv("Change",'<span class="mono">controller.py</span>&nbsp; <span style="color:var(--grn-t)">+1</span> <span style="color:var(--red-t)">−2</span>')}</div>
      <div class="note">{ic("triangle-alert")}<span>Removes a guard. The pump no longer stops on a high leak reading.</span></div>
      <div class="card-f" style="padding-top:12px"><span class="btn btn-p">Accept<kbd>⌘↵</kbd></span><span class="btn btn-s">Reject</span><span class="btn btn-g">Try another</span></div></div>'''+
      A("87 of the 104 worlds still fail with this fix. Slip distance is next, and it needs a different change.")+
      sugg("Try a fix for slip distance","Replay w14 with this fix","Send what is left to a bounty"),
      chips=("w14","controller.py"))
    # signals
    def suction(t):
        base=14.0-0.02*max(0,t-20)+0.10*math.sin(t*2.1)+0.06*math.sin(t*5.3)
        if t>38.7: base=2.6+(base-2.6)*math.exp(-(t-38.7)/1.75)
        return base
    def grip(t):
        v=100-0.25*max(0,t-20)+0.5*math.sin(t*1.3)
        if t>38.7: v=max(0,v-(t-38.7)*(v/3.9))
        return v
    W_=524; H=132; L=36; R=12;T=8;B=4
    t0,t1=36,46
    X=lambda t: L+(W_-L-R)*(t-t0)/(t1-t0)
    def chart(fn,vmax,lim,liml,unit,ytop,col="#C9CED6"):
        Y=lambda v: T+(H-T-B)*(1-v/vmax)
        gr=""
        for v in (0,vmax/2,vmax):
            gr+=f'<line x1="{L}" x2="{W_-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="rgba(255,255,255,.07)"/><text x="{L-8}" y="{Y(v)+4:.1f}" text-anchor="end" class="tx">{v:g}</text>'
        vx="".join(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{T}" y2="{H-B}" stroke="rgba(255,255,255,.04)"/>' for t in range(36,47,2))
        p=line_path(fn,t0,t1,X(t0),X(t1),T,H-B,0,vmax,n=300)
        lm=f'<line x1="{L}" x2="{W_-R}" y1="{Y(lim):.1f}" y2="{Y(lim):.1f}" stroke="#E5534B" stroke-width="1" stroke-dasharray="4 4"/><text x="{L+4}" y="{Y(lim)+13:.1f}" class="tx" style="fill:#F27B73">{liml}</text>' if lim else ""
        return f'<svg width="{W_}" height="{H}" viewBox="0 0 {W_} {H}"><style>.tx{{font:400 11px Inter;fill:#737A85;font-feature-settings:"tnum"}}</style>{gr}{vx}{lm}<path d="{p}" fill="none" stroke="{col}" stroke-width="1.5" stroke-linejoin="round"/>CUR</svg>'
    tn=41.2
    cur=lambda y1,y0,v,tx: f'<line x1="{int(X(tn))+.5}" x2="{int(X(tn))+.5}" y1="0" y2="{H}" stroke="#3E7BFA"/>'+ f'<circle cx="{X(tn):.1f}" cy="{y1:.1f}" r="3" fill="#3E7BFA" stroke="#111317" stroke-width="2"/>'
    sY=T+(H-T-B)*(1-suction(tn)/16); gY=T+(H-T-B)*(1-grip(tn)/100)
    ch1=chart(suction,16,8,"Hold limit 8 kPa","kPa",0).replace("CUR",cur(sY,0,0,0))
    ch2=chart(grip,100,0,"","%",0).replace("CUR",cur(gY,0,0,0))
    # x axis
    ax="".join(f'<text x="{X(t):.1f}" y="12" text-anchor="{"end" if t==46 else "middle"}" class="tx">{t} s</text>' for t in range(36,47,2))
    axis=f'<svg width="{W_}" height="16" viewBox="0 0 {W_} 16"><style>.tx{{font:400 11px Inter;fill:#737A85}}</style>{ax}</svg>'
    # event timeline
    TW=1068; TL=12; TR=12
    EX=lambda t: TL+(TW-TL-TR)*(t-t0)/(t1-t0)
    evs=[(37.0,"Dust on seal",0,"n"),(38.7,"Guard stops pump",0,"a"),(41.2,"Under hold limit",0,"r"),(42.6,"Grip lost",0,"r"),(44.1,"Tether catch",0,"r")]
    e=""
    colr={"n":"#A3A9B3","a":"#D69A2D","r":"#E5534B"}
    for t,l,lane,k in evs:
        x=EX(t)
        e+=f'<path d="M{x:.1f} 38 l5 5 -5 5 -5 -5z" fill="{colr[k]}" stroke="#111317" stroke-width="1"/><text x="{x+8:.1f}" y="47" font-family="Inter" font-size="12" fill="{"#ECEEF1" if k!="n" else "#A3A9B3"}">{l}</text>'
    tk=""
    for i in range(0,21):
        x=EX(36+i*.5); mj=i%4==0
        tk+=f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{70 if mj else 72}" y2="76" stroke="#4B515B"/>'
    # overview of the whole run, with the zoom window
    OX=lambda t: TL+(TW-TL-TR)*t/60
    ov=f'<rect x="{TL}" y="8" width="{TW-TL-TR}" height="8" rx="2" fill="#1E2228"/><rect x="{OX(36):.1f}" y="8" width="{OX(46)-OX(36):.1f}" height="8" fill="#3A3F48"/>'
    for t,col in [(12,"#A3A9B3"),(24,"#A3A9B3"),(37.0,"#A3A9B3"),(38.7,"#D69A2D"),(41.2,"#E5534B"),(42.6,"#E5534B"),(44.1,"#E5534B")]:
        ov+=f'<rect x="{OX(t)-1:.1f}" y="8" width="2" height="8" fill="{col}"/>'
    ph=EX(tn)
    et=f'<svg width="{TW}" height="76" viewBox="0 0 {TW} 76">{ov}<line x1="0" x2="{TW}" y1="24" y2="24" stroke="rgba(255,255,255,.07)"/><rect x="{EX(38.7):.1f}" y="54" width="{EX(44.1)-EX(38.7):.1f}" height="2" fill="#E5534B"/>{e}{tk}<line x1="{int(ph)+.5}" x2="{int(ph)+.5}" y1="24" y2="76" stroke="#3E7BFA"/><path d="M{ph-5:.1f} 24h10v6l-5 5-5-5z" fill="#3E7BFA"/>'+"".join(f'<text x="{EX(t):.1f}" y="68" text-anchor="{"start" if t==36 else "end" if t==46 else "middle"}" font-family="Inter" font-size="11" fill="#737A85">{t} s</text>' for t in range(36,47,2))+'</svg>'
    # diff
    def cl(a,b,g,code,k=""):
        return f'<div class="cl {k}"><span class="n">{a}</span><span class="n">{b}</span><span class="g">{g}</span><span>{code}</span></div>'
    K=lambda s:f'<span class="k">{s}</span>'; F=lambda s:f'<span class="fn">{s}</span>'; N=lambda s:f'<span class="nu">{s}</span>'; C=lambda s:f'<span class="cm">{s}</span>'; S=lambda s:f'<span class="se">{s}</span>'
    diff="".join([
      cl(59,59,"",f'{K("class")} {F("PumpController")}:'),
      cl(60,60,"",f'    {K("def")} {F("update_pump")}({S("self")}, obs):'),
      cl(61,61,"",f'        target = {S("self")}.cfg.target_kpa'),
      cl(62,62,"",f'        duty = {S("self")}.pid.{F("step")}(target, obs.suction_kpa)'),
      '<div class="lens">'+ic("flag",12)+'Failure traced here: w14 at 38.7 s. Guard sets duty to zero.</div>',
      cl(63,"","−",f'        {K("if")} obs.seal_leak &gt; {S("self")}.cfg.max_leak:',"del"),
      cl(64,"","−",f'            duty = {N("0.0")}  {C("# stop pump on leak")}',"del"),
      cl("",63,"+",f'        duty = {F("clamp")}(duty, {N("0.2")}, {N("1.0")})  {C("# keep some suction")}',"add"),
      cl(65,64,"",f'        {S("self")}.pump.{F("set_duty")}(duty)'),
      cl(66,65,"",""),
      cl(67,66,"",f'    {K("def")} {F("on_gust")}({S("self")}, obs):'),
      cl(68,67,"",f'        {S("self")}.pid.{F("reset")}()'),
    ])
    w=f'''
    <div class="row gap8" style="height:44px;flex:none;padding:0 12px;border-bottom:1px solid var(--line)">
      <span class="row gap4 nowrap"><span class="c3">Test run</span>{ic("chevron-right",12,"c3")}<span class="c3">Suction loss</span>{ic("chevron-right",12,"c3")}<span class="t14 m">w14, sandstorm</span></span>
      {bdg("Failed","r","x")}<span class="c2 grow" style="margin-left:4px">Dust on seal, 18 m/s wind</span>
      {bdg("Replay of recorded run","n","history")}
      <span class="btn btn-s">{ic("box")}Open in World</span>
    </div>
    <div class="row" style="height:324px;flex:none;align-items:stretch;border-bottom:1px solid var(--line)">
      <div class="vp grow" style="min-width:0;border-right:1px solid var(--line)">
        <img src="pro-assets/render-still.jpg" style="width:1180px;left:-631px;top:-274px" alt="Replay of the robot on glass">
        <svg class="overlay" width="543" height="324" viewBox="0 0 543 324"><path d="M183 63V51H195 M358 51H370V63 M370 270V282H358 M195 282H183V270" fill="none" stroke="#E5534B" stroke-width="1.5"/></svg>
        <span class="vp-tag" style="left:12px;top:12px">0:41.20</span>
        <span class="vp-tag" style="left:183px;top:23px">Seal leak 0.42, limit 0.30</span>
      </div>
      <div style="width:524px;flex:none;display:flex;flex-direction:column;overflow:hidden">
        <div class="row" style="height:20px;padding:4px 12px 0;margin-bottom:0"><span class="t12 m c2 grow">Suction, kPa</span><span class="t12 m">5.9 kPa at 0:41.20</span></div>
        {ch1}
        <div class="row" style="height:20px;padding:4px 12px 0"><span class="t12 m c2 grow">Grip margin, %</span><span class="t12 m">31% at 0:41.20</span></div>
        {ch2}
        {axis}
      </div>
    </div>
    <div style="flex:none;border-bottom:1px solid var(--line)">
      <div class="row gap4" style="height:36px;padding:0 8px;border-bottom:1px solid var(--line)"><span class="ib">{ic("chevron-left")}</span><span class="play">{ic("play")}</span><span class="ib">{ic("chevron-right")}</span><span style="margin-left:8px" class="m">0:41.20</span><span class="c3">of 1:00.00</span><span class="grow"></span><span class="smp" style="margin-right:8px">Sample signals and events</span><span class="btn btn-g btn-sm">{ic("skip-back",12)}Previous event</span><span class="btn btn-g btn-sm">Next event{ic("skip-forward",12)}</span></div>
      {et}
    </div>
    <div class="grow row" style="align-items:stretch;min-height:0">
      <div class="grow" style="min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--line);overflow:hidden">
        <div class="ph"><span class="mono" style="color:var(--t1);font-weight:400">policy/highrise/controller.py</span><span class="c3" style="font-weight:400">Line 63</span><span class="sp"></span><span style="color:var(--grn-t)">+1</span><span style="color:var(--red-t)">−2</span><span class="seg" style="height:24px;margin-left:4px"><span class="on">Inline</span><span>Split</span></span></div>
        <div class="code" style="padding:4px 0">{diff}</div>
      </div>
      <div style="width:304px;flex:none;display:flex;flex-direction:column">
        <div class="ph"><span style="color:var(--t1)">Fix check</span><span class="sp"></span>{bdg("Not applied","n")}</div>
        <div style="padding:12px">
          <div class="row" style="align-items:baseline;gap:8px"><span class="t20 m">11 to 17</span><span class="c2">passes of 104</span></div>
          <svg width="280" height="8" viewBox="0 0 280 8" style="margin:8px 0 8px"><rect x="0" y="0" width="280" height="8" rx="2" fill="#262B32"/><rect x="0" y="0" width="{280*17/104:.1f}" height="8" rx="2" fill="#5CC186"/><rect x="0" y="0" width="{280*11/104:.1f}" height="8" rx="2" fill="#ECEEF1"/></svg><div class="t12 c2 row gap12" style="margin-bottom:8px"><span class="row gap4"><span class="sw" style="background:#ECEEF1"></span>Before, 11</span><span class="row gap4"><span class="sw" style="background:#5CC186"></span>With fix, 17</span></div>
          {kv("Fresh worlds","104")}{kv("Better","6")}{kv("Worse","0")}{kv("Still failing","87")}{kv("Guard","Removed")}<div class="row gap8" style="margin-top:8px"><span class="btn btn-s" style="flex:1">Compare replays</span></div>
        </div>
      </div>
    </div>'''
    return shell("CrashLab: Fix","Fix",c,w)

# ---------- pro-4
def pro4():
    c=chat(
      U("Send what we did not test to a bounty.")+
      steps([("check","Listed gaps","7"),("check","Drafted bounty"),("check","Funded local ledger","1,000"),("check","Ran gate on submissions","3 of 4")])+
      A("Testers sent 4 worlds. Submission 3 passed the gate: the failure repeated 7 of 8 times and the reference twin passed.","It pays 100 from the local ledger. Nothing moves on chain.")+
      f'''<div class="card"><div class="card-h"><span class="t14 m grow">Propose payout</span>{bdg("Needs approval","ac")}</div>
      <div class="card-b">{kv("Submission","3")}{kv("New failure",'<span class="mono">slip_distance</span>')}{kv("Amount","100 test units")}{kv("Dispute window","60 s")}</div>
      <div class="card-f"><span class="btn btn-p">Propose</span><span class="btn btn-s">Hold</span><span class="btn btn-g">See replay</span></div></div>'''+
      A("After you propose, a 60 s dispute window opens. I did not check 3 things, and they are listed with the verdict.")+
      sugg("Show the replay of submission 3","Add a gap to this bounty","Pause new submissions"),
      chips=("Bounty",))
    subs=[
     ("4","0x7ac2…91de","3100031","Running","—","In gate","a"),
     ("3","0xf109…b703","3100024","<span class=mono>slip_distance</span>","7 of 8","Accepted","g"),
     ("2","0xf109…b703","3100011","<span class=mono>no_failure</span>","0 of 1","Rejected","r"),
     ("1","0xf109…b703","3100007","<span class=mono>invalid_file</span>","—","Rejected","r"),
    ]
    rows=""
    for s in subs:
        b={"a":bdg(s[5],"a","loader"),"g":bdg(s[5],"g","check"),"r":bdg(s[5],"r","x")}[s[6]]
        rep=s[4]
        meter=""
        if rep=="7 of 8":
            cells="".join(f'<rect x="{i*6}" y="0" width="4" height="12" rx="1" fill="{"#C9CED6" if i<7 else "#3A3F48"}"/>' for i in range(8))
            meter=f'<svg width="46" height="12" viewBox="0 0 46 12">{cells}</svg>'
        cls=' class="sel-r"' if s[0]=="3" else ""
        rows+=f'<tr{cls}><td class="p">{s[0]}</td><td><span class="mono">{s[1]}</span></td><td>{s[2]}</td><td>{s[3]}</td><td><span class="row gap8">{meter}{rep}</span></td><td>{b}</td></tr>'
    gaps=[("Salt crust on the seal","Chemistry is not in the model","Open"),("Cracked or chipped glass","No fracture model","Open"),("Bird strike","No impact events","Open"),("Tether wear over months","No ageing model","Open"),("Pump wear","No ageing model","Open"),("Facade crane in the path","No moving obstacles","Open"),("Sensor drift","Noise only, no drift","Open")]
    gr="".join(f'<tr><td class="p">{a}</td><td>{b}</td></tr>' for a,b,_ in gaps)
    stats=[("Cap","1,000"),("Per failure","100"),("Reserved","100"),("Left","900"),("Gate needs","7 of 8"),("Dispute window","60 s")]
    st=""
    for i,(k,v) in enumerate(stats):
        st+=f'<div style="padding:0 16px;{"border-left:1px solid var(--line);" if i else "padding-left:12px;"}"><div class="t12 c2">{k}</div><div class="t20 m">{v}</div></div>'
    # stepper
    stp=[("Drafted","7 gaps","d"),("Funded","1,000 test units","d"),("Submission accepted","Submission 3","d"),("Payout proposed","Waiting for you","a"),("Dispute window","60 s","p"),("Paid","100 test units","p")]
    sh=""
    for i,(n,m,s) in enumerate(stp):
        mark={"d":f'<span style="color:var(--grn-t)">{ic("circle-check",16)}</span>',"a":f'<span style="color:var(--ac-t)">{ic("circle-dot",16)}</span>',"p":f'<span style="color:var(--t4)">{ic("circle",16)}</span>'}[s]
        col={"d":"var(--t2)","a":"var(--t1)","p":"var(--t3)"}[s]
        rail="" if i==len(stp)-1 else f'<div style="position:absolute;left:7.5px;top:20px;bottom:-4px;width:1px;background:var(--line2)"></div>'
        sh+=f'<div class="row gap8" style="position:relative;height:28px">{rail}{mark}<span class="grow {"m" if s=="a" else ""}" style="color:{col}">{n}</span><span class="t12 c3">{m}</span></div>'
    w=f'''
    <div class="row gap8" style="height:44px;flex:none;padding:0 12px;border-bottom:1px solid var(--line)">
      <span class="t14 m nowrap">Find new failures in the window robot</span>
      {bdg("Local ledger. Not on chain.","a","landmark")}
      <span class="grow"></span><span class="mono c3">spec 0xb80f33…299f</span><span class="ib s">{ic("copy")}</span>
      <span class="btn btn-s">{ic("share-2")}Share</span><span class="btn btn-s">{ic("play")}Run the gate</span>
    </div>
    <div class="row" style="height:64px;flex:none;border-bottom:1px solid var(--line)">{st}<span class="grow"></span><span class="t12 c3" style="padding-right:12px">Amounts in test units</span></div>
    <div class="grow row" style="align-items:stretch;min-height:0">
      <div class="grow" style="min-width:0;display:flex;flex-direction:column;border-right:1px solid var(--line);position:relative">
        <div class="ph"><span style="color:var(--t1)">Submissions</span><span class="c3" style="font-weight:400">4</span><span class="sp"></span><span class="smp">Submission 4 is sample</span></div>
        <table class="tbl"><colgroup><col style="width:52px"><col style="width:128px"><col style="width:88px"><col><col style="width:116px"><col style="width:104px"></colgroup>
        <thead><tr><th class="sorted"><span class="row">No.{ic("arrow-down",12)}</span></th><th>Tester</th><th>Seed</th><th>Result</th><th>Repeats</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>
        <div class="ph" style="border-top:0;margin-top:16px;border-top:1px solid var(--line)"><span style="color:var(--t1)">Not tested</span><span class="c3" style="font-weight:400">7 in this bounty</span><span class="sp"></span><span class="smp">Sample list</span></div>
        <table class="tbl" style="margin-top:0"><colgroup><col style="width:240px"><col></colgroup><thead><tr><th>Gap</th><th>Why the code cannot test it</th></tr></thead><tbody>{gr}</tbody></table>
        <div class="ph" style="margin-top:16px;border-top:1px solid var(--line)"><span style="color:var(--t1)">Disputes</span><span class="c3" style="font-weight:400">0</span></div>
        <div class="grow" style="display:flex;align-items:center;padding:0 12px"><div class="row gap12"><span class="ib" style="background:var(--raised);color:var(--t3)">{ic("gavel")}</span><div><div class="m">No disputes yet</div><div class="c2">They appear here when the window opens.</div></div></div></div>
        <div class="toast" style="right:12px;bottom:12px">{ic("circle-check",14,"tgr")}<span>Gate finished for submission 3</span><span class="btn btn-g btn-sm">View</span></div>
      </div>
      <div style="width:336px;flex:none;display:flex;flex-direction:column;overflow:hidden">
        <div class="ph"><span style="color:var(--t1)">Verdict, submission 3</span><span class="sp"></span><span class="ib s">{ic("x")}</span></div>
        <div style="padding:12px 12px 8px">
          <div class="row gap8"><span style="color:var(--grn-t)">{ic("circle-check",16)}</span><span class="t16 m">Accepted</span></div>
          <p class="c2" style="margin-top:4px">New <span class="mono">slip_distance</span> failure. It repeated on jittered re-runs and the reference twin passed.</p>
        </div>
        <div style="padding:0 12px 8px">{kv("Repeats","7 of 8")}{kv("Gate needs","7")}{kv("Reference twin","Pass")}{kv("Sim runs","10")}{kv("Time","48.2 s")}</div>
        <div class="ph" style="border-top:1px solid var(--line)"><span>Ledger</span><span class="sp"></span><span class="c3" style="font-weight:400">Step 4 of 6</span></div>
        <div style="padding:8px 12px">{sh}</div>
        <div class="row gap8" style="padding:4px 12px 12px"><span class="btn btn-s" style="flex:1">Propose payout</span><span class="btn btn-d">Pay</span></div>
        <div class="ph" style="border-top:1px solid var(--line)"><span>Not checked</span><span class="c3" style="font-weight:400">3</span></div>
        <div class="c2" style="padding:8px 12px">
          <div class="row gap8" style="height:24px">{ic("circle-slash",14)}World ID of the submitter</div>
          <div class="row gap8" style="height:24px">{ic("circle-slash",14)}Collusion with the company</div>
          <div class="row gap8" style="height:24px">{ic("circle-slash",14)}Money left and the deadline</div>
        </div>
      </div>
    </div>'''
    return shell("CrashLab: Bounty","Bounty",c,w,ledger=True)

for n,fn in (("pro-1",pro1),("pro-2",pro2),("pro-3",pro3),("pro-4",pro4)):
    open(n+".html","w").write(fn())

# ---------- component sheet
def sysheet():
    def sec(t,b,st=""): return f'<section style="margin-bottom:16px;{st}"><div class="t12 m c2" style="margin-bottom:8px">{t}</div>{b}</section>'
    def state(lb,h): return f'<div style="display:flex;flex-direction:column;gap:4px;align-items:flex-start">{h}<span class="t11 c3">{lb}</span></div>'
    def swatch(c,n): return f'<div style="flex:1"><div style="height:32px;background:{c};border-radius:4px;box-shadow:inset 0 0 0 1px var(--line)"></div><div class="t11 c2" style="margin-top:4px">{n}</div><div class="t11 c3">{c}</div></div>'
    surf=f'<div class="row gap8">{swatch("#0B0C0E","App")}{swatch("#111317","Panel")}{swatch("#16191E","Raised")}{swatch("#1E2228","Hover")}{swatch("#262B32","Active")}</div>'
    acc=f'<div class="row gap8">{swatch("#3E7BFA","Accent")}{swatch("#E5534B","Red")}{swatch("#D69A2D","Amber")}{swatch("#3FA66A","Green")}{swatch("#C9CED6","Neutral mark")}</div>'
    typ="".join(f'<div class="row gap16" style="height:{max(24,lh)}px"><span class="t11 c3" style="width:44px">{z}/{lh}</span><span class="{c}">{tx}</span></div>' for z,lh,c,tx in [(20,28,"t20 m","Stat values"),(16,24,"t16 m","Verdict titles"),(14,20,"t14 m","Card and page titles"),(13,20,"t13","Body text, 52 worlds, 31 failed"),(12,16,"t12","Labels, table headers, meta"),(11,16,"t11","Axis ticks and sample tags")])+f'<div class="row gap16" style="height:24px"><span class="t11 c3" style="width:44px">Mono</span><span class="mono">controller.py:63</span></div>'
    btn=lambda c,st="":f'<span class="btn {c}" style="{st}">Label</span>'
    btns=f"""<div style="display:grid;grid-template-columns:64px repeat(5,1fr);gap:8px;align-items:center">
    <span></span>{"".join(f'<span class="t11 c3">{x}</span>' for x in ["Default","Hover","Press","Focus","Disabled"])}
    <span class="t12 c2">Primary</span>{btn("btn-p")}{btn("btn-p","background:var(--ac-h)")}{btn("btn-p","background:var(--ac-p);transform:scale(.97)")}{btn("btn-p","box-shadow:0 0 0 2px var(--panel),0 0 0 4px var(--ac)")}{btn("btn-d")}
    <span class="t12 c2">Secondary</span>{btn("btn-s")}{btn("btn-s","background:var(--active)")}{btn("btn-s","background:var(--active);transform:scale(.97)")}{btn("btn-s","box-shadow:0 0 0 2px var(--panel),0 0 0 4px var(--ac)")}{btn("btn-d")}
    <span class="t12 c2">Ghost</span>{btn("btn-g")}{btn("btn-g","background:var(--hover);color:var(--t1)")}{btn("btn-g","background:var(--active);color:var(--t1);transform:scale(.97)")}{btn("btn-g","box-shadow:0 0 0 2px var(--panel),0 0 0 4px var(--ac)")}{btn("btn-g","color:var(--t4)")}
    </div>"""
    inputs=f"""<div class="row gap8" style="align-items:flex-start">{state("Default",f'<div class="inp" style="width:120px">{ic("search")}<span class="c3">Filter</span></div>')}{state("Focus",f'<div class="inp focus" style="width:120px">{ic("search")}<span class="caret" style="margin:0 -7px 0 0"></span><span class="c3">Filter</span></div>')}{state("Disabled",f'<div class="inp" style="width:120px;color:var(--t4)"><span>Filter</span></div>')}{state("Select",f'<span class="sel"><span class="lb">Group</span>All{ic("chevron-down",12)}</span>')}</div>
    <div class="row gap8" style="margin-top:8px"><span class="seg"><span class="on">All <b>52</b></span><span>Failed <b>31</b></span><span>Held <b>13</b></span></span><span class="seg"><span class="on">Inline</span><span>Split</span></span></div>"""
    badges=f'<div class="row gap8" style="flex-wrap:wrap">{bdg("Failed","r","x")}{bdg("Passed","g","check")}{bdg("Held back","n","lock")}{bdg("Flaky","a","shuffle")}{bdg("In gate","a","loader")}{bdg("Needs approval","ac")}{bdg("Simulated")}{bdg("Local ledger. Not on chain.","a","landmark")}</div>'
    tooltip=f'<div style="position:relative;height:28px"><div class="tooltip" style="left:0;top:0">Show wind vectors<kbd>W</kbd></div><div class="tooltip" style="left:172px;top:0"><span class="c2">Search</span><kbd>⌘K</kbd></div></div>'
    prog=f'<div class="row gap12"><span class="t12 c2" style="width:60px">62 of 104</span><div class="grow" style="height:4px;background:var(--active);border-radius:2px"><div style="width:60%;height:4px;background:var(--ac);border-radius:2px"></div></div></div>'
    tb=f"""<table class="tbl" style="background:var(--panel)"><colgroup><col style="width:64px"><col><col style="width:96px"></colgroup><thead><tr><th class="sorted"><span class="row">World{ic("arrow-up",12)}</span></th><th>Reason</th><th>Status</th></tr></thead><tbody><tr><td class="p">w01</td><td>Default row</td><td>{bdg("Passed","g","check")}</td></tr><tr class="hov-r"><td class="p">w05</td><td>Hover row</td><td>{bdg("Failed","r","x")}</td></tr><tr class="sel-r"><td class="p">w14</td><td>Selected row</td><td>{bdg("Failed","r","x")}</td></tr></tbody></table>"""
    tree=f"""<div class="steps"><div class="st">{ic("chevron-down",12)}<span>Sand and dust</span><span class="meta">10</span></div><div class="st hov" style="padding-left:20px">{ic("globe")}<span style="color:var(--t1)">w03, light haze</span><span class="meta">Hover</span></div><div class="st" style="padding-left:20px;background:var(--ac-bg);color:var(--t1)">{ic("globe")}<span>w14, sandstorm</span><span class="meta">Selected</span></div><div class="st">{ic("chevron-right",12)}<span>Wind</span><span class="meta">12</span></div></div>"""
    stp=steps([("check","Built world","Floor 62"),("loader","Trying a fix","Running","run")])
    empty=f'<div class="row gap12"><span class="ib" style="background:var(--raised);color:var(--t3)">{ic("gavel")}</span><div class="grow"><div class="m">No disputes yet</div><div class="c2">They appear here when the window opens.</div></div></div>'
    toast=f'<div style="position:relative;height:40px"><div class="toast" style="left:0;top:0">{ic("circle-check",14,"tgr")}<span>Gate finished for submission 3</span><span class="btn btn-g btn-sm">View</span></div></div>'
    cmdk=f'<div class="inp" style="color:var(--t3);padding-right:4px">{ic("search")}<span class="grow">Search worlds, files and commands</span><kbd>⌘K</kbd></div>'
    K=lambda s:f'<span class="k">{s}</span>'; F=lambda s:f'<span class="fn">{s}</span>'; N=lambda s:f'<span class="nu">{s}</span>'; C=lambda s:f'<span class="cm">{s}</span>'; S=lambda s:f'<span class="se">{s}</span>'
    def cl(a,b,g,code,k=""): return f'<div class="cl {k}"><span class="n">{a}</span><span class="n">{b}</span><span class="g">{g}</span><span>{code}</span></div>'
    code='<div class="code" style="background:var(--raised);border-radius:6px;padding:4px 0;overflow:hidden">'+cl(62,62,"",f'    duty = {S("self")}.pid.{F("step")}(target)')+cl(63,"","−",f'    {K("if")} obs.seal_leak &gt; {S("self")}.cfg.max_leak:',"del")+cl(64,"","−",f'        duty = {N("0.0")}  {C("# stop pump")}',"del")+cl("",63,"+",f'    duty = {F("clamp")}(duty, {N("0.2")}, {N("1.0")})',"add")+cl(65,64,"",f'    {S("self")}.pump.{F("set_duty")}(duty)')+'</div>'
    tl=f'<div class="row gap4"><span class="ib">{ic("chevron-left")}</span><span class="play">{ic("play")}</span><span class="ib">{ic("chevron-right")}</span><span class="m" style="margin-left:8px">0:41.20</span><span class="c3">of 1:00.00</span></div><svg width="420" height="24" viewBox="0 0 420 24" style="margin-top:4px"><line x1="0" x2="420" y1="12" y2="12" stroke="rgba(255,255,255,.12)"/><path d="M120 7l5 5-5 5-5-5z" fill="#A3A9B3"/><path d="M216 7l5 5-5 5-5-5z" fill="#D69A2D"/><path d="M300 7l5 5-5 5-5-5z" fill="#E5534B"/><line x1="264" x2="264" y1="0" y2="24" stroke="#3E7BFA"/></svg>'
    colA=sec("Surfaces",surf)+sec("Accent and status",acc)+sec("Type scale",typ)+sec("Icons, one 1.25 px stroke",'<div class="row gap12 c2">'+"".join(ic(i) for i in ["globe","flask-conical","wrench","coins","file-code-2","wind","video","ruler","history","landmark","gavel","triangle-alert"])+'</div>')+sec("Approval card",f'''<div class="card"><div class="card-h"><span class="t14 m grow">Test this on 52 worlds</span>{bdg("Needs approval","ac")}</div><div class="card-b">{kv("Worlds to run","39")}{kv("Held back to check fixes","13")}</div><div class="card-f"><span class="btn btn-p">Approve and run</span><span class="btn btn-s">See the 52 worlds</span></div></div>''')
    colB=sec("Buttons",btns)+sec("Inputs, select, segmented control",inputs)+sec("Badges",badges)+sec("Tooltip and command hint",tooltip+'<div style="margin-top:8px">'+cmdk+'</div>')+sec("Progress",prog)+sec("Empty state",empty)+sec("Toast",toast)
    colC=sec("Table with sorted header",tb)+sec("Tree and step rows",tree+'<div style="margin-top:4px">'+stp+'</div>')+sec("Timeline",tl)+sec("Code block and diff",code)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CrashLab: Components</title><style>{CSS}</style></head><body style="background:var(--panel)">
    <div class="row" style="height:40px;flex:none;padding:0 24px;background:var(--app);border-bottom:1px solid var(--line)"><span class="m">CrashLab components</span><span class="c3" style="margin-left:12px">4 px grid, radii 4, 6, 8</span></div>
    <div style="flex:1;display:grid;grid-template-columns:400px 1fr 452px;gap:32px;padding:24px;min-height:0"><div>{colA}</div><div>{colB}</div><div>{colC}</div></div></body></html>'''
open("pro-system.html","w").write(sysheet())
