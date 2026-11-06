import re, math, random, os
ICONS = os.environ.get("LUCIDE", "/tmp/pro-pkgs.03dO/x-lucide-static-0.400.0/package/icons")

def ic(name, size=14, cls=""):
    s = open(f"{ICONS}/{name}.svg").read()
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    inner = re.search(r"<svg[^>]*>(.*)</svg>", s, re.S).group(1)
    inner = re.sub(r"\s*\n\s*", "", inner)
    c = f' class="{cls}"' if cls else ""
    return f'<svg{c} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{24*1.25/size:.3f}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{inner}</svg>'

CSS = r"""
@font-face{font-family:Inter;src:url(pro-assets/inter-latin-wght-normal.woff2) format("woff2");font-weight:100 900}
@font-face{font-family:"JetBrains Mono";src:url(pro-assets/jetbrains-mono-latin-wght-normal.woff2) format("woff2");font-weight:100 800}
:root{--app:#0B0C0E;--panel:#111317;--raised:#16191E;--hover:#1E2228;--active:#262B32;
--line:rgba(255,255,255,.07);--line2:rgba(255,255,255,.12);
--t1:#ECEEF1;--t2:#A3A9B3;--t3:#737A85;--t4:#4B515B;
--ac:#3E7BFA;--ac-h:#5089FB;--ac-p:#2F6AE6;--ac-t:#7DA7FF;--ac-bg:rgba(62,123,250,.14);--ring:rgba(62,123,250,.45);
--red:#E5534B;--red-t:#F27B73;--red-bg:rgba(229,83,75,.13);--amb:#D69A2D;--amb-t:#E3B04F;--amb-bg:rgba(214,154,45,.13);--grn:#3FA66A;--grn-t:#5CC186;--grn-bg:rgba(63,166,106,.13);
--f-suc:#E2574C;--f-slip:#D3A017;--f-edge:#14A39A;--f-teth:#9A78F0;
--sans:Inter,-apple-system,system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1440px;height:900px;overflow:hidden;background:var(--app)}
body{font:400 13px/20px var(--sans);color:var(--t1);font-feature-settings:"tnum","cv11";font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased;display:flex;flex-direction:column}
svg{display:block;flex:none}
.t11{font-size:11px;line-height:16px}.t12{font-size:12px;line-height:16px}.t13{font-size:13px;line-height:20px}.t14{font-size:14px;line-height:20px}.t16{font-size:16px;line-height:24px}.t20{font-size:20px;line-height:28px;letter-spacing:-.01em}
.m{font-weight:500}.c2{color:var(--t2)}.c3{color:var(--t3)}.mono{font-family:var(--mono);font-size:12px;line-height:16px}
.row{display:flex;align-items:center}.gap4{gap:4px}.gap8{gap:8px}.gap12{gap:12px}.gap16{gap:16px}.grow{flex:1;min-width:0}.nowrap{white-space:nowrap}.right{text-align:right}

/* title bar */
.title{height:40px;flex:none;background:var(--app);display:flex;align-items:center;padding:0 12px;border-bottom:1px solid var(--line);position:relative}
.lights{display:flex;gap:8px;margin-right:16px}.lights i{width:12px;height:12px;border-radius:6px;background:#32363D}
.brand{display:flex;align-items:center;gap:8px;font-weight:500}
.crumb{display:flex;align-items:center;gap:4px;height:28px;padding:0 8px;border-radius:6px;color:var(--t2);margin-left:4px}
.crumb svg{color:var(--t3)}
.cmdk{position:absolute;left:50%;top:6px;margin-left:-180px;width:360px;height:28px;background:var(--raised);border-radius:6px;display:flex;align-items:center;gap:8px;padding:0 4px 0 8px;color:var(--t3)}
kbd{font:500 11px/16px var(--sans);color:var(--t2);background:var(--hover);border-radius:4px;padding:0 4px;min-width:20px;text-align:center;display:inline-block}
.avatar{width:24px;height:24px;border-radius:6px;background:var(--active);color:var(--t2);font-size:11px;line-height:24px;text-align:center;font-weight:500;margin-left:4px}

/* shell */
.shell{flex:1;display:flex;min-height:0}
.chat{width:372px;flex:none;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column}
.work{flex:1;min-width:0;display:flex;flex-direction:column;background:var(--panel)}
.status{height:24px;flex:none;background:var(--app);border-top:1px solid var(--line);display:flex;align-items:center;padding:0 12px;gap:16px;font-size:12px;line-height:16px;color:var(--t3)}
.status svg{color:var(--t3)}.status .row{gap:4px}

/* tabs */
.tabs{height:36px;flex:none;background:var(--app);display:flex;align-items:stretch;border-bottom:1px solid var(--line);padding-right:8px}
.tab{display:flex;align-items:center;gap:8px;padding:0 12px;color:var(--t3);border-right:1px solid var(--line);margin-bottom:-1px;position:relative}
.tab .n{font-size:11px;line-height:16px;color:var(--t2);background:var(--hover);border-radius:4px;padding:0 4px;font-weight:500}
.tab.on{background:var(--panel);color:var(--t1)}
.tab.on svg{color:var(--t2)}
.tab.file{font-family:var(--mono);font-size:12px}
.tabs .sp{flex:1;border-bottom:0}

/* buttons */
.btn{height:28px;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:0 12px;border-radius:6px;font:500 13px/20px var(--sans);white-space:nowrap;color:var(--t1);border:0}
.btn-p{background:var(--ac);color:#fff}.btn-s{background:var(--hover)}.btn-g{background:transparent;color:var(--t2);padding:0 8px}
.btn-p kbd{background:rgba(255,255,255,.18);color:#fff}
.btn-d{background:var(--raised);color:var(--t4)}
.btn-sm{height:24px;padding:0 8px;font-size:12px;line-height:16px;border-radius:4px;gap:4px}
.ib{width:28px;height:28px;display:inline-flex;align-items:center;justify-content:center;border-radius:6px;color:var(--t2);flex:none}
.ib.s{width:24px;height:24px;border-radius:4px}
.ib.on{background:var(--ac-bg);color:var(--ac-t)}.ib.hov{background:var(--hover);color:var(--t1)}
.vr{width:1px;height:16px;background:var(--line2);flex:none;margin:0 4px}

/* badges */
.bdg{display:inline-flex;align-items:center;gap:4px;height:20px;padding:0 8px 0 4px;border-radius:4px;font:500 12px/16px var(--sans);white-space:nowrap}
.bdg.plain{padding:0 8px}
.b-n{background:var(--hover);color:var(--t2)}.b-r{background:var(--red-bg);color:var(--red-t)}.b-a{background:var(--amb-bg);color:var(--amb-t)}.b-g{background:var(--grn-bg);color:var(--grn-t)}.b-ac{background:var(--ac-bg);color:var(--ac-t)}
.smp{font-size:11px;line-height:16px;color:var(--t3);font-weight:400}

/* inputs */
.inp{height:28px;background:var(--raised);border-radius:6px;display:flex;align-items:center;gap:8px;padding:0 8px;color:var(--t2);white-space:nowrap}
.inp svg{color:var(--t3)}
.inp.focus{box-shadow:0 0 0 1px var(--ac),0 0 0 3px var(--ring);color:var(--t1)}
.sel{height:28px;background:var(--raised);border-radius:6px;display:inline-flex;align-items:center;gap:4px;padding:0 4px 0 8px;color:var(--t1);white-space:nowrap}
.sel .lb{color:var(--t3)}.sel>svg:last-child{color:var(--t3)}
.seg{height:28px;background:var(--raised);border-radius:6px;display:inline-flex;padding:2px;gap:0}
.seg span{display:flex;align-items:center;gap:4px;padding:0 8px;border-radius:4px;color:var(--t2);white-space:nowrap}
.seg span.on{background:var(--active);color:var(--t1)}
.seg b{font-weight:400;color:var(--t3)}.seg .on b{color:var(--t2)}
.caret{display:inline-block;width:1px;height:16px;background:var(--ac-t);margin-left:-4px}

/* panel header */
.ph{height:32px;flex:none;display:flex;align-items:center;gap:8px;padding:0 12px;border-bottom:1px solid var(--line);font-size:12px;line-height:16px;font-weight:500;color:var(--t2)}
.ph .sp{flex:1}

/* chat */
.chat-h{height:36px;flex:none;display:flex;align-items:center;padding:0 4px 0 12px;border-bottom:1px solid var(--line);gap:0}
.chat-b{flex:1;min-height:0;padding:12px;display:flex;flex-direction:column;gap:12px;overflow:hidden;justify-content:flex-start}
.u{background:var(--raised);border-radius:8px;padding:8px 12px}
.a{color:var(--t1);padding:0 4px}
.a p+p{margin-top:8px}
.steps{display:flex;flex-direction:column;padding:0}
.st{height:24px;display:flex;align-items:center;gap:8px;padding:0 4px;border-radius:4px;color:var(--t2);white-space:nowrap}
.st svg:first-child{color:var(--t3)}
.st .meta{margin-left:auto;color:var(--t3);font-size:12px;line-height:16px}
.st.run{color:var(--t1)}.st.run svg:first-child{color:var(--ac-t)}
.st.hov{background:var(--raised)}
.card{background:var(--raised);border-radius:8px;overflow:hidden}
.card-h{display:flex;align-items:center;gap:8px;padding:8px 12px 4px}
.card-b{padding:4px 12px 8px}
.kv{display:flex;justify-content:space-between;align-items:center;min-height:24px;gap:12px}
.kv>:first-child{color:var(--t2)}.kv>:last-child{white-space:nowrap}
.card-f{display:flex;gap:8px;padding:8px 12px 12px}
.note{display:flex;gap:8px;padding:8px 12px;background:var(--amb-bg);color:var(--amb-t);margin:4px 0 0}
.note svg{margin-top:3px}
.linkrow{display:flex;align-items:center;gap:8px;height:32px;padding:0 12px;border-top:1px solid var(--line);color:var(--t2)}
.linkrow svg:last-child{margin-left:auto;color:var(--t3)}
.opts{display:flex;gap:4px;padding:4px 4px 0}
.comp{margin:0 12px 12px;background:var(--raised);border-radius:8px;flex:none;box-shadow:inset 0 0 0 1px var(--line)}
.comp .ta{padding:12px 12px 8px;color:var(--t3);min-height:40px}
.comp .bar{display:flex;align-items:center;gap:4px;padding:0 8px 8px}
.chip{height:24px;display:inline-flex;align-items:center;gap:4px;padding:0 8px 0 4px;border-radius:4px;background:var(--hover);color:var(--t2);font-size:12px;line-height:16px;white-space:nowrap}
.chip svg{color:var(--t3)}
.send{width:24px;height:24px;border-radius:4px;background:var(--hover);color:var(--t4);display:flex;align-items:center;justify-content:center}
.send.live{background:var(--ac);color:#fff}

.sugg{display:flex;flex-direction:column}
.sg{height:28px;display:flex;align-items:center;gap:8px;padding:0 4px;color:var(--t2);border-radius:4px;white-space:nowrap}
.sg svg{color:var(--t3)}
/* tables */
.tbl{width:100%;border-collapse:collapse;table-layout:fixed}
.tbl th{height:28px;font-weight:500;font-size:12px;line-height:16px;color:var(--t3);text-align:left;padding:0 8px;border-bottom:1px solid var(--line);white-space:nowrap}
.tbl th.sorted{color:var(--t1)}
.tbl th .row{gap:4px}
.tbl td{height:32px;padding:0 8px;border-bottom:1px solid var(--line);white-space:nowrap;overflow:hidden;color:var(--t2)}
.tbl td.p{color:var(--t1)}
.tbl th:first-child,.tbl td:first-child{padding-left:12px}
.tbl th:last-child,.tbl td:last-child{padding-right:12px}
.tbl tr.sel-r td{background:var(--ac-bg);color:var(--t1)}
.tbl tr.hov-r td{background:var(--raised)}
.tbl .num{text-align:right}
.tbl .num .row{justify-content:flex-end}
.sw{width:8px;height:8px;border-radius:2px;flex:none;display:inline-block}

/* inspector */
.sec{padding:8px 0;border-bottom:1px solid var(--line)}
.sec-h{height:24px;display:flex;align-items:center;gap:4px;padding:0 12px 0 8px;font-weight:500;color:var(--t1)}
.sec-h svg{color:var(--t3)}
.prop{height:28px;display:grid;grid-template-columns:92px 1fr;align-items:center;padding:0 12px 0 28px;gap:8px}
.prop>span:first-child{color:var(--t2);white-space:nowrap}
.val{height:24px;background:var(--raised);border-radius:4px;display:flex;align-items:center;justify-content:space-between;padding:0 8px;color:var(--t1);white-space:nowrap}
.val i{font-style:normal;color:var(--t3);font-size:12px;line-height:16px}
.val.ro{background:none;padding:0 8px}
.val.foc{box-shadow:0 0 0 1px var(--ac),0 0 0 3px var(--ring)}
.tooltip{position:absolute;background:var(--active);color:var(--t1);border-radius:6px;padding:4px 8px;font-size:12px;line-height:16px;display:flex;gap:8px;align-items:center;white-space:nowrap;box-shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.4);z-index:5}
.toast{position:absolute;background:var(--hover);border-radius:8px;padding:8px 8px 8px 12px;display:flex;align-items:center;gap:8px;box-shadow:inset 0 0 0 1px var(--line),0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.4);white-space:nowrap;z-index:5}

/* viewport */
.vp{position:relative;overflow:hidden;background:#000}
.vp img{position:absolute;display:block}
.vp-tag{position:absolute;background:rgba(11,12,14,.82);color:var(--t1);border-radius:4px;padding:2px 8px;font-size:12px;line-height:16px;white-space:nowrap}
.overlay{position:absolute;inset:0;pointer-events:none}

/* timeline */
.tl-bar{height:36px;display:flex;align-items:center;padding:0 8px;gap:4px;border-bottom:1px solid var(--line)}
.play{width:28px;height:28px;border-radius:6px;background:var(--hover);color:var(--t1);display:flex;align-items:center;justify-content:center}

/* code */
.code{font:400 12px/20px var(--mono);color:#C8CDD5}
.cl{display:grid;grid-template-columns:36px 36px 20px 1fr;height:20px;white-space:pre}
.cl .n{color:var(--t4);text-align:right;padding-right:8px}.cl .g{text-align:center;color:var(--t3)}
.cl.del{background:rgba(229,83,75,.12)}.cl.del .n,.cl.del .g{color:var(--red-t)}
.cl.add{background:rgba(63,166,106,.12)}.cl.add .n,.cl.add .g{color:var(--grn-t)}
.k{color:#B9A3F0}.fn{color:#8DB4F5}.str{color:#9CCB9A}.lens{height:20px;display:flex;align-items:center;gap:8px;padding-left:92px;font:400 12px/16px var(--sans);color:var(--t3)}.tgr{color:var(--grn-t)}.nu{color:#E2B27A}.cm{color:#6B727D}.se{color:#7FB7C9}
"""

def shell(title, active, chat, work, ledger=False):
    tabs = [("World","globe",None,False),("Test run","flask-conical","52",False),("Fix","wrench",None,False),("Bounty","coins",None,False),("controller.py","file-code-2",None,True)]
    t = ""
    for n,i,c,f in tabs:
        cl = "tab"+(" on" if n==active else "")+(" file" if f else "")
        t += f'<div class="{cl}">{ic(i)}{n}{f"<span class=n>{c}</span>" if c else ""}</div>'
    logo = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#ECEEF1" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><path d="M9.5 2.5H3.5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V6.5"/><path d="M13.5 2.5 9.8 6.2l.9 1.9-2.3.2-.6 2.2-3.3 2.9"/></svg>'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}</style></head><body>
<header class="title"><div class="lights"><i></i><i></i><i></i></div><div class="brand">{logo}CrashLab</div><div class="crumb"><span class="c3">/</span>&nbsp;Dubai tower robot{ic("chevron-down",12)}</div>
<div class="cmdk">{ic("search")}<span class="grow">Search worlds, files and commands</span><kbd>⌘K</kbd></div>
<div class="grow"></div><div class="row gap4"><span class="bdg plain b-n">Simulated</span><div class="vr"></div><span class="ib">{ic("panel-left")}</span><span class="ib">{ic("panel-right")}</span><span class="ib">{ic("settings")}</span><span class="avatar">VL</span></div></header>
<div class="shell"><aside class="chat">{chat}</aside><main class="work"><div class="tabs">{t}<div class="sp"></div><div class="row gap4"><span class="ib">{ic("columns-2")}</span><span class="ib">{ic("ellipsis")}</span></div></div>{work}</main></div>
<footer class="status"><span class="row">{ic("box",12)}Simulated</span><span>Hand-built physics, not checked against real hardware</span><span class="grow"></span>{'<span class="row" style="color:var(--t2)">'+ic("landmark",12)+'Local ledger. Not on chain.</span>' if ledger else ''}<span>AI calls 4 of 10</span><span class="mono" style="font-size:12px">sim 0e36d3bf</span></footer>
</body></html>'''

def chat(body, chips=("World: floor 62",), title="First tests", live=False, text=None):
    ch = "".join(f'<span class="chip">{ic("at-sign",12)}{c}</span>' for c in chips)
    ta = text or 'Ask for a change or a new test'
    return f'''<div class="chat-h"><span class="m" style="margin-right:4px">{title}</span>{ic("chevron-down",12,"c3")}<span class="grow"></span><span class="ib">{ic("plus")}</span><span class="ib">{ic("history")}</span><span class="ib">{ic("ellipsis")}</span></div>
<div class="chat-b">{body}</div>
<div class="comp"><div class="ta">{ta}</div><div class="bar">{ch}<span class="grow"></span><span class="btn btn-g btn-sm">Auto{ic("chevron-down",12)}</span><span class="send{' live' if live else ''}">{ic("arrow-up")}</span></div></div>'''

def U(t): return f'<div class="u">{t}</div>'
def A(*ps): return '<div class="a">'+"".join(f"<p>{p}</p>" for p in ps)+'</div>'
def steps(items):
    o=""
    for it in items:
        i,l,m = it[0],it[1],it[2] if len(it)>2 else ""
        run = len(it)>3 and it[3]
        o+=f'<div class="st{" run" if run else ""}">{ic(i)}<span>{l}</span>{f"""<span class="meta">{m}</span>""" if m else ""}</div>'
    return f'<div class="steps">{o}</div>'
def sugg(*items):
    return '<div class="sugg">'+"".join(f'<div class="sg">{ic("corner-down-right")}{t}</div>' for t in items)+'</div>'
def kv(k,v): return f'<div class="kv"><span>{k}</span><span>{v}</span></div>'
def bdg(t,kind="n",icon=None):
    if icon: return f'<span class="bdg b-{kind}">{ic(icon,12)}{t}</span>'
    return f'<span class="bdg plain b-{kind}">{t}</span>'
def pth(pts): return "M"+" L".join(f"{x:.1f} {y:.1f}" for x,y in pts)
