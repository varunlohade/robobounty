(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const ic = (n, c = "") => `<svg class="i ${c}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n]}</svg>`;
  const esc = s => String(s).replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const hash = location.hash.slice(1);

  /* rows that navigate, and "/" for search */
  $$("[data-href]").forEach(r => {
    r.addEventListener("click", () => (location.href = r.dataset.href));
    r.addEventListener("keydown", e => { if (e.key === "Enter") location.href = r.dataset.href; });
  });
  document.addEventListener("keydown", e => {
    if (e.key === "/" && !/INPUT/.test(document.activeElement.tagName)) {
      const f = $("#q,#libq");
      if (f) { e.preventDefault(); f.focus(); }
    }
  });

  /* login: idle, verifying, verified */
  const login = $("#login");
  if (login) {
    const b = $("#wid"), t = $("#wid-t"), i = $("#wid-i"), c = $("#wid-c");
    let timer;
    const set = s => {
      login.className = "login state-" + s;
      c.hidden = s !== "verifying";
      b.classList.toggle("wait", s === "verifying");
      if (s === "idle") { t.textContent = "Sign in with World ID"; i.innerHTML = ic("scan", "i16"); }
      if (s === "verifying") { t.textContent = "Waiting for World App"; i.innerHTML = ic("loader", "i16 spin"); }
      if (s === "verified") {
        t.textContent = "Verified. Opening CrashLab";
        i.innerHTML = ic("check", "i16");
        $("#s2").className = "done"; $("#s3").className = "done";
        $("#s2i").innerHTML = ic("check"); $("#s3i").innerHTML = ic("check");
      }
    };
    b.addEventListener("click", () => {
      if (login.classList.contains("state-verifying")) return;
      set("verifying");
      if (hash) return;
      timer = setTimeout(() => { set("verified"); timer = setTimeout(() => (location.href = "home.html"), 900); }, 4200);
    });
    c.addEventListener("click", () => { clearTimeout(timer); set("idle"); });
    set(["verifying", "verified"].includes(hash) ? hash : "idle");
  }

  /* crashlab: robot picker, tool frames, and the frame that grows into the tool */
  const shot = $("#shot");
  if (shot) {
    const R = {
      window: { t: "Window cleaning robot", w: "dubai_tower.world", shot: "frames/full-lab-3.jpg",
        worlds: [["dubai_tower.world", "Wind 10 m/s", "Make the wind stronger and wet the glass."], ["dubai_tower.world", "Wetness 0.9", "make it rain"], ["window_tower.world", "Robot speed 0.15 m/s", "undo that"]],
        flow: [["frames/full-lab-3.jpg", "Build the world", "Type a change, watch it run"], ["frames/full-grid-window-all-live.jpg", "Run every world", "50 scenarios, 40 to run"], ["frames/full-build-part-ac_unit.jpg", "Add a part", "AC unit on the facade"]] },
      plant: { t: "Plant inspection robot", w: "inspection_plant.world", shot: "frames/full-grid-detail.jpg",
        worlds: [["inspection_plant.world", "Low pipe at x 1.0 m", "The robot fell at 5.2 s, near low_pipe."], ["inspection_plant.world", "Dropped tray", "The robot fell at 16.3 s, near dropped_tray."], ["inspection_plant.world", "Default plant route", "Reached all 3 waypoints in 20.1 s."]],
        flow: [["frames/full-grid-detail.jpg", "Read the failure", "Judge, numbers, code line"], ["frames/full-grid-window-all-live.jpg", "Run every world", "50 scenarios, 40 to run"], ["frames/plant-walk.jpg", "Replay the run", "Default route, passed"]] },
    };
    const swap = src => { shot.classList.remove("in"); void shot.offsetWidth; shot.src = src; shot.classList.add("in"); };
    const pick = k => {
      const d = R[k];
      $("#st-t").textContent = d.t; $("#st-w").textContent = d.w;
      $$("[data-robot]").forEach(x => x.setAttribute("aria-pressed", x.dataset.robot === k));
      $("#worlds").innerHTML = d.worlds.map(w => `<li tabindex="0"><b>${esc(w[2])}</b><p><code>${esc(w[0])}</code>${esc(w[1])}</p></li>`).join("");
      const f = $("#flow");
      f.innerHTML = d.flow.map((x, i) => `<button aria-pressed="${i === 0}" data-src="${x[0]}"><img src="${x[0]}" alt=""><span><b>${x[1]}</b><small>${x[2]}</small></span></button>`).join("");
      $$("button", f).forEach(b => {
        const on = () => { $$("button", f).forEach(o => o.setAttribute("aria-pressed", o === b)); swap(b.dataset.src); };
        b.addEventListener("mouseenter", on); b.addEventListener("focus", on); b.addEventListener("click", on);
      });
      swap(d.shot);
    };
    $$("[data-robot]").forEach(b => b.addEventListener("click", () => pick(b.dataset.robot)));
    pick(hash === "plant" ? "plant" : "window");
    /* one orchestrated moment: the frame grows to fill the window, then the tool takes over */
    $("#open").addEventListener("click", e => {
      if (matchMedia("(prefers-reduced-motion:reduce)").matches) return;
      e.preventDefault();
      const href = e.currentTarget.href, r = $("#win").getBoundingClientRect();
      const o = document.createElement("div");
      o.className = "opening";
      o.style.cssText = `left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;border-radius:8px`;
      o.innerHTML = `<img src="${shot.src}" alt="">`;
      document.body.appendChild(o);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        o.style.cssText = "left:0;top:0;width:100vw;height:100vh;border-radius:0";
      }));
      if (hash !== "hold") setTimeout(() => (location.href = href), 520);
    });
  }

  /* bounties: filter, sort, select */
  const bt = $("#bt");
  if (bt) {
    const ST = { open: ["Open", "circle", "quiet"], reviewing: ["Checking", "loader", "live"], paid: ["Paid", "ok", "ok"] };
    let status = "all", q = "", sel = 1, dir = -1, robot = 0;
    const ROBOTS = ["Any robot", "Window", "Inspection"];
    const seg = $("#st");
    const counts = s => BOUNTIES.filter(b => s === "all" || b.status === s).length;
    seg.innerHTML = [["all", "All"], ["open", "Open"], ["reviewing", "Checking"], ["paid", "Paid"]].map(([k, l]) => `<button data-k="${k}" aria-pressed="${k === "all"}">${l}<i>${counts(k)}</i></button>`).join("");
    const row = b => {
      const s = ST[b.status];
      return `<tr class="row" tabindex="0" data-id="${b.id}" aria-selected="${b.id === sel}"><td><span class="title">${esc(b.title)}</span><span class="sub">${b.robot}, ${b.sev.toLowerCase()}, ${b.req}</span></td><td><div class="cells mini">${"<span class=c-pub></span>".repeat(b.worlds.length)}${"<span class=c-hide></span>".repeat(b.hidden)}</div><span class="sub" style="margin-top:6px">${b.worlds.length} public, ${b.hidden} hidden</span></td><td class="pay">${b.pay}</td><td><span class="tag ${s[2]}">${ic(s[1], b.status === "reviewing" ? "spin" : "")}${s[0]}</span></td></tr>`;
    };
    const draw = () => {
      const list = BOUNTIES.filter(b => (status === "all" || b.status === status) && (!robot || b.robot === ROBOTS[robot]) && (!q || (b.title + b.robot + b.line + b.req).toLowerCase().includes(q))).sort((a, b) => dir * (a.pay - b.pay) || a.id - b.id);
      $("tbody", bt).innerHTML = list.map(row).join("") || `<tr><td colspan="4" class="t2" style="height:96px;white-space:normal">No bounty matches this filter. Clear the search or pick another status.</td></tr>`;
      $$("tr.row", bt).forEach(r => {
        const go = () => choose(+r.dataset.id);
        r.addEventListener("click", go);
        r.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      });
    };
    const detail = b => {
      const s = ST[b.status];
      const hid = Array.from({ length: b.hidden }, (_, i) => `<span class="${i < b.done ? "c-pass" : "c-hide"}"></span>`).join("");
      const steps = [["Patch received", b.file ? `<code>${esc(b.file)}</code>` : "No patch yet"], ["Public worlds", b.stage >= 1 ? `${b.worlds.length} of ${b.worlds.length} pass` : "Waiting"], ["Hidden worlds", b.stage >= 4 ? `${b.hidden} of ${b.hidden} pass` : b.stage >= 2 ? `${b.done} of ${b.hidden} pass so far` : "Waiting"], ["Contract pays", b.stage >= 4 ? `${b.pay} test units` : "Only on a full pass"]];
      const cls = i => (b.stage < 0 ? "" : i < b.stage || b.stage >= 4 ? "d" : i === b.stage ? "n" : "");
      $("#d-in").innerHTML = `
      <div class="dh"><div class="top"><h1>${esc(b.title)}</h1><span class="tag ${s[2]}">${ic(s[1], b.status === "reviewing" ? "spin" : "")}${s[0]}</span></div>
      <p class="req">${b.req}: ${esc(b.text)}</p></div>
      <div class="facts"><div><span>Pay <em class="sample" style="font-style:normal">Sample</em></span><b>${b.pay} test units</b></div><div><span>Severity</span><b>${b.sev}</b></div><div><span>Code line</span><b><code>${b.line}</code></b></div><div><span>Dispute window</span><b>60 s</b></div></div>
      <div class="band"><div class="frame"><img src="${b.frame}" alt="Still from a simulated run"></div><div class="side"><p>Still from a recorded run in this robot's world. Per-world stills come with the next renders.</p><a class="btn sec" href="../../../lab.html">${ic("replay")}Replay the recorded run</a></div></div>
      <div class="dsect"><h2>Public failing worlds</h2><span class="t3 small">${b.worlds.length}</span></div>
      <table><thead><tr><th>World</th><th class="num">Fails at</th><th>Reading</th><th>Re-runs</th><th></th></tr></thead><tbody>${b.worlds.map(w => `<tr><td>${esc(w.id)}</td><td class="num">${w.at}</td><td class="t2">${esc(w.reading)}</td><td class="t2">${w.repeat ? w.repeat + " same" : "Not re-run"}</td><td class="num"><a class="icon-b" href="../../../lab.html" title="Replay the recorded run" aria-label="Replay the recorded run">${ic("replay")}</a></td></tr>`).join("")}</tbody></table>
      <div class="dsect"><h2>Hidden worlds</h2><span class="tag quiet small">${ic("eyeoff", "i12")}${b.hidden} stay hidden</span></div>
      <div class="hidden-w"><div class="cells">${hid}</div><p>Nobody sees these worlds. The code runs your fix on them and shows only a count.</p></div>
      <div class="dsect" style="height:40px"><h2>Submission</h2><span style="display:flex;gap:12px;align-items:center">${b.file ? `<span class="t3 small"><span class="sample">Sample</span> <code>0x7c1e…09ab</code></span>` : ""}${b.status === "paid" ? "" : `<button class="btn ${b.file ? "sec" : "pri"}">Submit a fix</button>`}</span></div>
      <div class="flowline">${steps.map((x, i) => `<div class="${cls(i)}"><b>${x[0]}</b><small>${x[1]}</small></div>`).join("")}</div>
      ${b.subs ? `<table class="subs"><tbody>${b.subs.map(x => `<tr><td><code>${esc(x[0])}</code></td><td><span class="tag ${x[3]}">${ic(x[2], x[2] === "loader" ? "spin" : "")}${esc(x[1])}</span></td></tr>`).join("")}</tbody></table>` : `<div style="padding:4px 24px" class="t3 small">No fix yet. A fix runs on the public worlds, then on the hidden worlds.</div>`}`;
    };
    const choose = id => {
      sel = id;
      $$("tr.row", bt).forEach(r => r.setAttribute("aria-selected", +r.dataset.id === id));
      const d = $("#detail");
      d.classList.add("swap");
      setTimeout(() => { detail(BOUNTIES.find(b => b.id === id)); d.classList.remove("swap"); }, 90);
    };
    $$("button", seg).forEach(x => x.addEventListener("click", () => { status = x.dataset.k; $$("button", seg).forEach(o => o.setAttribute("aria-pressed", o === x)); draw(); }));
    $("#rb").addEventListener("click", e => { robot = (robot + 1) % 3; e.currentTarget.firstChild.textContent = ROBOTS[robot]; draw(); });
    $("#q").addEventListener("input", e => { q = e.target.value.toLowerCase(); draw(); });
    $("#sortpay").addEventListener("click", () => { dir = -dir; $("#ar").innerHTML = ic(dir < 0 ? "down" : "up", "i12"); draw(); });
    draw(); detail(BOUNTIES[0]);
  }

  /* data: library search and sort, campaign switch, cell tooltip */
  const lib = $("#lib");
  if (lib) {
    const all = WORLDS.filter(w => w.kind !== "pass");
    const rank = { detach: 0, slip_distance: 1, false_done: 2, stalled: 3, time_limit: 4, wind_hold: 5, battery_stop: 6 };
    let q = "", key = "at", dir = 1;
    const mark = s => { s = esc(s ?? ""); if (!q) return s; const i = s.toLowerCase().indexOf(q); return i < 0 ? s : s.slice(0, i) + "<mark>" + s.slice(i, i + q.length) + "</mark>" + s.slice(i + q.length); };
    const draw = () => {
      const list = all.filter(w => !q || [w.id, w.group, w.name, w.reading, w.line, w.kind].join(" ").toLowerCase().includes(q)).sort((a, b) => {
        if (key === "sev") return rank[a.kind] - rank[b.kind] || (a.at ?? 1e9) - (b.at ?? 1e9);
        const x = a[key] ?? 1e9, y = b[key] ?? 1e9;
        return dir * (x > y ? 1 : x < y ? -1 : 0);
      });
      $("#libc").textContent = q ? `${list.length} of ${all.length}` : "";
      $("#libn").textContent = q ? "" : `${all.length} worlds from campaign_dubai_final`;
      const ids = new Set(list.map(w => w.id));
      $$("#map i").forEach(c => c.classList.toggle("dim", !!q && !ids.has(c.dataset.w)));
      $("tbody", lib).innerHTML = list.map(w => `<tr class="row" tabindex="0"><td>${mark(w.id)}</td><td class="t2">${mark(w.group)}</td><td><span class="sw ${w.cls}"></span>${mark(w.name)}</td><td class="num">${w.at == null ? '<span class="t4">None</span>' : w.at.toFixed(2)}</td><td class="t2">${mark(w.reading)}</td><td class="${w.flaky ? "" : "t2"}">${w.flaky ? '<span class="tag hold">Flaky, ' + w.repeat + "</span>" : w.repeat}</td><td><code class="t2">${mark(w.line)}</code></td><td class="num"><a class="btn bare show-on-hover" href="../../../lab.html" style="height:22px">${ic("replay", "i12")}Replay</a></td></tr>`).join("") || `<tr><td colspan="8" class="t2" style="height:72px">No world matches. Try a type such as detach, or a code line.</td></tr>`;
    };
    $("#libq").addEventListener("input", e => { q = e.target.value.toLowerCase().trim(); draw(); });
    $$("th.sort", lib).forEach(th => th.addEventListener("click", () => {
      const k = th.dataset.s; dir = key === k ? -dir : 1; key = k;
      $$("th.sort", lib).forEach(o => { o.classList.toggle("on", o === th); $(".ar", o)?.remove(); });
      th.insertAdjacentHTML("beforeend", `<span class="ar">${ic(dir > 0 ? "up" : "down", "i12")}</span>`);
      draw();
    }));
    draw();
    const atH = $('th[data-s="at"]', lib);
    atH.classList.add("on");
    atH.insertAdjacentHTML("beforeend", `<span class="ar">${ic("up", "i12")}</span>`);

    const tip = $("#tip");
    const show = el => {
      const w = WORLDS.find(x => x.id === el.dataset.w);
      tip.innerHTML = `<b>${w.id}</b> <span class="t2">${w.name}${w.flaky ? ", flaky" : ""}${w.at == null ? "" : " at " + w.at.toFixed(2) + " s"}</span><p>${esc(w.group)}</p><p>${w.minp.toFixed(1)} Pa lowest, ${w.slip.toFixed(2)} m slide, ${(w.cov * 100).toFixed(1)}% cleaned</p>`;
      const r = el.getBoundingClientRect();
      tip.style.left = Math.min(Math.max(8, r.left + r.width / 2 - 136), $("#map").getBoundingClientRect().right - 272) + "px";
      tip.style.top = r.top - tip.offsetHeight - 8 + "px";
      tip.classList.add("on");
    };
    const hide = () => tip.classList.remove("on");
    $$("#map i").forEach(c => {
      c.addEventListener("mouseenter", () => show(c)); c.addEventListener("mouseleave", hide);
      c.addEventListener("focus", () => show(c)); c.addEventListener("blur", hide);
    });
    $$("[data-camp]").forEach(r => r.addEventListener("click", () => {
      $$("[data-camp]").forEach(o => o.setAttribute("aria-selected", o === r));
      const k = r.dataset.camp, charts = $("#charts");
      if (!charts.dataset.full) charts.dataset.full = charts.innerHTML;
      if (k === "final") { charts.innerHTML = charts.dataset.full; $$("#map i").forEach(c => { c.addEventListener("mouseenter", () => show(c)); c.addEventListener("mouseleave", hide); }); return; }
      const name = r.children[0].textContent;
      charts.innerHTML = `<div style="grid-column:1/4;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:12px;padding:24px"><h2>${esc(name)}: totals only on this page</h2><p class="t2" style="max-width:520px">The world rows for this batch stay with the recorded run. Open it in CrashLab to see each world, or pick campaign_dubai_final for the full table.</p><a class="btn sec" href="../../../lab.html">Open in CrashLab</a></div>`;
    }));
  }

  /* providers */
  const pd = $("#pd");
  if (pd) {
    const P = {
      mujoco: { t: "MuJoCo", img: "frames/plant-walk.jpg", lede: "Runs the physics for the window robot and the plant robot. Every result on this site comes from it.", d: [["Version", "3.8.1 in Python, 3.16.0 in the browser"], ["Used by", "All campaigns and batches"], ["Limit", "Physics here is hand-built and not calibrated to hardware."]] },
      newton: { t: "Newton", img: "frames/plant-lowpipe.jpg", lede: "Runs in a separate lab to compare a walking robot on 7 worlds. No campaign on this site uses it yet.", d: [["Sim", "<code>sim newton_lab f85fa21e6f4e</code>"], ["Worlds", "Flat, box in path, low friction, clear box, ramp drop, ramp long, steps"], ["Limit", "Not calibrated. Not a real-robot result."]] },
      blender: { t: "Blender", img: "frames/tower-wind.jpg", lede: "Re-renders the recorded physics for film stills. It changes no result. MuJoCo stays the physics source.", d: [["Role", "Picture only"], ["Limit", "A re-render of a recorded run, labelled as one."]] },
      world: { t: "World ID", img: "frames/login-snow.jpg", lede: "Proves one unique human, so one person cannot flood a bounty with submissions.", d: [["Cap", "5 submissions per bounty"], ["State", "Not connected yet. Until it is, the cap counts names and not people."]] },
      contract: { t: "FailureBounty contract", img: "frames/tower-acunit.jpg", lede: "Holds the pay and releases it only after a pass and a dispute window. The site uses a local ledger with the same rules.", d: [["File", "<code>FailureBounty.sol</code>"], ["Tests", "41 pass, 0 fail, on a local test EVM"], ["Limit", "Not deployed. Not audited by a human or an outside firm."]] },
      window: { t: "High-rise window robot", img: "frames/tower-rain.jpg", lede: "A suction climber we built in MuJoCo. A scripted Python controller drives it. AI sits in the test loop, not in the robot.", d: [["Controller", "<code>highrise/controller.py</code>"], ["Hash", "<code>85e7220d4a09</code>"], ["Requirements", "R1 to R7, written before the campaign"], ["Limit", "Not checked against real hardware."]] },
      anymal: { t: "ANYmal C", img: "frames/plant-walk.jpg", lede: "A trained walking policy from upstream drives the legs. Our small route follower tells it where to go.", d: [["Controller", "<code>inspection/controller.py</code>"], ["Sim", "<code>packs/inspection b1c89c64f172</code>"], ["Limit", "Nobody has checked the policy against a real robot."]] },
      claude: { t: "Claude", img: "frames/full-lab-3.jpg", lede: "Reads your words and calls typed engine functions. It writes no physics. It also lists scenarios and tries fixes.", d: [["Model", "<code>claude-opus-5-5</code>"], ["Fix try 2", "15.7 s, $0.07, 3 turns"], ["Limit", "Scenario reasons are reasoned guesses, not evidence that these cases occur."]] },
    };
    const draw = k => {
      const p = P[k];
      pd.innerHTML = `<div class="frame"><img src="${p.img}" alt=""><span class="frame-note">Simulated</span></div><div class="in"><h2>${p.t}</h2><p class="lede">${p.lede}</p><dl>${p.d.map(x => `<dt>${x[0]}</dt><dd>${x[1]}</dd>`).join("")}</dl></div>`;
    };
    $$("[data-p]").forEach(r => {
      const go = () => {
        $$("[data-p]").forEach(o => o.setAttribute("aria-selected", o === r));
        pd.classList.add("swap");
        setTimeout(() => { draw(r.dataset.p); pd.classList.remove("swap"); }, 90);
      };
      r.addEventListener("click", go);
      r.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    });
    draw("window");
  }
})();
