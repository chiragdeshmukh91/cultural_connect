/* Culture Connect — unified authenticated workspace.
 * Discover (For you · Circles · Events · Hosts) + inline agent status/drawer, compact visual cards, a drag-and-drop interest
 * board and a Circle planning board. Every card is rendered from real API data; every action calls the real backend.
 * Legacy routes (#/dashboard, #/circles, #/activities, #/orgs, #/agent) stay valid and render inside this workspace.
 */
(() => {
  "use strict";
  const app = document.getElementById("app");
  const X = () => window.CCAPI;
  const capi = (...a) => X().capi(...a);
  const me = () => X().CC;
  const myTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } };
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------ icons (stroke, 24px grid)
  const P = {
    music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    sport: '<circle cx="12" cy="12" r="9"/><path d="M12 3a15 15 0 0 1 0 18M3 12h18M5.6 5.6c3.5 2.6 9.3 2.6 12.8 0M5.6 18.4c3.5-2.6 9.3-2.6 12.8 0"/>',
    camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/>',
    book: '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2zM22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    leaf: '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z"/><path d="M2 21c0-3 1.9-5.4 5.1-6"/>',
    game: '<rect x="2" y="7" width="20" height="11" rx="5"/><path d="M6 12h4M8 10v4"/><circle cx="15.5" cy="11" r=".8"/><circle cx="17.5" cy="13.5" r=".8"/>',
    plane: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
    food: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7"/>',
    palette: '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.6-.7 1.6-1.7 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1a1.6 1.6 0 0 1 1.6-1.6h2c3 0 5.6-2.5 5.6-5.6C22 6 17.5 2 12 2z"/>',
    crown: '<path d="M2 4l3 12h14l3-12-6 7-4-7-4 7-6-7zM5 20h14"/>',
    hands: '<path d="M11 14h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m7 20 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="m2 15 6 6"/><path d="M19.5 8.5c.7-.7 1.5-1.6 1.5-2.7A2.7 2.7 0 0 0 18.3 3c-.8 0-1.5.3-2 .8l-.3.3-.3-.3c-.5-.5-1.2-.8-2-.8A2.7 2.7 0 0 0 11 5.8c0 1.2.8 2 1.5 2.7L16 12z"/>',
    heart: '<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/><path d="M3.2 12H9l.5-1 2 4.5 2-7 1.5 3.5h5.3"/>',
    film: '<rect x="2" y="2" width="20" height="20" rx="2.5"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
    sparkle: '<path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/><path d="M19 3v4M17 5h4"/>',
    compass: '<circle cx="12" cy="12" r="10"/><path d="m16.2 7.8-2.1 6.3-6.3 2.1 2.1-6.3z"/>',
    building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    bot: '<rect x="3" y="8" width="18" height="12" rx="3"/><path d="M12 8V4M8 14h.01M16 14h.01M9 18h6"/><circle cx="12" cy="3" r="1"/>',
    check: '<path d="M20 6 9 17l-5-5"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>', star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>', gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>', shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>', key: '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.3-9.3M17 6l3 3M14 9l2 2"/>', logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>', idcard: '<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="8" cy="12" r="2.5"/><path d="M14 10h5M14 14h3"/>', chev: '<path d="m9 6 6 6-6 6"/>', ban: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>', trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>', search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>', grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>', refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/>',
  };
  const ic = (k, cls = "") => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[k] || P.sparkle}</svg>`;

  // Themes: an interest/title maps to an icon, gradient and (when the project has one) a real photo asset.
  const THEMES = [
    ["music", /music|jazz|song|band|guitar|piano|concert|blues|soul|sing|choir|drum|dj|listening|podcast|artist/, "music", ["#7c3aed", "#ec4899"], "/assets/music.jpg"],
    ["film", /film|movie|cinema|screening|watch|tv\b|series|documentar/, "film", ["#1d1b3a", "#6d4aff"], "/assets/cinema.jpg"],
    ["art", /art|paint|draw|sketch|craft|pottery|clay|ceramic|design|sculpt|handicraft/, "palette", ["#f97316", "#ec4899"], "/assets/art.jpg"],
    ["book", /book|read|poetry|poem|story|writing|literature|novel|library|educat|school|learning|tutor|literacy/, "book", ["#0ea5e9", "#6366f1"], "/assets/story.jpg"],
    ["photo", /photo|camera|film photography|portrait/, "camera", ["#0f766e", "#22c55e"], ""],
    ["sport", /cricket|football|soccer|tennis|sport|yoga|run|fitness|cycling|badminton|basketball|swim|hockey|gym/, "sport", ["#16a34a", "#0ea5e9"], ""],
    ["nature", /nature|hike|hiking|garden|climate|trek|bird|plant|environment|outdoor|forest|wildlife/, "leaf", ["#15803d", "#84cc16"], ""],
    ["chess", /chess|board game|puzzle|strategy/, "crown", ["#334155", "#7c3aed"], ""],
    ["game", /gaming|game|minecraft|esport|video/, "game", ["#4f46e5", "#06b6d4"], ""],
    ["travel", /travel|trip|explore|journey|backpack/, "plane", ["#0284c7", "#f59e0b"], ""],
    ["food", /cook|food|baking|cuisine|recipe|chef|tea|coffee/, "food", ["#ea580c", "#facc15"], "/assets/craft.jpg"],
    ["care", /volunteer|charity|feeding|dog|animal|community|ngo|cause|welfare|service|senior|elder|youth|neighbour|neighbor|shelter/, "hands", ["#db2777", "#f59e0b"], ""],
    ["health", /diabetes|health|wellbeing|support|mental|caregiv|recovery|cancer|asthma/, "heart", ["#0d9488", "#38bdf8"], ""],
    ["talk", /politic|debate|civic|discussion|dialogue|language|speak/, "mic", ["#9333ea", "#0ea5e9"], ""],
  ];
  function theme(text) {
    const t = String(text || "").toLowerCase();
    const hit = THEMES.find(([, re]) => re.test(t));
    return hit ? { key: hit[0], icon: hit[2], g: hit[3], photo: hit[4] } : { key: "default", icon: "sparkle", g: ["#5b3fd6", "#ec4899"], photo: "" };
  }
  function art(text, extra = "", size = "") {
    const th = theme(text);
    const bg = th.photo ? `linear-gradient(135deg,${th.g[0]}d9,${th.g[1]}cc),url(${th.photo})` : `linear-gradient(135deg,${th.g[0]},${th.g[1]})`;
    return `<div class="art ${size} t-${th.key}" style="background-image:${bg}" role="img" aria-label="${esc(th.key === "default" ? "Culture Connect" : th.key)} illustration">
      <span class="art-blob b1"></span><span class="art-blob b2"></span>${ic(th.icon, "art-ic")}${extra}</div>`;
  }
  window.wsArt = art;
  window.wsTheme = theme;
  window.wsIcon = ic;

  const RS = { declared: ["you", "You said"], qloo: ["qloo", "Qloo"], app: ["app", "App"], preference: ["app", "App"] };
  const reason = (r) => r ? `<p class="why1"><span class="src ${RS[r.source]?.[0] || "app"}">${RS[r.source]?.[1] || "App"}</span>${esc(r.text)}</p>` : "";
  const bestReason = (rs) => (rs || []).find((r) => r.source === "qloo") || (rs || [])[0];
  function wall(s) { const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(s || ""); return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : null; }
  const dateBadge = (s) => { const d = wall(s); return d ? `<span class="date-badge"><b>${d.getDate()}</b>${esc(d.toLocaleDateString(undefined, { month: "short" }))}</span>` : ""; };
  const whenTxt = (e) => { const d = wall(e.starts_at); return d ? `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} · ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` : ""; };
  const locTxt = (e) => e.location_status === "online" ? "Online" : e.location_status === "confirmed" ? [e.venue_name, e.address].filter(Boolean).join(", ") : "Location to be confirmed";

  // ------------------------------------------------------------------ cards
  function circleTile(c, opts = {}) {
    const tags = [...new Set((c.signals || []).map((s) => s.name).concat(c.topic_label ? [c.topic_label] : []))].slice(0, 2);
    const act = opts.action !== undefined ? opts.action : c.my_status === "active" ? `<a class="btn soft sm" href="#/c/${esc(c.id)}">Open</a>`
      : c.my_status === "pending" ? `<span class="pill">Request pending</span>`
      : `<button class="btn primary sm" data-join="${esc(c.id)}">${c.join_mode === "request" ? "Request to join" : "Join"}</button>`;
    return `<article class="cc-tile" data-item="circle:${esc(c.id)}">${art(`${c.topic_label || ""} ${c.name}`, opts.dismiss ? `<button class="tile-x" data-dismiss="circle:${esc(c.id)}" aria-label="Not interested in ${esc(c.name)}">${ic("x")}</button>` : "")}
      <div class="tile-b"><a class="tile-t" href="#/c/${esc(c.id)}">${esc(c.name)}</a>
        <div class="tags">${tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
        ${opts.noReason ? "" : reason(bestReason(c.reasons))}
        <div class="tile-f"><span class="meta">${ic("users")}${c.member_count} member${c.member_count === 1 ? "" : "s"}${c.area ? ` · ${esc(c.area)}` : c.meeting_mode === "online" ? " · Online" : ""}</span>${act}</div></div></article>`;
  }
  function eventTile(e, opts = {}) {
    const host = e.owner ? (e.owner.kind === "org" ? `${esc(e.owner.name)}${e.owner.verification_status === "verified" ? ` <span class="vok" title="Verified organisation">${ic("check")}</span>` : ""}` : esc(e.owner.name)) : "";
    const act = e.my_rsvp === "going" ? `<span class="pill ok">${ic("check")} Going</span>` : e.my_rsvp ? `<a class="btn soft sm" href="#/e/${esc(e.id)}">${esc(e.my_rsvp.replace("_", " "))}</a>`
      : `<button class="btn primary sm" data-rsvp="${esc(e.id)}">RSVP</button>`;
    return `<article class="cc-tile" data-item="event:${esc(e.id)}">${art(`${e.title} ${(e.interest_tags || []).join(" ")} ${e.category || ""}`, dateBadge(e.starts_at) + (opts.dismiss ? `<button class="tile-x" data-dismiss="event:${esc(e.id)}" aria-label="Not interested in ${esc(e.title)}">${ic("x")}</button>` : ""))}
      <div class="tile-b"><a class="tile-t" href="#/e/${esc(e.id)}">${esc(e.title)}</a>
        <div class="meta">${ic("calendar")}${esc(whenTxt(e))}</div>
        <div class="meta">${ic("pin")}${esc(locTxt(e))}</div>
        ${opts.noReason ? "" : reason(bestReason(e.reasons))}
        <div class="tile-f"><span class="meta">${host ? `${ic(e.owner.kind === "org" ? "building" : "users")}${host}` : ""}</span>${act}</div></div></article>`;
  }
  function proposalTile(p) {
    return `<article class="cc-tile prop">${art(p.title, `<span class="date-badge prop-b">Proposal</span>`)}
      <div class="tile-b"><a class="tile-t" href="${esc(p.link)}">${esc(p.title)}</a>
        <div class="meta">${ic("users")}${esc(p.circle_name)} · by ${esc(p.by)}</div>
        <p class="why1"><span class="src app">Not confirmed</span>Members vote first; a host approves before it becomes an event.</p>
        <div class="tile-f"><span></span><a class="btn soft sm" href="${esc(p.link)}">Vote</a></div></div></article>`;
  }
  window.wsCircleTile = circleTile;
  window.wsEventTile = eventTile;

  // ------------------------------------------------------------------ workspace chrome (header + tabs + agent pill)
  const TABS = [["dashboard", "For you", "sparkle"], ["circles", "Circles", "users"], ["activities", "Events", "calendar"], ["orgs", "Hosts", "building"]];
  const WS_ROUTES = ["dashboard", "circles", "activities", "orgs", "agent"];
  window.wsSet = (r) => {
    const on = WS_ROUTES.includes(r) && me() && me().me;
    if (on) app.dataset.ws = r; else delete app.dataset.ws;
    document.body.classList.toggle("signed", !!(me() && me().auth));
    document.body.classList.toggle("has-profile", !!(me() && me().me));
    botNav();
  };
  function chromeHtml(r) {
    return `<div class="ws-head"><div class="ws-hl"><h1>Your next connection starts here.</h1></div>
      <div class="ws-tools"><form class="ws-search" role="search"><label class="sr" for="wsQ">Search Circles and events</label>${ic("search")}<input id="wsQ" type="search" placeholder="Search an interest…" maxlength="60"/></form>
        <button class="agent-pill" id="wsAgent" type="button" aria-haspopup="dialog" aria-controls="agDrawer"><span class="ap-dot"></span><span id="wsAgentTxt">Checking agents…</span></button></div></div>
      <nav class="ws-tabs" aria-label="Discover sections">${TABS.map(([k, l, i]) => `<a href="#/${k}" class="${r === k ? "on" : ""}" ${r === k ? 'aria-current="page"' : ""}>${ic(i)}${l}</a>`).join("")}</nav>`;
  }
  function ensureChrome() {
    const r = app.dataset.ws;
    if (!r || app.querySelector(":scope > .ws-head")) return;
    app.insertAdjacentHTML("afterbegin", chromeHtml(r));
    const f = app.querySelector(".ws-search");
    f.onsubmit = (e) => { e.preventDefault(); const q = document.getElementById("wsQ").value.trim(); location.hash = `#/circles${q ? `?q=${encodeURIComponent(q)}` : ""}`; };
    document.getElementById("wsAgent").onclick = openDrawer;
    agentPill();
  }
  new MutationObserver(ensureChrome).observe(app, { childList: true });

  // ------------------------------------------------------------------ agent status (inline pill + drawer)
  const STAGE_TXT = { profile_saved: "Saving your preferences", qloo_resolution: "Understanding your interests", cultural_insights: "Asking Qloo for cultural links",
    circle_matching: "Finding compatible Circles", event_matching: "Finding events", ranking: "Ranking your matches", recommendations_ready: "Saving recommendations" };
  let pillTimer = null, lastState = null;
  async function agentState() {
    const [d, s] = await Promise.all([capi("/api/agent/discovery").catch(() => null), capi("/api/agent/summary").catch(() => null)]);
    const st = d && d.status;
    let txt = "Up to date", cls = "ok";
    if (st && st.state === "running") {
      const cur = st.stages.find((x) => ["running", "pending"].includes(x.state));
      txt = (cur && STAGE_TXT[cur.key]) || "Discovering your interests"; cls = "run";
    } else if (s && s.approvals_pending) { txt = `Waiting for your approval (${s.approvals_pending})`; cls = "ask"; }
    else if (s && s.invites_pending) { txt = `${s.invites_pending} Circle invitation${s.invites_pending === 1 ? "" : "s"}`; cls = "ask"; }
    else if (s && s.running) { txt = "Planning activities"; cls = "run"; }
    else if (st && st.state === "failed") { txt = "Discovery failed — retry"; cls = "err"; }
    else if (st && st.state === "consent_off") { txt = "Discovery off"; cls = "off"; }
    else if (d && d.result && d.result.degraded) { txt = "Partial results"; cls = "ask"; }
    return { d, s, txt, cls };
  }
  async function agentPill() {
    clearTimeout(pillTimer);
    const el = document.getElementById("wsAgentTxt");
    if (!el) return;
    const a = await agentState();
    const pill = document.getElementById("wsAgent");
    if (!pill) return;
    el.textContent = a.txt; pill.dataset.state = a.cls;
    const busy = a.cls === "run";
    if (lastState === "run" && !busy && app.dataset.ws === "dashboard" && window.wsForYou) window.wsForYou(true);  // results arrived
    lastState = a.cls;
    if (busy) pillTimer = setTimeout(agentPill, 2500);
  }
  window.wsAgentPill = agentPill;

  function drawer() {
    let d = document.getElementById("agDrawer");
    if (!d) {
      document.body.insertAdjacentHTML("beforeend", `<div class="ag-scrim" id="agScrim" hidden></div><aside class="ag-drawer" id="agDrawer" role="dialog" aria-modal="true" aria-labelledby="agDT" hidden>
        <div class="row between"><h3 id="agDT">${ic("bot")} Agent activity</h3><button class="iconbtn" id="agClose" aria-label="Close">${ic("x")}</button></div><div id="agDBody"></div></aside>`);
      d = document.getElementById("agDrawer");
      const close = () => { d.hidden = true; document.getElementById("agScrim").hidden = true; document.getElementById("wsAgent")?.focus(); };
      document.getElementById("agClose").onclick = close;
      document.getElementById("agScrim").onclick = close;
      d.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    }
    return d;
  }
  async function openDrawer() {
    const d = drawer();
    d.hidden = false; document.getElementById("agScrim").hidden = false;
    const body = document.getElementById("agDBody");
    body.innerHTML = `<div class="skel"></div>`;
    document.getElementById("agClose").focus();
    await fillDrawer(body);
  }
  async function fillDrawer(body) {
    const [a, inv, appr, runs] = await Promise.all([agentState(), capi("/api/agent/invites").catch(() => []), capi("/api/agent/approvals").catch(() => []),
      capi("/api/agent/runs?limit=6").catch(() => [])]);
    const st = a.d && a.d.status;
    const NAME = { discovery: "Discovery", circle_formation: "Circle formation", event_planning: "Activity planning", coordinate_proposal: "Vote tally",
      event_followup: "Event follow-up", event_followup_votes: "Vote reminder" };
    const pend = inv.filter((v) => v.my_status === "invited" && v.status !== "cancelled");
    body.innerHTML = `<p class="ag-now" data-state="${a.cls}"><span class="ap-dot"></span>${esc(a.txt)}</p>
      ${st ? `<ol class="mini-stages">${st.stages.map((s) => `<li class="s-${s.state}" title="${esc(s.message || "")}">${esc(s.label)}</li>`).join("")}</ol>` : ""}
      ${st && (st.state === "failed" || (a.d.result && a.d.result.degraded)) ? `<button class="btn soft sm" id="agRetry">${ic("refresh")} Retry discovery</button>` : ""}
      ${pend.length ? `<h4>Invitations</h4>${pend.map((v) => `<div class="ag-item"><b>${esc(v.name)}</b><span class="muted tiny">${v.counts.accepted}/${v.min_size} accepted · ${esc((v.my_reasons[0] || {}).text || "")}</span>
        <div class="row end"><button class="btn ghost sm" data-inv="${esc(v.id)}" data-act="decline">Not for me</button><button class="btn primary sm" data-inv="${esc(v.id)}" data-act="accept">Join</button></div></div>`).join("")}` : ""}
      ${appr.length ? `<h4>Activities</h4>${appr.map((x) => `<div class="ag-item"><b>${esc(x.title)}</b><span class="muted tiny">${esc(x.circle_name)} · ${x.stage === "voting" ? "voting open" : `ready: ${esc(x.selected.time || "")}${x.selected.place ? " · " + esc(x.selected.place.name) + " (not booked)" : ""}`}</span>
        <div class="row end">${x.can_approve ? `<button class="btn ghost sm" data-appr="${esc(x.id)}" data-act="reject">Reject</button><button class="btn primary sm" data-appr="${esc(x.id)}" data-act="approve" data-tz="${esc(x.selected.timezone)}">Approve</button>`
          : `<a class="btn soft sm" href="#/c/${esc(x.circle_id)}/events">Vote</a>`}</div></div>`).join("")}` : ""}
      <h4>Recent work</h4>${runs.map((r) => `<div class="ag-run-row"><span class="rs ${esc(r.status)}">${esc(r.status)}</span><div><b>${esc(NAME[r.kind] || r.kind)}</b>${r.circle_name ? ` · ${esc(r.circle_name)}` : ""}
        <div class="muted tiny">${esc(r.trigger)}</div>${r.error ? `<div class="form-err tiny">${esc(r.error)}</div>` : ""}</div></div>`).join("") || `<p class="muted small">Nothing yet.</p>`}
      <div class="row between" style="margin-top:12px"><a href="#/agent/runs" class="small">Full step-by-step log</a><a href="#/agent/settings" class="small">Agent settings</a></div>`;
    body.querySelectorAll("a").forEach((l) => l.addEventListener("click", () => { document.getElementById("agDrawer").hidden = true; document.getElementById("agScrim").hidden = true; }));
    const rb = document.getElementById("agRetry");
    if (rb) rb.onclick = () => withBusy(rb, async () => { const x = await capi("/api/agent/discovery/refresh", { method: "POST", body: {} }); toast(x.queued ? "Discovery restarted" : x.message, !x.queued); agentPill(); fillDrawer(body); });
    body.querySelectorAll("[data-inv]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const v = await capi(`/api/agent/invites/${b.dataset.inv}/${b.dataset.act}`, { method: "POST", body: {} });
      celebrate(b); toast(b.dataset.act === "accept" ? (v.status === "formed" ? "Circle formed — you're in!" : "Accepted — it forms when enough people join") : "Declined");
      fillDrawer(body); agentPill();
    }));
    body.querySelectorAll("[data-appr]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      if (b.dataset.act === "approve") { const r = await capi(`/api/agent/approvals/${b.dataset.appr}/approve`, { method: "POST", body: { timezone: b.dataset.tz || myTz() } }); toast("Published — nothing is booked automatically"); location.hash = `#/e/${r.event_id}`; }
      else { await capi(`/api/agent/approvals/${b.dataset.appr}/reject`, { method: "POST", body: {} }); toast("Rejected"); fillDrawer(body); }
    }));
  }

  function celebrate(el) {
    if (reduce || !el) return;
    const r = el.getBoundingClientRect();
    const s = document.createElement("span"); s.className = "pop"; s.style.left = `${r.left + r.width / 2}px`; s.style.top = `${r.top}px`;
    document.body.appendChild(s); setTimeout(() => s.remove(), 700);
  }

  // ------------------------------------------------------------------ "For you" — the main Discover view
  let fyTimer = null;
  window.wsForYou = async (quiet = false) => {
    clearTimeout(fyTimer);
    const p = me().me;
    if (!quiet || !app.querySelector(".fy")) app.innerHTML = `<div class="fy">${'<div class="skel big"></div>'}<div class="cc-tiles">${'<div class="skel tile-sk"></div>'.repeat(3)}</div></div>`;
    const [res, mine] = await Promise.all([capi("/api/agent/discovery").catch(() => ({ result: null, status: null })), capi("/api/me/circles").catch(() => [])]);
    if (app.dataset.ws !== "dashboard") return;
    const r = res.result, st = res.status || {};
    const running = st.state === "running";
    const top = (r && r.top) || [];
    const feat = top[0];
    const shownC = new Set(feat && feat.type === "circle" ? [feat.id] : []), shownE = new Set(feat && feat.type === "event" ? [feat.id] : []);
    const circles = ((r && r.circles) || []).filter((c) => !shownC.has(c.id)).slice(0, 3);
    const events = ((r && r.events) || []).filter((e) => !shownE.has(e.id)).slice(0, 4);
    const props = ((r && r.proposals) || []).slice(0, 2);
    const reasonTxt = (x) => { const b = bestReason(x.reasons); return b ? b.text : ""; };
    const featAction = !feat ? "" : feat.type === "circle" ? `<a class="btn ghost-w" href="#/c/${esc(feat.id)}">Explore Circle</a><button class="btn white" data-join="${esc(feat.id)}">${feat.join_mode === "request" ? "Request to join" : "Join"}</button>`
      : feat.my_rsvp === "going" ? `<span class="pill ok">${ic("check")} You're going</span><a class="btn ghost-w" href="#/e/${esc(feat.id)}">Details</a>` : `<a class="btn ghost-w" href="#/e/${esc(feat.id)}">Details</a><button class="btn white" data-rsvp="${esc(feat.id)}">RSVP</button>`;
    const featTags = feat ? (feat.type === "circle" ? [...new Set((feat.signals || []).map((s) => s.name).concat([feat.topic_label]))] : feat.interest_tags || []).slice(0, 2) : [];
    const emptyLine = (txt, href, label) => `<div class="empty-line"><span>${esc(txt)}</span>${href ? `<a class="btn soft sm" href="${href}">${label}</a>` : ""}</div>`;
    app.innerHTML = `<div class="fy">
      ${!p.discoverable ? emptyLine("Discovery is off, so we can't recommend anything yet.", "#/me", "Turn it on") : ""}
      ${feat ? `<section class="fy-feature" aria-label="Featured for you">${art(feat.type === "circle" ? `${feat.topic_label} ${feat.name}` : `${feat.title} ${(feat.interest_tags || []).join(" ")}`, feat.type === "event" ? dateBadge(feat.starts_at) : "", "feat-art")}
        <div class="feature-b"><span class="kicker">${ic(feat.type === "circle" ? "users" : "calendar")}${feat.type === "circle" ? "Circle picked for you" : "Event picked for you"}</span>
          <h2>${esc(feat.type === "circle" ? feat.name : feat.title)}</h2>
          <div class="tags">${featTags.map((t) => `<span class="tag w">${esc(t)}</span>`).join("")}${feat.type === "event" ? `<span class="tag w">${esc(whenTxt(feat))}</span>` : `<span class="tag w">${feat.member_count} member${feat.member_count === 1 ? "" : "s"}</span>`}</div>
          <p>${esc(reasonTxt(feat))}</p><div class="row">${featAction}</div></div></section>`
        : running ? `<section class="fy-feature finding"><div class="finder">${ic("compass", "spin")}</div><div class="feature-b"><span class="kicker">${ic("bot")}Working on it</span><h2>Finding your people…</h2><p id="fyStage">Understanding your interests with Qloo.</p></div></section>`
        : st.state === "failed" ? emptyLine("Discovery couldn't finish.", "", "") + `<button class="btn soft sm" id="fyRetry">${ic("refresh")} Retry</button>`
        : emptyLine(r ? "Nothing matches your interests yet — new Circles are being formed for you." : "No recommendations yet.", "#/me", r ? "Add interests" : "Set up interests")}
      ${r && r.degraded ? `<p class="note">${ic("refresh")} Some Qloo data was unavailable, so these results are partial. We'll retry automatically.</p>` : ""}
      <div class="sec-row"><h2>${ic("users")} Circles for you</h2><a href="#/circles" class="more">See all ${ic("arrow")}</a></div>
      ${circles.length ? `<div class="cc-tiles">${circles.map((c) => circleTile(c, { dismiss: true })).join("")}</div>` : running ? `<div class="cc-tiles">${'<div class="skel tile-sk"></div>'.repeat(3)}</div>` : emptyLine(mine.length ? "No other Circles fit right now." : "No Circles fit yet.", "#/circles", "Browse Circles")}
      <div class="sec-row"><h2>${ic("calendar")} Coming up</h2><a href="#/activities" class="more">All events ${ic("arrow")}</a></div>
      ${events.length || props.length ? `<div class="cc-tiles">${events.map((e) => eventTile(e, { dismiss: true })).join("")}${props.map(proposalTile).join("")}</div>` : running ? `<div class="cc-tiles">${'<div class="skel tile-sk"></div>'.repeat(2)}</div>` : emptyLine("Nothing planned yet.", "#/activities", "Find an activity")}
      ${mine.length ? `<div class="sec-row"><h2>${ic("compass")} Your Circles</h2><a href="#/my" class="more">My Circles ${ic("arrow")}</a></div>
        <div class="chiprow">${mine.slice(0, 8).map((c) => `<a class="mini-circle" href="#/c/${esc(c.id)}"><span class="mc-ic" style="background:linear-gradient(135deg,${theme(c.topic_label).g.join(",")})">${ic(theme(c.topic_label).icon)}</span>${esc(c.name)}${c.my_status === "pending" ? ' <em>pending</em>' : ""}</a>`).join("")}</div>` : ""}
      ${r ? interestBoard(p, r) : ""}
    </div>`;
    bindActions(app, () => window.wsForYou(true));
    const rb = document.getElementById("fyRetry");
    if (rb) rb.onclick = () => withBusy(rb, async () => { await capi("/api/agent/discovery/refresh", { method: "POST", body: {} }); window.wsForYou(); agentPill(); });
    bindBoard();
    if (running) {
      const cur = (st.stages || []).find((x) => ["running", "pending"].includes(x.state));
      const s = document.getElementById("fyStage"); if (s && cur) s.textContent = `${STAGE_TXT[cur.key] || "Working"}…`;
      fyTimer = setTimeout(() => app.dataset.ws === "dashboard" && window.wsForYou(true), 2500);
      agentPill();
    }
  };

  function bindActions(root, after) {
    root.querySelectorAll("[data-join]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const j = await capi(`/api/circles/${b.dataset.join}/join`, { method: "POST", body: {} });
      celebrate(b); toast(j.status === "active" ? "You're in! 🎉" : "Request sent — a host will review it");
      setTimeout(after, 600);
    }));
    root.querySelectorAll("[data-rsvp]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      await capi(`/api/events/${b.dataset.rsvp}/rsvp`, { body: { status: "going" } });
      celebrate(b); toast("RSVP saved — see you there!");
      b.outerHTML = `<span class="pill ok">${ic("check")} Going</span>`;
    }));
    root.querySelectorAll("[data-dismiss]").forEach((b) => b.onclick = (e) => { e.preventDefault(); withBusy(b, async () => {
      const [t, ...rest] = b.dataset.dismiss.split(":");
      await capi("/api/agent/feedback", { body: { item_type: t, item_id: rest.join(":"), action: "dismissed" } });
      const card = b.closest(".cc-tile"); if (card) { card.classList.add("gone"); setTimeout(() => card.remove(), reduce ? 0 : 250); }
      toast("Hidden — we won't suggest it again");
    }); });
  }
  window.wsBindActions = bindActions;

  // ------------------------------------------------------------------ drag-and-drop interest board
  function interestBoard(p, r) {
    const declared = (p.interests || []).map((i) => ({ label: i.label, q: (i.signals || []).length > 0 }));
    const saved = (r.discover_new || []).filter((x) => x.saved);
    const explore = (r.discover_new || []).filter((x) => !x.saved);
    const gone = r.not_interested || [];
    if (!declared.length && !explore.length && !saved.length) return "";
    const chip = (x, from) => `<li class="ichip q" draggable="true" tabindex="0" data-id="${esc(x.id)}" data-from="${from}" aria-label="${esc(x.name)} — Qloo discovery">
      ${ic("grip", "grip")}<span>${esc(x.name)}</span><span class="ichip-b">
      ${from !== "mine" ? `<button type="button" data-move="mine" aria-label="Add ${esc(x.name)} to my interests">${ic("star")}</button>` : ""}
      ${from !== "explore" ? `<button type="button" data-move="explore" aria-label="Move ${esc(x.name)} back to explore">${ic("refresh")}</button>` : ""}
      ${from !== "no" ? `<button type="button" data-move="no" aria-label="Not interested in ${esc(x.name)}">${ic("x")}</button>` : ""}</span></li>`;
    return `<section class="iboard" aria-label="Tune your discoveries">
      <div class="sec-row"><h2>${ic("sparkle")} Tune your discoveries</h2><span class="muted small">Drag, or use the buttons. Qloo found these from your interests.</span></div>
      <div class="ib-cols">
        <div class="ib-col" data-zone="mine"><h3>My interests</h3><ul>
          ${declared.map((d) => `<li class="ichip mine" title="From your profile">${ic("lock", "grip")}<span>${esc(d.label)}</span></li>`).join("")}
          ${saved.map((x) => chip(x, "mine")).join("")}</ul><a href="#/me" class="tiny">Edit profile interests</a></div>
        <div class="ib-col" data-zone="explore"><h3>Explore more <span class="src qloo">Qloo</span></h3><ul>${explore.map((x) => chip(x, "explore")).join("") || `<li class="muted small">Nothing new right now.</li>`}</ul></div>
        <div class="ib-col" data-zone="no"><h3>Not interested</h3><ul>${gone.map((x) => chip(x, "no")).join("") || `<li class="muted small">Drop here to hide.</li>`}</ul></div>
      </div></section>`;
  }
  const ACTION = { mine: "saved", no: "dismissed", explore: "clear" };
  async function moveChip(li, to) {
    if (!li || li.dataset.from === to) return;
    const id = li.dataset.id;
    const zone = app.querySelector(`.ib-col[data-zone="${to}"] ul`);
    const prev = li.parentElement;
    zone.appendChild(li); li.dataset.from = to; li.classList.add("moving");  // optimistic
    try {
      await capi("/api/agent/feedback", { body: { item_type: "interest", item_id: id, action: ACTION[to] } });
      toast(to === "mine" ? "Added — your matches are updating" : to === "no" ? "Hidden from your discoveries" : "Moved back to explore");
      setTimeout(() => app.dataset.ws === "dashboard" && window.wsForYou(true), 1500);
    } catch (e) { prev.appendChild(li); toast(e.message, true); }
    finally { li.classList.remove("moving"); }
  }
  function bindBoard() {
    const board = app.querySelector(".iboard");
    if (!board) return;
    let dragging = null;
    board.querySelectorAll(".ichip.q").forEach((li) => {
      li.addEventListener("dragstart", (e) => { dragging = li; e.dataTransfer.setData("text/plain", li.dataset.id); e.dataTransfer.effectAllowed = "move"; li.classList.add("drag"); });
      li.addEventListener("dragend", () => { li.classList.remove("drag"); board.querySelectorAll(".ib-col").forEach((c) => c.classList.remove("over")); });
      li.addEventListener("keydown", (e) => { const k = { "1": "mine", "2": "explore", "3": "no" }[e.key]; if (k) moveChip(li, k); });
    });
    board.querySelectorAll(".ib-col").forEach((col) => {
      col.addEventListener("dragover", (e) => { if (!dragging) return; e.preventDefault(); col.classList.add("over"); });
      col.addEventListener("dragleave", () => col.classList.remove("over"));
      col.addEventListener("drop", (e) => { e.preventDefault(); col.classList.remove("over"); if (dragging) moveChip(dragging, col.dataset.zone); dragging = null; });
    });
    board.addEventListener("click", (e) => { const b = e.target.closest("[data-move]"); if (b) moveChip(b.closest(".ichip"), b.dataset.move); });
  }

  // ------------------------------------------------------------------ Circle planning board (Activities tab)
  const COLS = [["ideas", "Ideas"], ["proposed", "Proposed"], ["approved", "Approved"], ["completed", "Completed"]];
  window.wsPlanBoard = async (el, c, mod, evs) => {
    const items = [];
    for (const e of evs) {
      if (e.status === "proposed") items.push({ col: "proposed", id: e.id, title: e.title, sub: `${e.source === "agent" ? "Agent draft" : "Member proposal"} · voting`, link: `#/c/${c.id}/events`, kind: "proposal" });
      else if (e.status === "confirmed" && e.event_id) {
        let ev = null; try { ev = await capi(`/api/events/${e.event_id}`); } catch { ev = null; }
        if (!ev || ev.status === "cancelled") continue;
        items.push({ col: ev.status === "completed" ? "completed" : "approved", id: e.event_id, title: ev.title, sub: whenTxt(ev), link: `#/e/${e.event_id}`, kind: "event", status: ev.status });
      }
    }
    el.innerHTML = `<section class="pboard" aria-label="Activity planning board"><div class="sec-row"><h3>${ic("calendar")} Planning board</h3>
      <span class="muted small">${mod ? "Drag a card to the next stage (or use its button). Every move is checked by the server." : "Hosts move activities between stages."}</span></div>
      <div class="pb-cols">${COLS.map(([k, l]) => `<div class="pb-col" data-col="${k}"><h4>${l} <span class="n">${items.filter((i) => i.col === k).length || ""}</span></h4>
        ${k === "ideas" ? `<div class="pb-idea">${art(c.topic_label, "", "sm")}<p class="small">Let the agent draft options from Qloo insights and members' availability.</p>${mod ? `<button class="btn soft sm" id="pbPlan">${ic("sparkle")} Draft with agent</button>` : ""}</div>` : ""}
        ${items.filter((i) => i.col === k).map((i) => `<a class="pb-card" href="${esc(i.link)}" ${mod && i.col !== "completed" ? 'draggable="true"' : ""} data-id="${esc(i.id)}" data-col="${i.col}" data-kind="${i.kind}">
          <b>${esc(i.title)}</b><span class="tiny muted">${esc(i.sub)}</span>
          ${mod && i.col === "proposed" ? `<button type="button" class="btn soft sm" data-adv="approved">Approve ${ic("arrow")}</button>` : ""}
          ${mod && i.col === "approved" ? `<button type="button" class="btn soft sm" data-adv="completed">Mark completed ${ic("arrow")}</button>` : ""}</a>`).join("")}</div>`).join("")}</div></section>`;
    const reload = () => location.hash.includes(`/c/${c.id}/events`) && window.dispatchEvent(new HashChangeEvent("hashchange"));
    async function advance(card, to) {
      const from = card.dataset.col;
      const ok = (from === "proposed" && to === "approved") || (from === "approved" && to === "completed");
      if (!ok) return toast(to === "ideas" ? "Activities can't move back to ideas." : "That move isn't allowed — activities go Proposed → Approved → Completed.", true);
      try {
        if (to === "approved") { await capi(`/api/agent/proposals/${card.dataset.id}/approve-now`, { body: { timezone: myTz() } }); toast("Approved and published — the venue isn't booked automatically"); }
        else { await capi(`/api/events/${card.dataset.id}/complete`, { method: "POST", body: {} }); toast("Marked completed — attendees will be asked for feedback"); }
        celebrate(card); reload();
      } catch (e) {
        const d = e.data && e.data.detail;
        toast(d && d.failed ? `${d.message} ${d.failed.map((f) => f.check).join(", ")}` : e.message, true);
      }
    }
    if (!mod) return;
    const pb = document.getElementById("pbPlan");
    if (pb) pb.onclick = () => withBusy(pb, async () => { const r = await capi(`/api/agent/circles/${c.id}/plan`, { method: "POST", body: {} }); toast(r.queued ? "The planning agent is drafting options…" : r.message, !r.queued); agentPill(); });
    let drag = null;
    el.querySelectorAll(".pb-card[draggable]").forEach((cd) => {
      cd.addEventListener("dragstart", (e) => { drag = cd; e.dataTransfer.setData("text/plain", cd.dataset.id); cd.classList.add("drag"); });
      cd.addEventListener("dragend", () => { cd.classList.remove("drag"); el.querySelectorAll(".pb-col").forEach((x) => x.classList.remove("over")); });
    });
    el.querySelectorAll(".pb-col").forEach((col) => {
      col.addEventListener("dragover", (e) => { if (drag) { e.preventDefault(); col.classList.add("over"); } });
      col.addEventListener("dragleave", () => col.classList.remove("over"));
      col.addEventListener("drop", (e) => { e.preventDefault(); col.classList.remove("over"); if (drag) advance(drag, col.dataset.col); drag = null; });
    });
    el.querySelectorAll("[data-adv]").forEach((b) => b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); withBusy(b, () => advance(b.closest(".pb-card"), b.dataset.adv)); });
  };

  // ------------------------------------------------------------------ mobile bottom navigation
  function botNav() {
    let n = document.getElementById("botNav");
    if (!n) {
      document.body.insertAdjacentHTML("beforeend", `<nav class="botnav" id="botNav" aria-label="Main">
        <a href="#/dashboard" data-k="d">${ic("compass")}<span>Discover</span></a><a href="#/my" data-k="m">${ic("users")}<span>My Circles</span></a>
        <a href="#/notifications" data-k="n">${ic("bot")}<span>Updates</span></a><a href="#/me" data-k="p">${ic("user")}<span>Profile</span></a></nav>`);
      n = document.getElementById("botNav");
    }
    const h = location.hash;
    const k = /^#\/(dashboard|circles|activities|orgs|agent)/.test(h) ? "d" : /^#\/(my|c\/)/.test(h) ? "m" : h.startsWith("#/notifications") ? "n" : h.startsWith("#/me") ? "p" : "";
    n.querySelectorAll("a").forEach((a) => a.classList.toggle("on", a.dataset.k === k));
  }
})();
