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
  const QUICK = [["♟️", "Chess"], ["🏏", "Cricket"], ["⚽", "Football"], ["🎵", "Jazz"], ["🎨", "Painting"], ["📚", "Poetry"],
    ["🌍", "Climate action"], ["🩺", "Diabetes"], ["🧘", "Yoga"], ["🍳", "Cooking"], ["🎮", "Minecraft"], ["💬", "Politics"]];
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
    if (!CC.token) { CC.me = null; CC.meLoaded = true; return null; }
    if (CC.meLoaded && !force) return CC.me;
    try { CC.me = await capi("/api/me"); }
    catch (e) {
      if (e.status === 401) { CC.token = null; store.del(LS_TOKEN); }
      CC.me = null;
    }
    CC.meLoaded = true;
    navState();
    return CC.me;
  }
  function setToken(t) { CC.token = t; store.set(LS_TOKEN, t); CC.meLoaded = false; }

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
        `<a href="#/circles" data-cc="circles">Circles</a><a href="#/my" data-cc="my" hidden>My Circles</a><a href="#/join" data-cc="join" class="nav-cta">Join</a>`);
    }
    const signed = !!CC.me;
    nav.querySelector('[data-cc="my"]').hidden = !signed;
    const j = nav.querySelector('[data-cc="join"]');
    j.textContent = signed ? `👤 ${CC.me.alias}` : "Join";
    j.setAttribute("href", signed ? "#/me" : "#/join");
    const h = location.hash || "#/";
    nav.querySelectorAll("a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") !== "#/" ? h.startsWith(a.getAttribute("href")) : h === "#/" || h === ""));
  }

  // ------------------------------------------------------------------ router hook (called by app.js route())
  window.ccRoute = async (parts) => {
    const r = (parts[0] || "").split("?")[0];
    if (!["join", "me", "circles", "my", "c"].includes(r)) return false;
    await loadMe();
    navState();
    renderDraftTray();
    try {
      if (r === "join") await (CC.me ? viewProfile(true) : viewJoin());
      else if (r === "me") await (CC.me ? viewProfile(false) : viewRestore());
      else if (r === "circles") await viewDiscover(parts[1]);
      else if (r === "my") await (CC.me ? viewMy() : viewRestore());
      else if (r === "c" && parts[1]) await viewCircle(parts[1].split("?")[0], (parts[2] || "discussion").split("?")[0]);
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
    nb.textContent = "Organize a group →";
    nb.classList.remove("primary"); nb.classList.add("ghost");
    nb.insertAdjacentHTML("beforebegin", `<a class="btn primary" id="joinIndividual" href="${CC.me ? "#/circles" : "#/join"}">${CC.me ? "🧭 Find my Circles" : "✨ Join as an individual"}</a>`);
    const sample = document.getElementById("newSample");
    if (sample) { sample.classList.remove("ghost"); sample.classList.add("soft"); sample.textContent = "Try a sample organization"; }
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
    app.innerHTML = `
    <div class="title-row"><div><span class="how-kicker">${mode === "join" ? "✨ Join as an individual" : "👤 My profile"}</span>
      <h2 style="margin-top:10px">${mode === "join" ? "Find your people" : "Edit your profile"}</h2>
      <p>${mode === "join" ? "Tell us what you love, can teach or want to learn. Nothing is shared until you choose to." : "Changes apply to future matches. You stay in control of what members see."}</p></div></div>
    <form id="pf" class="grid2 join-grid" novalidate>
      <div class="card cc"><div class="cc-head"><span class="cc-badge">${ICON.users}</span><div><h2>About you</h2><p>Pseudonyms welcome</p></div><span class="cc-orb a"></span></div>
        <div class="cc-body">
          <div class="field"><label for="fAlias">Display name or alias *</label><div class="iwrap">${ICON.flag}<input id="fAlias" type="text" required minlength="2" maxlength="40" value="${esc(p.alias || "")}" autocomplete="nickname"/></div></div>
          <div class="field"><label for="fArea">Broad area <span class="hint">· city or neighbourhood, never your address</span></label><div class="iwrap">${ICON.pin}<input id="fArea" type="text" maxlength="60" value="${esc(p.area || "")}" placeholder="e.g. Pune, Kothrud"/></div></div>
          <div class="grid2"><div class="field"><label for="fLang">Preferred language (optional)</label><input id="fLang" type="text" maxlength="30" value="${esc(p.language || "")}" placeholder="e.g. Marathi"/></div>
            <div class="field"><label for="fBudget">Max spend per event (optional, private)</label><input id="fBudget" type="number" min="0" max="10000" value="${p.budget_max ?? ""}"/></div></div>
          <div class="field"><label for="fBio">Short bio (optional, shown only if you share your interests)</label><textarea id="fBio" maxlength="280" rows="2">${esc(p.bio || "")}</textarea></div>
          <label class="switch"><input type="checkbox" id="fAdult" ${mode !== "join" ? "checked" : ""}/><span class="sw"></span><span class="si">🔞</span> I am 18 or older *</label>
          <p class="muted small">Self-serve Circles are adults-only. Under-18s can take part through a school, club or other organization.</p>
        </div></div>
      <div class="card"><h3>🎯 Your interests & issues *</h3>
        <p class="muted small">Games, sports, arts, causes, a health topic you want to talk about… Health and political topics are optional — joining such a Circle is visible to its members.</p>
        <div class="quickpicks" aria-label="Quick picks — drag into the box or press to add">${QUICK.map(([e, l]) => `<button type="button" class="qp" draggable="true" data-qp="${esc(l)}" data-emoji="${e}">${e} ${esc(l)}</button>`).join("")}</div>
        <div class="dropzone" id="dz" tabindex="-1"><div class="row" style="flex-wrap:nowrap">
          <input id="fInt" type="text" maxlength="60" placeholder="Type any interest or drop a bubble here…" aria-label="Add an interest"/>
          <button class="btn soft sm" type="button" id="fIntAdd">Add</button></div>
          <div id="intList" aria-live="polite"></div></div>
      </div>
      <div class="card"><h3>🗓 Preferences <span class="muted small">(all optional, private)</span></h3>
        <label>Availability</label>${chipGroup("availability", AVAIL, p.availability || [])}
        <label>How you like to meet</label>${chipGroup("activity_prefs", PREFS, p.activity_prefs || [])}
        <label>Accessibility needs <span class="hint">· used as hard requirements, never shown to others</span></label>${chipGroup("accessibility", ACCESS, p.accessibility || [])}
        <div class="field"><label for="fExcl">Never recommend topics (comma-separated)</label><input id="fExcl" type="text" maxlength="200" value="${esc((p.exclude_topics || []).join(", "))}"/></div>
      </div>
      <div class="card"><h3>🔒 Privacy & consent</h3>
        <label class="switch"><input type="checkbox" id="fDisc" ${p.discoverable ? "checked" : ""}/><span class="sw"></span><span class="si">🧭</span> Use my profile to recommend Circles (discovery consent)</label>
        <label class="switch"><input type="checkbox" id="fShowArea" ${p.show_area ? "checked" : ""}/><span class="sw"></span><span class="si">📍</span> Show my broad area to fellow members</label>
        <label class="switch"><input type="checkbox" id="fShare" ${p.share_interests ? "checked" : ""}/><span class="sw"></span><span class="si">🎯</span> Show my interests & bio to fellow members, and let Circle planning use them</label>
        <div class="visible-box"><b>Who sees what</b><ul>
          <li><b>Members of Circles you join:</b> your alias${"" /* */}, your role, and — only if switched on — your area, interests and bio.</li>
          <li><b>Never shown to anyone:</b> budget, availability, accessibility needs, excluded topics. They're used only as private constraints.</li>
          <li><b>Qloo</b> receives only interest names/IDs from our server — never your alias or area. Withdraw consent or delete everything anytime.</li></ul></div>
      </div>
      <div class="row between join-actions">${mode === "join" ? `<a class="btn ghost" href="#/me">Have a recovery key?</a>` : `<span></span>`}
        <button class="btn primary" type="submit" id="pfSubmit">${mode === "join" ? "Create profile & find Circles →" : "Save changes"}</button></div>
    </form>`;
    const root = document.getElementById("pf");
    root.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => { b.classList.toggle("on"); b.setAttribute("aria-pressed", b.classList.contains("on")); }));

    const list = document.getElementById("intList");
    const timers = {};
    function drawInts() {
      list.innerHTML = st.ints.length ? st.ints.map((t, i) => `<div class="int-row" data-i="${i}">
        <div class="row between"><b>${esc(t.label)}</b><div class="row">
          <select data-intent="${i}" aria-label="Intent for ${esc(t.label)}">${INTENTS.map(([v, l]) => `<option value="${v}" ${t.intent === v ? "selected" : ""}>${l}</option>`).join("")}</select>
          <button type="button" class="iconbtn" data-rm="${i}" aria-label="Remove ${esc(t.label)}">✕</button></div></div>
        <div class="cands">${t.candidates ? (t.candidates.length ? t.candidates.map((c) => candHtml(c, (t.signals || []).some((s) => s.id === c.id))).join("")
          : `<span class="muted small">${esc(t.error || "No Qloo match — it still counts as your declared interest.")}</span>`)
          : t.signals && t.signals.length ? t.signals.map((s) => candHtml({ ...s, description: "", source: s.source || "saved" }, true)).join("") + `<button type="button" class="btn soft sm" data-research="${i}">↻ Search Qloo again</button>`
          : `<span class="muted small"><span class="spinner"></span> Matching with Qloo…</span>`}</div></div>`).join("")
        : `<div class="empty-mini">👆 Add at least one interest — drag a bubble, press one, or type your own.</div>`;
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
        if (st.ints.some((t) => !t.candidates && !(t.signals && t.signals.length))) return toast("Still matching with Qloo — one moment…", true);
        const b = document.getElementById("fBudget").value;
        const body = {
          alias, area: document.getElementById("fArea").value.trim(), language: document.getElementById("fLang").value.trim(),
          bio: document.getElementById("fBio").value.trim(), budget_max: b === "" ? null : Number(b),
          availability: readMulti(root, "availability"), activity_prefs: readMulti(root, "activity_prefs"), accessibility: readMulti(root, "accessibility"),
          exclude_topics: document.getElementById("fExcl").value.split(",").map((x) => x.trim()).filter(Boolean).slice(0, 10),
          adult_confirmed: true, discoverable: document.getElementById("fDisc").checked,
          show_area: document.getElementById("fShowArea").checked, share_interests: document.getElementById("fShare").checked,
          interests: st.ints.map((t) => ({ label: t.label, intent: t.intent, signals: (t.signals || []).map((s) => ({ id: s.id, kind: s.kind })) })),
        };
        const res = await capi("/api/me", { method: mode === "join" ? "POST" : "PUT", body });
        (res.warnings || []).forEach((w) => toast(w));
        if (res.token) { setToken(res.token); store.del(LS_DRAFT); }
        CC.me = res.profile; CC.meLoaded = true; CC.rec = null; navState();
        if (res.token) showRecovery(res.token);
        else { toast("Profile saved ✓"); location.hash = "#/circles"; }
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
    app.insertAdjacentHTML("beforeend", `<div class="grid2" style="margin-top:18px">
      <div class="card"><h3>🧭 Discovery</h3><p class="muted small">${p.discoverable ? `Consent given ${fmtTime(p.consent_at)}. Your profile is used to recommend Circles.` : "Discovery is off — you won't get recommendations and your Qloo taste cache is deleted."}</p>
        <button class="btn ${p.discoverable ? "danger" : "primary"} sm" id="consentBtn">${p.discoverable ? "Withdraw discovery consent" : "Turn discovery on"}</button>
        ${p.taste_retrieved_at ? `<p class="muted small">Qloo taste insights last retrieved ${fmtTime(p.taste_retrieved_at)}.</p>` : ""}
        <h3 style="margin-top:18px">🚫 Blocked people</h3>${blocks.length ? blocks.map((b) => `<div class="row between"><span>${esc(b.alias || "Unknown")}</span><button class="btn soft sm" data-unblock="${esc(b.user_id)}">Unblock</button></div>`).join("") : `<p class="muted small">You haven't blocked anyone.</p>`}</div>
      <div class="card"><h3>🔑 Recovery key</h3><p class="muted small">Use it to open your profile on another device.</p>
        <div class="keybox"><code>${"•".repeat(24)}</code><button class="btn soft sm" id="showKey" type="button">Reveal</button></div>
        <div class="row" style="margin-top:12px"><button class="btn ghost sm" id="signOut">Sign out on this device</button></div>
        <h3 style="margin-top:18px">🗑 Delete my account</h3>
        <p class="muted small">Deletes your profile, interests, Qloo mappings, memberships, votes, RSVPs and blocks. Your posts are erased (threads keep a “[deleted account]” placeholder). Circles you host pass to another member or are archived.</p>
        <button class="btn danger sm" id="delMe">Delete everything</button></div></div>`);
    document.getElementById("consentBtn").onclick = (e) => withBusy(e.currentTarget, async () => {
      CC.me = await capi("/api/me/consent", { method: "PUT", body: { discoverable: !p.discoverable } }); CC.rec = null; viewProfile();
    });
    app.querySelectorAll("[data-unblock]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => { await capi("/api/me/blocks", { body: { user_id: b.dataset.unblock, blocked: false } }); viewProfile(); })));
    document.getElementById("showKey").onclick = (e) => { e.currentTarget.previousElementSibling.textContent = CC.token; };
    document.getElementById("signOut").onclick = () => { if (!confirm("Sign out? You'll need your recovery key to come back.")) return; setToken(null); store.del(LS_TOKEN); CC.me = null; location.hash = "#/"; };
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
      ${recs.length ? `<div class="grid2">${recs.map((c) => circleCard(c, `<details class="why-box" open><summary>Why this Circle?</summary>${reasonList(c.reasons)}<p class="muted tiny">${esc(c.rank_basis)}</p></details>
          <div class="row between"><button class="btn ghost sm" data-skip="${esc(c.id)}">Skip</button><div class="row"><a class="btn soft sm" href="#/c/${esc(c.id)}">View</a><button class="btn primary sm" data-join="${esc(c.id)}">Join Circle</button></div></div>`)).join("")}</div>`
        : `<div class="card empty-state"><div class="es-ic">🌱</div><h3>No existing Circle fits yet</h3><p class="muted">That's how every community starts. Create one below — others with the same interest will be matched to it.</p></div>`}
      ${exc.length ? `<p class="muted small">Hidden because they don't meet your requirements: ${exc.map(([k, v]) => `${v} × ${esc(k)}`).join(", ")}. Requirements always win over taste matches.</p>` : ""}
      ${rec.create_suggestions.length ? `<h2 class="sec-h">🌱 Start a new Circle</h2><div class="grid3">${rec.create_suggestions.map((s) => `<div class="card start-card">
          <h3>${esc(s.label)}</h3><p class="muted small">${s.signals.length ? `Linked to Qloo: ${s.signals.map((x) => esc(x.name)).join(", ")}` : "Declared interest (no Qloo ID)"}</p>
          ${s.suggested_category !== "general" ? `<span class="badge ${s.suggested_category === "health" ? "participant" : "generated"}">${s.suggested_category} topic</span>` : ""}
          <button class="btn primary sm" data-create="${s.interest_id}">Create “${esc(s.label)}” Circle</button></div>`).join("")}</div>` : ""}` : ""}
    <h2 class="sec-h">🔎 Browse all public Circles</h2>
    <form class="row" id="bf"><input type="search" id="bq" value="${esc(q)}" placeholder="Search Circles…" aria-label="Search Circles" style="max-width:360px"/><button class="btn soft sm">Search</button></form>
    <div class="grid3" style="margin-top:12px">${all.length ? all.map((c) => circleCard(c, `<div class="row end"><a class="btn soft sm" href="#/c/${esc(c.id)}">${c.my_status === "active" ? "Open" : "View"}</a></div>`)).join("")
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
    slot.innerHTML = `<form class="card cc" id="cf" style="margin-top:20px"><div class="cc-head"><span class="cc-badge">${ICON.users}</span><div><h2>Create “${esc(s.label)}” Circle</h2><p>You'll be the host. Nothing is published until you confirm.</p></div><span class="cc-orb a"></span></div>
      <div class="cc-body"><div class="grid2">
        <div class="field"><label for="cName">Circle name *</label><input id="cName" type="text" minlength="3" maxlength="80" required value="${esc(s.label)} Circle"/></div>
        <div class="field"><label for="cCat">Topic type</label><select id="cCat">${[["general", "General"], ["health", "Health & wellbeing (peer support)"], ["political", "Politics & civic"]].map(([v, l]) => `<option value="${v}" ${s.suggested_category === v ? "selected" : ""}>${l}</option>`).join("")}</select></div></div>
        <div class="field"><label for="cPurpose">Purpose</label><textarea id="cPurpose" maxlength="400" rows="2" placeholder="What will members do together?"></textarea></div>
        <div class="grid3">
          <div class="field"><label for="cMode">Meeting mode</label><select id="cMode"><option value="either">Online or in person</option><option value="in_person">In person</option><option value="online">Online</option></select></div>
          <div class="field"><label for="cArea">Broad area</label><input id="cArea" type="text" maxlength="60" value="${esc(CC.me.area || "")}"/></div>
          <div class="field"><label for="cVis">Visibility</label><select id="cVis"><option value="public">Public — discoverable</option><option value="private">Private — invite code + approval</option></select></div>
          <div class="field"><label for="cCap">Capacity</label><input id="cCap" type="number" min="3" max="50" value="12"/></div>
          <div class="field"><label for="cMin">Minimum to meet</label><input id="cMin" type="number" min="2" max="10" value="3"/></div>
          <div class="field"><label for="cLang">Language (optional)</label><input id="cLang" type="text" maxlength="30" value="${esc(CC.me.language || "")}"/></div></div>
        <label>Members here want to…</label>${chipGroup("cint", INTENTS, s.intent === "teach" || s.intent === "learn" ? ["teach", "learn"] : [s.intent])}
        <label>Accessibility you commit to</label>${chipGroup("cacc", ACCESS, ["flexible_participation"])}
        <label class="switch"><input type="checkbox" id="cMemEv" checked/><span class="sw"></span><span class="si">📅</span> Any member may propose events (hosts confirm)</label>
        <div class="row end"><button class="btn ghost" type="button" id="cCancel">Cancel</button><button class="btn primary" type="submit">Create Circle</button></div></div></form>`;
    slot.querySelectorAll("[data-multi]").forEach((b) => (b.onclick = () => b.classList.toggle("on")));
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
        try {
          const c = await capi("/api/circles", { body });
          CC.rec = null; toast("Circle created 🎉"); location.hash = `#/c/${c.id}`;
        } catch (err) {
          if (err.status === 409 && err.data && err.data.detail && err.data.detail.circle_id) {
            slot.insertAdjacentHTML("afterbegin", `<div class="notice">${esc(err.data.detail.message)} <a class="btn soft sm" href="#/c/${esc(err.data.detail.circle_id)}">Open “${esc(err.data.detail.name)}”</a></div>`);
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
    app.innerHTML = `<section class="how-hero" style="padding-bottom:10px"><span class="how-kicker">⭕ My Circles</span><h1>Your <span>communities</span></h1></section>
      <div class="grid2"><div><h2 class="sec-h">Circles</h2>${mine.length ? mine.map((c) => circleCard(c, `<div class="row between"><span class="badge ${c.my_status === "pending" ? "participant" : "qloo"}">${c.my_status === "pending" ? "awaiting approval" : c.my_role}</span><a class="btn soft sm" href="#/c/${esc(c.id)}">Open</a></div>`)).join("")
        : `<div class="card empty-state"><div class="es-ic">🧭</div><h3>No Circles yet</h3><a class="btn primary" href="#/circles">Discover Circles</a></div>`}</div>
      <div><h2 class="sec-h">📅 My Events</h2>${evs.length ? evs.map((e) => `<a class="card ev-row" href="#/c/${esc(e.circle_id)}/events">
          <span class="badge ${e.status === "confirmed" ? "qloo" : "participant"}">${e.status}</span><div><b>${esc(e.title)}</b><div class="muted small">${esc(e.circle_name)}${e.chosen_time ? " · " + esc(fmtIso(e.chosen_time)) : ""}${e.my_rsvp ? " · you: " + esc(e.my_rsvp.replace("_", " ")) : ""}</div></div></a>`).join("")
        : `<div class="card empty-state"><div class="es-ic">📅</div><h3>No events yet</h3><p class="muted">Open a Circle and plan an activity with the agent.</p></div>`}</div></div>`;
  }

  // ------------------------------------------------------------------ circle page
  async function viewCircle(cid, tab) {
    const invite = queryParam("invite");
    const c = await capi(`/api/circles/${encodeURIComponent(cid)}${invite ? `?invite=${encodeURIComponent(invite)}` : ""}`);
    const m = c.my_membership, member = m && m.status === "active", mod = member && ["host", "moderator"].includes(m.role);
    const tabs = [["discussion", "💬 Discussion"], ["events", "📅 Events"], ["members", "👥 Members"], ["about", "ℹ️ About"]];
    app.innerHTML = `
    <section class="circle-hero cat-${c.category}">
      <div><span class="how-kicker">${c.category === "health" ? "🩺 Peer support" : c.category === "political" ? "🗳 Civic dialogue" : "⭕ Circle"}${c.visibility === "private" ? " · 🔒 Private" : ""}</span>
        <h1>${esc(c.name)}</h1><p>${esc(c.purpose || `People who share an interest in ${c.topic_label}.`)}</p>
        <div class="sigs">${c.signals.map((s) => `<span class="kind ${esc(s.kind)}" title="Qloo ${esc(s.type)}">${esc(s.kind)} · ${esc(s.name)}</span>`).join("") || `<span class="kind tag">declared · ${esc(c.topic_label)}</span>`}</div></div>
      <div class="ch-side"><div class="ch-count"><b>${c.member_count}</b><span>of ${c.capacity} members</span></div>
        ${!CC.me ? `<a class="btn primary" href="#/join">Join to take part</a>`
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
          <input type="text" maxlength="200" placeholder="Confirmed location (optional)" aria-label="Location"/>
          <button class="btn primary sm" ${e.time_options.length ? "" : "disabled"}>Confirm final plan</button></form>` : ""}
      ${e.status === "confirmed" ? `<div class="rsvp"><b>RSVP</b> <span class="muted small">${e.rsvp_counts.going || 0}/${e.capacity} going · ${e.rsvp_counts.maybe || 0} maybe</span>
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
    list.querySelectorAll("[data-confirm]").forEach((f) => (f.onsubmit = (ev) => {
      ev.preventDefault();
      const eid = f.closest("[data-eid]").dataset.eid, [o, t] = f.querySelectorAll("select");
      withBusy(f.querySelector("button"), async () => {
        try {
          await capi(`/api/circle-events/${eid}/confirm`, { body: { option: +o.value, time_index: t.value === "" ? null : +t.value, location_note: f.querySelector("input").value.trim() || null } });
          toast("Event confirmed 🎉 — members can RSVP now"); tabEvents(c, body, mod);
        } catch (err) {
          if (err.data && err.data.detail && err.data.detail.failed) { toast("Can't confirm: " + err.data.detail.failed.map((k) => `${k.check} (${k.note})`).join("; "), true); return; }
          throw err;
        }
      });
    }));
  }

  window.ccAfterHome = async () => { await loadMe(); navState(); renderDraftTray(); decorateHome(); };
  // initial nav state once app.js has booted
  window.addEventListener("hashchange", () => { navState(); renderDraftTray(); });
  loadMe().then(() => { navState(); renderDraftTray(); decorateHome(); });
})();
