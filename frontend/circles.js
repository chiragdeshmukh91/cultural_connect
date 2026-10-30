/* Culture Connect — individuals & Circles (self-serve journey).
 * Loaded after app.js and reuses its helpers (api/esc/toast/withBusy/candHtml/prettyType/initials/color).
 * All authorization is enforced by the backend; this file only renders what the API returns.
 */
(() => {
  "use strict";
  const LS_TOKEN = "cc_token", LS_DRAFT = "cc_draft";
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: in-memory only */ } },
    del(k) { try { localStorage.removeItem(k); } catch { } },
  };
  const CC = { token: store.get(LS_TOKEN, null), me: null, meLoaded: false, rec: null, skipped: new Set(store.get("cc_skipped", [])) };
  const INTENTS = [["enjoy", "😊 Enjoy"], ["teach", "🎓 Can teach"], ["learn", "🌱 Want to learn"], ["discuss", "💬 Discuss"], ["collaborate", "🤝 Collaborate"]];
  const AVAIL = [["weekday_daytime", "☀️ Weekday daytime"], ["weekday_evening", "🌙 Weekday evenings"], ["weekend", "🎉 Weekends"]];
  const PREFS = [["in_person", "🧑‍🤝‍🧑 In person"], ["online", "💻 Online"], ["indoor", "🏠 Indoor"], ["outdoor", "🌳 Outdoor"]];
  const ACCESS = [["wheelchair", "♿ Step-free / wheelchair"], ["quiet_space", "🤫 Quiet space"], ["visual_aids", "🔎 Large print / visual aids"],
    ["captions", "💬 Captions"], ["flexible_participation", "🙌 Flexible participation"]];
  const QUICK = [["🎵", "Music"], ["🏏", "Cricket"], ["✈️", "Travel"], ["📷", "Photography"], ["🎮", "Gaming"], ["📚", "Books"],
    ["🌿", "Nature"], ["🤝", "Volunteering"], ["♟️", "Chess"], ["🎷", "Jazz"], ["🎨", "Painting"], ["🧘", "Yoga"], ["🍳", "Cooking"],
    ["⚽", "Football"], ["🌍", "Climate action"], ["🩺", "Diabetes"]];
  const SRC = { declared: ["participant", "Declared"], qloo: ["qloo", "Qloo-derived"], preference: ["generated", "Preference"] };
  const fmtTime = (ts) => { try { return new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch { return ""; } };
  const fmtIso = (s) => { try { return new Date(s).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }); } catch { return s; } };
  const app = document.getElementById("app");

  // ------------------------------------------------------------------ API with bearer token
  async function capi(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (CC.token) headers.Authorization = "Bearer " + CC.token;
    let res;
    try {
      res = await fetch(path, { method: opts.method || (opts.body ? "POST" : "GET"), headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
    } catch {
      throw Object.assign(new Error("You appear to be offline — check your connection and try again."), { status: 0 });
    }
    const text = await res.text();
    let data; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!res.ok) {
      let msg = data && data.detail;
      if (Array.isArray(msg)) msg = msg.map((d) => d.msg.replace(/^Value error, /, "")).join(" ");
      else if (msg && typeof msg === "object") msg = msg.message || JSON.stringify(msg);
      const err = new Error(msg || `Request failed (${res.status})`);
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  }
  async function loadMe(force = false) {
    if (!CC.token) { CC.me = null; CC.auth = null; CC.meLoaded = true; navState(); return null; }
    if (CC.meLoaded && !force) return CC.me;
    try {
      CC.auth = await capi("/api/auth/me");
      CC.me = CC.auth.has_profile ? await capi("/api/me") : null;
    } catch (e) {
      if (e.status === 401) { CC.token = null; store.del(LS_TOKEN); if (/expired/i.test(e.message)) toast(e.message, true); }
      CC.me = null; CC.auth = null;
    }
    CC.meLoaded = true;
    navState();
    return CC.me;
  }
  function setToken(t) { CC.token = t; if (t) store.set(LS_TOKEN, t); else store.del(LS_TOKEN); CC.meLoaded = false; }

  // ------------------------------------------------------------------ draft from the playground (local only)
  const draft = () => store.get(LS_DRAFT, []);
  window.ccDraftAdd = (label, emoji) => {
    const d = draft();
    if (d.some((x) => x.label.toLowerCase() === String(label).toLowerCase())) return false;
    d.push({ label: String(label).slice(0, 60), emoji: emoji || "✨" });
    store.set(LS_DRAFT, d.slice(0, 12));
    renderDraftTray();
    return true;
  };
  window.ccDraftHas = (label) => draft().some((x) => x.label.toLowerCase() === String(label).toLowerCase());
  function renderDraftTray() {
    let tray = document.getElementById("draftTray");
    const d = draft();
    const onJoin = /^#\/(join|me)/.test(location.hash);
    if (!d.length || onJoin || CC.me) { if (tray) tray.remove(); return; }
    if (!tray) { tray = document.createElement("div"); tray.id = "draftTray"; tray.className = "draft-tray"; document.body.appendChild(tray); }
    tray.innerHTML = `<span class="dt-l">📝 Draft profile</span>${d.slice(0, 4).map((x) => `<span class="dt-chip">${esc(x.emoji)} ${esc(x.label)}</span>`).join("")}
      ${d.length > 4 ? `<span class="dt-chip">+${d.length - 4}</span>` : ""}<a class="btn primary sm" href="#/join">Continue →</a>
      <button class="iconbtn" type="button" aria-label="Clear draft" id="dtClear">✕</button>`;
    tray.querySelector("#dtClear").onclick = () => { store.del(LS_DRAFT); renderDraftTray(); };
  }

  // ------------------------------------------------------------------ nav
  function navState() {
    const nav = document.querySelector(".topnav");
    if (!nav) return;
    if (!nav.querySelector("[data-cc]")) {
      nav.querySelector('a[href="#/how"]')?.insertAdjacentHTML("beforebegin",
        `<a href="#/dashboard" data-cc="dash" hidden>Discover</a><a href="#/my" data-cc="my" hidden>My Circles</a><a href="#/me" data-cc="prof" hidden>Profile</a>
         <a href="#/org" data-cc="orgr" hidden>Organiser</a>
         <a href="#/notifications" data-cc="bell" class="bell" hidden aria-label="Notifications">🔔<span class="bell-n" hidden></span></a>
         <a href="#/auth/signin" data-cc="join" class="nav-cta">Sign in</a>`);
      const how = nav.querySelector('a[href="#/how"]');
      if (how) how.after(nav.querySelector('[data-cc="join"]'));
    }
    const signed = !!CC.auth;
    // Signed-in navigation is three destinations (Discover · My Circles · Profile); Home and How it works stay public.
    nav.querySelector('[data-cc="dash"]').hidden = !CC.me;
    nav.querySelector('[data-cc="my"]').hidden = !CC.me;
    nav.querySelector('[data-cc="prof"]').hidden = !CC.me;
    nav.querySelector('[data-cc="orgr"]').hidden = !(CC.auth && CC.auth.orgs && CC.auth.orgs.length);
    nav.querySelector('[data-cc="bell"]').hidden = !signed;
    nav.querySelectorAll('a[href="#/"], a[href="#/how"]').forEach((a) => (a.hidden = !!CC.me));
    const j = nav.querySelector('[data-cc="join"]');
    j.textContent = signed ? (CC.me ? CC.me.alias : "Finish setup") : "Sign in";
    j.setAttribute("href", signed ? (CC.me ? "#/me" : "#/start") : "#/auth/signin");
    j.hidden = !!CC.me;  // the Profile link covers it
    if (window.ppNav) window.ppNav();
    const h = location.hash || "#/";
    const ws = /^#\/(dashboard|circles|activities|orgs|agent)/.test(h);
    nav.querySelectorAll("a").forEach((a) => a.classList.toggle("on", a.dataset.cc === "dash" ? ws : a.dataset.cc === "my" ? /^#\/(my|c\/)/.test(h)
      : a.getAttribute("href") !== "#/" ? h.startsWith(a.getAttribute("href")) : h === "#/" || h === ""));
  }

  // ------------------------------------------------------------------ router hook (called by app.js route())
  window.ccRoute = async (parts) => {
    const r = (parts[0] || "").split("?")[0];
    if (window.ppRoute && ["auth", "start", "dashboard", "activities", "orgs", "o", "org", "org-invite", "e", "notifications", "admin", "agent"].includes(r)) {
      await loadMe(); renderDraftTray();
      if (window.wsSet) window.wsSet(r);
      try { await window.ppRoute(r, parts); } catch (e) { fail(e); }
      return true;
    }
    if (!["join", "me", "circles", "my", "c"].includes(r)) { if (window.wsSet) window.wsSet(r); return false; }
    await loadMe();
    if (window.wsSet) window.wsSet(r);
    navState();
    renderDraftTray();
    try {
      if ((r === "join" || r === "me" || r === "my") && !CC.auth) { location.hash = `#/auth/${r === "join" ? "signup" : "signin"}?next=${r}`; return true; }
      if (r === "join") await (CC.me ? viewProfile(true) : viewJoin());
      else if (r === "me") await (CC.me ? viewProfile(false) : viewJoin());
      else if (r === "circles") await viewDiscover(parts[1]);
      else if (r === "my") await (CC.me ? viewMy() : viewRestore());
      else if (r === "c" && parts[1]) await viewCircle(parts[1].split("?")[0], (parts[2] || "chat").split("?")[0]);
      else return false;
    } catch (e) { fail(e); }
    return true;
  };
  function fail(e) {
    const unauth = e.status === 401;
    app.innerHTML = `<div class="card empty-state"><div class="es-ic">${unauth ? "🔐" : e.status === 403 ? "🚫" : e.status === 404 ? "🔍" : "⚠️"}</div>
      <h2>${unauth ? "Please create a profile or restore it" : e.status === 404 ? "Not found" : e.status === 403 ? "Not allowed" : "Something went wrong"}</h2>
      <p class="muted">${esc(e.message)}</p><div class="row" style="justify-content:center">
      <a class="btn primary" href="${unauth ? "#/join" : "#/circles"}">${unauth ? "Join" : "Back to Circles"}</a></div></div>`;
  }
  const queryParam = (k) => { const m = location.hash.match(new RegExp(`[?&]${k}=([^&]+)`)); return m ? decodeURIComponent(m[1]) : null; };

  // home: add individual entry point next to the organization flow
  function decorateHome() {
    const nb = document.getElementById("newBlank");
    if (!nb || document.getElementById("joinIndividual")) return;
    // Two clear entry points; the anonymous organiser demo stays available as a small link.
    nb.insertAdjacentHTML("beforebegin", `<a class="btn primary" id="joinIndividual" href="${CC.me ? "#/dashboard" : CC.auth ? "#/join" : "#/auth/signup?next=join"}">🧭 Find My Circle</a>
      <a class="btn ghost" id="orgEntry" href="${CC.auth ? "#/org" : "#/auth/signup?next=org"}">🏢 ${CC.auth && CC.auth.orgs && CC.auth.orgs.length ? "Manage my Organisation" : "Start an Organisation"}</a>`);
    nb.hidden = true;
    const sample = document.getElementById("newSample");
    if (sample) { sample.className = "linkbtn demo-link"; sample.textContent = "▶ Try the organiser demo (sample data)"; }
  }

  // ------------------------------------------------------------------ onboarding / profile form
  function chipGroup(name, opts, selected) {
    return `<div class="goalgrid" role="group" aria-label="${esc(name)}">${opts.map(([v, l]) =>
      `<button type="button" class="goal ${selected.includes(v) ? "on" : ""}" data-multi="${name}" data-v="${v}" aria-pressed="${selected.includes(v)}">${l}</button>`).join("")}</div>`;
  }
  function readMulti(root, name) { return [...root.querySelectorAll(`[data-multi="${name}"].on`)].map((b) => b.dataset.v); }

  function profileForm(p, mode) {
    const ints = (p.interests || []).map((i) => ({ label: i.label, intent: i.intent, signals: (i.signals || []).map((s) => ({ ...s })), candidates: null, category: "" }));
    draft().forEach((d) => { if (!ints.some((i) => i.label.toLowerCase() === d.label.toLowerCase())) ints.push({ label: d.label, intent: "enjoy", signals: null, candidates: null }); });
    const st = { ints };
    const I = (k) => (window.wsIcon ? window.wsIcon(k) : "");
    const th = (t) => (window.wsTheme ? window.wsTheme(t) : { g: ["#5b3fd6", "#ec4899"], icon: "sparkle" });
    const tops = (p.interests || []).slice(0, 3).map((i) => i.label);
    const heroTheme = th(tops.join(" "));
    const chipRow = (name, opts, sel) => `<div class="pf-chips" role="group" aria-label="${esc(name)}">${opts.map(([v, l]) =>
      `<button type="button" class="pf-chip goal ${sel.includes(v) ? "on" : ""}" data-multi="${name}" data-v="${v}" aria-pressed="${sel.includes(v)}">${l}</button>`).join("")}</div>`;
    const toggle = (id, on, icon, title, sub) => `<label class="pf-toggle"><input type="checkbox" id="${id}" ${on ? "checked" : ""}/>
      <span class="pt-ic">${I(icon)}</span><span class="pt-t"><b>${title}</b><small>${sub}</small></span><span class="sw"></span></label>`;
    app.innerHTML = `
    <section class="pf-hero" style="--g1:${heroTheme.g[0]};--g2:${heroTheme.g[1]}">
      <span class="pf-blob b1"></span><span class="pf-blob b2"></span>
      <div class="pf-avatar"><span>${esc((p.alias || "You").split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase())}</span><i>${I(heroTheme.icon)}</i></div>
      <div class="pf-id"><span class="pf-kick">${mode === "join" ? "Let's get you matched" : "Your profile"}</span>
        <h1>${mode === "join" ? "Find your people" : esc(p.alias)}</h1>
        <div class="pf-meta">${p.area ? `<span>${I("pin")}${esc(p.area)}</span>` : ""}<span>${I("sparkle")}${(p.interests || []).length} interests</span>
          <span class="${p.discoverable ? "on" : "off"}">${I("compass")}Discovery ${p.discoverable ? "on" : "off"}</span></div></div>
      ${tops.length ? `<div class="pf-tops">${tops.map((t) => `<span style="background:linear-gradient(135deg,${th(t).g.join(",")})">${I(th(t).icon)}${esc(t)}</span>`).join("")}</div>` : ""}
    </section>
    <form id="pf" class="pf-grid" novalidate><div class="pf-col">
      <section class="pf-card pf-int"><header class="hc-pink">${I("sparkle")}<h2>Your interests</h2><span class="req">required</span></header>
        <div class="quickpicks pf-qp" aria-label="Quick picks — tap or drag to add">${QUICK.map(([e, l]) => { const t = th(l); return `<button type="button" class="qp" draggable="true" data-qp="${esc(l)}" data-emoji="${e}" style="--g1:${t.g[0]};--g2:${t.g[1]}"><span class="qp-ic">${I(t.icon)}</span>${esc(l)}</button>`; }).join("")}</div>
        <div class="dropzone" id="dz" tabindex="-1"><div class="pf-add">${I("search")}
          <input id="fInt" type="text" maxlength="60" placeholder="Add anything — a band, a sport, a cause…" aria-label="Add an interest"/>
          <button class="btn primary sm" type="button" id="fIntAdd">Add</button></div>
          <div id="intList" aria-live="polite"></div></div>
        <p class="pf-hint">${I("compass")} Qloo links each interest to cultural signals. Health or political topics are optional.</p>
      </section></div><div class="pf-col">
      <section class="pf-card"><header>${I("user")}<h2>About you</h2></header>
        <div class="pf-fields">
          <label class="pf-f"><span>${I("user")}Name or alias *</span><input id="fAlias" type="text" required minlength="2" maxlength="40" value="${esc(p.alias || "")}" autocomplete="nickname"/></label>
          <label class="pf-f"><span>${I("pin")}Area</span><input id="fArea" type="text" maxlength="60" value="${esc(p.area || "")}" placeholder="City or neighbourhood"/></label>
          <label class="pf-f"><span>${I("mic")}Language</span><input id="fLang" type="text" maxlength="30" value="${esc(p.language || "")}" placeholder="Optional"/></label>
          <label class="pf-f"><span>${I("lock")}Max spend / event</span><input id="fBudget" type="number" min="0" max="10000" value="${p.budget_max ?? ""}" placeholder="Private"/></label>
          <label class="pf-f wide"><span>${I("book")}Short bio</span><textarea id="fBio" maxlength="280" rows="2" placeholder="Optional — shown only if you share interests">${esc(p.bio || "")}</textarea></label>
        </div>
        <label class="pf-adult ${mode === "join" ? "" : "pf-hide"}"><input type="checkbox" id="fAdult" ${mode !== "join" ? "checked" : ""}/> <b>I'm 18 or older</b> <small>· required for self-serve Circles</small></label>
      </section>
      <section class="pf-card pf-vibe"><header class="hc-amber">${I("sparkle")}<h2>Your vibe</h2><span class="opt">optional · private</span></header>
        <div class="pf-row"><span class="pf-l">${I("calendar")}When</span>${chipRow("availability", AVAIL, p.availability || [])}</div>
        <div class="pf-row"><span class="pf-l">${I("users")}How</span>${chipRow("activity_prefs", PREFS, p.activity_prefs || [])}</div>
        <div class="pf-row"><span class="pf-l">${I("heart")}Access</span>${chipRow("accessibility", ACCESS, p.accessibility || [])}</div>
        <label class="pf-row"><span class="pf-l">${I("x")}Avoid</span><input id="fExcl" type="text" maxlength="200" value="${esc((p.exclude_topics || []).join(", "))}" placeholder="Topics never to recommend, comma-separated"/></label>
      </section>
      <section class="pf-card"><header class="hc-indigo">${I("lock")}<h2>Privacy &amp; visibility</h2></header>
        ${toggle("fDisc", p.discoverable, "compass", "Auto-discovery", "Recommend Circles & events for me")}
        ${toggle("fShowArea", p.show_area, "pin", "Show my area", "To members of my Circles")}
        ${toggle("fShare", p.share_interests, "users", "Share my interests", "With my Circles & their planning")}
        <details class="pf-who"><summary>${I("lock")} Who sees what?</summary><ul>
          <li><b>Members:</b> your alias and role — area, interests and bio only if you switch them on.</li>
          <li><b>Nobody:</b> budget, availability, accessibility needs, avoided topics.</li>
          <li><b>Qloo:</b> only interest names/IDs from our server — never your alias or area.</li></ul></details>
      </section></div>
      <div class="pf-save"><span class="pf-save-t">${I("refresh")}<span>${mode === "join" ? "Only your name and interests are required." : "Saving refreshes your recommendations."}</span></span>
        <span class="row">${mode === "join" ? "" : `<button class="btn ghost" type="button" id="pfDiscard">Discard</button>`}<button class="btn primary" type="submit" id="pfSubmit">${mode === "join" ? "Finish & see my recommendations →" : "Save changes"}</button></span></div>
    </form>`;
    const root = document.getElementById("pf");
    root.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => { b.classList.toggle("on"); b.setAttribute("aria-pressed", b.classList.contains("on")); }));

    const list = document.getElementById("intList");
    const timers = {};
    function drawInts() {
      list.innerHTML = st.ints.length ? st.ints.map((t, i) => `<div class="int-row" data-i="${i}">
        <div class="row between"><span class="ir-h">${window.wsTheme ? `<span class="ir-ic" style="background:linear-gradient(135deg,${window.wsTheme(t.label).g.join(",")})">${window.wsIcon(window.wsTheme(t.label).icon)}</span>` : ""}<b>${esc(t.label)}</b></span><div class="row">
          <select data-intent="${i}" aria-label="Intent for ${esc(t.label)}">${INTENTS.map(([v, l]) => `<option value="${v}" ${t.intent === v ? "selected" : ""}>${l}</option>`).join("")}</select>
          <button type="button" class="iconbtn" data-rm="${i}" aria-label="Remove ${esc(t.label)}">✕</button></div></div>
        <div class="cands">${t.candidates ? (t.candidates.length ? t.candidates.map((c) => candHtml(c, (t.signals || []).some((s) => s.id === c.id))).join("")
          : `<span class="muted small">${esc(t.error || "No Qloo match — it still counts as your declared interest.")}</span>`)
          : t.signals && t.signals.length ? t.signals.map((s) => candHtml({ ...s, description: "", source: s.source || "saved" }, true)).join("") + `<button type="button" class="btn soft sm" data-research="${i}">↻ Search Qloo again</button>`
          : `<span class="muted small"><span class="spinner"></span> Matching with Qloo…</span>`}</div></div>`).join("")
        : `<div class="empty-mini">Tap a bubble above or type your own.</div>`;
      list.querySelectorAll("[data-intent]").forEach((s) => (s.onchange = () => (st.ints[+s.dataset.intent].intent = s.value)));
      list.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { st.ints.splice(+b.dataset.rm, 1); drawInts(); }));
      list.querySelectorAll("[data-research]").forEach((b) => (b.onclick = () => resolveOne(st.ints[+b.dataset.research])));
    }
    list.addEventListener("click", (e) => {
      const b = e.target.closest("[data-cid]"); if (!b) return;
      const t = st.ints[+b.closest("[data-i]").dataset.i];
      const c = (t.candidates || []).find((x) => x.id === b.dataset.cid); if (!c) return;
      t.signals = t.signals || [];
      const ix = t.signals.findIndex((s) => s.id === c.id);
      if (ix >= 0) t.signals.splice(ix, 1);
      else if (t.signals.length >= 4) return toast("Pick up to 4 Qloo matches per interest", true);
      else t.signals.push({ id: c.id, kind: c.kind, name: c.name, type: c.type });
      b.classList.toggle("sel");
    });
    async function resolveOne(t) {
      t.candidates = null; t.error = null; drawInts();
      try {
        const r = await capi("/api/interests/resolve", { body: { label: t.label } });
        t.candidates = r.candidates || [];
        if (!t.signals || !t.signals.length) t.signals = (r.suggested_ids || []).map((id) => t.candidates.find((c) => c.id === id)).filter(Boolean).map((c) => ({ id: c.id, kind: c.kind, name: c.name, type: c.type }));
        if (r.warnings && r.warnings.length && !t.candidates.length) t.error = "Qloo is busy — saved as a declared interest for now.";
      } catch (e) { t.candidates = []; t.error = e.status === 429 ? "Qloo rate limit — try again in a moment." : "Couldn't reach Qloo — it'll be saved as a declared interest."; }
      drawInts();
    }
    function addInterest(label) {
      label = String(label || "").trim().slice(0, 60);
      if (!label) return;
      if (st.ints.some((x) => x.label.toLowerCase() === label.toLowerCase())) return toast(`“${label}” is already in your list`);
      if (st.ints.length >= 12) return toast("Up to 12 interests", true);
      const t = { label, intent: "enjoy", signals: null, candidates: null };
      st.ints.push(t); drawInts();
      clearTimeout(timers[label]); timers[label] = setTimeout(() => resolveOne(t), 300); // debounce bursts of adds
    }
    const inp = document.getElementById("fInt");
    document.getElementById("fIntAdd").onclick = () => { addInterest(inp.value); inp.value = ""; inp.focus(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addInterest(inp.value); inp.value = ""; } });
    root.querySelectorAll("[data-qp]").forEach((b) => {
      b.onclick = () => addInterest(b.dataset.qp);
      b.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", b.dataset.qp); e.dataTransfer.effectAllowed = "copy"; });
    });
    const dz = document.getElementById("dz");
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("over"));
    dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); addInterest(e.dataTransfer.getData("text/plain")); });
    drawInts();
    st.ints.forEach((t) => { if (!t.signals) resolveOne(t); });

    root.onsubmit = (e) => {
      e.preventDefault();
      const btn = document.getElementById("pfSubmit");
      withBusy(btn, async () => {
        const alias = document.getElementById("fAlias").value.trim();
        if (alias.length < 2) { document.getElementById("fAlias").focus(); return toast("Please add an alias (2+ characters)", true); }
        if (!document.getElementById("fAdult").checked) return toast("Self-serve Circles are for adults (18+)", true);
        if (!st.ints.length) { inp.focus(); return toast("Add at least one interest", true); }
        // Don't make people wait for Qloo: interests still matching are saved as declared and the discovery agent resolves them.
        const pendingQ = st.ints.some((t) => !t.candidates && !(t.signals && t.signals.length));
        const b = document.getElementById("fBudget").value;
        const body = {
          alias, area: document.getElementById("fArea").value.trim(), language: document.getElementById("fLang").value.trim(),
          bio: document.getElementById("fBio").value.trim(), budget_max: b === "" ? null : Number(b),
          availability: readMulti(root, "availability"), activity_prefs: readMulti(root, "activity_prefs"), accessibility: readMulti(root, "accessibility"),
          exclude_topics: document.getElementById("fExcl").value.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 10),
          adult_confirmed: true, discoverable: document.getElementById("fDisc").checked,
          show_area: document.getElementById("fShowArea").checked, share_interests: document.getElementById("fShare").checked,
          interests: st.ints.map((t) => ({ label: t.label, intent: t.intent, signals: (t.signals || []).map((s) => ({ id: s.id, kind: s.kind })) })),
          timezone: (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; } })(),
        };
        const res = await capi("/api/me", { method: mode === "join" ? "POST" : "PUT", body });
        (res.warnings || []).forEach((w) => toast(w));
        store.del(LS_DRAFT);
        CC.me = res.profile; CC.rec = null; await loadMe(true);
        toast(mode === "join" ? "Profile created ✓" : "Profile saved ✓");
        if (res.agent_run) toast(pendingQ ? "🤖 Discovery started — we'll finish matching your interests with Qloo" : "🤖 Discovery started — finding Circles and events for you");
        else if (mode === "join" && !body.discoverable) toast("Discovery consent is off, so we can't recommend Circles yet. You can turn it on anytime.");
        location.hash = "#/dashboard";
      });
    };
  }
  function showRecovery(token) {
    app.innerHTML = `<div class="card ready" style="max-width:640px;margin:0 auto">
      <div class="es-ic">🔑</div><h2>Your profile is ready</h2>
      <p class="muted">There are no passwords here. This private recovery key is the only way to open your profile on another device. Keep it secret — anyone with it can act as you.</p>
      <div class="keybox"><code id="rk">${esc(token)}</code><button class="btn soft sm" id="rkCopy" type="button">Copy</button></div>
      <div class="row" style="justify-content:center;margin-top:16px"><a class="btn primary" href="#/circles">Find my Circles →</a></div></div>`;
    document.getElementById("rkCopy").onclick = async () => { try { await navigator.clipboard.writeText(token); toast("Copied — store it somewhere safe"); } catch { toast("Select the key and copy it manually", true); } };
  }
  async function viewJoin() { profileForm({ discoverable: true, share_interests: false, show_area: false }, "join"); }
  async function viewProfile(fromJoin) {
    const p = await loadMe(true);
    if (!p) return viewJoin();
    profileForm(p, "edit");
    const blocks = await capi("/api/me/blocks").catch(() => []);
    const I = (k) => (window.wsIcon ? window.wsIcon(k) : "");
    app.insertAdjacentHTML("beforeend", `<section class="pf-card pf-acct"><header class="hc-slate">${I("gear")}<div class="pf-ht"><h2>Account settings</h2><small>Sign-in, recommendations and safety</small></div></header>
      <div class="pf-acct-grid">
        <div class="pf-panel"><span class="pf-ph">${I("idcard")} Account</span>${window.ppAccountCard ? window.ppAccountCard() : ""}</div>
        <div class="pf-panel"><span class="pf-ph g">${I("compass")} Recommendations<span class="pf-pill ${p.discoverable ? "ok" : "off"}">${p.discoverable ? "Active" : "Off"}</span></span>
          <p class="pf-pt">${p.discoverable ? "Qloo-powered discovery updates your Circles and events as things change." : "Off — no recommendations; your Qloo taste cache is deleted."}</p>
          ${p.discoverable && (p.consent_at || p.taste_retrieved_at) ? `<div class="pf-times">${p.consent_at ? `<div><small>On since</small><b>${fmtTime(p.consent_at)}</b></div>` : ""}${p.taste_retrieved_at ? `<div><small>Qloo insights updated</small><b>${fmtTime(p.taste_retrieved_at)}</b></div>` : ""}</div>` : ""}
          <div class="pf-btns"><button type="button" class="btn ${p.discoverable ? "ghost" : "primary"} sm" id="consentBtn">${p.discoverable ? "Turn off" : "Turn on"}</button><a class="btn soft sm" href="#/agent/settings">${I("bot")} Agent settings</a></div></div>
        <div class="pf-panel"><span class="pf-ph r">${I("shield")} Safety</span>
          <div class="pf-blk"><span>${I("ban")}<span><b>Blocked profiles</b><small>${blocks.length ? `${blocks.length} blocked` : "Nobody blocked"}</small></span></span><em>${blocks.length}</em></div>
          ${blocks.map((b) => `<div class="pf-blk-r"><span>${esc(b.alias || "Unknown")}</span><button type="button" class="btn soft sm" data-unblock="${esc(b.user_id)}">Unblock</button></div>`).join("")}
          <div class="pf-del"><div class="row between"><b>${I("trash")} Delete account</b></div>
            <details><summary>What gets deleted?</summary><p>Profile, interests, Qloo mappings, memberships, votes, RSVPs and blocks. Posts are erased; Circles you host pass to another member or are archived.</p></details>
            <button type="button" class="btn danger sm" id="delMe">Delete everything</button></div></div>
      </div></section>`);
    const dsc = document.getElementById("pfDiscard");
    if (dsc) dsc.onclick = () => viewProfile();
    document.getElementById("consentBtn").onclick = (e) => withBusy(e.currentTarget, async () => {
      CC.me = await capi("/api/me/consent", { method: "PUT", body: { discoverable: !p.discoverable } }); CC.rec = null; viewProfile();
    });
    app.querySelectorAll("[data-unblock]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => { await capi("/api/me/blocks", { body: { user_id: b.dataset.unblock, blocked: false } }); viewProfile(); })));
    if (window.ppBindAccountCard) window.ppBindAccountCard();
    document.getElementById("delMe").onclick = (e) => {
      if (prompt('Type DELETE to permanently delete your account') !== "DELETE") return;
      withBusy(e.currentTarget, async () => { await capi("/api/me", { method: "DELETE" }); store.del(LS_TOKEN); CC.token = null; CC.me = null; toast("Account deleted"); location.hash = "#/"; });
    };
  }
  async function viewRestore() {
    app.innerHTML = `<div class="card" style="max-width:560px;margin:0 auto"><div class="es-ic">🔑</div><h2>Restore your profile</h2>
      <p class="muted">Paste the private recovery key you saved when you joined.</p>
      <form id="rf"><div class="field"><label for="rKey">Recovery key</label><input id="rKey" type="password" autocomplete="off" required/></div>
      <div class="row between"><a class="btn ghost" href="#/join">New here? Join</a><button class="btn primary" type="submit">Restore</button></div></form></div>`;
    document.getElementById("rf").onsubmit = (e) => {
      e.preventDefault();
      withBusy(e.submitter, async () => {
        setToken(document.getElementById("rKey").value.trim());
        const me = await loadMe(true);
        if (!me) { setToken(null); store.del(LS_TOKEN); throw new Error("That key didn't match any profile."); }
        toast(`Welcome back, ${me.alias}`); location.hash = "#/circles";
      });
    };
  }

  // ------------------------------------------------------------------ discover
  function reasonList(rs) {
    return `<ul class="reasons">${(rs || []).map((r) => { const [cls, lab] = SRC[r.source] || ["generated", r.source];
      return `<li><span class="badge ${cls}">${lab}</span> ${esc(r.text)}</li>`; }).join("")}</ul>`;
  }
  function circleCard(c, extra = "") {
    const pct = Math.min(100, Math.round((c.member_count / c.capacity) * 100));
    return `<article class="card circle-card cat-${c.category}">
      <div class="cc-top"><span class="cc-emoji" aria-hidden="true">${c.category === "health" ? "🩺" : c.category === "political" ? "🗳" : "⭕"}</span>
        <div style="min-width:0"><h3><a href="#/c/${esc(c.id)}">${esc(c.name)}</a></h3>
        <div class="muted small">${esc(c.topic_label)} · ${c.meeting_mode === "either" ? "online or in person" : c.meeting_mode.replace("_", " ")}${c.area ? " · " + esc(c.area) : ""}${c.visibility === "private" ? " · 🔒 private" : ""}</div></div></div>
      ${c.purpose ? `<p class="small">${esc(c.purpose)}</p>` : ""}
      <div class="sigs">${(c.signals || []).slice(0, 3).map((s) => `<span class="kind ${esc(s.kind)}">${esc(s.kind)} · ${esc(s.name)}</span>`).join("")}</div>
      <div class="cap"><div class="cap-bar"><i style="width:${pct}%"></i></div><span>${c.member_count}/${c.capacity} members${c.member_count < c.min_size ? ` · needs ${c.min_size - c.member_count} more` : ""}</span></div>
      ${extra}</article>`;
  }
  async function viewDiscover() {
    app.innerHTML = `<div class="card empty"><span class="spinner"></span> Looking for Circles${CC.me ? " that fit you" : ""}…</div>`;
    const q = queryParam("q") || "";
    const [all, rec] = await Promise.all([capi(`/api/circles?q=${encodeURIComponent(q)}`), CC.me && CC.me.discoverable ? (CC.rec ? Promise.resolve(CC.rec) : capi("/api/circles/recommendations")) : Promise.resolve(null)]);
    if (rec) CC.rec = rec;
    const recs = rec ? rec.recommendations.filter((r) => !CC.skipped.has(r.id)) : [];
    const exc = rec ? Object.entries(rec.excluded) : [];
    app.innerHTML = `
    <section class="how-hero" style="padding-bottom:10px"><span class="how-kicker">🧭 Discover Circles</span>
      <h1>${CC.me ? `Hi ${esc(CC.me.alias)}, here's <span>where you fit</span>` : `Small groups. <span>Shared passions.</span>`}</h1></section>
    ${!CC.me ? `<div class="card cta-card"><div><h3>Get personal recommendations</h3><p class="muted">Create a pseudonymous profile — Qloo links your interests to Circles you'll actually enjoy.</p></div><a class="btn primary" href="#/join">✨ Join as an individual</a></div>` : ""}
    ${CC.me && !CC.me.discoverable ? `<div class="notice">Discovery is off, so we can't recommend Circles. <a href="#/me">Turn it on in your profile</a> — or browse below.</div>` : ""}
    ${rec ? `<h2 class="sec-h">✨ Recommended for you</h2>
      ${(rec.warnings || []).map((w) => `<div class="notice">${esc(w)}</div>`).join("")}
      ${recs.length && window.wsCircleTile ? `<div class="cc-tiles">${recs.map((c) => window.wsCircleTile(c)).join("")}</div>`
        : recs.length ? `<div class="grid2">${recs.map((c) => circleCard(c, `<details class="why-box" open><summary>Why this Circle?</summary>${reasonList(c.reasons)}<p class="muted tiny">${esc(c.rank_basis)}</p></details>
          <div class="row between"><button class="btn ghost sm" data-skip="${esc(c.id)}">Skip</button><div class="row"><a class="btn soft sm" href="#/c/${esc(c.id)}">View</a><button class="btn primary sm" data-join="${esc(c.id)}">Join Circle</button></div></div>`)).join("")}</div>`
        : `<div class="card empty-state"><div class="es-ic">🌱</div><h3>No existing Circle fits yet</h3><p class="muted">That's how every community starts. Create one below — others with the same interest will be matched to it.</p></div>`}
      ${exc.length ? `<p class="muted small">Hidden because they don't meet your requirements: ${exc.map(([k, v]) => `${v} × ${esc(k)}`).join(", ")}. Requirements always win over taste matches.</p>` : ""}
      ${rec.create_suggestions.length ? `<h2 class="sec-h">🌱 Start a new Circle</h2><div class="cc-tiles">${rec.create_suggestions.map((s) => `<div class="card start-card">${window.wsArt ? window.wsArt(s.label, `<span class="date-badge prop-b">New</span>`) : ""}
          <h3>${esc(s.label)}</h3><p class="muted small">${s.signals.length ? `Linked to Qloo: ${[...new Set(s.signals.map((x) => x.name))].map(esc).join(", ")}` : "Declared interest (no Qloo ID)"}</p>
          ${s.suggested_category !== "general" ? `<span class="badge ${s.suggested_category === "health" ? "participant" : "generated"}">${s.suggested_category} topic</span>` : ""}
          <button class="btn primary sm" data-create="${s.interest_id}">Create “${esc(s.label)}” Circle</button></div>`).join("")}</div>` : ""}` : ""}
    <h2 class="sec-h">🔎 Browse all public Circles</h2>
    <form class="row" id="bf"><input type="search" id="bq" value="${esc(q)}" placeholder="Search Circles…" aria-label="Search Circles" style="max-width:360px"/><button class="btn soft sm">Search</button></form>
    <div class="${window.wsCircleTile ? "cc-tiles" : "grid3"}" style="margin-top:12px">${all.length ? all.map((c) => window.wsCircleTile ? window.wsCircleTile(c, { noReason: true,
        action: `<a class="btn ${c.my_status === "active" ? "primary" : "soft"} sm" href="#/c/${esc(c.id)}">${c.my_status === "active" ? "Open" : c.my_status === "pending" ? "Pending" : "View"}</a>` })
      : circleCard(c, `<div class="row end"><a class="btn soft sm" href="#/c/${esc(c.id)}">${c.my_status === "active" ? "Open" : "View"}</a></div>`)).join("")
      : `<div class="card empty-state" style="grid-column:1/-1"><div class="es-ic">⭕</div><h3>No public Circles yet</h3><p class="muted">${CC.me ? "Be the first — create one from your interests above." : "Join to create the first one."}</p></div>`}</div>
    <div id="createSlot"></div>`;
    document.getElementById("bf").onsubmit = (e) => { e.preventDefault(); location.hash = `#/circles?q=${encodeURIComponent(document.getElementById("bq").value.trim())}`; };
    app.querySelectorAll("[data-skip]").forEach((b) => (b.onclick = () => { CC.skipped.add(b.dataset.skip); store.set("cc_skipped", [...CC.skipped]); viewDiscover(); }));
    app.querySelectorAll("[data-join]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => {
      const r = await capi(`/api/circles/${b.dataset.join}/join`, { method: "POST" });
      CC.rec = null; toast(r.status === "pending" ? "Request sent to the host" : "Welcome to the Circle 🎉");
      location.hash = `#/c/${b.dataset.join}`;
    })));
    app.querySelectorAll("[data-create]").forEach((b) => (b.onclick = () => createForm(rec.create_suggestions.find((s) => String(s.interest_id) === b.dataset.create))));
  }
  function createForm(s) {
    const slot = document.getElementById("createSlot");
    const I = (k) => (window.wsIcon ? window.wsIcon(k) : "");
    const seg = (name, id, opts, cur) => `<select id="${id}" hidden>${opts.map(([v, l]) => `<option value="${v}" ${v === cur ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div class="b-cards" role="radiogroup" aria-label="${esc(name)}">${opts.map(([v, l, ic, sub]) => `<button type="button" role="radio" class="b-card ${v === cur ? "on" : ""}" aria-checked="${v === cur}" data-for="${id}" data-v="${v}">
        <span class="bc-ic">${I(ic)}</span><b>${l}</b>${sub ? `<small>${sub}</small>` : ""}</button>`).join("")}</div>`;
    slot.innerHTML = `<form class="builder cbuild" id="cf" novalidate><div class="b-main">
      <div class="b-title"><span class="kicker">${I("sparkle")} New Circle</span><h2>Start a “${esc(s.label)}” Circle</h2><p class="muted small">You'll host it. Nothing is public until you create it.</p></div>
      <section class="b-step"><header><span class="b-num">1</span><h3>Basics</h3><span class="b-ic">${I("users")}</span></header>
        <label class="pf-f"><span>${I("users")}Circle name *</span><input id="cName" type="text" minlength="3" maxlength="80" required value="${esc(s.label)} Circle"/></label>
        <label class="pf-f"><span>${I("book")}Purpose</span><textarea id="cPurpose" maxlength="400" rows="2" placeholder="What will members do together?"></textarea></label>
        <span class="pf-f"><span>${I("sparkle")}Topic type</span></span>
        ${seg("Topic type", "cCat", [["general", "General", "sparkle", "Hobbies & culture"], ["health", "Peer support", "heart", "Health & wellbeing"], ["political", "Civic", "mic", "Politics & dialogue"]], s.suggested_category || "general")}</section>
      <section class="b-step"><header><span class="b-num">2</span><h3>Where & who</h3><span class="b-ic">${I("pin")}</span></header>
        ${seg("Meeting mode", "cMode", [["either", "Both", "compass", "Online or in person"], ["in_person", "In person", "pin", "Meet nearby"], ["online", "Online", "bot", "Video calls"]], "either")}
        <div class="pf-fields"><label class="pf-f"><span>${I("pin")}Broad area</span><input id="cArea" type="text" maxlength="60" value="${esc(CC.me.area || "")}"/></label>
          <label class="pf-f"><span>${I("mic")}Language</span><input id="cLang" type="text" maxlength="30" value="${esc(CC.me.language || "")}" placeholder="Optional"/></label></div>
        ${seg("Visibility", "cVis", [["public", "Public", "compass", "Anyone can discover it"], ["private", "Private", "lock", "Invite link + approval"]], "public")}</section>
      <section class="b-step"><header><span class="b-num">3</span><h3>Size & style</h3><span class="b-ic">${I("calendar")}</span></header>
        <div class="b-range"><label for="cCap">${I("users")} Capacity <output id="cCapO">12</output></label><input id="cCap" type="range" min="3" max="50" value="12"/></div>
        <div class="b-range"><label for="cMin">${I("check")} Minimum to meet <output id="cMinO">3</output></label><input id="cMin" type="range" min="2" max="10" value="3"/></div>
        <span class="pf-l">${I("users")} Members here want to…</span>${chipGroup("cint", INTENTS, s.intent === "teach" || s.intent === "learn" ? ["teach", "learn"] : [s.intent])}
        <span class="pf-l">${I("heart")} Accessibility you commit to</span>${chipGroup("cacc", ACCESS, ["flexible_participation"])}
        <label class="pf-toggle"><input type="checkbox" id="cMemEv" checked/><span class="pt-ic">${I("calendar")}</span><span class="pt-t"><b>Members can propose activities</b><small>Hosts still confirm</small></span><span class="sw"></span></label></section>
      <div class="b-actions"><button class="btn ghost" type="button" id="cCancel">Cancel</button><button class="btn primary" type="submit">${I("check")} Create Circle</button></div></div>
      <aside class="b-preview"><span class="b-pv-l">${I("sparkle")} Live preview</span><div id="cPv"></div>
        <ul class="b-perks"><li>${I("bot")}<span><b>Planning agent</b> drafts activities once ${"members join"}</span></li><li>${I("compass")}<span><b>Matched people</b> get it recommended</span></li><li>${I("lock")}<span><b>You moderate</b> members & posts</span></li></ul></aside></form>`;
    slot.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => b.classList.toggle("on")));
    slot.querySelectorAll(".b-card").forEach((b) => (b.onclick = () => {
      document.getElementById(b.dataset.for).value = b.dataset.v;
      slot.querySelectorAll(`.b-card[data-for="${b.dataset.for}"]`).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
      pv();
    }));
    const pv = () => {
      const cap = +document.getElementById("cCap").value, min = +document.getElementById("cMin").value;
      document.getElementById("cCapO").textContent = cap; document.getElementById("cMinO").textContent = min;
      const mode = document.getElementById("cMode").value;
      document.getElementById("cPv").innerHTML = window.wsCircleTile ? window.wsCircleTile({ id: "preview", name: document.getElementById("cName").value || `${s.label} Circle`,
        topic_label: s.label, signals: s.signals || [], member_count: 1, area: mode === "online" ? "" : document.getElementById("cArea").value, meeting_mode: mode,
        reasons: [{ source: "app", text: document.getElementById("cPurpose").value || `People who share an interest in ${s.label}.` }] },
        { action: `<span class="pill">${document.getElementById("cVis").value === "private" ? `${I("lock")} Private` : `${I("compass")} Public`} · up to ${cap}</span>` }) : "";
    };
    slot.addEventListener("input", pv);
    pv();
    slot.scrollIntoView({ behavior: "smooth", block: "start" });
    document.getElementById("cCancel").onclick = () => (slot.innerHTML = "");
    document.getElementById("cf").onsubmit = (e) => {
      e.preventDefault();
      withBusy(e.submitter, async () => {
        const body = { interest_id: s.interest_id, name: document.getElementById("cName").value.trim(), purpose: document.getElementById("cPurpose").value.trim(),
          category: document.getElementById("cCat").value, meeting_mode: document.getElementById("cMode").value, area: document.getElementById("cArea").value.trim(),
          visibility: document.getElementById("cVis").value, capacity: +document.getElementById("cCap").value, min_size: +document.getElementById("cMin").value,
          language: document.getElementById("cLang").value.trim(), intents: readMulti(slot, "cint"), accessibility: readMulti(slot, "cacc"),
          member_events: document.getElementById("cMemEv").checked };
        if (body.min_size > body.capacity) return toast("Minimum can't be larger than capacity", true);
        try {
          const c = await capi("/api/circles", { body });
          CC.rec = null; toast("Circle created 🎉"); location.hash = `#/c/${c.id}`;
        } catch (err) {
          if (err.status === 409 && err.data && err.data.detail && err.data.detail.circle_id) {
            slot.querySelector(".b-main").insertAdjacentHTML("afterbegin", `<div class="notice">${esc(err.data.detail.message)} <a class="btn soft sm" href="#/c/${esc(err.data.detail.circle_id)}">Open “${esc(err.data.detail.name)}”</a></div>`);
            return;
          }
          throw err;
        }
      });
    };
  }

  // ------------------------------------------------------------------ my circles + events
  async function viewMy() {
    const [mine, evs] = await Promise.all([capi("/api/me/circles"), capi("/api/me/events")]);
    app.innerHTML = `<div class="page-head"><h1>My Circles</h1><a class="btn soft sm" href="#/circles">Find more</a></div>
      <div class="my-grid"><div>${mine.length ? `<div class="cc-tiles">${mine.map((c) => window.wsCircleTile ? window.wsCircleTile(c, { noReason: true,
          action: c.my_status === "pending" ? `<span class="pill">Awaiting approval</span>` : `<a class="btn primary sm" href="#/c/${esc(c.id)}">Open</a>` }) : "").join("")}</div>`
        : `<div class="empty-line"><span>No Circles yet.</span><a class="btn primary sm" href="#/dashboard">Discover Circles</a></div>`}</div>
      <div class="my-side"><h2 class="sec-h small-h">📅 My activities</h2>${evs.length ? evs.map((e) => `<a class="card ev-row" href="#/c/${esc(e.circle_id)}/events">
          <span class="badge ${e.status === "confirmed" ? "qloo" : "participant"}">${e.status}</span><div><b>${esc(e.title)}</b><div class="muted small">${esc(e.circle_name)}${e.chosen_time ? " · " + esc(fmtIso(e.chosen_time)) : ""}${e.my_rsvp ? " · you: " + esc(e.my_rsvp.replace("_", " ")) : ""}</div></div></a>`).join("")
        : `<div class="empty-line"><span>Nothing planned yet.</span><a class="btn soft sm" href="#/activities">Find an activity</a></div>`}</div></div>`;
  }

  // ------------------------------------------------------------------ circle page
  async function viewCircle(cid, tab) {
    const invite = queryParam("invite");
    const c = await capi(`/api/circles/${encodeURIComponent(cid)}${invite ? `?invite=${encodeURIComponent(invite)}` : ""}`);
    const m = c.my_membership, member = m && m.status === "active", mod = member && ["host", "moderator"].includes(m.role);
    const tabs = [["chat", "💬 Chat"], ["discussion", "🧵 Threads"], ["events", "📅 Activities"], ["members", "👥 Members"], ["about", "ℹ️ About"]];
    app.innerHTML = `
    <section class="circle-hero cat-${c.category}">
      <div><span class="how-kicker">${c.category === "health" ? "🩺 Peer support" : c.category === "political" ? "🗳 Civic dialogue" : "⭕ Circle"}${c.visibility === "private" ? " · 🔒 Private" : ""}</span>
        ${c.org ? `<a class="org-pill" href="#/o/${esc(c.org.slug)}">🏢 ${esc(c.org.name)} · ${c.org.verification_status === "verified" ? "✓ Verified" : c.org.verification_status === "pending" ? "Verification pending" : "Not verified"}</a>` : ""}
        <h1>${esc(c.name)}</h1><p>${esc(c.purpose || `People who share an interest in ${c.topic_label}.`)}</p>
        <div class="sigs">${c.signals.map((s) => `<span class="kind ${esc(s.kind)}" title="Qloo ${esc(s.type)}">${esc(s.kind)} · ${esc(s.name)}</span>`).join("") || `<span class="kind tag">declared · ${esc(c.topic_label)}</span>`}</div></div>
      <div class="ch-side"><div class="ch-count"><b>${c.member_count}</b><span>of ${c.capacity} members</span></div>
        ${!CC.auth ? `<a class="btn primary" href="#/auth/signup?next=join">Sign up to take part</a>`
          : !CC.me && !member ? `<a class="btn primary" href="#/join">Create your profile to join</a>`
          : member ? `<button class="btn ghost sm" id="leaveBtn">Leave Circle</button>`
          : m && m.status === "pending" ? `<span class="badge participant">Request pending</span>`
          : `<button class="btn primary" id="joinBtn">${c.visibility === "private" ? "Request to join" : "Join Circle"}</button>`}</div></section>
    ${c.notice ? `<div class="pinned" role="note"><b>📌 Pinned notice</b><p>${esc(c.notice)}</p></div>` : ""}
    ${c.invite_code ? `<div class="notice">🔒 Invite link for this private Circle (requests still need your approval): <code>${esc(location.origin + location.pathname)}#/c/${esc(c.id)}?invite=${esc(c.invite_code)}</code></div>` : ""}
    ${member ? `<nav class="cc-tabs" role="tablist">${tabs.map(([k, l]) => `<a role="tab" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}" href="#/c/${esc(c.id)}/${k}">${l}</a>`).join("")}</nav><div id="tabBody"></div>`
      : `<div class="grid2">${aboutHtml(c)}<div class="card empty-state"><div class="es-ic">🔐</div><h3>Members-only space</h3><p class="muted">Discussion, events and the member list are visible to members only.</p></div></div>`}`;
    const jb = document.getElementById("joinBtn");
    if (jb) jb.onclick = (e) => withBusy(e.currentTarget, async () => {
      const r = await capi(`/api/circles/${c.id}/join${invite ? `?invite=${encodeURIComponent(invite)}` : ""}`, { method: "POST" });
      CC.rec = null; toast(r.status === "pending" ? "Request sent — the host will review it" : "Welcome! Say hello 👋"); viewCircle(cid, "discussion");
    });
    const lb = document.getElementById("leaveBtn");
    if (lb) lb.onclick = (e) => { if (!confirm(`Leave ${c.name}?`)) return; withBusy(e.currentTarget, async () => { await capi(`/api/circles/${c.id}/leave`, { method: "POST" }); CC.rec = null; toast("You left the Circle"); location.hash = "#/my"; }); };
    if (!member) return;
    const body = document.getElementById("tabBody");
    if (tab === "chat" && window.ppChat) return window.ppChat(c, body, mod, "");
    if (tab === "events") return tabEvents(c, body, mod);
    if (tab === "members") return tabMembers(c, body);
    if (tab === "about") { body.innerHTML = `<div class="grid2">${aboutHtml(c)}${m.role === "host" ? hostSettings(c) : ""}</div><div id="reportsSlot"></div>`; bindHost(c); if (mod) loadReports(c); return; }
    return tabDiscussion(c, body, mod);
  }
  function aboutHtml(c) {
    return `<div class="card"><h3>What to expect</h3><ul class="ticks">${c.expectations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      ${c.accessibility.length ? `<p class="small"><b>Accessibility commitments:</b> ${c.accessibility.map((a) => esc(a.replace(/_/g, " "))).join(", ")}</p>` : ""}
      ${c.intents.length ? `<p class="small"><b>Members here:</b> ${c.intents.map(esc).join(", ")}</p>` : ""}
      <h3 style="margin-top:14px">Community guidelines</h3><ol class="small guidelines">${c.guidelines.map((g) => `<li>${esc(g)}</li>`).join("")}</ol></div>`;
  }
  function hostSettings(c) {
    return `<form class="card" id="hs"><h3>⚙️ Host settings</h3>
      <div class="field"><label for="hName">Name</label><input id="hName" type="text" minlength="3" maxlength="80" value="${esc(c.name)}"/></div>
      <div class="field"><label for="hPurpose">Purpose</label><textarea id="hPurpose" maxlength="400" rows="2">${esc(c.purpose)}</textarea></div>
      <div class="grid3"><div class="field"><label for="hCap">Capacity</label><input id="hCap" type="number" min="3" max="50" value="${c.capacity}"/></div>
        <div class="field"><label for="hMin">Minimum</label><input id="hMin" type="number" min="2" max="10" value="${c.min_size}"/></div>
        <div class="field"><label for="hCat">Topic type</label><select id="hCat">${["general", "health", "political"].map((v) => `<option ${c.category === v ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <label>Accessibility commitments</label>${chipGroup("hacc", ACCESS, c.accessibility)}
      <label class="switch"><input type="checkbox" id="hMemEv" ${c.member_events ? "checked" : ""}/><span class="sw"></span><span class="si">📅</span> Members may propose events</label>
      <div class="row end"><button class="btn primary sm" type="submit">Save settings</button></div></form>`;
  }
  function bindHost(c) {
    const f = document.getElementById("hs"); if (!f) return;
    f.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => b.classList.toggle("on")));
    f.onsubmit = (e) => { e.preventDefault(); withBusy(e.submitter, async () => {
      await capi(`/api/circles/${c.id}`, { method: "PATCH", body: { name: document.getElementById("hName").value.trim(), purpose: document.getElementById("hPurpose").value.trim(),
        capacity: +document.getElementById("hCap").value, min_size: +document.getElementById("hMin").value, category: document.getElementById("hCat").value,
        accessibility: readMulti(f, "hacc"), member_events: document.getElementById("hMemEv").checked } });
      toast("Settings saved"); viewCircle(c.id, "about"); }); };
  }
  async function loadReports(c) {
    const slot = document.getElementById("reportsSlot");
    const reps = await capi(`/api/circles/${c.id}/reports`).catch(() => []);
    slot.innerHTML = `<div class="card" style="margin-top:18px"><h3>🛡 Reports (${reps.filter((r) => r.status === "open").length} open)</h3>
      ${reps.length ? reps.map((r) => `<div class="ev"><span class="badge ${r.status === "open" ? "participant" : "qloo"}">${r.status}</span><div style="flex:1"><b>${esc(r.target_type)} ${r.target_alias ? "by " + esc(r.target_alias) : ""}</b>
        <div class="small">Reason: ${esc(r.reason)}</div>${r.post_body ? `<blockquote class="small">${esc(r.post_body)}</blockquote>` : ""}</div>
        ${r.status === "open" ? `<button class="btn soft sm" data-resolve="${r.id}">Mark resolved</button>` : ""}</div>`).join("") : `<p class="muted small">No reports. 🎉</p>`}</div>`;
    slot.querySelectorAll("[data-resolve]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => { await capi(`/api/circles/${c.id}/reports/${b.dataset.resolve}/resolve`, { method: "POST" }); loadReports(c); })));
  }

  // discussion
  async function tabDiscussion(c, body, mod) {
    let before = null, posts = [];
    body.innerHTML = `<div class="card composer"><label for="newPost">Start a conversation</label>
      <textarea id="newPost" rows="3" maxlength="2000" placeholder="Share something with the Circle…"></textarea>
      <div class="row between"><span class="muted tiny" id="npCount">0 / 2000</span><button class="btn primary sm" id="npBtn">Post</button></div></div>
      <div id="postList" aria-live="polite"><div class="card empty"><span class="spinner"></span> Loading discussion…</div></div><div class="row" style="justify-content:center"><button class="btn ghost sm" id="moreBtn" hidden>Load older posts</button></div>`;
    const np = document.getElementById("newPost");
    np.oninput = () => (document.getElementById("npCount").textContent = `${np.value.length} / 2000`);
    document.getElementById("npBtn").onclick = (e) => withBusy(e.currentTarget, async () => {
      if (!np.value.trim()) return toast("Write something first", true);
      await capi(`/api/circles/${c.id}/posts`, { body: { body: np.value } }); np.value = ""; before = null; posts = []; await load();
    });
    const list = document.getElementById("postList");
    const one = (p, reply) => `<div class="post ${reply ? "reply" : ""} ${p.hidden ? "is-hidden" : ""}" data-pid="${p.id}">
      <div class="post-h"><span class="avatar sm" style="background:${color((p.author || "?").length)}">${esc(initials(p.author))}</span><b>${esc(p.author)}</b>
        <span class="muted tiny">${fmtTime(p.created_at)}${p.edited_at ? " · edited" : ""}${p.hidden ? " · hidden by moderator" : ""}</span></div>
      <div class="post-b">${p.deleted ? `<i class="muted">[deleted]</i>` : p.blocked ? `<i class="muted">Hidden — you blocked this person.</i>` : p.hidden && !mod ? `<i class="muted">Hidden by a moderator.</i>` : esc(p.body).replace(/\n/g, "<br/>")}</div>
      ${p.deleted ? "" : `<div class="post-a">${!reply ? `<button class="linkbtn" data-act="reply">Reply</button>` : ""}
        ${p.mine ? `<button class="linkbtn" data-act="edit">Edit</button><button class="linkbtn" data-act="del">Delete</button>`
          : `<button class="linkbtn" data-act="report">Report</button>${p.author_id ? `<button class="linkbtn" data-act="block" data-uid="${esc(p.author_id)}">${p.blocked ? "" : "Block"}</button>` : ""}`}
        ${mod && !p.mine ? `<button class="linkbtn" data-act="${p.hidden ? "unhide" : "hide"}">${p.hidden ? "Unhide" : "Hide"}</button><button class="linkbtn" data-act="del">Delete</button>` : ""}</div>`}</div>`;
    async function load() {
      const r = await capi(`/api/circles/${c.id}/posts?limit=15${before ? `&before=${before}` : ""}`);
      posts = posts.concat(r.posts); before = r.next_before;
      list.innerHTML = posts.length ? posts.map((p) => `<div class="card thread">${one(p, false)}${p.replies.map((x) => one(x, true)).join("")}<div class="reply-slot"></div></div>`).join("")
        : `<div class="card empty-state"><div class="es-ic">💬</div><h3>No posts yet</h3><p class="muted">Introduce yourself — ${c.category === "health" ? "share only what you're comfortable with." : `what drew you to ${esc(c.topic_label)}?`}</p></div>`;
      document.getElementById("moreBtn").hidden = !before;
    }
    document.getElementById("moreBtn").onclick = (e) => withBusy(e.currentTarget, load);
    list.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const postEl = b.closest("[data-pid]"), pid = postEl.dataset.pid, act = b.dataset.act;
      const run = (fn) => withBusy(b, async () => { await fn(); before = null; posts = []; await load(); });
      if (act === "reply") {
        const slot = postEl.parentElement.querySelector(".reply-slot");
        slot.innerHTML = `<div class="row" style="flex-wrap:nowrap;margin-top:8px"><input type="text" maxlength="2000" placeholder="Write a reply…" aria-label="Reply"/><button class="btn primary sm">Reply</button></div>`;
        const i = slot.querySelector("input"); i.focus();
        slot.querySelector("button").onclick = (ev) => { if (!i.value.trim()) return; withBusy(ev.currentTarget, async () => { await capi(`/api/circles/${c.id}/posts`, { body: { body: i.value, parent_id: +pid } }); before = null; posts = []; await load(); }); };
      } else if (act === "edit") {
        const cur = postEl.querySelector(".post-b").innerText;
        const v = prompt("Edit your post", cur); if (v === null || !v.trim()) return;
        run(() => capi(`/api/circles/${c.id}/posts/${pid}`, { method: "PATCH", body: { body: v } }));
      } else if (act === "del") { if (confirm("Delete this post?")) run(() => capi(`/api/circles/${c.id}/posts/${pid}`, { method: "DELETE" })); }
      else if (act === "hide" || act === "unhide") run(() => capi(`/api/circles/${c.id}/posts/${pid}/hide`, { body: { hidden: act === "hide" } }));
      else if (act === "report") {
        const reason = prompt("Why are you reporting this post? (moderators will review)"); if (!reason || reason.trim().length < 3) return;
        withBusy(b, async () => { await capi(`/api/circles/${c.id}/reports`, { body: { target_type: "post", target_id: pid, reason } }); toast("Reported — thank you"); });
      } else if (act === "block") {
        if (!confirm("Block this person? You won't see their posts, and you won't be matched into Circles together.")) return;
        run(() => capi("/api/me/blocks", { body: { user_id: b.dataset.uid, blocked: true } }));
      }
    });
    await load();
  }

  // members
  async function tabMembers(c, body) {
    body.innerHTML = `<div class="card empty"><span class="spinner"></span></div>`;
    const r = await capi(`/api/circles/${c.id}/members`);
    body.innerHTML = `<div class="card"><h3>👥 ${r.members.filter((x) => x.status === "active").length} members</h3>
      <p class="muted small">Members only see aliases plus what each person chose to share.</p>
      ${r.members.map((x, i) => `<div class="person"><div class="avatar" style="background:${color(i)}">${esc(initials(x.alias))}</div><div style="flex:1;min-width:0">
        <div class="row between"><h4>${esc(x.alias)} ${x.me ? '<span class="muted small">(you)</span>' : ""}</h4><span class="badge ${x.status === "pending" ? "participant" : x.role === "member" ? "generated" : "qloo"}">${x.status === "pending" ? "pending" : x.role}</span></div>
        <div class="meta">${x.area ? "📍 " + esc(x.area) + " · " : ""}joined ${fmtTime(x.joined_at)}</div>
        ${x.bio ? `<p class="small">${esc(x.bio)}</p>` : ""}
        ${x.interests ? `<div class="ints">${x.interests.map((t) => `<span class="int ${t.intent === "teach" ? "teach" : t.intent === "learn" ? "learn" : ""}">${esc(t.label)}</span>`).join("")}</div>` : ""}
        ${x.me ? "" : `<div class="post-a">${r.can_moderate && x.status === "pending" ? `<button class="linkbtn" data-ma="approve" data-u="${esc(x.user_id)}">Approve</button><button class="linkbtn" data-ma="decline" data-u="${esc(x.user_id)}">Decline</button>` : ""}
          ${r.can_moderate && x.status === "active" && x.role !== "host" ? `<button class="linkbtn" data-ma="remove" data-u="${esc(x.user_id)}">Remove</button>` : ""}
          ${r.is_host && x.status === "active" && x.role === "member" ? `<button class="linkbtn" data-ma="make_moderator" data-u="${esc(x.user_id)}">Make moderator</button>` : ""}
          ${r.is_host && x.role === "moderator" ? `<button class="linkbtn" data-ma="make_member" data-u="${esc(x.user_id)}">Remove moderator</button>` : ""}
          <button class="linkbtn" data-rep="${esc(x.user_id)}">Report</button><button class="linkbtn" data-blk="${esc(x.user_id)}">Block</button></div>`}
      </div></div>`).join("")}</div>`;
    body.querySelectorAll("[data-ma]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => { await capi(`/api/circles/${c.id}/members/${b.dataset.u}`, { body: { action: b.dataset.ma } }); toast("Done"); tabMembers(c, body); })));
    body.querySelectorAll("[data-rep]").forEach((b) => (b.onclick = (e) => { const reason = prompt("Why are you reporting this member?"); if (!reason || reason.trim().length < 3) return;
      withBusy(e.currentTarget, async () => { await capi(`/api/circles/${c.id}/reports`, { body: { target_type: "user", target_id: b.dataset.rep, reason } }); toast("Reported — moderators will review"); }); }));
    body.querySelectorAll("[data-blk]").forEach((b) => (b.onclick = (e) => { if (!confirm("Block this person?")) return;
      withBusy(e.currentTarget, async () => { await capi("/api/me/blocks", { body: { user_id: b.dataset.blk, blocked: true } }); toast("Blocked"); }); }));
  }

  // events (member-led, planned by the existing agent)
  function checkRows(checks) {
    return `<ul class="checks">${(checks || []).map((k) => `<li class="${k.status}"><span>${k.status === "pass" ? "✔" : k.status === "warn" ? "⚠" : "✖"}</span><b>${esc(k.check)}</b> <span class="muted">${esc(k.note)}</span></li>`).join("")}</ul>`;
  }
  function optionCard(e, k, i) {
    const ev = Object.fromEntries((e.plan.evidence || []).map((x) => [x.eid, x]));
    const votes = e.votes.activity[i] || e.votes.activity[String(i)] || 0;
    const chosen = e.status === "confirmed" && e.chosen_option === i;
    return `<div class="opt ${chosen ? "chosen" : ""} ${e.status === "confirmed" && !chosen ? "dim" : ""}">
      <div class="opt-h"><span class="opt-l">${String.fromCharCode(65 + i)}</span><div><b>${esc(k.title)}</b><div class="muted tiny">${esc(k.format_name)} · ${esc(k.generated_by)}</div></div></div>
      <p class="small">${esc(k.summary)}</p>
      <div class="stats"><span>🕒 ${k.duration_min} min</span><span>💲 ~${k.cost_estimate?.amount ?? 0} ${esc(e.constraints.currency)} <span class="muted tiny">(estimate)</span></span></div>
      <details><summary>Agenda & resources</summary><ol class="agenda">${k.agenda.map((a) => `<li><div><b>${esc(a.title)} (${a.minutes} min)</b>${esc(a.detail)}</div></li>`).join("")}</ol>
        <p class="small"><b>Resources:</b> ${(k.materials || []).map(esc).join(" · ")}</p>
        ${(k.roles || []).length ? `<p class="small"><b>Roles:</b> ${k.roles.map((r) => `${esc(r.member)} — ${esc(r.role)}`).join("; ")}</p>` : ""}</details>
      <details><summary>Constraint checklist</summary>${checkRows(k.checks)}</details>
      <details><summary>Open questions</summary><ul class="small">${(k.unresolved_questions || []).map((q) => `<li>${esc(q)}</li>`).join("")}</ul></details>
      <div class="refs">${(k.evidence_refs || []).map((r) => ev[r] ? `<span class="ref" title="${esc(ev[r].source.toUpperCase() + ": " + ev[r].detail)}">${r} · ${ev[r].source === "qloo" ? "Qloo" : "declared"} · ${esc(String(ev[r].label).slice(0, 32))}</span>` : "").join("")}</div>
      ${e.status === "proposed" ? `<button class="btn ${e.my_votes.activity === i ? "primary" : "soft"} sm" data-vote="activity" data-choice="${i}">👍 ${e.my_votes.activity === i ? "Your vote" : "Vote"} · ${votes}</button>` : ""}
      ${chosen ? `<span class="badge qloo">✓ Chosen plan</span>` : ""}</div>`;
  }
  async function tabEvents(c, body, mod) {
    body.innerHTML = `<div class="card empty"><span class="spinner"></span> Loading events…</div>`;
    const evs = await capi(`/api/circles/${c.id}/events`);
    const canPropose = c.member_events || mod;
    body.innerHTML = `${canPropose ? `<details class="card" id="propBox" ${evs.length ? "" : "open"}><summary class="sum-big">✨ Plan an activity with the agent</summary>
      <form id="ef" class="ef"><p class="muted small">The agent uses the Circle topic, interests members chose to share, real Qloo evidence, and everyone's private constraints (in aggregate). It drafts two options; members vote; a host confirms. Nothing is booked or sent automatically.</p>
        <div class="grid3"><div class="field"><label for="eTitle">Title (optional)</label><input id="eTitle" type="text" maxlength="100"/></div>
          <div class="field"><label for="eDur">Duration (min) *</label><input id="eDur" type="number" min="15" max="480" value="90" required/></div>
          <div class="field"><label for="eBud">Total budget *</label><div class="row" style="flex-wrap:nowrap"><input id="eBud" type="number" min="0" max="10000" value="30" required/><input id="eCur" type="text" maxlength="8" value="USD" style="width:76px" aria-label="Currency"/></div></div>
          <div class="field"><label for="eSet">Setting</label><select id="eSet" ${c.meeting_mode === "online" ? "disabled" : ""}>${["any", "indoor", "outdoor", "online"].map((s) => `<option ${c.meeting_mode === "online" && s === "online" ? "selected" : ""}>${s}</option>`).join("")}</select></div>
          <div class="field"><label for="eCap">Capacity</label><input id="eCap" type="number" min="2" max="${c.capacity}" value="${c.capacity}"/></div>
          <div class="field"><label for="eLoc">Location note (optional)</label><input id="eLoc" type="text" maxlength="200" placeholder="e.g. library meeting room — to confirm"/></div></div>
        <label>Time options for members to vote on (up to 3)</label>
        <div class="grid3">${[0, 1, 2].map((i) => `<input type="datetime-local" class="eTime" aria-label="Time option ${i + 1}"/>`).join("")}</div>
        <div class="row end" style="margin-top:12px"><button class="btn primary" type="submit" id="eBtn">Ask the agent for 2 options</button></div></form></details>`
      : `<div class="notice">Only hosts and moderators can propose events in this Circle.</div>`}
      <div id="evList">${evs.length ? "" : `<div class="card empty-state"><div class="es-ic">📅</div><h3>No events yet</h3><p class="muted">Propose the first one — the agent does the heavy lifting.</p></div>`}</div>`;
    const list = document.getElementById("evList");
    list.insertAdjacentHTML("beforebegin", `<div id="planBoard"></div>`);
    if (window.wsPlanBoard) window.wsPlanBoard(document.getElementById("planBoard"), c, mod, evs).catch(() => {});
    list.insertAdjacentHTML("beforeend", evs.map((e) => `<div class="card event st-${e.status}" data-eid="${esc(e.id)}">
      <div class="row between"><div><span class="badge ${e.status === "confirmed" ? "qloo" : e.status === "cancelled" ? "generated" : "participant"}">${e.status === "proposed" ? "proposed — voting" : e.status}</span>
        <h3 style="margin:6px 0 0">${esc(e.title)}</h3><div class="muted small">Proposed by ${esc(e.proposer)} · ${fmtTime(e.created_at)}${e.chosen_time ? ` · <b>📅 ${esc(fmtIso(e.chosen_time))}</b>` : ""}${e.location_note ? " · 📍 " + esc(e.location_note) : ""}</div></div>
        ${e.status !== "cancelled" && e.can_cancel ? `<button class="btn danger sm" data-cancel>Cancel</button>` : ""}</div>
      ${e.plan.fallback ? `<div class="notice">${esc(e.plan.fallback)}</div>` : ""}
      <div class="opts">${e.plan.concepts.map((k, i) => optionCard(e, k, i)).join("")}</div>
      ${e.time_options.length && e.status === "proposed" ? `<div class="times"><b>🗳 When?</b>${e.time_options.map((t, i) => `<button class="btn ${e.my_votes.time === i ? "primary" : "soft"} sm" data-vote="time" data-choice="${i}">${esc(fmtIso(t))} · ${e.votes.time[i] || e.votes.time[String(i)] || 0}</button>`).join("")}</div>` : ""}
      ${e.status === "proposed" && e.can_manage ? `<form class="confirm-row" data-confirm><b>Host:</b>
          <select aria-label="Final option">${e.plan.concepts.map((k, i) => `<option value="${i}">Option ${String.fromCharCode(65 + i)}</option>`).join("")}</select>
          <select aria-label="Final time">${e.time_options.length ? e.time_options.map((t, i) => `<option value="${i}">${esc(fmtIso(t))}</option>`).join("") : `<option value="">Add time options first</option>`}</select>
          <select data-place aria-label="Meeting place"><option value="">📍 Location to be confirmed</option></select>
          <button class="btn primary sm" ${e.time_options.length ? "" : "disabled"}>Confirm & publish event</button></form>` : ""}
      ${e.status === "proposed" ? `<div class="places-box" data-places="${esc(e.id)}"></div>` : ""}
      ${e.status !== "cancelled" ? `<details class="disc" data-disc="${esc(e.id)}"><summary>💬 Discuss this ${e.status === "proposed" ? "proposal" : "activity"}</summary><div class="disc-body"></div></details>` : ""}
      ${e.status === "confirmed" && e.event_id ? `<div class="rsvp"><a class="btn primary" href="#/e/${esc(e.event_id)}">🎟 Open the event page — RSVP, meeting point & updates →</a></div>` : ""}
      ${e.status === "confirmed" && !e.event_id ? `<div class="rsvp"><b>RSVP</b> <span class="muted small">${e.rsvp_counts.going || 0}/${e.capacity} going · ${e.rsvp_counts.maybe || 0} maybe</span>
          ${["going", "maybe", "not_going"].map((s) => `<button class="btn ${e.my_rsvp === s ? "primary" : "soft"} sm" data-rsvp="${s}">${s === "going" ? "✅ Going" : s === "maybe" ? "🤔 Maybe" : "❌ Can't go"}</button>`).join("")}
          <p class="muted tiny">Confirmed by a host. Venue/price details are as entered by the host — Culture Connect doesn't book or verify them.</p></div>` : ""}
    </div>`).join(""));
    const ef = document.getElementById("ef");
    if (ef) ef.onsubmit = (e) => {
      e.preventDefault();
      withBusy(document.getElementById("eBtn"), async () => {
        const times = [...ef.querySelectorAll(".eTime")].map((i) => i.value).filter(Boolean);
        toast("The agent is planning with Qloo — this can take a few seconds…");
        await capi(`/api/circles/${c.id}/events`, { body: { title: document.getElementById("eTitle").value.trim(), duration_min: +document.getElementById("eDur").value,
          budget: +document.getElementById("eBud").value, currency: document.getElementById("eCur").value.trim() || "USD",
          setting: c.meeting_mode === "online" ? "online" : document.getElementById("eSet").value, capacity: +document.getElementById("eCap").value,
          location_note: document.getElementById("eLoc").value.trim(), time_options: times } });
        toast("Two options ready — vote below"); tabEvents(c, body, mod);
      });
    };
    list.addEventListener("click", (ev) => {
      const card = ev.target.closest("[data-eid]"); if (!card) return;
      const eid = card.dataset.eid;
      const v = ev.target.closest("[data-vote]"), r = ev.target.closest("[data-rsvp]"), x = ev.target.closest("[data-cancel]");
      if (v) withBusy(v, async () => { await capi(`/api/circle-events/${eid}/vote`, { body: { kind: v.dataset.vote, choice: +v.dataset.choice } }); tabEvents(c, body, mod); });
      if (r) withBusy(r, async () => { await capi(`/api/circle-events/${eid}/rsvp`, { body: { status: r.dataset.rsvp } }); tabEvents(c, body, mod); });
      if (x && confirm("Cancel this event for everyone?")) withBusy(x, async () => { await capi(`/api/circle-events/${eid}/cancel`, { method: "POST" }); tabEvents(c, body, mod); });
    });
    list.querySelectorAll("[data-places]").forEach((el) => { if (window.ppPlaces) window.ppPlaces(el, el.dataset.places, (places) => {
      const sel = list.querySelector(`[data-eid="${el.dataset.places}"] [data-place]`);
      if (sel) sel.innerHTML = `<option value="">📍 Location to be confirmed</option>` + places.map((p) => `<option value="${p.id}">${esc(p.name)} · ${p.votes} vote${p.votes === 1 ? "" : "s"}</option>`).join("");
    }); });
    list.querySelectorAll("[data-disc]").forEach((d) => d.addEventListener("toggle", () => {
      if (d.open && !d.dataset.loaded && window.ppChat) { d.dataset.loaded = "1"; window.ppChat(c, d.querySelector(".disc-body"), mod, `proposal:${d.dataset.disc}`, true); }
    }));
    list.querySelectorAll("[data-confirm]").forEach((f) => (f.onsubmit = (ev) => {
      ev.preventDefault();
      const eid = f.closest("[data-eid]").dataset.eid, [o, t, pl] = f.querySelectorAll("select");
      withBusy(f.querySelector("button"), async () => {
        try {
          const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone) || "UTC";
          const r = await capi(`/api/circle-events/${eid}/confirm`, { body: { option: +o.value, time_index: t.value === "" ? null : +t.value,
            place_id: pl.value === "" ? null : +pl.value, timezone: tz } });
          toast("Event published to the Circle 🎉"); location.hash = `#/e/${r.event_id}`;
        } catch (err) {
          if (err.data && err.data.detail && err.data.detail.failed) { toast("Can't confirm: " + err.data.detail.failed.map((k) => `${k.check} (${k.note})`).join("; "), true); return; }
          throw err;
        }
      });
    }));
  }

  window.CCAPI = { capi, CC, loadMe, setToken, navState, fmtTime, fmtIso, circleCard, reasonList, chipGroup, readMulti, fail, store, ACCESS, AVAIL, PREFS };
  window.ccAfterHome = async () => { await loadMe(); navState(); renderDraftTray(); decorateHome(); };
  // initial nav state once app.js has booted
  window.addEventListener("hashchange", () => { navState(); renderDraftTray(); });
  loadMe().then(() => { navState(); renderDraftTray(); decorateHome(); });
})();
