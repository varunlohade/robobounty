# Layout sketch of the app shell. Chat text and values are sample only.
CSS = """
@font-face{font-family:Inter;src:url(inter-latin-wght-normal.woff2) format("woff2");font-weight:100 900}
@font-face{font-family:"JetBrains Mono";src:url(jetbrains-mono-latin-wght-normal.woff2) format("woff2");font-weight:100 800}
*{box-sizing:border-box;margin:0}
html,body{width:1440px;height:900px;overflow:hidden;background:#0B0C0E;color:#ECEEF1;font:400 13px/20px Inter;font-variant-numeric:tabular-nums}
.app{display:grid;width:1440px;height:900px;grid-template-rows:36px 1fr 24px}
.title{display:flex;align-items:center;padding:0 12px;background:#111317;border-bottom:1px solid rgba(255,255,255,.07);position:relative}
.lights{display:flex;gap:8px}.lights i{width:12px;height:12px;border-radius:50%;background:#30343B}
.name{position:absolute;left:0;right:0;text-align:center;color:#A3A9B3;font-size:12px}
.body{display:flex;min-height:0}
.activity{width:44px;background:#111317;display:flex;flex-direction:column;align-items:center;padding-top:8px;gap:4px;flex:none}
.activity b{width:32px;height:32px;border-radius:6px;display:grid;place-items:center;color:#737A85}
.activity b.on{color:#ECEEF1;background:#1E2228}
.chat{width:380px;flex:none;background:#111317;display:flex;flex-direction:column;min-height:0}
.chat.l{border-right:1px solid rgba(255,255,255,.07)}.chat.r{border-left:1px solid rgba(255,255,255,.07)}
.chead{height:36px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;font-weight:500;flex:none}
.chead span{color:#737A85;font-weight:400}
.log{flex:1;padding:8px 12px;display:flex;flex-direction:column;gap:12px;overflow:hidden}
.me{background:#1E2228;border-radius:8px;padding:8px 12px}
.steps{display:flex;flex-direction:column;gap:4px;color:#A3A9B3}
.steps div{display:flex;justify-content:space-between}.steps em{font-style:normal;color:#737A85}
.steps div::before{content:"✓";color:#5CC186;margin-right:8px}.steps span{flex:1}
.box{margin:0 12px 12px;background:#16191E;border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:12px;height:92px;display:flex;flex-direction:column;justify-content:space-between;color:#737A85;flex:none}
.box div{display:flex;justify-content:space-between;align-items:center;font-size:12px}
.send{width:24px;height:24px;border-radius:6px;background:#3E7BFA;color:#fff;display:grid;place-items:center}
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.tabs{height:36px;background:#111317;display:flex;flex:none;border-bottom:1px solid rgba(255,255,255,.07)}
.tab{padding:0 16px;display:flex;align-items:center;background:#0B0C0E;border-right:1px solid rgba(255,255,255,.07);font-family:"JetBrains Mono";font-size:12px}
.sim{flex:1;position:relative;background:url(render-still.jpg) center/cover;min-height:0}
.tag{position:absolute;background:rgba(11,12,14,.78);border-radius:6px;padding:2px 8px;font-size:12px}
.bar{height:40px;background:#111317;display:flex;align-items:center;gap:12px;padding:0 12px;flex:none;border-top:1px solid rgba(255,255,255,.07)}
.track{flex:1;height:4px;background:#2A2F37;border-radius:2px;position:relative}
.track i{position:absolute;left:0;top:0;height:4px;width:28%;background:#ECEEF1;border-radius:2px}
.status{background:#111317;border-top:1px solid rgba(255,255,255,.07);display:flex;align-items:center;justify-content:space-between;padding:0 12px;font-size:11px;color:#A3A9B3}
.label{position:absolute;right:16px;bottom:64px;background:#3E7BFA;color:#fff;font:500 20px/28px Inter;padding:4px 12px;border-radius:6px}
"""
chat = lambda side: f"""<div class="chat {side}"><div class="chead">Chat <span>New chat</span></div>
<div class="log">
<div class="me">Window robot for towers in Dubai. High floor, strong wind.</div>
<div class="steps"><div><span>Built the world</span></div><div><span>Ran one test</span></div></div>
<div>The world is ready. The robot finished one run. Does the scene look right?</div>
<div class="me">Make the wind stronger and wet the glass.</div>
<div class="steps"><div><span>Changed the world</span></div></div>
<div>Done. Watch the run again.</div>
</div>
<div class="box">Ask for a change to the world<div><span>Agent</span><i class="send" style="font-style:normal">↑</i></div></div></div>"""
activity = '<div class="activity"><b class="on">◧</b><b>▦</b><b>⚙</b></div>'
main = lambda lab: f"""<div class="main"><div class="tabs"><div class="tab">dubai_tower.world</div></div>
<div class="sim"><div class="tag" style="left:12px;top:12px">Simulated</div><div class="label">{lab}</div></div>
<div class="bar"><span>▶</span><span>0:33</span><div class="track"><i></i></div><span>2:00</span><span style="color:#A3A9B3">1×</span></div></div>"""
def page(name, inner, lab):
    html = f"""<!doctype html><meta charset=utf-8><style>{CSS}</style><div class="app">
<div class="title"><div class="lights"><i></i><i></i><i></i></div><div class="name">CrashLab — dubai_tower</div></div>
<div class="body">{inner}</div>
<div class="status"><span>Simulated. Hand-built physics.</span><span>Sample picture</span></div></div>"""
    open(f"{name}.html","w").write(html)
page("A", activity+chat("l")+main("A: chat on the left"), "A")
page("B", activity+main("B: chat on the right")+chat("r"), "B")
