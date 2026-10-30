/* Culture Connect — accounts, dashboard, activities, organisations, real events, chat, meeting places, notifications.
 * Loaded after circles.js; reuses its API client (window.CCAPI) and app.js helpers (esc, toast, withBusy, initials, color).
 * Every success message here is shown only after the backend confirmed the operation.
 */
(() => {
  "use strict";
  const app = document.getElementById("app");
  const X = () => window.CCAPI;
  const capi = (...a) => X().capi(...a);
  const me = () => X().CC;
  const qp = (k) => { const m = location.hash.match(new RegExp(`[?&]${k}=([^&]+)`)); return m ? decodeURIComponent(m[1]) : null; };
  const myTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } };
  const uid = () => (crypto && crypto.randomUUID ? crypto.randomUUID().replace(/-/g, "") : Math.random().toString(36).slice(2) + Date.now().toString(36)).slice(0, 32);
  const fmtTs = (ts) => { try { return new Date(ts * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }); } catch { return ""; } };
  // Event times are wall-clock in the event's own timezone: show the numbers as stored, plus the zone name.
  function wall(s) { const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(s || ""); return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) : null; }
  function when(e) {
    const a = wall(e.starts_at), b = wall(e.ends_at);
    if (!a) return esc(e.starts_at);
    const day = a.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
    const t = (d) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    const sameDay = b && a.toDateString() === b.toDateString();
    return `${day}, ${t(a)}–${b ? (sameDay ? t(b) : b.toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })) : ""} <span class="muted">(${esc(e.timezone)})</span>`;
  }
  const STATUS = { draft: ["generated", "Draft"], published: ["qloo", "Upcoming"], full: ["participant", "Full"], past: ["generated", "Past"],
    cancelled: ["danger-b", "Cancelled"], completed: ["generated", "Completed"] };
  const statusBadge = (s) => { const [c, l] = STATUS[s] || ["generated", s]; return `<span class="badge ${c}">${l}</span>`; };
  const verifyBadge = (s) => s === "verified" ? `<span class="badge vb-ok" title="Reviewed by a Culture Connect administrator">✓ Verified</span>`
    : s === "pending" ? `<span class="badge vb-pend">Verification pending</span>` : `<span class="badge vb-no">Not verified</span>`;
  function contactBtn(ct, label = "Contact organiser") {
    if (!ct || !ct.kind) return `<span class="muted small">The organiser hasn't published a contact method.</span>`;
    if (ct.kind === "circle_chat") return `<a class="btn soft" href="${esc(ct.value)}">💬 Message the host in Circle chat</a>`;
    const href = ct.kind === "email" ? `mailto:${ct.value}` : ct.kind === "phone" ? `tel:${ct.value.replace(/[^+0-9]/g, "")}` : ct.value;
    const icon = ct.kind === "email" ? "✉️" : ct.kind === "phone" ? "📞" : "🔗";
    return `<a class="btn soft" href="${esc(href)}" ${ct.kind === "url" ? 'target="_blank" rel="noopener noreferrer"' : ""}>${icon} ${esc(label)}</a>`;
  }
  function mapEmbed(m, label) {
    const d = 0.004, bbox = `${m.lon - d},${m.lat - d * 0.7},${m.lon + d},${m.lat + d * 0.7}`;
    return `<div class="mapbox"><iframe title="Map of ${esc(label)}" loading="lazy" referrerpolicy="no-referrer"
      src="https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent(bbox)}&layer=mapnik&marker=${m.lat},${m.lon}"></iframe>
      <p class="muted tiny">Map © OpenStreetMap contributors. Pin ${m.source === "nominatim" ? "found by address search (OpenStreetMap Nominatim)" : m.source === "qloo" ? "from a Qloo place result" : "placed by the organiser"} —
      a map pin doesn't confirm the venue is open, safe or booked. <a href="https://www.openstreetmap.org/?mlat=${m.lat}&mlon=${m.lon}#map=18/${m.lat}/${m.lon}" target="_blank" rel="noopener noreferrer">Open larger map</a></p></div>`;
  }
  const needAuth = (next) => { if (!me().auth) { location.hash = `#/auth/signin?next=${encodeURIComponent(next || location.hash.slice(2))}`; return true; } return false; };
  const empty = (ic, title, text = "", cta = "") => `<div class="card empty-state"><div class="es-ic">${ic}</div><h3>${title}</h3>${text ? `<p class="muted">${text}</p>` : ""}${cta}</div>`;
  const skel = (n = 3) => `<div class="skel-wrap">${Array.from({ length: n }, () => `<div class="skel"></div>`).join("")}</div>`;
  const goNext = (fallback) => { const n = qp("next"); location.hash = n ? (n.startsWith("#") ? n : `#/${n}`) : fallback; };

  // ------------------------------------------------------------------ router
  window.ppRoute = async (r, parts) => {
    const sub = (parts[1] || "").split("?")[0], third = (parts[2] || "").split("?")[0];
    if (r === "auth") return viewAuth(sub || "signin");
    if (r === "start") return needAuth("start") || viewStart();
    if (r === "dashboard") return needAuth("dashboard") || viewDashboard();
    if (r === "activities") return viewActivities();
    if (r === "notifications") return needAuth("notifications") || viewNotifications();
    if (r === "orgs") return viewOrgs();
    if (r === "o" && sub) return viewOrgPublic(sub);
    if (r === "org") return needAuth("org") || (sub ? viewWorkspace(sub, third || "overview", parts[3]) : viewOrgHome());
    if (r === "org-invite") return needAuth(location.hash.slice(2)) || viewOrgInvite();
    if (r === "e" && sub) return viewEvent(sub);
    if (r === "admin") return needAuth("admin") || viewAdmin();
    if (r === "agent") return needAuth(location.hash.slice(2)) || (me().me ? window.agView(parts) : viewStart());
    return false;
  };

  // ------------------------------------------------------------------ auth
  function pwHint() { return `<p class="muted tiny">At least 10 characters, with upper- and lower-case letters and a number.</p>`; }
  async function viewAuth(mode) {
    const titles = { signin: "Welcome back", signup: "Create your account", forgot: "Reset your password", reset: "Choose a new password", verify: "Confirm your email", recover: "Restore an older profile" };
    const shell = (inner, sub = "") => `<div class="auth-wrap"><div class="card auth-card"><div class="auth-logo">🔐</div><h2>${titles[mode] || "Account"}</h2>${sub ? `<p class="muted">${sub}</p>` : ""}${inner}</div></div>`;
    if (mode === "signup") {
      app.innerHTML = shell(`<form id="af" novalidate>
        <div class="field"><label for="aEmail">Email</label><input id="aEmail" type="email" autocomplete="email" required/></div>
        <div class="field"><label for="aPw">Password</label><input id="aPw" type="password" autocomplete="new-password" required/>${pwHint()}</div>
        <div class="field"><label for="aPw2">Confirm password</label><input id="aPw2" type="password" autocomplete="new-password" required/></div>
        <p class="form-err" id="aErr" role="alert"></p>
        <button class="btn primary wide" type="submit">Create account</button>
        <p class="small center">Already have an account? <a href="#/auth/signin${qp("next") ? `?next=${encodeURIComponent(qp("next"))}` : ""}">Sign in</a></p></form>`,
        "One account works for both individuals and organisations.");
      bindForm(async () => {
        const email = val("aEmail"), pw = val("aPw");
        if (pw !== val("aPw2")) throw new Error("Passwords don't match.");
        const r = await capi("/api/auth/signup", { body: { email, password: pw, mode: qp("next") === "org" ? "organisation" : qp("next") === "join" ? "individual" : null } });
        X().setToken(r.token); await X().loadMe(true);
        toast(r.email_delivery === "sent" ? "Account created — check your inbox to confirm your email" : "Account created ✓");
        goNext("#/start");
      });
    } else if (mode === "signin") {
      app.innerHTML = shell(`<form id="af" novalidate>
        <div class="field"><label for="aEmail">Email</label><input id="aEmail" type="email" autocomplete="email" required/></div>
        <div class="field"><label for="aPw">Password</label><input id="aPw" type="password" autocomplete="current-password" required/></div>
        <p class="form-err" id="aErr" role="alert"></p>
        <button class="btn primary wide" type="submit">Sign in</button>
        <p class="small center"><a href="#/auth/forgot">Forgot password?</a> · New here? <a href="#/auth/signup${qp("next") ? `?next=${encodeURIComponent(qp("next"))}` : ""}">Create an account</a></p>
        <p class="tiny center muted"><a href="#/auth/recover">I have a recovery key from an older profile</a></p></form>`);
      bindForm(async () => {
        const r = await capi("/api/auth/signin", { body: { email: val("aEmail"), password: val("aPw") } });
        X().setToken(r.token); await X().loadMe(true);
        toast("Signed in ✓");
        goNext(me().me ? "#/dashboard" : "#/start");
      });
    } else if (mode === "forgot") {
      app.innerHTML = shell(`<form id="af"><div class="field"><label for="aEmail">Account email</label><input id="aEmail" type="email" autocomplete="email" required/></div>
        <p class="form-err" id="aErr" role="alert"></p><button class="btn primary wide" type="submit">Send reset link</button>
        <p class="small center"><a href="#/auth/signin">Back to sign in</a></p></form><div id="aOut"></div>`);
      bindForm(async () => {
        const r = await capi("/api/auth/forgot", { body: { email: val("aEmail") } });
        document.getElementById("aOut").innerHTML = `<div class="notice">${esc(r.message)}${r.email_configured ? "" : "<br/><b>Note:</b> email isn't configured on this server yet, so the link was written to the server console instead of being emailed."}</div>`;
      });
    } else if (mode === "reset") {
      app.innerHTML = shell(`<form id="af"><div class="field"><label for="aPw">New password</label><input id="aPw" type="password" autocomplete="new-password" required/>${pwHint()}</div>
        <div class="field"><label for="aPw2">Confirm password</label><input id="aPw2" type="password" autocomplete="new-password" required/></div>
        <p class="form-err" id="aErr" role="alert"></p><button class="btn primary wide" type="submit">Save new password</button></form>`, "You'll be signed out on other devices.");
      bindForm(async () => {
        if (val("aPw") !== val("aPw2")) throw new Error("Passwords don't match.");
        const r = await capi("/api/auth/reset", { body: { token: qp("token") || "", password: val("aPw") } });
        X().setToken(r.token); await X().loadMe(true); toast("Password updated ✓"); location.hash = "#/dashboard";
      });
    } else if (mode === "verify") {
      app.innerHTML = shell(`<p class="muted">Confirming…</p>`);
      try { await capi("/api/auth/verify", { body: { token: qp("token") || "" } }); app.innerHTML = shell(`<div class="notice ok-n">✅ Your email is confirmed.</div><a class="btn primary wide" href="#/dashboard">Continue</a>`); if (me().auth) X().loadMe(true); }
      catch (e) { app.innerHTML = shell(`<div class="notice">${esc(e.message)}</div><a class="btn ghost wide" href="#/me">Go to my account</a>`); }
    } else if (mode === "recover") {
      app.innerHTML = shell(`<form id="af"><div class="field"><label for="aKey">Recovery key</label><input id="aKey" type="password" autocomplete="off" required/></div>
        <p class="form-err" id="aErr" role="alert"></p><button class="btn primary wide" type="submit">Restore</button></form>`,
        "Profiles created before accounts existed used a private recovery key. After restoring, add an email and password to secure it.");
      bindForm(async () => {
        X().setToken(val("aKey"));
        await X().loadMe(true);
        if (!me().auth) { X().setToken(null); throw new Error("That key didn't match any profile."); }
        toast("Profile restored — now secure it with an email and password"); location.hash = "#/me";
      });
    } else location.hash = "#/auth/signin";
  }
  const val = (id) => (document.getElementById(id).value || "").trim();
  function bindForm(fn) {
    const f = document.getElementById("af");
    f.onsubmit = (e) => {
      e.preventDefault();
      const err = document.getElementById("aErr"); if (err) err.textContent = "";
      withBusy(f.querySelector('button[type="submit"]'), async () => {
        try { await fn(); } catch (ex) { if (err) err.textContent = ex.status === 0 ? "You appear to be offline." : ex.message; else throw ex; }
      });
    };
  }
  window.ppAccountCard = () => {
    const a = me().auth || {};
    if (a.legacy) return `<div class="notice">This profile was created before accounts existed. Add an email and password so you never lose access.</div>
      <form id="claimF"><div class="field"><label for="cEmail">Email</label><input id="cEmail" type="email" required/></div>
      <div class="field"><label for="cPw">Password</label><input id="cPw" type="password" autocomplete="new-password" required/>${pwHint()}</div>
      <button class="btn primary sm" type="submit">Secure my account</button></form>`;
    const ac = a.account || {};
    const Ic = (k) => (window.wsIcon ? window.wsIcon(k) : "");
    return `<div class="ac-id"><small>Email</small><b>${esc(ac.email || "")}</b>
        <div class="ac-v">${ac.email_verified ? `<span class="pf-pill ok">${Ic("check")} Confirmed</span>` : `<span class="pf-pill warn">Not confirmed</span><button type="button" class="linkbtn" id="resendV">Resend link</button>`}</div></div>
      <div class="ac-acts"><details class="ac-row"><summary><span>${Ic("key")} Change password</span>${Ic("chev")}</summary>
        <form id="pwF"><div class="field"><label for="pwCur">Current password</label><input id="pwCur" type="password" autocomplete="current-password"/></div>
        <div class="field"><label for="pwNew">New password</label><input id="pwNew" type="password" autocomplete="new-password"/>${pwHint()}</div><button class="btn soft sm" type="submit">Update password</button></form></details>
        <a class="ac-row" href="#/org"><span>${Ic("building")} ${a.orgs && a.orgs.length ? "My organisations" : "Create an organisation"}</span>${Ic("chev")}</a>
        <button type="button" class="ac-out" id="signOut">${Ic("logout")} Sign out</button></div>`;
  };
  window.ppBindAccountCard = () => {
    const cf = document.getElementById("claimF");
    if (cf) cf.onsubmit = (e) => { e.preventDefault(); withBusy(e.submitter, async () => {
      const r = await capi("/api/auth/claim", { body: { email: val("cEmail"), password: val("cPw") } });
      X().setToken(r.token); await X().loadMe(true); toast("Account secured ✓"); location.reload(); }); };
    const rv = document.getElementById("resendV");
    if (rv) rv.onclick = (e) => withBusy(e.currentTarget, async () => { const r = await capi("/api/auth/resend-verification", { method: "POST" }); toast(r.email_configured ? "Verification email sent" : "Email isn't configured on this server — the link was written to the server console"); });
    const pf = document.getElementById("pwF");
    if (pf) pf.onsubmit = (e) => { e.preventDefault(); withBusy(e.submitter, async () => { await capi("/api/auth/password", { body: { current: val("pwCur"), new: val("pwNew") } }); toast("Password updated ✓"); pf.reset(); }); };
    const so = document.getElementById("signOut");
    if (so) so.onclick = (e) => withBusy(e.currentTarget, async () => { await capi("/api/auth/signout", { method: "POST" }).catch(() => {}); X().setToken(null); me().me = null; me().auth = null; X().navState(); toast("Signed out"); location.hash = "#/"; });
  };

  // ------------------------------------------------------------------ start (choose path)
  async function viewStart() {
    const a = me().auth;
    app.innerHTML = `<section class="how-hero"><span class="how-kicker">👋 Welcome</span><h1>How would you like to <span>take part?</span></h1>
      <p class="muted">You can do both with the same account.</p></section>
      <div class="grid2 start-grid">
        <a class="card start-path" href="${me().me ? "#/dashboard" : "#/join"}" data-mode="individual"><div class="sp-ic g1">🧭</div><h2>Find my Circle</h2>
          <p class="muted">Tell us what you enjoy, can teach or want to learn. We'll match you with small groups nearby.</p><span class="btn primary">${me().me ? "Open my dashboard" : "Start onboarding"} →</span></a>
        <a class="card start-path" href="#/org" data-mode="organisation"><div class="sp-ic g5">🏢</div><h2>Start or manage an Organisation</h2>
          <p class="muted">Publish real events, run programmes, and help people form Circles.</p><span class="btn ghost">${a.orgs && a.orgs.length ? "Open my organisation" : "Create an organisation"} →</span></a></div>`;
    app.querySelectorAll("[data-mode]").forEach((el) => el.addEventListener("click", () => { capi("/api/auth/mode", { method: "PUT", body: { mode: el.dataset.mode } }).catch(() => {}); }));
  }

  // ------------------------------------------------------------------ dashboard
  // ------------------------------------------------------------------ personalised discovery dashboard
  // Everything below comes from GET /api/agent/discovery: results persisted by the backend discovery workflow
  // (Qloo resolution -> insights -> Circle + event matching -> ranking). Nothing here is generated in the browser.
  let dashTimer = null;
  const RSRC = { declared: ["participant", "You said"], qloo: ["qloo", "Qloo"], app: ["generated", "App"], preference: ["generated", "App"] };
  const why = (rs, n = 3) => `<div class="why">${(rs || []).slice(0, n).map((r) => { const [c, l] = RSRC[r.source] || RSRC.app; return `<div><span class="badge ${c}">${l}</span> ${esc(r.text)}</div>`; }).join("")}</div>`;
  const STAGE_IC = { done: "✓", warning: "⚠", failed: "✕", running: "⏳", pending: "…", skipped: "↷", not_run: "·" };
  function evDate(e) { const d = wall(e.starts_at); return d ? `<div class="evc-date"><b>${d.getDate()}</b><span>${d.toLocaleDateString(undefined, { month: "short" })}</span></div>` : ""; }
  function evLoc(e) { return e.location_status === "online" ? "💻 Online" : e.location_status === "confirmed" ? "📍 " + esc([e.venue_name, e.address].filter(Boolean).join(", ")) : "📍 Location to be confirmed"; }
  function recEvent(e) {
    const own = e.owner || {};
    return `<div class="card rec-row" data-rec="event:${esc(e.id)}">${evDate(e)}<div class="rec-main"><div class="row between"><a href="#/e/${esc(e.id)}"><b>${esc(e.title)}</b></a>
      <button class="iconbtn" data-dismiss="event:${esc(e.id)}" title="Not interested" aria-label="Dismiss ${esc(e.title)}">✕</button></div>
      <div class="muted small">${when(e)} · ${evLoc(e)}</div>
      <div class="muted tiny">${own.kind === "org" ? `🏢 ${esc(own.name)} ${verifyBadge(own.verification_status)}` : own.name ? `⭕ ${esc(own.name)}` : ""} · ${e.going}/${e.capacity} going · <span class="badge generated">${esc(e.source)}</span>
      ${(e.interest_tags || []).map((t) => `<span class="chip sm">${esc(t)}</span>`).join("")}</div>
      ${why(e.reasons)}
      <div class="row end">${e.my_rsvp ? `<span class="badge participant ok-b">You: ${esc(e.my_rsvp.replace("_", " "))}</span>` : ""}<a class="btn ${e.my_rsvp ? "soft" : "primary"} sm" href="#/e/${esc(e.id)}">${e.my_rsvp ? "View" : "RSVP"}</a></div></div></div>`;
  }
  function recCircle(c) {
    return `<div class="card rec-row" data-rec="circle:${esc(c.id)}"><div class="evc-date circ">⭕</div><div class="rec-main"><div class="row between"><a href="#/c/${esc(c.id)}"><b>${esc(c.name)}</b></a>
      <button class="iconbtn" data-dismiss="circle:${esc(c.id)}" title="Not interested" aria-label="Dismiss ${esc(c.name)}">✕</button></div>
      <div class="muted small">${c.member_count}/${c.capacity} members · ${esc(c.meeting_mode.replace("_", " "))}${c.area ? " · " + esc(c.area) : ""}${c.org ? ` · 🏢 ${esc(c.org.name)}` : ""}</div>
      ${(c.signals || []).length ? `<div class="tiny">${c.signals.map((s) => `<span class="chip sm" title="Qloo ID ${esc(s.id)}">🔷 ${esc(s.name)} <span class="muted">${esc(s.kind)}</span></span>`).join("")}</div>` : ""}
      ${why(c.reasons)}
      <div class="row end"><a class="btn soft sm" href="#/c/${esc(c.id)}">View</a><button class="btn primary sm" data-join="${esc(c.id)}">${c.join_mode === "request" ? "Request to join" : "Join"}</button></div></div></div>`;
  }
  function statusBar(st, r) {
    if (!st) return "";
    if (st.state === "consent_off") return `<div class="card ds-status warn"><b>🔒 Discovery is off.</b> Turn on discovery consent so we can recommend Circles and events. <a class="btn primary sm" href="#/me">Privacy settings</a></div>`;
    const label = { running: "⏳ Finding Circles and events for you…", ready: r && r.degraded ? "⚠ Recommendations ready — some Qloo data was unavailable (degraded)" : "✓ Recommendations up to date",
      failed: "✕ Discovery failed", paused: "⏸ Discovery paused", skipped: "↷ Discovery skipped", not_started: "Discovery hasn't started yet", onboarding: "Finish onboarding to start discovery" }[st.state] || st.state;
    const fail = st.state === "failed" || st.state === "skipped" || st.state === "not_started" || (r && r.degraded);
    return `<details class="card ds-status ${st.state === "running" ? "run" : fail ? "warn" : "ok"}" ${st.state === "running" || st.state === "failed" ? "open" : ""}>
      <summary><b>${label}</b> <span class="muted tiny">${r ? `· updated ${fmtTs(r.generated_at)}` : ""}${st.retry_at ? ` · retry scheduled ${fmtTs(st.retry_at)}` : ""}</span>
      ${fail ? `<button class="btn soft sm" id="dsRetry" type="button">↻ Retry now</button>` : ""}</summary>
      <ol class="ds-stages">${st.stages.map((s) => `<li class="s-${s.state}" title="${esc(s.message || "")}"><span>${STAGE_IC[s.state] || "·"}</span>${esc(s.label)}</li>`).join("")}</ol>
      ${st.error ? `<p class="form-err small">${esc(st.error)}</p>` : ""}
      ${st.stages.filter((s) => s.state === "warning" || s.state === "failed").map((s) => `<p class="small muted">⚠ <b>${esc(s.label)}:</b> ${esc(s.message)}</p>`).join("")}
      <p class="tiny muted">Every stage runs on the server and is logged step by step in the <a href="#/agent/runs">Agent Activity Centre</a>.</p></details>`;
  }
  async function viewDashboard() {
    const p = me().me;
    if (!p) return viewStart();
    if (window.wsForYou) return window.wsForYou();  // unified Discover workspace (workspace.js)
    clearTimeout(dashTimer);
    if (!app.querySelector(".dash-hero")) app.innerHTML = skel(4);
    const [circles, res, ag] = await Promise.all([capi("/api/me/circles").catch(() => []),
      capi("/api/agent/discovery").catch(() => ({ result: null, status: null })), capi("/api/agent/summary").catch(() => null)]);
    if (!location.hash.startsWith("#/dashboard")) return;
    const r = res.result, st = res.status;
    const verified = me().auth.account && me().auth.account.email_verified;
    const ints = [...new Set([...(p.interests || []).map((i) => i.label), ...((r && r.events) || []).flatMap((e) => e.interest_tags || [])])];
    const f = window.__dashF || (window.__dashF = { interest: "", days: "", loc: "" });
    const evs = ((r && r.events) || []).filter((e) => (!f.interest || (e.interest_tags || []).includes(f.interest))
      && (!f.days || (wall(e.starts_at) && wall(e.starts_at) - new Date() <= +f.days * 864e5))
      && (!f.loc || (f.loc === "online" ? e.location_status === "online" : norm([e.venue_name, e.address].join(" ")).includes(norm(f.loc)))));
    const top = (r && r.top) || [];
    const topIds = new Set(top.map((x) => `${x.type}:${x.id}`));
    const moreCircles = ((r && r.circles) || []).filter((c) => !topIds.has(`circle:${c.id}`));
    app.innerHTML = `
    ${me().auth.account && !verified ? `<div class="notice">Please confirm your email (${esc(me().auth.account.email)}). <a href="#/me">Resend link</a></div>` : ""}
    <section class="dash-hero"><div><span class="how-kicker">🧭 Your discovery</span><h1>Hi ${esc(p.alias)} 👋</h1>
      <p class="muted">Picked for your interests${p.area ? ` around ${esc(p.area)}` : ""} — no searching needed. ${ag && ag.invites_pending ? `<a href="#/agent">🤖 ${ag.invites_pending} Circle invitation(s) waiting</a>` : ""}</p></div></section>
    ${statusBar(st, r)}
    <h2 class="sec-h">✨ Recommended for you</h2>
    ${top.length ? `<div class="grid2 rec-grid">${top.map((x) => x.type === "event" ? recEvent(x) : recCircle(x)).join("")}</div>`
      : st && st.state === "running" ? skel(2)
      : empty("🌱", "No matches yet", r ? "No existing Circle or upcoming event matches your interests right now. We'll update this automatically when one appears" + ((r.formation || []).length ? ` — and we're forming new Circles for ${r.formation.map((x) => esc(x.label)).join(", ")}.` : ".") : "", `<a class="btn soft" href="#/me">Add interests</a>`)}
    <div class="grid2" style="margin-top:22px">
      <div><h2 class="sec-h">⭕ Your Circles</h2>
        ${circles.length ? circles.map((c) => `<a class="card ev-row" href="#/c/${esc(c.id)}"><span>⭕</span><div><b>${esc(c.name)}</b><div class="muted tiny">${c.member_count} members · ${c.my_status === "pending" ? "request pending" : esc(c.my_role)}</div></div></a>`).join("")
          : `<p class="muted small">You haven't joined a Circle yet.</p>`}
        ${moreCircles.length ? `<h3 class="sec-h small-h">More Circles for you</h3>${moreCircles.slice(0, 4).map(recCircle).join("")}` : ""}
        ${((r && r.proposals) || []).length ? `<h3 class="sec-h small-h">🗳 Activity proposals in your Circles</h3>${r.proposals.map((x) => `<a class="card ev-row" href="${esc(x.link)}"><span class="badge participant">Proposal</span><div><b>${esc(x.title)}</b><div class="muted tiny">⭕ ${esc(x.circle_name)} · by ${esc(x.by)} · ${esc(x.label)}</div></div></a>`).join("")}` : ""}
      </div>
      <div><h2 class="sec-h">📅 Events for your interests</h2>
        <div class="row dash-filters">
          <select id="dfInt" aria-label="Interest"><option value="">All interests</option>${ints.map((i) => `<option ${f.interest === i ? "selected" : ""}>${esc(i)}</option>`).join("")}</select>
          <select id="dfDays" aria-label="Date"><option value="">Any date</option><option value="7" ${f.days === "7" ? "selected" : ""}>Next 7 days</option><option value="30" ${f.days === "30" ? "selected" : ""}>Next 30 days</option></select>
          <input id="dfLoc" type="text" maxlength="40" placeholder="Area or 'online'" value="${esc(f.loc)}" aria-label="Location"/></div>
        ${evs.length ? evs.slice(0, 8).map(recEvent).join("") : `<p class="muted small">${r && r.events.length ? "No events match these filters." : "No upcoming Culture Connect events match your interests yet."} ${r && r.external_events && !r.external_events.configured ? "External event listings aren't connected." : ""}</p>`}
      </div></div>
    ${r && (r.discover_new || []).length ? `<h2 class="sec-h" style="margin-top:22px">🔷 Discover something new <span class="badge qloo">Qloo</span></h2>
      <p class="muted small">${esc(r.discover_new[0].because)}. Save one to use it for your matches, or explore it.</p>
      <div class="dn-list">${r.discover_new.map((x) => `<div class="dn ${x.saved ? "on" : ""}"><b>${esc(x.name)}</b>
        <button class="iconbtn" data-save="${esc(x.id)}" data-saved="${x.saved ? 1 : 0}" title="${x.saved ? "Saved — click to unsave" : "Save to my discoveries"}">${x.saved ? "★" : "☆"}</button>
        <a class="iconbtn" href="#/circles?q=${encodeURIComponent(x.name)}" title="Explore Circles">→</a>
        <button class="iconbtn" data-dismiss="interest:${esc(x.id)}" title="Not for me">✕</button></div>`).join("")}</div>
      ${(r.activity_ideas || []).length ? `<p class="tiny muted" style="margin-top:8px">Ideas (item from Qloo, wording by the app): ${r.activity_ideas.slice(0, 4).map((i) => esc(i.idea)).join(" · ")}</p>` : ""}
      <p class="tiny"><a href="#/me">Update my interests</a></p>` : ""}`;
    const again = () => setTimeout(() => location.hash.startsWith("#/dashboard") && viewDashboard(), 900);
    app.querySelectorAll("[data-join]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const j = await capi(`/api/circles/${b.dataset.join}/join`, { method: "POST", body: {} });
      toast(j.status === "active" ? "Joined ✓" : "Request sent — a host will review it ✓"); again();
    }));
    app.querySelectorAll("[data-dismiss]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const [t, ...rest] = b.dataset.dismiss.split(":"); const id = rest.join(":");
      await capi("/api/agent/feedback", { body: { item_type: t, item_id: id, action: "dismissed" } });
      b.closest(".rec-row, .dn")?.remove(); toast("Got it — we won't suggest that again");
    }));
    app.querySelectorAll("[data-save]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      await capi("/api/agent/feedback", { body: { item_type: "interest", item_id: b.dataset.save, action: b.dataset.saved === "1" ? "clear" : "saved" } });
      toast(b.dataset.saved === "1" ? "Removed from saved" : "Saved — updating your matches"); again();
    }));
    const rb = document.getElementById("dsRetry");
    if (rb) rb.onclick = (e) => { e.preventDefault(); withBusy(rb, async () => { const x = await capi("/api/agent/discovery/refresh", { method: "POST", body: {} }); if (!x.queued) toast(x.message || "Not started", true); else { toast("Discovery restarted"); again(); } }); };
    [["dfInt", "interest"], ["dfDays", "days"], ["dfLoc", "loc"]].forEach(([id, k]) => { const el = document.getElementById(id); if (el) el.onchange = () => { f[k] = el.value.trim(); viewDashboard(); }; });
    if (st && st.state === "running") dashTimer = setTimeout(() => location.hash.startsWith("#/dashboard") && viewDashboard(), 2500);
  }
  const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  function eventRow(e) {
    return `<a class="card ev-row" href="#/e/${esc(e.id)}">${statusBadge(e.display_status)}<div style="min-width:0"><b>${esc(e.title)}</b>
      <div class="muted small">${when(e)} · ${e.location_status === "confirmed" ? "📍 " + esc(e.venue_name || e.address) : e.location_status === "online" ? "💻 Online" : "📍 Location to be confirmed"}</div>
      <div class="muted tiny">${e.owner ? (e.owner.kind === "org" ? "🏢 " : "⭕ ") + esc(e.owner.name) : ""}${e.my_rsvp ? ` · you: ${esc(e.my_rsvp.replace("_", " "))}` : ""}</div></div></a>`;
  }
  function eventCard(e) {
    const pct = Math.min(100, Math.round((e.going / Math.max(1, e.capacity)) * 100));
    return `<a class="card evcard" href="#/e/${esc(e.id)}"><div class="evc-date">${(() => { const d = wall(e.starts_at); return d ? `<b>${d.getDate()}</b><span>${d.toLocaleDateString(undefined, { month: "short" })}</span>` : ""; })()}</div>
      <div class="evc-body"><div class="row between">${statusBadge(e.display_status)}${e.category ? `<span class="chip">${esc(e.category)}</span>` : ""}</div>
      <h3>${esc(e.title)}</h3><div class="muted small">${when(e)}</div>
      <div class="muted small">${e.location_status === "confirmed" ? "📍 " + esc([e.venue_name, e.address].filter(Boolean).join(", ")) : e.location_status === "online" ? "💻 Online" : "📍 Location to be confirmed"}</div>
      <div class="cap"><div class="cap-bar"><i style="width:${pct}%"></i></div><span>${e.going}/${e.capacity} going</span></div>
      ${e.owner ? `<div class="tiny muted">${e.owner.kind === "org" ? `🏢 ${esc(e.owner.name)} ${verifyBadge(e.owner.verification_status)}` : `⭕ ${esc(e.owner.name)}`}</div>` : ""}</div></a>`;
  }

  // ------------------------------------------------------------------ activities
  async function viewActivities() {
    app.innerHTML = skel(3);
    const q = qp("q") || "", area = qp("area") || (me().me ? me().me.area : "") || "";
    const [mine, pub] = await Promise.all([me().auth ? capi("/api/me/activities").catch(() => null) : Promise.resolve(null),
      capi(`/api/events?q=${encodeURIComponent(q)}&area=${encodeURIComponent(qp("area") || "")}`)]);
    const ws = !!window.wsEventTile && !!me().me;
    const line = (t, h, l) => `<div class="empty-line"><span>${t}</span>${h ? `<a class="btn soft sm" href="${h}">${l}</a>` : ""}</div>`;
    app.innerHTML = `<section class="how-hero" style="padding-bottom:6px"><span class="how-kicker">📅 Activities</span><h1>Things to <span>do together</span></h1></section>
      ${mine && ws ? (mine.upcoming.length || mine.proposals.length ? `<div class="grid2"><div><h2 class="sec-h">My upcoming</h2>${mine.upcoming.map(eventRow).join("") || line("Nothing booked yet.")}</div>
        <div><h2 class="sec-h">🗳 Proposals to vote on</h2>${mine.proposals.map((x) => `<a class="card ev-row" href="#/c/${esc(x.circle_id)}/events"><span class="badge participant">Proposal</span><div><b>${esc(x.title)}</b><div class="muted small">${esc(x.circle_name)} · not confirmed yet</div></div></a>`).join("") || line("Nothing to vote on.")}</div></div>`
        : line("Nothing planned yet — RSVP below or join a Circle.", "#/dashboard", "See picks for you"))
      : mine ? `<div class="grid2"><div><h2 class="sec-h">My upcoming</h2>${mine.upcoming.map(eventRow).join("") || empty("📭", "No upcoming activities", "RSVP to an event or vote on a Circle proposal.")}</div>
        <div><h2 class="sec-h">🗳 Proposals to vote on</h2>${mine.proposals.map((x) => `<a class="card ev-row" href="#/c/${esc(x.circle_id)}/events"><span class="badge participant">vote</span><div><b>${esc(x.title)}</b><div class="muted small">${esc(x.circle_name)}</div></div></a>`).join("") || empty("🗳", "Nothing to vote on")}
        ${mine.past.length ? `<h2 class="sec-h">Past</h2>${mine.past.slice(0, 5).map(eventRow).join("")}` : ""}</div></div>` : `<div class="card cta-card"><div><h3>Sign in to see your activities</h3><p class="muted">Your RSVPs and Circle events appear here.</p></div><a class="btn primary" href="#/auth/signin?next=activities">Sign in</a></div>`}
      <h2 class="sec-h">🌍 Public events by organisations</h2>
      <form class="row" id="evf"><input type="search" id="evq" placeholder="Search events…" value="${esc(q)}" aria-label="Search events" style="max-width:280px"/>
        <input type="search" id="eva" placeholder="Area (e.g. Pune)" value="${esc(qp("area") || "")}" aria-label="Area" style="max-width:200px"/><button class="btn soft sm">Search</button></form>
      <div class="${ws ? "cc-tiles" : "grid3"}" style="margin-top:12px">${pub.map((e) => ws ? window.wsEventTile({ ...e, my_rsvp: ((mine && mine.upcoming) || []).find((x) => x.id === e.id)?.my_rsvp || null }, { noReason: true }) : eventCard(e)).join("") || `<div style="grid-column:1/-1">${ws ? line("No public events match.", "#/activities", "Clear search") : empty("🗓", "No public events match", "Organisations publish events here as they're scheduled.")}</div>`}</div>`;
    if (ws && window.wsBindActions) window.wsBindActions(app, () => viewActivities());
    document.getElementById("evf").onsubmit = (e) => { e.preventDefault(); location.hash = `#/activities?q=${encodeURIComponent(val("evq"))}&area=${encodeURIComponent(val("eva"))}`; };
    void area;
  }

  // ------------------------------------------------------------------ notifications + bell
  async function viewNotifications() {
    const r = await capi("/api/notifications");
    app.innerHTML = `<div class="title-row"><div><span class="how-kicker">🔔 Notifications</span><h2 style="margin-top:10px">Updates for you</h2></div>
      ${r.unread ? `<button class="btn soft sm" id="readAll">Mark all as read</button>` : ""}</div>
      ${r.items.map((n) => `<a class="card ev-row notif ${n.read_at ? "" : "unread"}" href="${esc(n.link || "#/dashboard")}" data-nid="${n.id}"><span>${({ event_update: "✏️", event_cancelled: "❌", event_confirmed: "🎉", join_request: "🙋", join_approved: "✅", verification: "🛡", feedback: "⭐", report: "🚩" })[n.kind] || "🔔"}</span>
        <div><b>${esc(n.title)}</b>${n.body ? `<div class="small">${esc(n.body)}</div>` : ""}<div class="muted tiny">${fmtTs(n.created_at)}</div></div></a>`).join("") || empty("🔕", "No notifications yet")}`;
    const ra = document.getElementById("readAll");
    if (ra) ra.onclick = (e) => withBusy(e.currentTarget, async () => { await capi("/api/notifications/read", { method: "POST" }); bell(); viewNotifications(); });
    app.querySelectorAll("[data-nid]").forEach((a) => a.addEventListener("click", () => { capi(`/api/notifications/read?nid=${a.dataset.nid}`, { method: "POST" }).then(bell).catch(() => {}); }));
  }
  let bellTimer = null;
  async function bell() {
    const el = document.querySelector('[data-cc="bell"] .bell-n');
    if (!el || !me().auth) return;
    try { const r = await capi("/api/notifications/unread"); el.hidden = !r.unread; el.textContent = r.unread > 9 ? "9+" : r.unread; } catch { /* offline: keep last value */ }
  }
  window.addEventListener("hashchange", () => { if (me() && me().auth) bell(); });
  window.ppNav = () => {
    if (me().auth && !bellTimer) { bell(); bellTimer = setInterval(bell, 30000); }
    if (!me().auth && bellTimer) { clearInterval(bellTimer); bellTimer = null; }
  };

  // ------------------------------------------------------------------ organisations (public)
  // ------------------------------------------------------------------ organisations (visual cards, builder, public page)
  const I = (k) => (window.wsIcon ? window.wsIcon(k) : "");
  const thm = (t) => (window.wsTheme ? window.wsTheme(t) : { g: ["#5b3fd6", "#ec4899"], icon: "sparkle", key: "default" });
  function orgBanner(o, size = "") {
    const t = thm(`${o.category || ""} ${o.name || ""} ${o.description || ""}`);
    const mark = o.logo_url ? `<img class="ob-logo" src="${esc(o.logo_url)}" alt="${esc(o.name || "Organisation")} logo" loading="lazy" referrerpolicy="no-referrer"/>`
      : `<span class="ob-logo ph">${esc(initials(o.name || "?"))}</span>`;
    return `<div class="ob ${size}" style="--g1:${t.g[0]};--g2:${t.g[1]}"><span class="ob-blob b1"></span><span class="ob-blob b2"></span>
      <span class="ob-ic">${I(t.icon)}</span>${mark}</div>`;
  }
  function orgCard(o, href) {
    const ver = o.verification_status === "verified";
    return `<a class="org2" href="${esc(href || `#/o/${o.slug}`)}">${orgBanner(o)}
      <div class="org2-b"><div class="org2-t"><h3>${esc(o.name || "Your organisation")}</h3>${ver ? `<span class="vchip" title="Verified by Culture Connect">${I("check")} Verified</span>` : ""}</div>
        <div class="org2-tags">${o.category ? `<span>${I(thm(o.category).icon)}${esc(o.category)}</span>` : ""}${o.service_area ? `<span>${I("pin")}${esc(o.service_area)}</span>` : ""}</div>
        ${o.description ? `<p>${esc(o.description.slice(0, 120))}${o.description.length > 120 ? "…" : ""}</p>` : ""}
        <div class="org2-f">${o.upcoming_events != null ? `<span>${I("calendar")}<b>${o.upcoming_events}</b> upcoming</span><span>${I("users")}<b>${o.circles}</b> Circles</span>` : o.my_role ? `<span class="pill">${esc(o.my_role)}</span>` : "<span></span>"}
          <span class="org2-go">${I("arrow")}</span></div></div></a>`;
  }
  async function viewOrgs() {
    const q = qp("q") || "";
    const list = await capi(`/api/orgs?q=${encodeURIComponent(q)}`);
    const mine = me().auth && me().auth.orgs && me().auth.orgs.length;
    app.innerHTML = `<section class="how-hero" style="padding-bottom:6px"><span class="how-kicker">🏢 Organisations</span><h1>Groups doing <span>good work nearby</span></h1></section>
      <section class="org-cta"><div class="oc-art">${["hands", "book", "palette", "sport"].map((k, i) => `<span class="oc-b b${i}">${I(k)}</span>`).join("")}</div>
        <div class="oc-b-t"><span class="kicker">${I("building")} Hosts on Culture Connect</span><h2>Clubs, libraries & causes that bring people together</h2>
          <form class="org-search" id="of" role="search">${I("search")}<input type="search" id="oq" value="${esc(q)}" placeholder="Search by name, cause or area…" aria-label="Search organisations"/><button class="btn primary sm">Search</button></form></div>
        <a class="btn white" href="${me().auth ? "#/org" : "#/auth/signup?next=org"}">${I("sparkle")} ${mine ? "Manage my organisation" : "Start an organisation"}</a></section>
      <div class="org-grid">${list.map((o) => orgCard(o)).join("") || `<div class="empty-line" style="grid-column:1/-1"><span>${q ? "No organisations match." : "No organisations yet."}</span><a class="btn soft sm" href="${me().auth ? "#/org" : "#/auth/signup?next=org"}">Start one</a></div>`}</div>`;
    document.getElementById("of").onsubmit = (e) => { e.preventDefault(); location.hash = `#/orgs?q=${encodeURIComponent(val("oq"))}`; };
  }
  async function viewOrgPublic(slug) {
    const o = await capi(`/api/orgs/${encodeURIComponent(slug)}`);
    const ver = o.verification_status === "verified";
    app.innerHTML = `<section class="org-pub">${orgBanner(o, "xl")}
        <div class="op-b"><div><h1>${esc(o.name)}</h1>
          <div class="org2-tags">${ver ? `<span class="vchip">${I("check")} Verified</span>` : `<span class="nv">Not verified</span>`}${o.category ? `<span>${I(thm(o.category).icon)}${esc(o.category)}</span>` : ""}${o.service_area ? `<span>${I("pin")}${esc(o.service_area)}</span>` : ""}</div></div>
          <div class="row">${contactBtn(o.contact_kind ? { kind: o.contact_kind, value: o.contact_value } : null)}${o.my_role ? `<a class="btn primary" href="#/org/${esc(o.id)}">Manage</a>` : ""}</div></div></section>
      <div class="op-grid"><div class="pf-card"><header>${I("book")}<h3>About</h3></header><p>${esc(o.description || "No description yet.").replace(/\n/g, "<br/>")}</p>
        ${!ver ? `<p class="muted tiny">Not verified by Culture Connect yet — check details before attending.</p>` : ""}
        ${o.circles.length ? `<header style="margin-top:14px">${I("users")}<h3>Circles</h3></header><div class="chiprow">${o.circles.map((c) => `<a class="mini-circle" href="#/c/${esc(c.id)}"><span class="mc-ic" style="background:linear-gradient(135deg,${thm(c.name).g.join(",")})">${I(thm(c.name).icon)}</span>${esc(c.name)}</a>`).join("")}</div>` : ""}</div>
      <div><div class="sec-row" style="margin-top:0"><h2>${I("calendar")} Upcoming events</h2></div>
        ${o.upcoming_events.length ? `<div class="cc-tiles">${o.upcoming_events.map((e) => window.wsEventTile ? window.wsEventTile(e, { noReason: true }) : eventCard(e)).join("")}</div>` : `<div class="empty-line"><span>No upcoming events.</span></div>`}
        ${o.past_events.length ? `<h2 class="sec-h small-h">Previous events</h2>${o.past_events.map(eventRow).join("")}` : ""}</div></div>`;
    if (window.wsBindActions) window.wsBindActions(app, () => viewOrgPublic(slug));
  }

  // a logo URL that fails to load falls back to the designed banner (no inline handlers: CSP)
  document.addEventListener("error", (e) => { if (e.target && e.target.classList && e.target.classList.contains("ob-logo")) e.target.remove(); }, true);
  const CATS = ["Animal welfare", "Arts & culture", "Library", "Education", "Sports club", "Senior care", "Youth", "Environment", "Health & wellbeing", "Music"];
  function orgForm(o = {}) {
    const ck = o.contact_kind || "";
    return `<form id="orgF" class="builder" novalidate><div class="b-main">
      <section class="b-step"><header><span class="b-num">1</span><h3>Identity</h3><span class="b-ic">${I("building")}</span></header>
        <label class="pf-f"><span>${I("building")}Organisation name *</span><input id="oName" type="text" minlength="2" maxlength="100" required value="${esc(o.name || "")}" placeholder="e.g. Kothrud Book Club"/></label>
        <label class="pf-f"><span>${I("sparkle")}Category</span><input id="oCat" type="text" maxlength="60" value="${esc(o.category || "")}" placeholder="Pick one below or type your own"/></label>
        <div class="b-picks">${CATS.map((c) => { const t = thm(c); return `<button type="button" class="b-pick ${o.category === c ? "on" : ""}" data-cat="${esc(c)}" style="--g1:${t.g[0]};--g2:${t.g[1]}"><span>${I(t.icon)}</span>${esc(c)}</button>`; }).join("")}</div></section>
      <section class="b-step"><header><span class="b-num">2</span><h3>Your story</h3><span class="b-ic">${I("book")}</span></header>
        <label class="pf-f"><span>${I("book")}What do you do?</span><textarea id="oDesc" rows="3" maxlength="2000" placeholder="One or two sentences people will see on your page.">${esc(o.description || "")}</textarea></label>
        <span class="b-count" id="oDescN">${(o.description || "").length}/2000</span></section>
      <section class="b-step"><header><span class="b-num">3</span><h3>Reach</h3><span class="b-ic">${I("pin")}</span></header>
        <label class="pf-f"><span>${I("pin")}Service area</span><input id="oArea" type="text" maxlength="120" value="${esc(o.service_area || "")}" placeholder="e.g. Pune"/></label>
        <span class="pf-f"><span>${I("mic")}Public contact</span></span>
        <select id="oCk" hidden>${[["", "None"], ["email", "Email"], ["phone", "Phone"], ["url", "Website / form"]].map(([v, l]) => `<option value="${v}" ${ck === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="b-seg" role="radiogroup" aria-label="Public contact">${[["", "None", "x"], ["email", "Email", "mic"], ["phone", "Phone", "bot"], ["url", "Website", "compass"]].map(([v, l, i]) =>
          `<button type="button" role="radio" aria-checked="${ck === v}" class="${ck === v ? "on" : ""}" data-ck="${v}">${I(i)}${l}</button>`).join("")}</div>
        <input id="oCv" type="text" maxlength="200" value="${esc(o.contact_value || "")}" placeholder="Shown publicly" ${ck ? "" : "hidden"}/></section>
      <section class="b-step"><header><span class="b-num">4</span><h3>Look</h3><span class="b-ic">${I("palette")}</span></header>
        ${window.ccPhoto ? window.ccPhoto.html("oLogo", o.logo_url || "", { label: "Logo (optional)", icon: I("building") }) : ""}
        <p class="pf-hint">${I("sparkle")} No logo? We'll design a banner from your category.</p></section>
      <p class="form-err" id="aErr" role="alert"></p>
      <div class="b-actions"><button class="btn primary" type="submit">${I("check")} ${o.id ? "Save changes" : "Create organisation"}</button></div></div>
      <aside class="b-preview"><span class="b-pv-l">${I("sparkle")} Live preview</span><div id="orgPv"></div>
        ${o.id ? "" : `<ul class="b-perks"><li>${I("calendar")}<span><b>Publish events</b> people can RSVP to</span></li><li>${I("users")}<span><b>Run Circles</b> for your members</span></li><li>${I("check")}<span><b>Get verified</b> for a trusted badge</span></li></ul>`}</aside></form>`;
  }
  function bindOrgBuilder(o = {}) {
    const f = document.getElementById("orgF");
    if (!f) return;
    const pv = () => { document.getElementById("orgPv").innerHTML = orgCard({ ...o, name: val("oName") || "Your organisation", category: val("oCat"), service_area: val("oArea"),
      description: document.getElementById("oDesc").value, logo_url: /^(https:\/\/|\/uploads\/)/.test(val("oLogo")) ? val("oLogo") : "", upcoming_events: null, my_role: o.my_role || (o.id ? null : "owner") }, "#"); };
    if (window.ccPhoto) window.ccPhoto.bind(f, pv);
    f.addEventListener("input", () => { document.getElementById("oDescN").textContent = `${document.getElementById("oDesc").value.length}/2000`; pv(); });
    f.querySelectorAll("[data-cat]").forEach((b) => b.onclick = () => { document.getElementById("oCat").value = b.dataset.cat; f.querySelectorAll("[data-cat]").forEach((x) => x.classList.toggle("on", x === b)); pv(); });
    f.querySelectorAll("[data-ck]").forEach((b) => b.onclick = () => {
      document.getElementById("oCk").value = b.dataset.ck;
      f.querySelectorAll("[data-ck]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
      const cv = document.getElementById("oCv"); cv.hidden = !b.dataset.ck;
      cv.placeholder = { email: "hello@yourorg.org", phone: "+91 98xxxxxxx", url: "https://yourorg.org" }[b.dataset.ck] || ""; if (!cv.hidden) cv.focus();
    });
    pv();
  }
  const orgBody = () => ({ name: val("oName"), category: val("oCat"), description: document.getElementById("oDesc").value.trim(), service_area: val("oArea"),
    contact_kind: document.getElementById("oCk").value, contact_value: document.getElementById("oCk").value ? val("oCv") : "", logo_url: val("oLogo") });
  async function viewOrgHome() {
    const mine = await capi("/api/me/orgs");
    app.innerHTML = `<section class="org-cta builder-hero"><div class="oc-art">${["building", "calendar", "users", "check"].map((k, i) => `<span class="oc-b b${i}">${I(k)}</span>`).join("")}</div>
        <div class="oc-b-t"><span class="kicker">${I("building")} Organiser workspace</span><h2>${mine.length ? "Your organisations" : "Bring your community to life"}</h2>
          <p>${mine.length ? "Open a workspace to run events, Circles and programmes." : "Set up your organisation in under a minute."}</p></div></section>
      ${mine.length ? `<div class="org-grid">${mine.map((o) => orgCard(o, `#/org/${o.id}`)).join("")}</div>
        <details class="b-more"><summary>${I("sparkle")} Create another organisation</summary>${orgForm()}</details>` : orgForm()}
      <p class="muted small" style="margin-top:12px">${I("users")} Joining an existing team? Ask an owner for a staff invite link.</p>`;
    bindOrgBuilder();
    const f = document.getElementById("orgF");
    f.onsubmit = (e) => { e.preventDefault(); withBusy(e.submitter, async () => {
      try { const o = await capi("/api/orgs", { body: orgBody() }); await X().loadMe(true); toast("Organisation created ✓"); location.hash = `#/org/${o.id}`; }
      catch (ex) { document.getElementById("aErr").textContent = ex.message; } }); };
  }
  async function viewWorkspace(oid, tab, extra) {
    const d = await capi(`/api/orgs/${encodeURIComponent(oid)}/dashboard`);
    const o = d.org, owner = d.my_role === "owner", s = d.stats;
    const tabs = [["overview", "📊 Overview"], ["events", "📅 Events"], ["programmes", "🧩 Programmes"], ["circles", "⭕ Circles"], ["team", "👥 Team"], ["settings", "⚙️ Profile & verification"]];
    app.innerHTML = `<section class="org-hero ws"><div class="org-top">${o.logo_url ? `<img src="${esc(o.logo_url)}" alt="" class="org-logo"/>` : `<span class="org-logo ph">${esc(initials(o.name))}</span>`}
      <div><span class="how-kicker">🏢 Workspace · ${esc(d.my_role)}</span><h1>${esc(o.name)}</h1>${verifyBadge(o.verification_status)}</div></div>
      <div class="row"><a class="btn ghost sm" href="#/o/${esc(o.slug)}">View public page</a><a class="btn primary sm" href="#/org/${esc(o.id)}/new-event">＋ New event</a></div></section>
      <nav class="cc-tabs" role="tablist">${tabs.map(([k, l]) => `<a role="tab" aria-selected="${k === tab}" class="${k === tab ? "on" : ""}" href="#/org/${esc(o.id)}/${k}">${l}</a>`).join("")}</nav><div id="ws"></div>`;
    const ws = document.getElementById("ws");
    if (tab === "overview") {
      const ev = s.events;
      ws.innerHTML = `<div class="stat-grid">
        ${[["📅", (ev.published || 0), "Published events"], ["📝", (ev.draft || 0), "Drafts"], ["✅", (ev.completed || 0), "Completed"], ["🙋", s.going, "Going (RSVPs)"],
           ["🧾", s.attendance_marked ? `${s.attended}/${s.attendance_marked}` : "—", "Attended / marked"], ["⭐", s.feedback_avg ?? "—", `Avg feedback (${s.feedback_count})`],
           ["⭕", s.circles, `Circles · ${s.circle_members} members`], ["🧩", s.programmes, `Programmes · ${s.participants} participants`]]
          .map(([i, n, l]) => `<div class="card stat"><span>${i}</span><b>${esc(String(n))}</b><small>${l}</small></div>`).join("")}</div>
        ${s.pending_requests ? `<div class="notice">🙋 ${s.pending_requests} pending Circle join request(s) — see the Circles tab.</div>` : ""}
        <h2 class="sec-h">Upcoming</h2>${d.events.filter((e) => e.status === "published" && e.display_status !== "past").slice(0, 4).map(eventRow).join("") || empty("🗓", "No upcoming events", "", `<a class="btn primary" href="#/org/${esc(o.id)}/new-event">Create your first event</a>`)}`;
    } else if (tab === "events") {
      const groups = [["Drafts", d.events.filter((e) => e.status === "draft")], ["Upcoming", d.events.filter((e) => e.status === "published" && e.display_status !== "past")],
        ["Past, completed & cancelled", d.events.filter((e) => ["completed", "cancelled"].includes(e.status) || e.display_status === "past")]];
      ws.innerHTML = groups.map(([t, l]) => `<h2 class="sec-h">${t} (${l.length})</h2>${l.map(eventRow).join("") || `<p class="muted small">None.</p>`}`).join("");
    } else if (tab === "new-event" || tab === "edit-event") {
      let e = null;
      if (tab === "edit-event" && extra) e = await capi(`/api/events/${encodeURIComponent(extra)}`);
      ws.innerHTML = eventForm(e);
      bindEventForm(e, async (body) => {
        const r = e ? await capi(`/api/events/${e.id}`, { method: "PUT", body }) : await capi(`/api/orgs/${o.id}/events`, { body });
        toast(e ? "Event updated ✓" : "Draft saved ✓ — review and publish it"); location.hash = `#/e/${r.id}`;
      });
    } else if (tab === "programmes") {
      ws.innerHTML = `<div class="card"><h3>🧩 Programmes</h3><p class="muted small">Onboard participants with their consent, let Qloo find bridges, review proposed groups, then approve them as invite-only Circles.</p>
        <form class="row" id="pf2"><input id="pName" type="text" maxlength="100" placeholder="Programme name, e.g. Seniors × Students 2026" style="max-width:380px" aria-label="Programme name"/><button class="btn primary sm">Create programme</button></form></div>
        ${d.programmes.map((p) => `<a class="card ev-row" href="#/p/${esc(p.id)}/group"><span>🧩</span><div><b>${esc(p.name)}</b><div class="muted small">${p.participants} participants · ${p.groups} proposed groups · ${Object.keys(p.circles || {}).length} approved Circles · ${p.approved_plans} approved plans</div></div></a>`).join("") || empty("🧩", "No programmes yet")}`;
      document.getElementById("pf2").onsubmit = (ev) => { ev.preventDefault(); withBusy(ev.submitter, async () => { const p = await capi(`/api/orgs/${o.id}/programs`, { body: { name: val("pName") } }); toast("Programme created ✓"); location.hash = `#/p/${p.id}/group`; }); };
    } else if (tab === "circles") {
      ws.innerHTML = d.circles.map((c) => `<a class="card ev-row" href="#/c/${esc(c.id)}/members"><span>⭕</span><div><b>${esc(c.name)}</b><div class="muted small">${c.members} members${c.pending ? ` · <b>${c.pending} pending request(s)</b>` : ""} · ${esc(c.visibility)}</div></div></a>`).join("")
        || empty("⭕", "No organisation Circles yet", "Approve a proposed group in a programme to create one.");
    } else if (tab === "team") {
      const team = await capi(`/api/orgs/${o.id}/team`);
      ws.innerHTML = `<div class="card"><h3>👥 Team</h3>${team.map((t) => `<div class="row between person-row"><span><b>${esc(t.name)}</b> ${t.me ? "(you)" : ""} <span class="badge generated">${t.role}</span></span>
        ${owner && !t.me && t.role === "staff" ? `<button class="btn danger sm" data-rm="${esc(t.user_id)}">Remove</button>` : ""}</div>`).join("")}
        ${owner ? `<div style="margin-top:14px"><button class="btn soft sm" id="invBtn">Create staff invite link</button><div id="invOut"></div></div>` : ""}</div>`;
      const ib = document.getElementById("invBtn");
      if (ib) ib.onclick = (ev) => withBusy(ev.currentTarget, async () => { const r = await capi(`/api/orgs/${o.id}/invites`, { method: "POST" });
        document.getElementById("invOut").innerHTML = `<div class="notice">Share this one-time link (valid ${r.expires_in_days} days). It's shown only once:<br/><code>${esc(location.origin + location.pathname)}#/org-invite?code=${esc(r.code)}</code></div>`; });
      ws.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = (ev) => { if (!confirm("Remove this staff member?")) return; withBusy(ev.currentTarget, async () => { await capi(`/api/orgs/${o.id}/team/${b.dataset.rm}`, { method: "DELETE" }); toast("Removed"); viewWorkspace(oid, "team"); }); }));
    } else if (tab === "settings") {
      const full = await capi(`/api/orgs/${o.id}`);
      ws.innerHTML = `${owner ? orgForm(full) : `<div class="notice">Only owners can edit the organisation profile.</div>`}
        <div class="card" style="margin-top:16px"><h3>🛡 Verification</h3><p>Status: ${verifyBadge(full.verification_status)}</p>
        <p class="muted small">A Culture Connect administrator reviews your evidence (e.g. registration number, official website, press). Until then your pages say “Not verified” or “Verification pending”.</p>
        ${full.verification_note ? `<div class="notice">Reviewer note: ${esc(full.verification_note)}</div>` : ""}
        ${owner && full.verification_status !== "verified" ? `<form id="verF"><div class="field"><label for="vEv">Evidence for reviewers (not public)</label><textarea id="vEv" rows="3" minlength="10" maxlength="2000">${esc(full.verification_evidence || "")}</textarea></div>
          <button class="btn primary sm" type="submit">${full.verification_status === "pending" ? "Update request" : "Request verification"}</button></form>` : ""}</div>`;
      const f = document.getElementById("orgF");
      bindOrgBuilder(full);
      if (f) f.onsubmit = (ev) => { ev.preventDefault(); withBusy(ev.submitter, async () => { try { await capi(`/api/orgs/${o.id}`, { method: "PUT", body: orgBody() }); toast("Saved ✓"); viewWorkspace(oid, "settings"); } catch (ex) { document.getElementById("aErr").textContent = ex.message; } }); };
      const vf = document.getElementById("verF");
      if (vf) vf.onsubmit = (ev) => { ev.preventDefault(); withBusy(ev.submitter, async () => { await capi(`/api/orgs/${o.id}/verification`, { body: { evidence: document.getElementById("vEv").value } }); toast("Verification requested ✓"); viewWorkspace(oid, "settings"); }); };
    }
  }
  async function viewOrgInvite() {
    const r = await capi("/api/org-invites/accept", { body: { code: qp("code") || "" } });
    await X().loadMe(true); toast("You've joined the organisation team ✓"); location.hash = `#/org/${r.org_id}`;
  }
  async function viewAdmin() {
    const q = await capi("/api/admin/verifications");
    app.innerHTML = `<div class="title-row"><div><span class="how-kicker">🛡 Admin</span><h2 style="margin-top:10px">Verification requests</h2></div></div>
      ${q.map((o) => `<div class="card"><h3><a href="#/o/${esc(o.slug)}">${esc(o.name)}</a></h3><p class="small"><b>Evidence:</b> ${esc(o.verification_evidence)}</p>
        <div class="row"><input type="text" maxlength="500" placeholder="Note to the organisation" data-note="${esc(o.id)}" aria-label="Review note"/>
        <button class="btn primary sm" data-rev="approve" data-o="${esc(o.id)}">Approve</button><button class="btn danger sm" data-rev="reject" data-o="${esc(o.id)}">Reject</button></div></div>`).join("") || empty("✅", "No pending requests")}`;
    app.querySelectorAll("[data-rev]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => {
      await capi(`/api/admin/verifications/${b.dataset.o}`, { body: { decision: b.dataset.rev, note: app.querySelector(`[data-note="${b.dataset.o}"]`).value } }); toast("Review saved"); viewAdmin(); })));
  }

  // ------------------------------------------------------------------ event form
  function eventForm(e) {
    const v = (k, d = "") => esc(e && e[k] != null ? e[k] : d);
    const loc = e ? e.location_status : "tbc";
    const geoOn = me().auth && me().auth.geocoder;
    return `<form id="evF" class="card ev-form" novalidate><h2>${e ? "Edit event" : "New event"}</h2>
      <div class="grid2"><div class="field"><label for="fTitle">Title *</label><input id="fTitle" type="text" minlength="3" maxlength="120" required value="${v("title")}"/></div>
        <div class="field"><label for="fCat">Activity category</label><input id="fCat" type="text" maxlength="60" value="${v("category")}" placeholder="e.g. Volunteering, Chess, Walk"/></div></div>
      <div class="field"><label for="fDesc">Full description</label><textarea id="fDesc" rows="4" maxlength="5000">${v("description")}</textarea></div>
      <div class="field"><label for="fPurpose">Purpose</label><input id="fPurpose" type="text" maxlength="500" value="${v("purpose")}"/></div>
      ${window.ccPhoto ? window.ccPhoto.html("fImg", e && e.image_url ? e.image_url : "", { label: "Event photo (optional)" }) : ""}
      <div class="grid3"><div class="field"><label for="fStart">Starts *</label><input id="fStart" type="datetime-local" required value="${v("starts_at")}"/></div>
        <div class="field"><label for="fEnd">Ends *</label><input id="fEnd" type="datetime-local" required value="${v("ends_at")}"/></div>
        <div class="field"><label for="fTz">Timezone *</label><input id="fTz" type="text" maxlength="60" value="${v("timezone", myTz())}" list="tzs"/>
          <datalist id="tzs">${["Asia/Kolkata", "Europe/London", "America/New_York", "America/Los_Angeles", "Europe/Berlin", "Asia/Singapore", "Australia/Sydney", "UTC"].map((t) => `<option value="${t}">`).join("")}</datalist></div></div>
      <fieldset class="locset"><legend>Meeting point</legend>
        <div class="seg loc-seg" role="radiogroup">${[["tbc", "📍 To be confirmed"], ["confirmed", "✅ Confirmed address"], ["online", "💻 Online"]].map(([k, l]) => `<button type="button" role="radio" aria-checked="${loc === k}" data-loc="${k}" class="${loc === k ? "on" : ""}">${l}</button>`).join("")}</div>
        <div data-locpane="confirmed" ${loc === "confirmed" ? "" : "hidden"}>
          <div class="grid2"><div class="field"><label for="fVenue">Venue name</label><input id="fVenue" type="text" maxlength="120" value="${v("venue_name")}"/></div>
            <div class="field"><label for="fAddr">Full address *</label><input id="fAddr" type="text" maxlength="300" value="${v("raw_address", e ? e.address : "")}"/></div></div>
          ${geoOn ? `<button type="button" class="btn soft sm" id="geoBtn">🔎 Find this address on the map</button><div id="geoRes"></div>` : `<p class="muted tiny">Map search isn't configured on this server, so the address is shown without a map pin unless you enter exact coordinates.</p>`}
          <details ${e && e.lat != null ? "open" : ""}><summary class="small">I know the exact coordinates</summary><div class="grid2">
            <div class="field"><label for="fLat">Latitude</label><input id="fLat" type="number" step="any" min="-90" max="90" value="${e && e.lat != null ? e.lat : ""}"/></div>
            <div class="field"><label for="fLon">Longitude</label><input id="fLon" type="number" step="any" min="-180" max="180" value="${e && e.lon != null ? e.lon : ""}"/></div></div></details>
          <input type="hidden" id="fGeo" value="${v("geo_source")}"/></div>
        <div data-locpane="online" ${loc === "online" ? "" : "hidden"}><div class="field"><label for="fUrl">Joining link (https)</label><input id="fUrl" type="url" maxlength="400" value="${v("online_url")}"/></div></div>
        <p data-locpane="tbc" class="muted small" ${loc === "tbc" ? "" : "hidden"}>Attendees will see “Location to be confirmed” until you update it — they'll be notified when you do.</p></fieldset>
      <div class="grid3"><div class="field"><label for="fCap">Capacity *</label><input id="fCap" type="number" min="1" max="5000" required value="${v("capacity", 20)}"/></div>
        <div class="field"><label for="fDl">RSVP deadline</label><input id="fDl" type="datetime-local" value="${v("rsvp_deadline")}"/></div>
        <div class="field"><label for="fAge">Minimum age</label><input id="fAge" type="number" min="0" max="120" value="${e && e.min_age != null ? e.min_age : ""}"/></div></div>
      <div class="grid2"><div class="field"><label for="fCost">Cost</label><input id="fCost" type="text" maxlength="300" value="${v("cost_note")}" placeholder="e.g. Free / ₹100 for materials"/></div>
        <div class="field"><label for="fMat">What to bring</label><input id="fMat" type="text" maxlength="1000" value="${v("materials")}"/></div></div>
      <div class="grid2"><div class="field"><label for="fAcc">Accessibility</label><textarea id="fAcc" rows="2" maxlength="1000">${v("accessibility")}</textarea></div>
        <div class="field"><label for="fReq">Participation requirements</label><textarea id="fReq" rows="2" maxlength="1000">${v("requirements")}</textarea></div></div>
      <div class="field"><label for="fSafe">Safety instructions</label><textarea id="fSafe" rows="2" maxlength="1000">${v("safety")}</textarea></div>
      ${e && e.status === "published" ? `<div class="field"><label for="fReason">Reason for this change (sent to attendees)</label><input id="fReason" type="text" maxlength="300"/></div>` : ""}
      <p class="form-err" id="aErr" role="alert"></p><div class="row end">${e ? `<a class="btn ghost" href="#/e/${esc(e.id)}">Cancel</a>` : ""}<button class="btn primary" type="submit">${e ? "Save changes" : "Save draft"}</button></div></form>`;
  }
  function bindEventForm(e, save) {
    const f = document.getElementById("evF");
    if (window.ccPhoto) window.ccPhoto.bind(f);
    let loc = e ? e.location_status : "tbc";
    f.querySelectorAll("[data-loc]").forEach((b) => (b.onclick = () => {
      loc = b.dataset.loc;
      f.querySelectorAll("[data-loc]").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
      f.querySelectorAll("[data-locpane]").forEach((p) => (p.hidden = p.dataset.locpane !== loc));
    }));
    const gb = document.getElementById("geoBtn");
    if (gb) gb.onclick = (ev) => withBusy(ev.currentTarget, async () => {
      const res = await capi(`/api/geo/search?q=${encodeURIComponent(val("fAddr"))}`);
      document.getElementById("geoRes").innerHTML = res.length ? `<div class="geo-list">${res.map((r, i) => `<button type="button" class="cand" data-gi="${i}"><span class="ph">📍</span><span><b>${esc(r.display_name)}</b><small>${r.lat}, ${r.lon}</small></span></button>`).join("")}</div>`
        : `<p class="muted small">No match — check the address or enter it without a pin.</p>`;
      document.querySelectorAll("[data-gi]").forEach((b) => (b.onclick = () => { const r = res[+b.dataset.gi];
        document.getElementById("fAddr").value = r.display_name; document.getElementById("fLat").value = r.lat; document.getElementById("fLon").value = r.lon; document.getElementById("fGeo").value = "nominatim";
        document.querySelectorAll("[data-gi]").forEach((x) => x.classList.toggle("sel", x === b)); }));
    });
    ["fLat", "fLon"].forEach((id) => document.getElementById(id).addEventListener("input", () => (document.getElementById("fGeo").value = "organiser")));
    f.onsubmit = (ev) => {
      ev.preventDefault();
      const num = (id) => { const x = document.getElementById(id).value; return x === "" ? null : Number(x); };
      const body = { image_url: (document.getElementById("fImg") || {}).value || "", title: val("fTitle"), category: val("fCat"), description: document.getElementById("fDesc").value.trim(), purpose: val("fPurpose"),
        starts_at: val("fStart"), ends_at: val("fEnd"), timezone: val("fTz"), location_status: loc, venue_name: val("fVenue"), address: val("fAddr"),
        lat: num("fLat"), lon: num("fLon"), geo_source: num("fLat") === null ? "" : (val("fGeo") || "organiser"), online_url: val("fUrl"),
        capacity: num("fCap"), rsvp_deadline: val("fDl") || null, cost_note: val("fCost"), materials: val("fMat"),
        accessibility: document.getElementById("fAcc").value.trim(), requirements: document.getElementById("fReq").value.trim(),
        min_age: num("fAge"), safety: document.getElementById("fSafe").value.trim(), reason: document.getElementById("fReason") ? val("fReason") : "" };
      const err = document.getElementById("aErr"); err.textContent = "";
      if (!body.starts_at || !body.ends_at) { err.textContent = "Add a start and end time."; return; }
      withBusy(f.querySelector('button[type="submit"]'), async () => { try { await save(body); } catch (ex) { err.textContent = ex.message; } });
    };
  }

  // ------------------------------------------------------------------ event page
  async function viewEvent(eid) {
    app.innerHTML = skel(3);
    const e = await capi(`/api/events/${encodeURIComponent(eid)}`);
    const goingPct = Math.min(100, Math.round((e.going / Math.max(1, e.capacity)) * 100));
    const owner = e.owner ? (e.owner.kind === "org" ? `<a href="#/o/${esc(e.owner.slug)}">🏢 ${esc(e.owner.name)}</a> ${verifyBadge(e.owner.verification_status)}` : `<a href="#/c/${esc(e.owner.circle_id)}">⭕ ${esc(e.owner.name)}</a> <span class="muted small">(Circle members only)</span>`) : "";
    const canFeedback = e.status === "completed" && e.my_rsvp === "going" && !e.feedback.mine;
    app.innerHTML = `
    <section class="event-hero st-${esc(e.display_status)} ${e.image_url ? "has-photo" : ""}"${e.image_url ? ` style="background-image:linear-gradient(120deg,rgba(29,27,58,.86),rgba(29,27,58,.4)),url('${esc(e.image_url)}')"` : ""}><div><div class="row">${statusBadge(e.display_status)}${e.category ? `<span class="chip">${esc(e.category)}</span>` : ""}</div>
      <h1>${esc(e.title)}</h1><div class="eh-meta">🗓 ${when(e)}</div><div class="eh-meta">${owner}</div></div>
      <div class="eh-side"><div class="ch-count"><b>${e.going}</b><span>of ${e.capacity} going</span></div></div></section>
    ${e.status === "cancelled" ? `<div class="notice danger-n">❌ This event was cancelled. Reason: ${esc(e.cancel_reason)}</div>` : ""}
    ${e.status === "draft" ? `<div class="notice">📝 Draft — only organisers can see this page until it's published.</div>` : ""}
    <div class="grid2 ev-grid">
      <div>
        <div class="card"><h3>📍 Meeting point</h3>
          ${e.location_status === "confirmed" ? `<p><b>${esc(e.venue_name || "Venue")}</b><br/>${esc(e.address)}</p>${e.map ? mapEmbed(e.map, e.venue_name || e.address) : `<p class="muted tiny">No map pin — use the address above.</p>`}`
            : e.location_status === "online" ? `<p>💻 Online${e.online_url && e.my_rsvp === "going" ? ` — <a href="${esc(e.online_url)}" target="_blank" rel="noopener noreferrer">joining link</a>` : e.online_url ? " — the joining link appears once you RSVP “Going”." : ""}</p>`
            : `<p class="tbc">📍 <b>Location to be confirmed.</b> You'll be notified when the organiser confirms it.</p>`}</div>
        <div class="card"><h3>About this event</h3><p>${esc(e.description || "No description.").replace(/\n/g, "<br/>")}</p>${e.purpose ? `<p class="small"><b>Purpose:</b> ${esc(e.purpose)}</p>` : ""}
          <dl class="ev-dl">${[["💲 Cost", e.cost_note], ["🎒 Bring", e.materials], ["♿ Accessibility", e.accessibility], ["📋 Requirements", e.requirements], ["🔞 Minimum age", e.min_age != null ? String(e.min_age) : ""], ["🦺 Safety", e.safety]]
            .filter(([, x]) => x).map(([k, x]) => `<dt>${k}</dt><dd>${esc(x)}</dd>`).join("")}</dl></div>
        ${e.updates.length ? `<div class="card"><h3>🕒 Updates</h3><ul class="timeline">${e.updates.map((u) => `<li><b>${esc(u.message)}</b>${u.reason ? ` — ${esc(u.reason)}` : ""}<div class="muted tiny">${fmtTs(u.created_at)}</div></li>`).join("")}</ul></div>` : ""}
      </div>
      <div>
        <div class="card rsvp-card"><h3>RSVP</h3><div class="cap"><div class="cap-bar"><i style="width:${goingPct}%"></i></div><span>${e.going}/${e.capacity} going · ${e.rsvp_counts.maybe || 0} maybe</span></div>
          ${e.rsvp_deadline ? `<p class="muted small">RSVP by ${esc(when({ starts_at: e.rsvp_deadline, ends_at: "", timezone: e.timezone }).split("–")[0])}</p>` : ""}
          ${!me().auth ? `<a class="btn primary wide" href="#/auth/signin?next=${encodeURIComponent("e/" + e.id)}">Sign in to RSVP</a>`
            : e.rsvp_open ? `<div class="row">${["going", "maybe", "not_going"].map((s) => `<button class="btn ${e.my_rsvp === s ? "primary" : "soft"} sm" data-rsvp="${s}" aria-pressed="${e.my_rsvp === s}">${s === "going" ? "✅ Going" : s === "maybe" ? "🤔 Maybe" : "❌ Can't go"}</button>`).join("")}</div>`
            : `<p class="muted small">RSVPs are closed${e.my_rsvp ? ` — you said “${esc(e.my_rsvp.replace("_", " "))}”` : ""}.</p>`}
          <div style="margin-top:12px">${contactBtn(e.contact)}</div></div>
        ${e.status === "completed" ? `<div class="card"><h3>⭐ Feedback</h3><p class="small">${e.feedback.count ? `${e.feedback.count} response(s), average ${e.feedback.avg}/5` : "No feedback yet."}</p>
          ${canFeedback ? `<form id="fbF"><div class="stars" role="radiogroup" aria-label="Rating">${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-star="${n}" aria-label="${n} stars">★</button>`).join("")}</div>
            <textarea id="fbC" rows="2" maxlength="1000" placeholder="What went well? What could improve?"></textarea><button class="btn primary sm" type="submit">Send feedback</button></form>` : e.feedback.mine ? `<p class="small">You rated it ${e.feedback.mine.rating}/5. Thank you!</p>` : ""}</div>` : ""}
        ${e.owner && e.owner.kind === "circle" && e.status !== "draft" ? `<details class="card disc"><summary>💬 Event discussion</summary><div id="evDisc"></div></details>` : ""}
        ${e.can_manage ? `<div class="card manage"><h3>🛠 Organiser tools</h3><div class="row">
          ${e.status === "draft" ? `<button class="btn primary sm" id="pubBtn">Publish</button>` : ""}
          ${["draft", "published"].includes(e.status) && e.owner.kind === "org" ? `<a class="btn soft sm" href="#/org/${esc(e.owner.id)}/edit-event/${esc(e.id)}">Edit</a>` : ""}
          ${["draft", "published"].includes(e.status) && e.owner.kind === "circle" ? `<button class="btn soft sm" id="editCircleEv">Edit</button>` : ""}
          ${e.status === "published" ? `<button class="btn soft sm" id="doneBtn">Mark completed</button><button class="btn danger sm" id="cancelBtn">Cancel event</button>` : ""}</div>
          <div id="editSlot"></div><h4 style="margin-top:14px">Participants</h4><div id="parts"><span class="spinner"></span></div></div>` : ""}
      </div></div>`;
    app.querySelectorAll("[data-rsvp]").forEach((b) => (b.onclick = (ev) => withBusy(ev.currentTarget, async () => { await capi(`/api/events/${e.id}/rsvp`, { body: { status: b.dataset.rsvp } }); toast("RSVP saved ✓"); viewEvent(eid); })));
    const fb = document.getElementById("fbF");
    if (fb) { let rating = 0;
      fb.querySelectorAll("[data-star]").forEach((s) => (s.onclick = () => { rating = +s.dataset.star; fb.querySelectorAll("[data-star]").forEach((x) => x.classList.toggle("on", +x.dataset.star <= rating)); }));
      fb.onsubmit = (ev) => { ev.preventDefault(); if (!rating) return toast("Pick a rating", true); withBusy(ev.submitter, async () => { await capi(`/api/events/${e.id}/feedback`, { body: { rating, comment: document.getElementById("fbC").value } }); toast("Thanks for the feedback ✓"); viewEvent(eid); }); }; }
    const disc = app.querySelector("details.disc");
    if (disc) disc.addEventListener("toggle", () => { if (disc.open && !disc.dataset.l) { disc.dataset.l = 1; capi(`/api/circles/${e.owner.circle_id}`).then((c) => window.ppChat(c, document.getElementById("evDisc"), e.can_manage, `event:${e.id}`, true)).catch((x) => (document.getElementById("evDisc").innerHTML = `<p class="muted small">${esc(x.message)}</p>`)); } });
    if (!e.can_manage) return;
    const pb = document.getElementById("pubBtn");
    if (pb) pb.onclick = (ev) => withBusy(ev.currentTarget, async () => { await capi(`/api/events/${e.id}/publish`, { method: "POST" }); toast("Published ✓"); viewEvent(eid); });
    const db_ = document.getElementById("doneBtn");
    if (db_) db_.onclick = (ev) => { if (!confirm("Mark this event as completed? Attendees will be asked for feedback.")) return; withBusy(ev.currentTarget, async () => { await capi(`/api/events/${e.id}/complete`, { method: "POST" }); toast("Marked completed ✓"); viewEvent(eid); }); };
    const cb = document.getElementById("cancelBtn");
    if (cb) cb.onclick = (ev) => { const reason = prompt("Reason for cancelling (sent to everyone who RSVP'd):"); if (!reason || reason.trim().length < 3) return;
      withBusy(ev.currentTarget, async () => { await capi(`/api/events/${e.id}/cancel`, { body: { reason } }); toast("Event cancelled — attendees notified"); viewEvent(eid); }); };
    const ec = document.getElementById("editCircleEv");
    if (ec) ec.onclick = () => { const full = { ...e, raw_address: e.raw_address }; document.getElementById("editSlot").innerHTML = eventForm(full);
      bindEventForm(full, async (body) => { await capi(`/api/events/${e.id}`, { method: "PUT", body }); toast("Event updated ✓"); viewEvent(eid); }); };
    const parts = await capi(`/api/events/${e.id}/participants`).catch(() => []);
    const started = wall(e.starts_at) && wall(e.starts_at) < new Date();
    document.getElementById("parts").innerHTML = parts.length ? `<table class="ptable"><tr><th>Name</th><th>RSVP</th><th>Attended</th></tr>${parts.map((p) => `<tr><td>${esc(p.name)}</td><td>${esc(p.status.replace("_", " "))}</td>
      <td>${started ? `<button class="btn ${p.attended === true ? "primary" : "soft"} sm" data-att="${esc(p.user_id)}" data-v="1">✔</button><button class="btn ${p.attended === false ? "danger" : "soft"} sm" data-att="${esc(p.user_id)}" data-v="0">✖</button>` : `<span class="muted tiny">after start</span>`}</td></tr>`).join("")}</table>`
      : `<p class="muted small">No RSVPs yet.</p>`;
    app.querySelectorAll("[data-att]").forEach((b) => (b.onclick = (ev) => withBusy(ev.currentTarget, async () => { await capi(`/api/events/${e.id}/attendance`, { body: { user_id: b.dataset.att, attended: b.dataset.v === "1" } }); toast("Attendance saved"); viewEvent(eid); })));
  }

  // ------------------------------------------------------------------ Circle chat (persisted; polls every 5 s — not a live socket)
  window.ppChat = async (c, el, mod, thread = "", compact = false) => {
    const POLL = 5000;
    const st = { msgs: [], pending: [], lastId: 0, hasMore: false, timer: null, ok: true, checked: null };
    el.innerHTML = `<div class="chat ${compact ? "compact" : "card"}"><div class="chat-status" aria-live="polite"><span class="dot"></span><span class="txt">Connecting…</span></div>
      <button class="btn ghost sm chat-more" hidden>Load earlier messages</button><div class="chat-list" role="log" aria-label="Messages"></div>
      <form class="chat-form"><textarea rows="${compact ? 1 : 2}" maxlength="2000" placeholder="${compact ? "Reply in this thread…" : "Message the Circle…"}" aria-label="Message"></textarea><button class="btn primary sm" type="submit">Send</button></form>
      ${compact ? "" : `<p class="muted tiny">Messages are saved and visible to Circle members only. New messages appear within ~5 seconds. Never share phone numbers or addresses here.</p>`}</div>`;
    const list = el.querySelector(".chat-list"), more = el.querySelector(".chat-more"), status = el.querySelector(".chat-status"), form = el.querySelector(".chat-form"), ta = form.querySelector("textarea");
    const setStatus = (ok, txt) => { st.ok = ok; status.classList.toggle("lost", !ok); status.querySelector(".txt").textContent = txt; };
    const bubble = (m) => `<div class="msg ${m.mine ? "mine" : ""} ${m.hidden ? "is-hidden" : ""}" data-mid="${m.id}"><div class="msg-h"><b>${esc(m.author)}</b><span class="muted tiny">${fmtTs(m.created_at)}</span></div>
      <div class="msg-b">${m.deleted ? `<i class="muted">[message deleted]</i>` : m.blocked ? `<i class="muted">Hidden — you blocked this person.</i>` : m.hidden && !mod ? `<i class="muted">Hidden by a moderator.</i>` : esc(m.body).replace(/\n/g, "<br/>")}</div>
      ${m.deleted ? "" : `<div class="msg-a">${m.mine ? `<button class="linkbtn" data-ma="del">Delete</button>` : `<button class="linkbtn" data-ma="report">Report</button>`}${mod && !m.mine && !m.hidden ? `<button class="linkbtn" data-ma="hide">Hide</button>` : ""}</div>`}</div>`;
    const pend = (p) => `<div class="msg mine pending ${p.state}" data-cid="${esc(p.client_id)}"><div class="msg-b">${esc(p.body).replace(/\n/g, "<br/>")}</div>
      <div class="msg-a">${p.state === "failed" ? `<span class="fail-t">Not sent.</span> <button class="linkbtn" data-retry="${esc(p.client_id)}">Retry</button> <button class="linkbtn" data-drop="${esc(p.client_id)}">Discard</button>` : `<span class="muted tiny">Sending…</span>`}</div></div>`;
    function render(keepScroll) {
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
      list.innerHTML = (st.msgs.length || st.pending.length) ? st.msgs.map(bubble).join("") + st.pending.map(pend).join("")
        : `<div class="empty-mini">💬 No messages yet — say hello${thread ? " in this thread" : ""}!</div>`;
      more.hidden = !st.hasMore;
      if (!keepScroll || atBottom) list.scrollTop = list.scrollHeight;
    }
    async function initial() {
      try {
        const r = await capi(`/api/circles/${c.id}/messages?thread=${encodeURIComponent(thread)}&limit=40`);
        st.msgs = r.messages; st.hasMore = r.has_more; st.lastId = r.messages.length ? r.messages[r.messages.length - 1].id : 0;
        setStatus(true, `Saved chat · checks for new messages every ${POLL / 1000} s`); render();
      } catch (e) { setStatus(false, e.status === 0 ? "Connection lost — retrying…" : e.message); list.innerHTML = `<div class="empty-mini">Couldn't load messages. <button class="linkbtn" id="chatRetry">Retry</button></div>`;
        const b = el.querySelector("#chatRetry"); if (b) b.onclick = initial; }
    }
    async function poll() {
      if (!el.isConnected) { clearInterval(st.timer); return; }
      try {
        const r = await capi(`/api/circles/${c.id}/messages?thread=${encodeURIComponent(thread)}&after=${st.lastId}`);
        if (r.messages.length) {
          const known = new Set(st.msgs.map((m) => m.id));
          r.messages.forEach((m) => { if (!known.has(m.id)) st.msgs.push(m); });
          st.lastId = st.msgs[st.msgs.length - 1].id; render(true);
        }
        setStatus(true, `Saved chat · last checked ${new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}`);
      } catch (e) { setStatus(false, e.status === 0 ? "Connection lost — retrying every few seconds…" : `Couldn't refresh: ${e.message}`); }
    }
    async function send(p) {
      p.state = "sending"; render();
      try {
        await capi(`/api/circles/${c.id}/messages`, { body: { body: p.body, client_id: p.client_id, thread } });
        st.pending = st.pending.filter((x) => x !== p);
        await poll();
      } catch (e) { p.state = "failed"; render(); if (e.status && e.status !== 0) toast(e.message, true); }
    }
    form.onsubmit = (e) => { e.preventDefault(); const body = ta.value.trim(); if (!body) return; ta.value = "";
      const p = { client_id: uid(), body, state: "sending" }; st.pending.push(p); send(p); };
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
    more.onclick = (e) => withBusy(e.currentTarget, async () => {
      const r = await capi(`/api/circles/${c.id}/messages?thread=${encodeURIComponent(thread)}&limit=40&before=${st.msgs[0].id}`);
      st.msgs = r.messages.concat(st.msgs); st.hasMore = r.has_more; const h = list.scrollHeight; render(true); list.scrollTop = list.scrollHeight - h; });
    list.addEventListener("click", (e) => {
      const r = e.target.closest("[data-retry]"), d = e.target.closest("[data-drop]"), a = e.target.closest("[data-ma]");
      if (r) { const p = st.pending.find((x) => x.client_id === r.dataset.retry); if (p) send(p); }
      if (d) { st.pending = st.pending.filter((x) => x.client_id !== d.dataset.drop); render(); }
      if (a) {
        const mid = a.closest("[data-mid]").dataset.mid;
        if (a.dataset.ma === "report") { const reason = prompt("Why are you reporting this message?"); if (!reason || reason.trim().length < 3) return;
          withBusy(a, async () => { await capi(`/api/circles/${c.id}/messages/${mid}/report`, { body: { reason } }); toast("Reported — moderators will review"); }); }
        else if (confirm(a.dataset.ma === "del" ? "Delete your message?" : "Hide this message for members?")) withBusy(a, async () => {
          await capi(`/api/circles/${c.id}/messages/${mid}`, { method: "DELETE" });
          const m = st.msgs.find((x) => String(x.id) === mid); if (m) { if (a.dataset.ma === "del") m.deleted = true; else m.hidden = true; } render(true); });
      }
    });
    await initial();
    st.timer = setInterval(poll, POLL);
  };

  // ------------------------------------------------------------------ meeting-place poll for a proposal
  window.ppPlaces = async (el, pid, onLoad) => {
    const geoOn = me().auth && me().auth.geocoder;
    let found = null;
    async function load() {
      let r;
      try { r = await capi(`/api/proposals/${pid}/places`); } catch (e) { el.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
      onLoad && onLoad(r.places);
      el.innerHTML = `<div class="places"><div class="row between"><b>📍 Where should we meet?</b><button class="btn soft sm" data-addp>＋ Suggest a place</button></div>
        ${r.places.length ? r.places.map((p) => `<div class="place ${r.my_vote === p.id ? "voted" : ""}"><div style="min-width:0"><b>${esc(p.name)}</b> <span class="muted small">· ${esc(p.address)}</span>
          <div class="tiny muted">Suggested by ${esc(p.proposer)} · ${p.geo_source === "nominatim" ? "📌 located via OpenStreetMap search" : p.source_ref ? `🔷 Qloo place result${p.validation ? ` · ${p.validation.status === "verified" ? "✓ address + map pin from Qloo" : "⚠ partially verified"} · booking & capacity not verified` : ""}` : "address only, not verified"}${p.cost_note ? ` · 💲 ${esc(p.cost_note)}` : ""}${p.accessibility_note ? ` · ♿ ${esc(p.accessibility_note)}` : ""}
          ${p.lat != null ? ` · <a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=18/${p.lat}/${p.lon}" target="_blank" rel="noopener noreferrer">map</a>` : ""}${p.url ? ` · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">link</a>` : ""}</div></div>
          <button class="btn ${r.my_vote === p.id ? "primary" : "soft"} sm" data-pv="${p.id}" aria-pressed="${r.my_vote === p.id}">👍 ${p.votes}</button></div>`).join("")
          : `<p class="muted small">No places suggested yet. Opening hours, prices and availability aren't checked — note what you know.</p>`}
        <form class="place-form" hidden><div class="grid2"><div class="field"><label>Place name *</label><input name="name" type="text" minlength="2" maxlength="120" required/></div>
          <div class="field"><label>Address *</label><input name="address" type="text" minlength="3" maxlength="300" required/></div></div>
          ${geoOn ? `<button type="button" class="btn soft sm" data-geo>🔎 Find on map</button><div class="geo-out"></div>` : `<p class="muted tiny">Map search isn't configured, so this place is saved without a pin.</p>`}
          <div class="grid3"><div class="field"><label>Known cost</label><input name="cost_note" maxlength="200" placeholder="e.g. free / unknown"/></div>
            <div class="field"><label>Accessibility</label><input name="accessibility_note" maxlength="200" placeholder="e.g. step-free entrance"/></div>
            <div class="field"><label>Link (https)</label><input name="url" type="url" maxlength="400"/></div></div>
          <div class="row end"><button class="btn primary sm" type="submit">Add place</button></div></form></div>`;
      const form = el.querySelector(".place-form");
      el.querySelector("[data-addp]").onclick = () => { form.hidden = !form.hidden; };
      el.querySelectorAll("[data-pv]").forEach((b) => (b.onclick = (e) => withBusy(e.currentTarget, async () => { await capi(`/api/proposals/${pid}/places/vote`, { body: { place_id: +b.dataset.pv } }); toast("Vote saved ✓"); load(); })));
      const g = el.querySelector("[data-geo]");
      if (g) g.onclick = (e) => withBusy(e.currentTarget, async () => {
        const res = await capi(`/api/geo/search?q=${encodeURIComponent(form.address.value)}`);
        const out = el.querySelector(".geo-out");
        out.innerHTML = res.length ? res.map((x, i) => `<button type="button" class="cand" data-gi="${i}"><span class="ph">📍</span><span><b>${esc(x.display_name)}</b></span></button>`).join("") : `<p class="muted small">No match found.</p>`;
        out.querySelectorAll("[data-gi]").forEach((b) => (b.onclick = () => { found = res[+b.dataset.gi]; form.address.value = found.display_name; out.querySelectorAll("[data-gi]").forEach((x) => x.classList.toggle("sel", x === b)); }));
      });
      form.onsubmit = (e) => { e.preventDefault(); withBusy(e.submitter, async () => {
        const body = { name: form.name.value.trim(), address: form.address.value.trim(), cost_note: form.cost_note.value.trim(), accessibility_note: form.accessibility_note.value.trim(), url: form.url.value.trim() };
        if (found && found.display_name === body.address) { body.lat = found.lat; body.lon = found.lon; }
        await capi(`/api/proposals/${pid}/places`, { body }); found = null; toast("Place added ✓"); load(); }); };
    }
    await load();
  };
})();
