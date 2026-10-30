/* Culture Connect — vanilla JS single-page app. Talks only to our backend (/api/*), never to Qloo directly. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const app = $("#app");
const COLORS = ["#f59e0b", "#3b82f6", "#ef4f9a", "#14b8a6", "#8b5cf6", "#22c55e", "#f97316", "#0ea5e9"];
const STEPS = [
  ["group", "Create Group"], ["resolve", "Match to Qloo"], ["discover", "Discover"], ["plan", "Plan"], ["review", "Review"],
];
const S = { meta: null, program: null, group: null, busy: false, compare: {} };

// ------------------------------------------------------------------ utils
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  try { const t = JSON.parse(localStorage.getItem("cc_token") || "null"); if (t) headers.Authorization = "Bearer " + t; } catch { /* no storage */ }
  const res = await fetch(path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const text = await res.text();
  let data; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) || `HTTP ${res.status}`);
  return data;
}
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.className = "toast"), 3800);
}
const uid = () => "u" + Math.random().toString(36).slice(2, 9);
const initials = (n) => (n || "?").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
const color = (i) => COLORS[i % COLORS.length];
const prettyType = (u) => (u || "").split(":").slice(-1)[0].replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const kindIcon = { entity: "◆", tag: "#", audience: "◎" };
let saveTimer;
function save(now = false) {
  if (!S.program?.id) return;
  clearTimeout(saveTimer);
  const doSave = async () => {
    const { bridges, plans, ...doc } = S.program; // server owns computed fields
    try { await api(`/api/programs/${S.program.id}`, { method: "PUT", body: doc }); } catch (e) { toast("Save failed: " + e.message, true); }
  };
  if (now) return doSave();
  saveTimer = setTimeout(doSave, 500);
}
async function withBusy(btn, fn) {
  if (S.busy) return; S.busy = true;
  const old = btn?.innerHTML; if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Working…`; }
  try { return await fn(); } catch (e) { toast(e.message, true); } finally {
    S.busy = false; if (btn && document.body.contains(btn)) { btn.disabled = false; btn.innerHTML = old; }
  }
}

// ------------------------------------------------------------------ router
window.addEventListener("hashchange", route);
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  window.scrollTo(0, 0);
  // Individuals & Circles (circles.js) handle their own routes; organization routes below are unchanged.
  const first = (parts[0] || "").split("?")[0];
  if (["join", "me", "circles", "my", "c", "auth", "start", "dashboard", "activities", "orgs", "o", "org", "org-invite", "e", "notifications", "admin", "agent"].includes(first) && window.ccRoute) {
    parts[0] = first; if (await window.ccRoute(parts)) return;
  }
  if (parts[0] === "p" && parts[1]) {
    if (!S.program || S.program.id !== parts[1]) {
      try { S.program = await api(`/api/programs/${parts[1]}`); } catch { location.hash = "#/"; return; }
    }
    return renderStep(parts[2] || "group");
  }
  if (parts[0] === "how") return renderHow();
  await renderHome();
  if (window.ccAfterHome) window.ccAfterHome();
}
const go = (step) => (location.hash = `#/p/${S.program.id}/${step}`);

function stepper(active) {
  const idx = STEPS.findIndex((s) => s[0] === active);
  return `<div class="stepper">${STEPS.map(([k, l], i) => `<button class="step ${i < idx ? "done" : ""} ${i === idx ? "active" : ""}" data-go="${k}">
    <span class="dot">${i + 1}</span>${esc(l)}</button>`).join("")}</div>`;
}
function bindStepper() { app.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go))); }

// ------------------------------------------------------------------ home
async function renderHome() {
  let progs = [];
  try { progs = await api("/api/programs"); } catch {}
  app.innerHTML = `
  <section class="hero">
    <div>
      <h1>Different people.<br/>Shared passions.<br/><span>Real human connections.</span></h1>
      <p class="lead">Strangers in. <b>Friends out.</b> Qloo finds the bridge — our agent plans the meetup.</p>
      <div class="tiles">
        ${[["Mentor", "g1", '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>'],
           ["Causes", "g2", '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20a15 15 0 0 1 0-20"/>'],
           ["Sports", "g3", '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>'],
           ["Arts", "g4", '<path d="M12 2a10 10 0 0 0 0 20c1 0 1.5-.8 1.5-1.7 0-.5-.2-.8-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.7 1.7-1.7H16a6 6 0 0 0 6-6C22 6 17.5 2 12 2z"/><circle cx="7.5" cy="10.5" r="1.2"/><circle cx="11" cy="6.5" r="1.2"/><circle cx="16" cy="8" r="1.2"/>'],
           ["Dialogue", "g5", '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>'],
           ["Health", "g6", '<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/><path d="M3.5 12h5l1.5-3 2 6 1.5-3h7"/>']]
          .map(([l, g, d]) => `<div class="tile"><span class="ti ${g}"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg></span>${l}</div>`).join("")}
      </div>
      <div class="row">
        <button class="btn primary" id="newBlank">Start Exploring →</button>
        <button class="btn ghost" id="newSample">Load a sample community</button>
      </div>
    </div>
    <div class="hero-visual">
      <div class="hero-img"><img src="/assets/hero.jpg" alt="People of different ages creating art together"/></div>
      <span class="orb o1">📚</span><span class="orb o2">🎵</span><span class="orb o3">🌍</span><span class="orb o4">🎨</span><span class="orb o5">⚽</span>
      <div class="match" data-rot="bridge">${bridgeHtml(BRIDGES[0])}</div>
      <div class="picks"><img src="/assets/cinema.jpg" alt=""/><img src="/assets/music.jpg" alt=""/><img src="/assets/art.jpg" alt=""/><span>Qloo picks</span></div>
      <div class="float">✨ Real Qloo evidence</div>
    </div>
  </section>
  <section class="pg-wrap">
    <div class="pg-head"><span class="how-kicker">🧲 Live Qloo playground</span><h2>Drag any interest into <span>Qloo</span></h2></div>
    <div class="pg" id="pg"><canvas class="pg-lines"></canvas>
      <div class="pg-core" id="pgCore"><i></i><i></i><b>Qloo</b><small>drop here</small></div>
      <div class="pg-result" id="pgResult" hidden></div>
      <div class="pg-tip">🖐 drag onto Qloo · or tap a bubble</div>
    </div>
    <form class="pg-add" id="pgAdd"><input type="text" maxlength="40" placeholder="＋ Add your own interest…" aria-label="Add an interest bubble"/><button class="btn soft sm" type="submit">Add bubble</button></form>
  </section>
  ${progs.length ? `<section class="card" style="margin-top:22px"><h3>Your programs</h3>
    ${progs.map((p) => `<div class="row between" style="padding:8px 0;border-bottom:1px solid var(--line)">
      <div><b>${esc(p.name || "Untitled")}</b> <span class="muted small">· ${p.participants} participants</span></div>
      <div class="row"><a class="btn soft sm" href="#/p/${p.id}/group">Open</a><button class="btn danger sm" data-del="${p.id}">Delete</button></div></div>`).join("")}
  </section>` : ""}
  <section class="grid2" style="margin-top:22px">
    <div class="card"><h3>⭐ Key Features</h3><div class="grid3">
      ${[["🔗", "#ede9fe", "Cultural Bridge Engine", "Find unexpected connections with Qloo"], ["♿", "#e0f2fe", "Inclusive by Design", "All ages & abilities"],
         ["🛡", "#dcfce7", "Transparent AI", "Every claim cites Qloo evidence"], ["🎨", "#ffedd5", "Multi-Format Activities", "Learn, play, create, debate"],
         ["🎛", "#ede9fe", "Customizable Plans", "Organizer stays in control"], ["💜", "#fce7f3", "Community Impact", "Strangers become a group"]]
        .map(([i, bg, t, d]) => `<div class="feature"><div class="ic" style="background:${bg}">${i}</div><b>${t}</b><span>${d}</span></div>`).join("")}
    </div></div>
    <div class="card"><h3>Architecture Overview</h3>
      <div class="arch" style="margin:22px 0">
        <div class="node" style="background:#ede9fe">👥 Participant<br/>interests</div><span class="arrow">→</span>
        <div class="node" style="background:#e0e7ff">Qloo API<br/><small>search · tags · audiences · insights</small></div><span class="arrow">→</span>
        <div class="node" style="background:#fef3c7">✨ Agentic<br/>Planner</div><span class="arrow">→</span>
        <div class="node" style="background:#dcfce7">📅 Inclusive<br/>Experience</div>
      </div>
      <p class="muted small">The browser only calls this app's backend. The backend holds the Qloo key, logs every Qloo request (see “Qloo calls”),
      and the planner may only cite evidence that came from participants or from real Qloo responses.</p>
      <p class="small" style="text-align:center;color:var(--primary);font-weight:700">Powered by Qloo. Designed for people. 💜</p>
    </div>
  </section>`;
  $("#newBlank").onclick = () => createProgram(false);
  $("#newSample").onclick = () => createProgram(true);
  app.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this program?")) return;
    await api(`/api/programs/${b.dataset.del}`, { method: "DELETE" }); renderHome();
  }));
}

async function createProgram(sample) {
  let doc = { name: "New community program", location: "", participants: [], constraints: { ...(S.meta?.default_constraints || {}) },
    grouping: { min_size: 2, max_size: 6, same_area_only: false } };
  if (sample) {
    const samples = await api("/samples.json");
    doc = { ...doc, ...samples[0], constraints: { ...doc.constraints, ...(samples[0].constraints || {}) } };
    doc.participants = doc.participants.map((p) => ({ ...p, id: uid(), interests: p.interests.map((i) => ({ ...i, resolved: [] })) }));
  }
  S.program = await api("/api/programs", { body: doc });
  go("group");
}

function renderHow() {
  const I = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const steps = [
    { g: "g1", t: "Add people", s: "Strangers + what they love, teach or want to learn",
      i: I('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>'),
      demo: `<div class="hd-row"><img class="hd-ph" src="/assets/p1.jpg" alt=""/><span class="hd-chip teach">🎓 Chess</span></div>
             <div class="hd-row"><img class="hd-ph" src="/assets/p4.jpg" alt=""/><span class="hd-chip">🌍 Climate</span></div>
             <div class="hd-row"><img class="hd-ph" src="/assets/p6.jpg" alt=""/><span class="hd-chip learn">🌱 Guitar</span></div>`, api: [] },
    { g: "g3", t: "Match to Qloo", s: "Every interest becomes a real Qloo ID",
      i: I('<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/><path d="M8 11h6M11 8v6"/>'),
      demo: `<div class="hd-word" data-rot="word">“climate action”</div><div class="hd-arrow">↓</div>
             <div class="hd-row c"><span class="kind entity">entity</span><span class="kind tag">tag</span><span class="kind audience">audience</span></div>`,
      api: ["/search", "/v2/tags", "/v2/audiences"] },
    { g: "g2", t: "Find bridges", s: "Shared tastes link people who never met",
      i: I('<circle cx="5" cy="12" r="3"/><circle cx="19" cy="6" r="3"/><circle cx="19" cy="18" r="3"/><path d="M8 11l8-4M8 13l8 4"/>'),
      demo: `<div class="hd-bridge"><img class="hd-ph" src="/assets/p3.jpg" alt=""/><span class="hd-line"></span><span class="hd-hub" data-rot="emoji">🎵</span><span class="hd-line"></span><img class="hd-ph" src="/assets/p5.jpg" alt=""/></div>
             <div class="hd-row c"><span class="hd-pill">🎬 film</span><span class="hd-pill">🌍 causes</span><span class="hd-pill">⚽ sport</span></div>`,
      api: ["/v2/insights · taste"] },
    { g: "g5", t: "Agent plans", s: "Two activity ideas, each claim backed by evidence",
      i: I('<path d="m12 3-1.9 5.8L4 10l6.1 1.2L12 17l1.9-5.8L20 10l-6.1-1.2z"/><path d="M5 3v4M3 5h4M19 17v4M17 19h4"/>'),
      demo: `<img class="hd-img" src="/assets/story.jpg" alt=""/><div class="hd-bar" style="width:85%"></div><div class="hd-bar" style="width:60%;background:#f9a8d4"></div><div class="hd-bar" style="width:72%;background:#93c5fd"></div>
             <div class="hd-row c"><span class="hd-pill">E1</span><span class="hd-pill">E4</span><span class="hd-pill">E7</span></div>`,
      api: ["/v2/insights · explainability"] },
    { g: "g4", t: "You approve", s: "Tweak, reject or approve — then download",
      i: I('<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="m22 4-10 10-3-3"/>'),
      demo: `<img class="hd-img" src="/assets/craft.jpg" alt=""/><div class="hd-row c"><span class="hd-btn ok">✓ Approve</span></div><div class="hd-row c"><span class="hd-btn">✎ Tweak</span><span class="hd-btn">✕ Reject</span></div>`, api: [] },
  ];
  const orbit = [["🧩", "Entities"], ["🏷️", "Tags"], ["👥", "Audiences"], ["🧠", "Taste"], ["🔍", "Explain"], ["📍", "Venues"]];
  app.innerHTML = `
  <section class="how-hero">
    <span class="how-kicker">✨ How it works</span>
    <h1>From <span>strangers</span> to a <span>group</span> in 5 steps</h1>
    <div class="facestack">${[1, 2, 3, 4, 5, 6].map((n) => `<img src="/assets/p${n}.jpg" alt=""/>`).join("")}<span>🎵 🌍 🏏 🎨 ♟️ 💬</span></div>
  </section>
  <section class="how-flow">
    ${steps.map((x, i) => `<div class="how-step">
      <div class="how-num">${i + 1}</div>
      <div class="how-ic ${x.g}">${x.i}</div>
      <h3>${x.t}</h3><p>${x.s}</p>
      <div class="how-demo">${x.demo}</div>
      <div class="how-api">${x.api.length ? x.api.map((a) => `<code>${a}</code>`).join("") : "<span class='muted small'>no API call</span>"}</div>
    </div>`).join('<div class="how-conn" aria-hidden="true">→</div>')}
  </section>
  <section class="how-bottom">
    <div class="card how-hub">
      <h3>Qloo at the centre</h3>
      <div class="hub">
        <div class="hub-core"><b>Qloo</b><small>taste graph</small></div>
        ${orbit.map(([e, l], i) => `<div class="hub-sat" style="--a:${i * 60}deg"><span>${e}</span><small>${l}</small></div>`).join("")}
      </div>
    </div>
    <div class="card how-trust">
      <h3>Built on trust</h3>
      ${[["✅", "Real evidence", "Every claim links to a Qloo response"], ["🧑‍⚖️", "You decide", "Nothing is sent or booked automatically"],
         ["🔒", "Privacy first", "Consent-only, opt-in contacts"], ["⚖️", "Fair compare", "Side-by-side with a no-Qloo baseline"]]
        .map(([e, t, d]) => `<div class="trust"><span>${e}</span><div><b>${t}</b><small>${d}</small></div></div>`).join("")}
    </div>
  </section>
  <div class="row" style="justify-content:center;margin-top:22px">
    <button class="btn primary" id="howStart">Start Exploring →</button><button class="btn ghost" id="howSample">Try a sample community</button>
  </div>`;
  $("#howStart").onclick = () => createProgram(false);
  $("#howSample").onclick = () => createProgram(true);
}

// ------------------------------------------------------------------ rotating examples (no single hardcoded use case)
const BRIDGES = [["p1", "p2", "♟️", "Chess"], ["p4", "p3", "🎵", "Music"], ["p6", "p5", "🌍", "Climate"],
  ["p3", "p4", "🏏", "Cricket"], ["p2", "p6", "🎨", "Art"], ["p5", "p1", "💬", "Debate"], ["p1", "p4", "🩺", "Health"]];
const WORDS = ["“climate action”", "“jazz”", "“cricket”", "“chess”", "“diabetes”", "“street art”", "“politics”"];
const EMOJI = ["🎵", "🌍", "🏏", "🎨", "♟️", "💬", "🩺", "📚"];
function bridgeHtml([a, b, e, l]) {
  return `<img class="av" src="/assets/${a}.jpg" alt=""/><span class="link">${e}</span><img class="av" src="/assets/${b}.jpg" alt=""/>
    <div><b>${l} bridge</b><small>Matched via Qloo</small></div>`;
}
let rotTick = 0;
setInterval(() => {
  rotTick++;
  document.querySelectorAll("[data-rot]").forEach((el) => {
    const k = el.dataset.rot;
    el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap");
    if (k === "bridge") el.innerHTML = bridgeHtml(BRIDGES[rotTick % BRIDGES.length]);
    else if (k === "word") el.textContent = WORDS[rotTick % WORDS.length];
    else if (k === "emoji") el.textContent = EMOJI[rotTick % EMOJI.length];
  });
}, 2600);

// ------------------------------------------------------------------ step 1: group
const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  users: svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>'),
  flag: svg('<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>'),
  pin: svg('<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>'),
  clock: svg('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'),
  wallet: svg('<path d="M20 12V8H6a2 2 0 0 1 0-4h12v4"/><path d="M4 6v12a2 2 0 0 0 2 2h14v-4"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>'),
  home: svg('<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>'),
};
const GOAL_EMOJI = { connect: "🤝", learn: "📚", create: "🎨", play: "🎲", debate: "💬", support: "💜", act: "🚀" };
function renderStep(step) {
  const fn = { group: stepGroup, resolve: stepResolve, discover: stepDiscover, plan: stepPlan, review: stepReview, ready: stepReady }[step] || stepGroup;
  fn(); bindStepper();
}

function personCard(p, i, editable = true) {
  return `<div class="person">
    <div class="avatar" style="background:${color(i)}">${esc(initials(p.name))}</div>
    <div style="flex:1;min-width:0">
      <div class="row between"><h4>${esc(p.name)}</h4>
        ${editable ? `<div class="row"><button class="btn soft sm" data-edit="${p.id}">Edit</button><button class="iconbtn" data-rm="${p.id}" aria-label="Remove">✕</button></div>` : ""}</div>
      <div class="meta">${[p.age_band ? "Age " + p.age_band.replace(/_/g, "–").replace("–plus", "+").replace("under–18", "under 18") : "", p.location].filter(Boolean).map(esc).join(" · ")}
        ${p.consent === false ? ' · <b style="color:#b91c1c">no consent – excluded</b>' : ""}</div>
      <div class="ints">${p.interests.map((t) => `<span class="int ${t.intent} ${t.resolved?.length ? "ok" : ""}" title="${esc(t.intent)}">${t.intent === "teach" ? "🎓 " : t.intent === "learn" ? "🌱 " : ""}${esc(t.label)}</span>`).join("")}</div>
    </div></div>`;
}

function stepGroup() {
  const p = S.program, c = p.constraints || (p.constraints = {}), g = p.grouping || (p.grouping = { min_size: 2, max_size: 6 });
  const goals = S.meta.goals;
  app.innerHTML = `${stepper("group")}
  <div class="grid2">
    <div class="card cc">
      <div class="cc-head">
        <span class="cc-badge">${ICON.users}</span>
        <div><h2>1. Create a Community</h2><p>Set the vibe for your meetup.</p></div>
        <span class="cc-orb a"></span><span class="cc-orb b"></span><span class="cc-spark">✨</span>
      </div>
      <div class="cc-body">
        <div class="field"><label>Program name</label><div class="iwrap">${ICON.flag}<input type="text" id="pName" value="${esc(p.name)}"/></div></div>
        <div class="field"><label>Area / city <span class="hint">· powers Qloo venues</span></label><div class="iwrap">${ICON.pin}<input type="text" id="pLoc" placeholder="e.g. Pune, Brooklyn, Lower East Side" value="${esc(p.location)}"/></div></div>
        <label>Event goals</label>
        <div class="goalgrid" id="goals">${goals.map((x) => `<button type="button" class="goal ${(c.goals || []).includes(x) ? "on" : ""}" data-goal="${x}"><span>${GOAL_EMOJI[x] || "⭐"}</span>${x}</button>`).join("")}</div>
        <div class="ccgrid">
          <div class="mini t1"><div class="mh"><span class="mi">${ICON.clock}</span>Duration</div><div class="munit"><input type="number" min="15" step="5" id="cDur" value="${c.duration_min ?? 90}"/><em>min</em></div></div>
          <div class="mini t2"><div class="mh"><span class="mi">${ICON.wallet}</span>Budget</div><div class="munit"><input type="number" min="0" id="cBud" value="${c.budget ?? 50}"/><input type="text" id="cCur" class="cur" value="${esc(c.currency || "USD")}"/></div></div>
          <div class="mini t3"><div class="mh"><span class="mi">${ICON.home}</span>Setting</div>
            <div class="seg" id="cSet">${[["any", "🌐"], ["indoor", "🏠"], ["outdoor", "🌳"], ["online", "💻"]].map(([v, e]) => `<button type="button" data-set="${v}" class="${(c.setting || "any") === v ? "on" : ""}" title="${v}">${e}<small>${v}</small></button>`).join("")}</div></div>
          <div class="mini t4"><div class="mh"><span class="mi">${ICON.users}</span>Group size</div><div class="munit"><input type="number" min="2" id="gMin" value="${g.min_size}"/><em>to</em><input type="number" min="2" id="gMax" value="${g.max_size}"/></div></div>
        </div>
        <label class="switch"><input type="checkbox" id="gArea" ${g.same_area_only ? "checked" : ""}/><span class="sw"></span><span class="si">📍</span> Only match people from the same area</label>
        <label class="switch"><input type="checkbox" id="cSens" ${c.sensitive_topic ? "checked" : ""}/><span class="sw"></span><span class="si">🛡️</span> Sensitive topic → add facilitator & safeguards</label>
      </div>
    </div>
    <div class="card">
      <div class="title-row"><div><h2>Participants</h2><p>Tell us what each person loves, can teach, or wants to learn.</p></div></div>
      <div id="people">${p.participants.length ? p.participants.map((x, i) => personCard(x, i)).join("") : `<div class="empty">No participants yet — add a few people who don't know each other.</div>`}</div>
      <div id="formSlot"></div>
      <div class="row" style="margin-top:10px"><button class="btn soft" id="addP">＋ Add Participant</button></div>
    </div>
  </div>
  <div class="row end" style="margin-top:18px"><button class="btn primary" id="next" ${p.participants.length < 2 ? "disabled" : ""}>Next: Match to Qloo →</button></div>`;
  const bind = (id, fn) => ($(id).oninput = (e) => { fn(e.target); save(); });
  bind("#pName", (e) => (p.name = e.value)); bind("#pLoc", (e) => (p.location = e.value));
  bind("#cDur", (e) => (c.duration_min = +e.value)); bind("#cBud", (e) => (c.budget = +e.value)); bind("#cCur", (e) => (c.currency = e.value));
  app.querySelectorAll("[data-set]").forEach((el) => (el.onclick = () => {
    c.setting = el.dataset.set; app.querySelectorAll("[data-set]").forEach((x) => x.classList.toggle("on", x === el)); save();
  }));
  bind("#gMin", (e) => (g.min_size = +e.value)); bind("#gMax", (e) => (g.max_size = +e.value));
  $("#gArea").onchange = (e) => { g.same_area_only = e.target.checked; save(); };
  $("#cSens").onchange = (e) => { c.sensitive_topic = e.target.checked; save(); };
  app.querySelectorAll("[data-goal]").forEach((el) => (el.onclick = () => {
    const x = el.dataset.goal; c.goals = c.goals || [];
    c.goals = c.goals.includes(x) ? c.goals.filter((y) => y !== x) : [...c.goals, x]; el.classList.toggle("on"); save();
  }));
  app.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { p.participants = p.participants.filter((x) => x.id !== b.dataset.rm); save(); stepGroup(); bindStepper(); }));
  app.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => personForm(p.participants.find((x) => x.id === b.dataset.edit))));
  $("#addP").onclick = () => personForm(null);
  $("#next").onclick = async () => { await save(true); go("resolve"); };
}

function personForm(person) {
  const isNew = !person;
  const d = person ? JSON.parse(JSON.stringify(person)) : { id: uid(), name: "", age_band: "", location: S.program.location || "", consent: true,
    interests: [{ label: "", intent: "share", category: "" }] };
  const slot = $("#formSlot");
  const draw = () => {
    slot.innerHTML = `<div class="add-box">
      <div class="grid2"><div class="field"><label>Name (or alias)</label><input type="text" id="fName" value="${esc(d.name)}"/></div>
      <div class="field"><label>Age band (optional)</label><select id="fAge">${S.meta.age_bands.map((a) => `<option value="${a}" ${d.age_band === a ? "selected" : ""}>${a ? a.replace(/_/g, " ") : "prefer not to say"}</option>`).join("")}</select></div></div>
      <div class="field"><label>Area</label><input type="text" id="fLoc" value="${esc(d.location)}"/></div>
      <label>Interests — anything: a game, sport, cause, artist, book, film, skill, topic…</label>
      ${d.interests.map((t, i) => `<div class="irow">
        <input type="text" data-i="${i}" data-k="label" placeholder="e.g. chess, climate action, Bollywood, diabetes" value="${esc(t.label)}"/>
        <select data-i="${i}" data-k="intent">${S.meta.intents.map((x) => `<option value="${x.id}" ${t.intent === x.id ? "selected" : ""}>${x.label}</option>`).join("")}</select>
        <select data-i="${i}" data-k="category"><option value="">Any category</option>${S.meta.entity_types.map((x) => `<option value="${x.id}" ${t.category === x.id ? "selected" : ""}>${x.label}</option>`).join("")}</select>
        <button class="iconbtn" data-rmi="${i}" aria-label="Remove interest">✕</button></div>`).join("")}
      <button class="btn soft sm" id="fAddI">＋ interest</button>
      <label class="check"><input type="checkbox" id="fCons" ${d.consent !== false ? "checked" : ""}/> Participant consented to share these interests with the organizer and their matched group</label>
      <div class="row end"><button class="btn ghost sm" id="fCancel">Cancel</button><button class="btn primary sm" id="fSave">${isNew ? "Add participant" : "Save changes"}</button></div></div>`;
    slot.querySelectorAll("[data-i]").forEach((el) => (el.oninput = el.onchange = () => {
      const t = d.interests[+el.dataset.i]; const old = t[el.dataset.k]; t[el.dataset.k] = el.value;
      if (el.dataset.k !== "intent" && old !== el.value) { t.resolved = []; delete t.candidates; }
    }));
    slot.querySelectorAll("[data-rmi]").forEach((b) => (b.onclick = () => { d.interests.splice(+b.dataset.rmi, 1); draw(); }));
    $("#fAddI").onclick = () => { d.interests.push({ label: "", intent: "share", category: "" }); draw(); };
    $("#fCancel").onclick = () => (slot.innerHTML = "");
    $("#fSave").onclick = () => {
      d.name = $("#fName").value.trim(); d.age_band = $("#fAge").value; d.location = $("#fLoc").value.trim(); d.consent = $("#fCons").checked;
      d.interests = d.interests.filter((t) => t.label.trim()).map((t) => ({ ...t, label: t.label.trim() }));
      if (!d.name || !d.interests.length) return toast("Add a name and at least one interest", true);
      const ps = S.program.participants; const ix = ps.findIndex((x) => x.id === d.id);
      ix >= 0 ? (ps[ix] = d) : ps.push(d); save(); stepGroup(); bindStepper();
    };
  };
  draw(); slot.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ------------------------------------------------------------------ step 2: resolve
function candHtml(c, sel) {
  const thumb = c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy"/>` : `<span class="ph">${kindIcon[c.kind] || "•"}</span>`;
  return `<button class="cand ${sel ? "sel" : ""}" data-cid="${esc(c.id)}" title="${esc(c.description || c.id)}">${thumb}
    <span><span class="kind ${c.kind}">${c.kind}</span> <b>${esc(c.name)}</b><small>${esc(prettyType(c.type))} · ${esc(c.source)}</small></span></button>`;
}
const MQ_SHOW = 5, mqOpen = new Set();
const mqI = (k) => (window.wsIcon ? window.wsIcon(k) : "");
const MQ_KIND = {
  entity: '<svg viewBox="0 0 24 24" class="ic" aria-hidden="true"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="m3 7 9 5 9-5M12 12v10"/></svg>',
  tag: '<svg viewBox="0 0 24 24" class="ic" aria-hidden="true"><path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/></svg>',
  audience: '<svg viewBox="0 0 24 24" class="ic" aria-hidden="true"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/></svg>'
};
const MQ_INTENT = { teach: "crown", learn: "book", share: "heart" };
function mqChip(c, sel) {
  const thumb = c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy" referrerpolicy="no-referrer"/>` : `<span class="mq-k k-${esc(c.kind)}">${MQ_KIND[c.kind] || "•"}</span>`;
  const tip = `${c.kind} · ${prettyType(c.type)} · ${c.source}${c.description ? " — " + c.description : ""}`;
  return `<button type="button" class="mq-c ${sel ? "sel" : ""}" data-cid="${esc(c.id)}" title="${esc(tip)}" aria-pressed="${sel}">
    <span class="mq-th">${thumb}${c.image ? `<span class="mq-kb k-${esc(c.kind)}">${MQ_KIND[c.kind] || ""}</span>` : ""}</span>
    <span class="mq-n"><b>${esc(c.name)}</b><small>${esc(prettyType(c.type))}</small></span><span class="mq-ok">${mqI("check")}</span></button>`;
}
function slotInner(t, key) {
  if (!t.candidates) return `<div class="mq-cs">${'<span class="mq-sk"></span>'.repeat(4)}</div>`;
  const cs = t.candidates.candidates, sel = new Set((t.resolved || []).map((r) => r.id));
  if (!cs.length) return `<div class="mq-none">${mqI("compass")} No Qloo match — try a broader word.</div>`;
  const open = mqOpen.has(key);
  const vis = open ? cs : cs.filter((c, i) => i < MQ_SHOW || sel.has(c.id));
  const more = cs.length - vis.length;
  return `<div class="mq-cs">${vis.map((c) => mqChip(c, sel.has(c.id))).join("")}
    ${more > 0 ? `<button type="button" class="mq-more" data-more="${key}">+${more}</button>` : open && cs.length > MQ_SHOW ? `<button type="button" class="mq-more" data-more="${key}">Less</button>` : ""}</div>
    ${t.candidates.warnings?.length ? `<div class="mq-none warn" title="${esc(t.candidates.warnings.join(" | "))}">⚠ Qloo warning</div>` : ""}`;
}
function mqCount(t) { return (t.resolved || []).length; }
function mqPersonStat(x) {
  const done = x.interests.filter((t) => mqCount(t)).length;
  return `<span class="mq-pbar"><i style="width:${x.interests.length ? Math.round(100 * done / x.interests.length) : 0}%"></i></span><b>${done}/${x.interests.length}</b>`;
}
function mqTotals(p) {
  let all = 0, done = 0;
  p.participants.forEach((x) => x.interests.forEach((t) => { all++; if (mqCount(t)) done++; }));
  return `<span class="mq-stat">${mqI("users")}<b>${p.participants.length}</b> people</span><span class="mq-stat ok">${mqI("check")}<b>${done}/${all}</b> matched</span>`;
}
function mqRefresh(pi, ii) {
  const p = S.program, x = p.participants[pi], t = x.interests[ii], key = `${pi}-${ii}`;
  const slot = app.querySelector(`[data-slot="${key}"]`); if (!slot) return;
  slot.querySelector(".cslot").innerHTML = slotInner(t, key);
  slot.querySelector(".mq-cnt").innerHTML = mqCount(t) ? `${mqI("check")}${mqCount(t)}` : "";
  slot.classList.toggle("done", !!mqCount(t));
  const card = slot.closest(".mq-p"); if (card) card.querySelector(".mq-prog").innerHTML = mqPersonStat(x);
  const tot = app.querySelector("#mqTot"); if (tot) tot.innerHTML = mqTotals(p);
}
let resolving = false;
function stepResolve() {
  const p = S.program;
  const th = (l) => (window.wsTheme ? window.wsTheme(l) : { g: ["#5b3fd6", "#ec4899"], icon: "sparkle" });
  app.innerHTML = `${stepper("resolve")}
  <section class="mq">
    <header class="mq-head"><span class="mq-logo">${mqI("sparkle")}</span>
      <div class="mq-ht"><h2>Match to Qloo</h2><p>Tap to confirm · only ${mqI("check")} picks are used</p></div>
      <div class="mq-tot" id="mqTot">${mqTotals(p)}</div>
      <button class="btn ghost sm" id="resAll" title="Search Qloo again for every interest">↻ Refresh</button></header>
    <div class="mq-legend"><span class="mq-k k-entity">${MQ_KIND.entity}</span>Entity<span class="mq-k k-tag">${MQ_KIND.tag}</span>Tag<span class="mq-k k-audience">${MQ_KIND.audience}</span>Audience</div>
    <div id="resList" class="mq-grid">${p.participants.map((x, pi) => `<article class="mq-p">
      <header><span class="avatar" style="background:${color(pi)}">${esc(initials(x.name))}</span><h4>${esc(x.name)}</h4>
        ${x.consent === false ? `<span class="mq-nc" title="No consent — skipped in matching">${mqI("lock")}</span>` : ""}<span class="mq-prog">${mqPersonStat(x)}</span></header>
      ${x.interests.map((t, ii) => { const g = th(t.label); return `<div class="mq-i ${mqCount(t) ? "done" : ""}" data-slot="${pi}-${ii}">
        <div class="mq-ih"><span class="mq-ii" style="background:linear-gradient(135deg,${g.g.join(",")})">${mqI(g.icon)}</span>
          <b>${esc(t.label)}</b><span class="mq-intent ${esc(t.intent)}" title="${esc(t.intent)}${t.category ? " · " + esc(prettyType(t.category)) : ""}">${mqI(MQ_INTENT[t.intent] || "sparkle")}${esc(t.intent)}</span>
          <span class="mq-cnt">${mqCount(t) ? `${mqI("check")}${mqCount(t)}` : ""}</span></div>
        <div class="cslot">${slotInner(t, `${pi}-${ii}`)}</div></div>`; }).join("")}</article>`).join("")}</div>
  </section>
  <div class="row between" style="margin-top:18px"><button class="btn ghost" id="back">← Back</button>
    <button class="btn primary" id="next">Next: Discover bridges →</button></div>`;
  $("#resList").onclick = (ev) => {
    const m = ev.target.closest("[data-more]");
    if (m) { const k = m.dataset.more; mqOpen.has(k) ? mqOpen.delete(k) : mqOpen.add(k); const [pi, ii] = k.split("-").map(Number); return mqRefresh(pi, ii); }
    const b = ev.target.closest("[data-cid]"); if (!b) return;
    const [pi, ii] = b.closest("[data-slot]").dataset.slot.split("-").map(Number);
    const t = p.participants[pi].interests[ii]; t.resolved = t.resolved || [];
    const c = t.candidates.candidates.find((x) => x.id === b.dataset.cid);
    const ix = t.resolved.findIndex((r) => r.id === c.id);
    if (ix >= 0) t.resolved.splice(ix, 1); else { const { explainability, ...slim } = c; t.resolved.push(slim); }
    save(); mqRefresh(pi, ii);
  };
  $("#back").onclick = () => go("group");
  $("#resAll").onclick = () => { p.participants.forEach((x) => x.interests.forEach((t) => delete t.candidates)); stepResolve(); bindStepper(); };
  $("#next").onclick = (e) => withBusy(e.currentTarget, async () => {
    const n = p.participants.reduce((a, x) => a + x.interests.filter((t) => t.resolved?.length).length, 0);
    if (!n) return toast("Confirm at least one Qloo match first", true);
    await save(true);
    toast("Running Qloo taste analysis for every participant…");
    S.program = await api("/api/discovery/run", { body: { program_id: p.id } });
    S.program = await api("/api/bridges/build", { body: { program_id: p.id } });
    S.group = S.program.bridges.groups[0]?.id; go("discover");
  });
  resolvePending();
}
async function resolvePending() {
  if (resolving) return; resolving = true;
  const p = S.program, jobs = [];
  p.participants.forEach((x, pi) => x.interests.forEach((t, ii) => { if (!t.candidates) jobs.push([pi, ii, t]); }));
  let changed = false;
  const worker = async () => {
    while (jobs.length) {
      const [pi, ii, t] = jobs.shift();
      try { t.candidates = await api("/api/interests/resolve", { body: { label: t.label, category: t.category || null } }); }
      catch (e) { t.candidates = { candidates: [], warnings: [e.message] }; }
      if (!t.resolved?.length) {
        t.resolved = (t.candidates.suggested_ids || []).map((id) => t.candidates.candidates.find((x) => x.id === id))
          .filter(Boolean).map(({ explainability, ...slim }) => slim);
      }
      changed = true;
      mqRefresh(pi, ii);
    }
  };
  try { await Promise.all([worker(), worker(), worker()]); } finally { resolving = false; }
  if (changed) save();
}

// ------------------------------------------------------------------ step 3: discover
function graphSvg(g) {
  const W = 640, H = 430, cx = W / 2, cy = H / 2;
  const mem = g.members, n = mem.length;
  const themes = g.themes.slice(1, 6);
  const pos = mem.map((m, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / n; return [cx + 175 * Math.cos(a), cy + 160 * Math.sin(a)]; });
  const tpos = themes.map((t, i) => { const a = -Math.PI / 2 + Math.PI / n + (i * 2 * Math.PI) / Math.max(themes.length, 1); return [cx + 110 * Math.cos(a), cy + 105 * Math.sin(a)]; });
  const idx = Object.fromEntries(mem.map((m, i) => [m.name, i]));
  let lines = pos.map(([x, y], i) => `<line data-from="c" data-to="m${i}" x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#c9bdff" stroke-width="2.5"/>`).join("");
  themes.forEach((t, ti) => {
    const who = new Set(); g.evidence.filter((e) => (e.label || "").includes(t.label)).forEach((e) => (e.between || []).forEach((w) => who.add(w)));
    who.forEach((w) => { if (idx[w] !== undefined) lines += `<line data-from="t${ti}" data-to="m${idx[w]}" x1="${tpos[ti][0]}" y1="${tpos[ti][1]}" x2="${pos[idx[w]][0]}" y2="${pos[idx[w]][1]}" stroke="#f0b4d4" stroke-dasharray="4 4" stroke-width="1.6"/>`; });
  });
  const wrap = (s, max = 16) => { const w = String(s).split(" "); const out = [""]; w.forEach((x) => { if ((out.at(-1) + " " + x).trim().length > max) out.push(x); else out[out.length - 1] = (out.at(-1) + " " + x).trim(); }); return out.slice(0, 3); };
  const center = wrap(g.primary_theme || "Shared theme", 14);
  return `<svg class="graph" viewBox="0 0 ${W} ${H}" role="img" aria-label="Connection graph">
    <defs><radialGradient id="cg"><stop offset="0" stop-color="#7c5cff"/><stop offset="1" stop-color="#4c2fc4"/></radialGradient></defs>
    ${lines}
    ${themes.map((t, i) => `<g class="gnode" data-node="t${i}"><circle cx="${tpos[i][0]}" cy="${tpos[i][1]}" r="30" fill="#fde7f3" stroke="#f9a8d4"/>
      ${wrap(t.label, 11).map((l, k, a) => `<text x="${tpos[i][0]}" y="${tpos[i][1] + 4 + (k - (a.length - 1) / 2) * 11}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#9d174d">${esc(l)}</text>`).join("")}</g>`).join("")}
    <g class="gnode" data-node="c"><circle cx="${cx}" cy="${cy}" r="66" fill="url(#cg)"/>
    <text x="${cx}" y="${cy - 24}" text-anchor="middle" font-size="11" fill="#e9e3ff" font-weight="700">✦ Shared Theme</text>
    ${center.map((l, k) => `<text x="${cx}" y="${cy + 2 + k * 16}" text-anchor="middle" font-size="14" font-weight="800" fill="#fff">${esc(l)}</text>`).join("")}</g>
    ${mem.map((m, i) => `<g class="gnode" data-node="m${i}"><circle cx="${pos[i][0]}" cy="${pos[i][1]}" r="36" fill="${color(i)}" stroke="#fff" stroke-width="4"/>
      <text x="${pos[i][0]}" y="${pos[i][1] + 6}" text-anchor="middle" font-size="17" font-weight="800" fill="#fff">${esc(initials(m.name))}</text>
      <text x="${pos[i][0]}" y="${pos[i][1] + 54}" text-anchor="middle" font-size="12" font-weight="700" fill="#1d1b3a">${esc(m.name)}</text></g>`).join("")}
  </svg>`;
}
const evBadge = (src) => `<span class="badge ${src.startsWith("participant") ? "participant" : src === "qloo" ? "qloo" : "generated"}">${src.startsWith("participant") ? (src.includes("qloo") ? "participant · Qloo ID" : "participant") : src}</span>`;
function stepDiscover() {
  const b = S.program.bridges;
  if (!b) { app.innerHTML = `${stepper("discover")}<div class="card empty">Run matching first. <a class="btn primary" href="#/p/${S.program.id}/resolve">Go</a></div>`; return; }
  const g = b.groups.find((x) => x.id === S.group) || b.groups[0]; S.group = g?.id;
  const people = S.program.participants;
  app.innerHTML = `${stepper("discover")}
  <div class="card">
    <div class="title-row"><div><h2>3. Discover Cultural Bridges</h2><p>How these strangers connect through Qloo's cultural graph — every link is traceable.</p></div><span class="sparkle">✨</span></div>
    ${b.groups.length ? `<div class="tabs">${b.groups.map((x) => `<span class="chip click ${x.id === g.id ? "on" : ""}" data-g="${x.id}">${x.id}: ${esc(x.members.map((m) => m.name).join(", "))}</span>`).join("")}</div>` :
      `<div class="notice">No group had a traceable bridge yet. Add more interests, confirm different Qloo matches, or loosen the area rule — nothing is fabricated.</div>`}
    ${g ? `<div class="grid2">
      <div class="graph-wrap">${graphSvg(g)}<span class="drag-hint">✋ Drag the bubbles</span>
        <div class="row" style="justify-content:center"><span class="chip">Cohesion ${g.cohesion}</span>${Object.entries(g.evidence_kinds).map(([k, v]) => `<span class="chip">${k.replace("_", " ")} × ${v}</span>`).join("")}</div></div>
      <div>
        <div class="why"><div style="font-size:1.6rem">💡</div><div><b>Why this connection?</b>
          <div class="muted small">${g.mentorships.length ? esc(g.mentorships[0].detail) + " " : ""}Top shared themes: ${g.themes.map((t) => esc(t.label)).slice(0, 4).join(" · ") || "—"}</div></div></div>
        <h4 style="margin-top:14px">Evidence (${g.evidence.length})</h4>
        <div style="max-height:330px;overflow:auto">${g.evidence.map((e) => `<div class="ev">${evBadge(e.source)}<div><b>${esc(e.label)}</b> <span class="muted small">· ${esc((e.between || []).join(" ↔ "))}</span><div class="small">${esc(e.detail)}</div></div></div>`).join("")}</div>
      </div></div>` : ""}
    ${b.unmatched.length ? `<div class="notice">Not matched yet: ${b.unmatched.map((u) => `<b>${esc(u.name)}</b>`).join(", ")} — ${esc(b.unmatched[0].hint)}</div>` : ""}
    ${b.excluded_no_consent.length ? `<div class="notice">Excluded (no consent): ${b.excluded_no_consent.map(esc).join(", ")}</div>` : ""}
    <details><summary>All pairwise bridges & method</summary><p class="muted small">${esc(b.method)}</p>
      <div class="cmp"><table><tr><th>Pair</th><th>Score</th><th>Evidence</th></tr>${b.pairs.sort((x, y) => y.score - x.score).map((x) => `<tr><td>${esc(x.a_name)} ↔ ${esc(x.b_name)}</td><td>${x.score}</td><td class="small">${x.evidence.map((e) => esc(e.kind)).join(", ")}</td></tr>`).join("")}</table></div></details>
  </div>
  <div class="row between" style="margin-top:18px"><button class="btn ghost" id="back">↻ Try different interests</button>
    <div class="row">${S.program.org_id && g ? ((S.program.circles || {})[g.id]
        ? `<a class="btn soft" href="#/c/${esc(S.program.circles[g.id])}">⭕ Open ${esc(g.id)} Circle</a>`
        : `<button class="btn soft" id="mkCircle">⭕ Approve ${esc(g.id)} as a Circle</button>`) : ""}
    <button class="btn primary" id="next" ${g ? "" : "disabled"}>Next: Plan Activity →</button></div></div>
  <div id="circleOut"></div>`;
  app.querySelectorAll("[data-g]").forEach((x) => (x.onclick = () => { S.group = x.dataset.g; stepDiscover(); bindStepper(); }));
  $("#back").onclick = () => go("resolve");
  $("#next").onclick = () => go("plan");
  const mk = $("#mkCircle");
  if (mk) mk.onclick = (e) => withBusy(e.currentTarget, async () => {
    // Organiser review step: turn this proposed group into a real invite-only organisation Circle.
    const r = await api(`/api/orgs/${S.program.org_id}/programs/${S.program.id}/groups/${g.id}/circle`, { body: { name: "" } });
    S.program = await api(`/api/programs/${S.program.id}`);
    const link = `${location.origin}${location.pathname}#/c/${r.circle_id}?invite=${r.invite_code}`;
    $("#circleOut").innerHTML = `<div class="notice">Circle created. Share this invite link with the participants — they sign in, request to join, and you approve them:<br/><code>${esc(link)}</code></div>`;
    toast("Circle created from this group");
  });
}

// ------------------------------------------------------------------ step 4: plan
function refChips(refs, ev) {
  const by = Object.fromEntries((ev || []).map((e) => [e.eid, e]));
  return `<div class="refs">${(refs || []).map((r) => by[r] ? `<span class="ref" title="${esc(by[r].source.toUpperCase() + ": " + by[r].detail)}">${r} · ${esc(by[r].label.slice(0, 40))}</span>` : "").join("")}</div>`;
}
function conceptCard(c, plan, actions = true) {
  return `<div class="card concept">
    <div class="banner">${c.anchor_image ? `<img src="${esc(c.anchor_image)}" alt=""/>` : ""}<h3>${esc(c.title)}</h3></div>
    <div class="body">
      <div class="row between"><span class="chip">${esc(c.format_name)}</span><span class="badge generated">${esc(c.generated_by)}</span></div>
      <p>${esc(c.summary)}</p>
      <div class="stats"><span>🕒 ${c.duration_min} min</span><span>👥 ${c.group_size} people</span><span>💲 ~${c.cost_estimate?.amount ?? 0} ${esc(plan.constraints?.currency || "")}</span><span>📍 ${esc(c.venue)}</span></div>
      <h4>How everyone can participate</h4><ul class="ticks">${(c.roles || []).map((r) => `<li><b>${esc(r.member)}</b> — ${esc(r.role)}</li>`).join("")}</ul>
      <details open><summary>Agenda</summary><ol class="agenda">${c.agenda.map((a) => `<li><div><b>${esc(a.title)} (${a.minutes} min)</b>${esc(a.detail)}</div></li>`).join("")}</ol></details>
      <details><summary>Materials, accessibility & safeguards</summary>
        <ul class="small">${(c.materials || []).map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
        <ul class="ticks">${(c.accessibility || []).map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
        ${(c.safeguards || []).map((m) => `<div class="notice">${esc(m)}</div>`).join("")}</details>
      <details><summary>Agent review</summary><div class="review small">${(c.review || []).map((k) => `<div class="${k.status === "pass" ? "ok" : k.status}">${k.status === "pass" ? "✔" : k.status === "warn" ? "⚠" : "✖"} <b>${esc(k.check)}</b> — ${esc(k.note)}</div>`).join("")}</div></details>
      <h4 style="margin-top:12px">Evidence cited</h4>${refChips(c.evidence_refs, plan.evidence)}
      ${(c.warnings || []).map((w) => `<div class="notice">${esc(w)}</div>`).join("")}
      ${actions ? `<div class="row between" style="margin-top:14px"><button class="btn danger sm" data-reject="${c.id}">✕ Reject idea</button>
        <div class="row"><button class="btn ghost sm" data-modify>✎ Modify Plan</button><button class="btn primary sm" data-approve="${c.id}">Approve Plan ✓</button></div></div>` : ""}
    </div></div>`;
}
async function ensurePlan(gid, force = false) {
  const st = (S.program.plans || {})[gid];
  if (st && !force) return st.current;
  const plan = await api("/api/events/generate", { body: { program_id: S.program.id, group_id: gid } });
  S.program.plans = S.program.plans || {}; S.program.plans[gid] = { current: plan, history: [], approved: null };
  return plan;
}
async function stepPlan() {
  const b = S.program.bridges; if (!b?.groups.length) return go("discover");
  const g = b.groups.find((x) => x.id === S.group) || b.groups[0]; S.group = g.id;
  app.innerHTML = `${stepper("plan")}<div class="card empty"><span class="spinner"></span> The agent is querying Qloo for ${esc(g.members.map((m) => m.name).join(", "))}'s shared anchors and drafting activities…</div>`;
  bindStepper();
  let plan; try { plan = await ensurePlan(g.id); } catch (e) { app.innerHTML = `${stepper("plan")}<div class="card notice">${esc(e.message)}</div>`; bindStepper(); return; }
  const anchors = (plan.evidence || []).filter((e) => e.kind === "anchor" || e.kind === "venue");
  app.innerHTML = `${stepper("plan")}
  <div class="title-row"><div><h2>4. Generate an Inclusive Activity</h2><p>Activities designed for ${esc(g.members.map((m) => m.name).join(", "))}. Hover an evidence chip to see its source.</p></div>
    <div class="row">${b.groups.length > 1 ? `<select id="gSel">${b.groups.map((x) => `<option value="${x.id}" ${x.id === g.id ? "selected" : ""}>${x.id}: ${esc(x.members.map((m) => m.name).join(", "))}</option>`).join("")}</select>` : ""}
      <button class="btn ghost sm" id="regen">↻ Regenerate</button></div></div>
  ${plan.fallback ? `<div class="notice">${esc(plan.fallback)}</div>` : ""}
  ${plan.revision_notes?.length ? `<div class="notice">Revised: ${esc(plan.revision_notes.join("; "))}</div>` : ""}
  <div class="grid2">${plan.concepts.map((c) => conceptCard(c, plan)).join("")}</div>
  <div class="grid2" style="margin-top:18px">
    <div class="card"><h3>Qloo anchors for this group</h3>
      ${anchors.length ? `<div class="thumbs">${anchors.map((a) => `<figure>${a.image ? `<img src="${esc(a.image)}" alt=""/>` : `<div class="ph"></div>`}<figcaption>${esc(a.label)}<br/><span class="muted">${esc(prettyType(a.type))}${a.driven_by?.length ? " · via " + esc(a.driven_by.join(", ")) : ""}</span></figcaption></figure>`).join("")}</div>`
        : `<p class="muted small">Qloo returned no group-level anchors for these signals${(plan.anchors?.warnings || []).length ? ": " + esc(plan.anchors.warnings.join("; ")) : "."}</p>`}
      <details><summary>Agent trace (${plan.trace.length} steps)</summary><div class="trace">${plan.trace.map((t) => `<div><b>${t.step}. ${esc(t.tool)}</b> ${esc(t.message)}</div>`).join("")}</div></details>
      <details><summary>Full evidence pack (${plan.evidence.length})</summary>${plan.evidence.map((e) => `<div class="ev">${evBadge(e.source)}<div><b>${e.eid} · ${esc(e.label)}</b><div class="small">${esc(e.detail)}</div></div></div>`).join("")}</details>
    </div>
    <div class="card cmp"><h3>Qloo vs. no-Qloo baseline</h3><p class="muted small">Same people, same constraints. The baseline only sees typed interests and makes no Qloo calls.</p>
      <div id="cmpBox">${S.compare[g.id] ? cmpHtml(S.compare[g.id]) : `<button class="btn soft" id="cmpBtn">Run comparison</button>`}</div></div>
  </div>
  <div class="row between" style="margin-top:18px"><button class="btn ghost" id="back">← Back</button><button class="btn primary" id="toReview">Review & Customize →</button></div>`;
  bindStepper();
  $("#gSel") && ($("#gSel").onchange = (e) => { S.group = e.target.value; stepPlan(); });
  $("#regen").onclick = (e) => withBusy(e.currentTarget, async () => { await ensurePlan(g.id, true); stepPlan(); });
  $("#back").onclick = () => go("discover"); $("#toReview").onclick = () => go("review");
  $("#cmpBtn") && ($("#cmpBtn").onclick = (e) => withBusy(e.currentTarget, async () => {
    S.compare[g.id] = await api("/api/events/compare", { body: { program_id: S.program.id, group_id: g.id } }); $("#cmpBox").innerHTML = cmpHtml(S.compare[g.id]);
  }));
  app.querySelectorAll("[data-reject]").forEach((x) => (x.onclick = (e) => withBusy(e.currentTarget, async () => {
    await revise({ reject_concept_id: x.dataset.reject }); stepPlan();
  })));
  app.querySelectorAll("[data-modify]").forEach((x) => (x.onclick = () => go("review")));
  app.querySelectorAll("[data-approve]").forEach((x) => (x.onclick = (e) => withBusy(e.currentTarget, async () => {
    const ap = await api("/api/events/approve", { body: { program_id: S.program.id, group_id: g.id, concept_id: x.dataset.approve } });
    S.program.plans[g.id].approved = ap; go("ready");
  })));
}
function cmpHtml(r) {
  const m = r.metrics, rows = [["Evidence items available", "evidence_items"], ["Traceable citations", "traceable_citations"], ["Citations from real Qloo responses", "qloo_citations"],
    ["Distinct activity formats", "distinct_formats"], ["Review checks passed", "checks_passed"], ["Personalised member roles", "personalised_roles"]];
  return `<table><tr><th>Metric</th><th>Baseline</th><th>Qloo-grounded</th></tr>${rows.map(([l, k]) => `<tr><td>${l}</td><td>${esc(m.baseline[k])}</td><td><b>${esc(m.qloo[k])}</b></td></tr>`).join("")}
    <tr><td>Concepts</td><td class="small">${r.baseline.concepts.map((c) => esc(c.title)).join("<br/>") || esc(r.baseline.fallback || "—")}</td><td class="small"><b>${r.qloo.concepts.map((c) => esc(c.title)).join("<br/>")}</b></td></tr></table>
    <p class="muted small">${esc(r.note)} Judge for yourself — we report counts, not a claim of superiority.</p>`;
}
async function revise(body) {
  const plan = await api("/api/events/revise", { body: { program_id: S.program.id, group_id: S.group, ...body } });
  S.program.plans[S.group].current = plan; S.program.constraints = { ...S.program.constraints, ...plan.constraints }; delete S.compare[S.group];
  toast("Plan revised: " + (plan.revision_notes || []).join("; "));
  return plan;
}

// ------------------------------------------------------------------ step 5: review
async function stepReview() {
  const b = S.program.bridges; if (!b?.groups.length) return go("discover");
  const g = b.groups.find((x) => x.id === S.group) || b.groups[0]; S.group = g.id;
  let plan; try { plan = await ensurePlan(g.id); } catch (e) { return toast(e.message, true); }
  const c = plan.constraints || S.program.constraints;
  app.innerHTML = `${stepper("review")}
  <div class="grid2">
    <div class="card">
      <div class="title-row"><div><h2>5. Review & Customize</h2><p>Adjust the plan for ${esc(g.members.map((m) => m.name).join(", "))}.</p></div><span class="sparkle">✨</span></div>
      <div class="grid2"><div class="card" style="box-shadow:none;border:1px solid var(--line)"><h4>Accessibility Options</h4>
        ${[["wheelchair", "Wheelchair accessible venue"], ["quiet_space", "Quiet space available"], ["visual_aids", "Visual aids / large print"], ["flexible_participation", "Flexible participation (no speaking required)"], ["sensitive_topic", "Sensitive topic safeguards"]]
          .map(([k, l]) => `<label class="check"><input type="checkbox" data-c="${k}" ${c[k] ? "checked" : ""}/> ${l}</label>`).join("")}</div>
      <div class="card" style="box-shadow:none;border:1px solid var(--line)"><h4>Other Constraints</h4>
        <div class="field"><label>Duration</label><select id="rDur">${[30, 45, 60, 90, 120, 180].map((d) => `<option value="${d}" ${+c.duration_min === d ? "selected" : ""}>${d} min</option>`).join("")}</select></div>
        <div class="field"><label>Budget (${esc(c.currency || "")})</label><input type="number" min="0" id="rBud" value="${c.budget}"/></div>
        <div class="field"><label>Setting</label><select id="rSet">${["any", "indoor", "outdoor", "online"].map((s) => `<option ${c.setting === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
        <div class="field"><label>Language / interpretation</label><input type="text" id="rLang" value="${esc(c.language || "")}"/></div></div></div>
      <div class="field"><label>Avoid a theme</label><select id="rTheme"><option value="">— keep all themes —</option>${g.themes.map((t) => `<option>${esc(t.label)}</option>`).join("")}</select></div>
      <div class="field"><label>Feedback for the agent (e.g. “shorter, outdoor, free, more hands-on for the kids”)</label><textarea id="rText" rows="3"></textarea></div>
      <div class="row between"><button class="btn ghost" id="back">← Back</button><button class="btn primary" id="upd">Update Plan ✨</button></div>
    </div>
    <div class="card"><h3>Updated Plan Preview</h3>${plan.concepts[0] ? conceptCard(plan.concepts[0], plan, false) : `<div class="empty">No concept yet.</div>`}
      ${plan.concepts[0] ? `<div class="row end" style="margin-top:12px"><button class="btn primary" id="appr">Approve this plan ✓</button></div>` : ""}</div>
  </div>`;
  bindStepper();
  $("#back").onclick = () => go("plan");
  $("#upd").onclick = (e) => withBusy(e.currentTarget, async () => {
    const cons = { duration_min: +$("#rDur").value, budget: +$("#rBud").value, setting: $("#rSet").value, language: $("#rLang").value };
    app.querySelectorAll("[data-c]").forEach((x) => (cons[x.dataset.c] = x.checked));
    await revise({ constraints: cons, text: $("#rText").value || null, reject_theme: $("#rTheme").value || null });
    stepReview();
  });
  $("#appr") && ($("#appr").onclick = (e) => withBusy(e.currentTarget, async () => {
    const ap = await api("/api/events/approve", { body: { program_id: S.program.id, group_id: g.id, concept_id: plan.concepts[0].id } });
    S.program.plans[g.id].approved = ap; go("ready");
  }));
}

// ------------------------------------------------------------------ ready
function stepReady() {
  const plans = Object.entries(S.program.plans || {}).filter(([, s]) => s.approved);
  if (!plans.length) return go("plan");
  app.innerHTML = `${stepper("review")}${plans.map(([gid, st]) => {
    const c = st.approved, ev = st.current.evidence || [];
    const anchors = ev.filter((e) => c.evidence_refs.includes(e.eid) || e.kind === "anchor").filter((e) => e.source === "qloo").slice(0, 4);
    return `<div class="card ready" style="margin-bottom:18px">
      <h2>✅ Your Inclusive Event Plan is Ready!</h2><p class="muted">A thoughtfully designed experience, grounded in real cultural connections.</p>
      <div class="statbar"><div>👥 ${c.group_size} participants</div><div>🕒 ${c.duration_min} min</div><div>📍 ${esc(c.venue)}</div><div>💜 Inclusive for all abilities</div></div>
      <div class="grid2" style="text-align:left">
        <div><h3>${esc(c.title)}</h3><p>${esc(c.summary)}</p><h4>Activity Agenda</h4><ol class="agenda">${c.agenda.map((a) => `<li><div><b>${esc(a.title)} (${a.minutes} min)</b>${esc(a.detail)}</div></li>`).join("")}</ol>
          <h4>Who does what</h4><ul class="ticks">${c.roles.map((r) => `<li><b>${esc(r.member)}</b> — ${esc(r.role)}</li>`).join("")}</ul></div>
        <div><h3>Qloo Evidence</h3><div class="thumbs">${anchors.map((a) => `<figure>${a.image ? `<img src="${esc(a.image)}" alt=""/>` : `<div class="ph"></div>`}<figcaption>${esc(a.label)}</figcaption></figure>`).join("") || '<p class="muted small">This plan is built on participant-provided overlap.</p>'}</div>
          <p class="small">${refChips(c.evidence_refs, ev)}</p>
          <ul class="ticks">${c.accessibility.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>${(c.safeguards || []).map((m) => `<div class="notice">${esc(m)}</div>`).join("")}
          <p class="muted small">Next steps are manual by design: the organizer invites participants, confirms the venue and accessibility. Culture Connect never messages people or books venues automatically.</p></div>
      </div></div>`;
  }).join("")}
  <div class="row" style="justify-content:center"><button class="btn ghost" id="dl">⬇ Download Plan</button><button class="btn ghost" id="pr">🖨 Print / PDF</button>
    <button class="btn primary" id="cp">⧉ Copy & Share</button><button class="btn soft" id="more">Plan another group</button></div>`;
  bindStepper();
  const getMd = () => fetch(`/api/programs/${S.program.id}/export`).then((r) => r.text());
  $("#dl").onclick = async () => { const blob = new Blob([await getMd()], { type: "text/markdown" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = (S.program.name || "plan").replace(/\W+/g, "_") + ".md"; a.click(); };
  $("#pr").onclick = () => window.print();
  $("#cp").onclick = async () => { try { await navigator.clipboard.writeText(await getMd()); toast("Plan copied — paste it anywhere to share."); } catch { toast("Clipboard blocked — use Download instead", true); } };
  $("#more").onclick = () => go("plan");
}

// ------------------------------------------------------------------ audit drawer + boot
$("#auditBtn").onclick = async () => {
  $("#drawer").classList.add("open");
  const rows = await api("/api/audit").catch(() => []);
  $("#auditList").innerHTML = rows.length ? rows.map((r) => `<div class="audit"><b>${esc(r.status)}</b> · ${r.ms}ms · ${esc(r.path)}<br/>${esc(Object.entries(r.params || {}).map(([k, v]) => k + "=" + v).join("&"))}</div>`).join("") : '<p class="muted">No Qloo calls yet.</p>';
};
$("#drawerClose").onclick = () => $("#drawer").classList.remove("open");

(async function boot() {
  try {
    const [h, m] = await Promise.all([api("/api/health"), api("/api/meta")]);
    S.meta = m;
    const st = $("#status");
    st.textContent = h.qloo_key_configured ? `Qloo ✓ · ${h.planner.startsWith("rule") ? "rule planner" : "LLM planner"}` : "Qloo key missing";
    st.className = "status " + (h.qloo_key_configured ? "ok" : "bad");
    st.title = `Qloo: ${h.qloo_base_url} · Planner: ${h.planner}`;
    api("/api/qloo/check").then(() => {}).catch((e) => { st.textContent = "Qloo unreachable"; st.className = "status bad"; st.title = e.message; });
  } catch (e) { $("#status").textContent = "backend offline"; $("#status").className = "status bad"; }
  route();
})();
