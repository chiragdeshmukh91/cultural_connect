/* Culture Connect — Agent Activity Centre (#/agent).
 * Shows only what the backend recorded: real runs, steps, data sources, errors, invitations and approvals.
 * Every action button calls the API and reports the server's answer; nothing here is simulated.
 */
(() => {
  "use strict";
  const app = document.getElementById("app");
  const X = () => window.CCAPI;
  const capi = (...a) => X().capi(...a);
  const myTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; } };
  const ago = (ts) => { if (!ts) return ""; const s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
  const fmtWall = (s) => { const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/.exec(s || ""); if (!m) return esc(s || ""); const d = new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]); return esc(d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })); };
  const KIND = { discovery: ["🧭", "Cultural discovery"], circle_formation: ["⭕", "Circle formation"], event_planning: ["🗓", "Activity planning"],
    coordinate_proposal: ["🗳", "Vote tally & approval"], event_followup: ["🔔", "Event follow-up"], event_followup_votes: ["🗳", "Vote reminder"] };
  const RUN_ST = { queued: ["generated", "Queued"], running: ["qloo", "Running"], succeeded: ["participant ok-b", "Done"], failed: ["danger-b", "Failed"],
    paused: ["generated", "Paused"], cancelled: ["generated", "Cancelled"], skipped: ["generated", "Skipped"] };
  const STEP_IC = { ok: "✅", warn: "⚠️", error: "❌", skipped: "⏭", running: "⏳" };
  const SRC = { qloo: ["qloo", "Qloo"], database: ["generated", "App data"], app: ["participant", "App rule"] };
  const badge = (cls, txt) => `<span class="badge ${cls}">${esc(txt)}</span>`;
  const reasonSrc = { declared: ["participant", "You said"], qloo: ["qloo", "Qloo"], app: ["generated", "App"], preference: ["generated", "Preference"] };
  let timer = null, tab = "overview";

  window.agView = async (parts) => {
    clearInterval(timer);
    tab = ["overview", "runs", "settings"].includes((parts[1] || "").split("?")[0]) ? parts[1].split("?")[0] : "overview";
    await render();
  };
  window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#/agent")) clearInterval(timer); });

  async function render() {
    if (!location.hash.startsWith("#/agent")) return;
    let sum;
    try { sum = await capi("/api/agent/summary"); } catch (e) { app.innerHTML = `<div class="card empty-state"><div class="es-ic">🤖</div><h3>${esc(e.message)}</h3></div>`; return; }
    app.innerHTML = `<section class="dash-hero ag-hero"><div><span class="how-kicker">🤖 Agent Activity Centre</span><h1>What your agents are doing</h1>
      <p class="muted">Every step below was actually executed and recorded by the server. <span class="badge qloo">Qloo</span> = returned by a real Qloo response ·
      <span class="badge participant">App rule</span> = computed by Culture Connect · <span class="badge generated">App data</span> = your saved data.</p></div>
      <div class="ag-stats"><div><b>${sum.running}</b><small>running</small></div><div><b>${sum.invites_pending}</b><small>invites</small></div><div><b>${sum.approvals_pending}</b><small>approvals</small></div></div></section>
      ${!sum.settings.automation ? `<div class="notice">⏸ Automation is paused — no automatic discovery or Circle invitations. <a href="#/agent/settings">Resume</a></div>` : ""}
      <div class="seg ag-tabs" role="tablist">${[["overview", "✨ Overview"], ["runs", "🧾 Execution log"], ["settings", "⚙️ Settings"]].map(([k, l]) =>
        `<a role="tab" href="#/agent/${k}" class="${tab === k ? "on" : ""}" aria-selected="${tab === k}">${l}</a>`).join("")}</div>
      <div id="agBody">${'<div class="skel"></div>'.repeat(2)}</div>`;
    const body = document.getElementById("agBody");
    try {
      if (tab === "overview") await overview(body, sum);
      else if (tab === "runs") await runsView(body);
      else settingsView(body, sum);
    } catch (e) { body.innerHTML = `<p class="form-err">${esc(e.message)}</p>`; }
  }

  // ------------------------------------------------------------------ overview: approvals, invitations, discovery
  async function overview(body, sum) {
    const [inv, appr, disc] = await Promise.all([capi("/api/agent/invites"), capi("/api/agent/approvals"), capi("/api/agent/discovery")]);
    const d = disc.result;
    body.innerHTML = `
      ${appr.length ? `<h2 class="sec-h">🗳 Activities drafted by the planning agent</h2>${appr.map(apprCard).join("")}` : ""}
      ${inv.length ? `<h2 class="sec-h">⭕ Circle invitations</h2><div class="grid2">${inv.map(invCard).join("")}</div>` : ""}
      <div class="row between" style="margin-top:22px"><h2 class="sec-h" style="margin:0">🧭 Latest discovery</h2>
        <button class="btn soft sm" id="agRefresh">🔄 Refresh with Qloo</button></div>
      ${d ? discoveryView(d) : `<div class="card empty-state"><div class="es-ic">🌱</div><h3>No discovery yet</h3>
        <p class="muted">It runs automatically after you save your profile with discovery consent on.</p><a class="btn primary" href="#/me">Profile & privacy</a></div>`}
      <details class="card ag-rules"><summary>📐 How the agents match people (application rules, not Qloo scores)</summary>
        <p class="small">${esc(sum.match_rules.summary)}</p><b class="small">Hard constraints first</b>
        <ul class="small">${sum.match_rules.hard_constraints.map((x) => `<li>${esc(x)}</li>`).join("")}</ul><b class="small">Then points</b>
        <ul class="small">${Object.entries(sum.match_rules.points).map(([k, v]) => `<li>${esc(k)}: <b>+${v}</b></li>`).join("")}</ul></details>`;
    document.getElementById("agRefresh").onclick = (e) => withBusy(e.currentTarget, async () => {
      const r = await capi("/api/agent/discovery/refresh", { method: "POST", body: {} });
      if (!r.queued) return toast(r.message || "Not started", true);
      toast("Discovery queued — watch it in the execution log"); location.hash = "#/agent/runs";
    });
    body.querySelectorAll("[data-inv]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const v = await capi(`/api/agent/invites/${b.dataset.inv}/${b.dataset.act}`, { method: "POST", body: {} });
      toast(v.status === "formed" && b.dataset.act === "accept" ? "You're in — the Circle is formed ✓" : b.dataset.act === "accept" ? "Accepted ✓ — waiting for others" : "Done ✓");
      if (v.status === "formed" && v.circle_id && b.dataset.act === "accept") location.hash = `#/c/${v.circle_id}`; else render();
    }));
    body.querySelectorAll("[data-appr]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      if (b.dataset.act === "approve") {
        const r = await capi(`/api/agent/approvals/${b.dataset.appr}/approve`, { method: "POST", body: { timezone: b.dataset.tz || myTz() } });
        toast("Approved — event published ✓"); location.hash = `#/e/${r.event_id}`;
      } else {
        await capi(`/api/agent/approvals/${b.dataset.appr}/reject`, { method: "POST", body: {} }); toast("Draft rejected"); render();
      }
    }));
  }

  function apprCard(a) {
    const s = a.selected;
    return `<div class="card ag-appr"><div class="row between"><div><b>${esc(a.title)}</b><div class="muted small">⭕ ${esc(a.circle_name)} · ${a.options.length} option(s) · ${a.times.length} time(s)</div></div>
      ${a.stage === "voting" ? badge("participant", "Voting open") : badge("qloo", "Ready for approval")}</div>
      ${a.stage === "voting" ? `<p class="small muted">Voting closes ${a.vote_deadline ? new Date(a.vote_deadline * 1000).toLocaleString() : "soon"} (or as soon as every member has voted).
        <a href="#/c/${esc(a.circle_id)}/events">Vote now →</a></p>`
        : `<ul class="ag-sel small"><li>🎯 <b>${esc(s.option)}</b></li><li>📅 ${fmtWall(s.time)} <span class="muted">(${esc(s.timezone)})</span></li>
          <li>📍 ${s.place ? `${esc(s.place.name)} — ${esc(s.place.address)} <span class="muted">(suggested place, not booked)</span>` : "Location to be confirmed"}</li></ul>
          <p class="tiny muted">${esc(a.selection.rule)}</p>
          ${a.can_approve ? `<div class="row end"><button class="btn ghost sm" data-appr="${esc(a.id)}" data-act="reject">✕ Reject</button>
            <a class="btn soft sm" href="#/c/${esc(a.circle_id)}/events">✎ Edit / review</a>
            <button class="btn primary sm" data-appr="${esc(a.id)}" data-act="approve" data-tz="${esc(s.timezone)}">✓ Approve & publish</button></div>`
            : `<p class="small muted">Waiting for a host to approve.</p>`}`}</div>`;
  }

  function invCard(v) {
    const st = v.status === "gathering" ? badge("generated", `Gathering · ${v.counts.eligible}/${v.min_size}`) : v.status === "formed" ? badge("participant ok-b", "Formed")
      : badge("qloo", `${v.counts.accepted}/${v.min_size} accepted`);
    const act = v.my_status === "invited" && v.status !== "cancelled"
      ? `<div class="row end"><button class="btn ghost sm" data-inv="${esc(v.id)}" data-act="decline">Not for me</button><button class="btn primary sm" data-inv="${esc(v.id)}" data-act="accept">Join this Circle</button></div>`
      : v.my_status === "accepted" && v.status === "open" ? `<div class="row between"><span class="small">✓ You accepted — the Circle forms at ${v.min_size} people.</span><button class="btn ghost sm" data-inv="${esc(v.id)}" data-act="withdraw">Withdraw</button></div>`
      : v.status === "formed" && v.circle_id ? `<div class="row end"><a class="btn soft sm" href="#/c/${esc(v.circle_id)}">Open Circle →</a></div>`
      : v.status === "gathering" ? `<p class="small muted">The agent will invite people once ${v.min_size} matching members have consented to discovery. Nobody sees your details.</p>`
      : `<p class="small muted">You ${esc(v.my_status)} this invitation.</p>`;
    return `<div class="card ag-inv"><div class="row between"><b>${esc(v.name)}</b>${st}</div>
      <p class="small">${esc(v.description)} <span class="badge generated" title="${esc(v.description_source)}">App text</span></p>
      ${v.signals.length ? `<div class="chips">${v.signals.map((s) => `<span class="chip" title="Qloo ID ${esc(s.id)}">🔷 ${esc(s.name)} <span class="muted tiny">${esc(s.kind)}</span></span>`).join("")}</div>` : ""}
      ${v.notice ? `<p class="tiny muted">ℹ️ ${esc(v.notice)}</p>` : ""}
      <div class="reasons small">${v.my_reasons.map((r) => `<div>${badge((reasonSrc[r.source] || reasonSrc.app)[0], (reasonSrc[r.source] || reasonSrc.app)[1])} ${esc(r.text)}</div>`).join("")}</div>
      ${act}</div>`;
  }

  function discoveryView(d) {
    const q = d.qloo || {};
    return `<p class="muted small">Updated ${ago(d.generated_at)} · <a href="#/agent/runs">see every step</a></p>
      ${(d.warnings || []).map((w) => `<div class="notice">⚠️ ${esc(w)}</div>`).join("")}
      <div class="grid2"><div><h3 class="small-h">⭕ Circles matched for you</h3>
        ${d.recommendations.length ? d.recommendations.map((c) => `<a class="card ev-row" href="#/c/${esc(c.id)}"><span>⭕</span><div style="min-width:0"><b>${esc(c.name)}</b>
          <div class="muted tiny">${c.member_count} member(s) · ${esc(c.meeting_mode.replace("_", " "))}${c.area ? " · " + esc(c.area) : ""}</div>
          <div class="reasons tiny">${c.reasons.slice(0, 3).map((r) => `<div>${badge((reasonSrc[r.source] || reasonSrc.app)[0], (reasonSrc[r.source] || reasonSrc.app)[1])} ${esc(r.text)}</div>`).join("")}</div></div></a>`).join("")
          : `<p class="muted small">No existing Circle fits yet${d.formation && d.formation.length ? ` — the agent is forming ${d.formation.length} new one(s): ${d.formation.map((f) => esc(f.label)).join(", ")}` : ""}.</p>`}</div>
      <div><h3 class="small-h">🔷 Qloo taste insights <span class="badge qloo">Qloo</span></h3>
        ${(q.related_interests || []).length ? `<p class="tiny muted">Related interests Qloo returned for your interests:</p><div class="chips">${q.related_interests.map((t) => `<span class="chip" title="${esc(t.id)}">${esc(t.name)}</span>`).join("")}</div>` : `<p class="muted small">Qloo returned no related interests (or none of your interests has a Qloo ID yet).</p>`}
        ${(d.activity_ideas || []).length ? `<p class="tiny muted" style="margin-top:12px">Cross-category ideas — the item is from Qloo, the idea wording is generated by the app:</p>
          ${d.activity_ideas.map((i) => `<div class="small">💡 ${esc(i.idea)} ${badge("qloo", (i.qloo.type || "").split(":").pop() || "entity")}</div>`).join("")}` : ""}</div></div>`;
  }

  // ------------------------------------------------------------------ execution log
  async function runsView(body) {
    const runs = await capi("/api/agent/runs?limit=40");
    if (!runs.length) { body.innerHTML = `<div class="card empty-state"><div class="es-ic">🧾</div><h3>No agent runs yet</h3><p class="muted">Save your profile with discovery consent to start.</p></div>`; return; }
    body.innerHTML = runs.map((r, i) => runCard(r, i === 0)).join("");
    body.querySelectorAll("[data-ctl]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      await capi(`/api/agent/runs/${b.dataset.run}/${b.dataset.ctl}`, { method: "POST", body: {} }); toast(`${b.dataset.ctl} ✓`); render();
    }));
    if (runs.some((r) => ["queued", "running"].includes(r.status))) timer = setInterval(() => { if (document.getElementById("agBody")) render(); }, 4000);
  }

  function runCard(r, first = false) {
    const [ic, name] = KIND[r.kind] || ["🤖", r.kind];
    const [cls, lab] = RUN_ST[r.status] || ["generated", r.status];
    const ctl = r.can_control ? [["pause", ["queued", "running"]], ["resume", ["paused"]], ["retry", ["failed", "skipped"]], ["cancel", ["queued", "paused", "failed"]]]
      .filter(([, s]) => s.includes(r.status)).map(([a]) => `<button class="btn ghost sm" data-ctl="${a}" data-run="${esc(r.id)}">${{ pause: "⏸ Pause", resume: "▶ Resume", retry: "↻ Retry", cancel: "✕ Cancel" }[a]}</button>`).join("") : "";
    return `<details class="card ag-run" ${first || ["running", "failed"].includes(r.status) ? "open" : ""}><summary><span class="ag-ic">${ic}</span><div style="min-width:0;flex:1"><b>${esc(name)}</b>${r.circle_name ? ` <span class="muted small">· ⭕ ${esc(r.circle_name)}</span>` : ""}
        <div class="muted tiny">Trigger: ${esc(r.trigger)} · ${ago(r.created_at)}${r.attempts > 1 ? ` · attempt ${r.attempts}/${r.max_attempts}` : ""}</div></div>${badge(cls, lab)}</summary>
      ${r.error ? `<p class="form-err small">${esc(r.error)}</p>` : ""}
      <ol class="ag-steps">${r.steps.map((s) => `<li class="st-${esc(s.status)}"><div><span>${STEP_IC[s.status] || "•"}</span> <b>${esc(s.tool.replace(/_/g, " "))}</b>
        <span class="muted tiny">${s.finished_at ? `${Math.max(0, Math.round((s.finished_at - s.started_at) * 1000))} ms` : ""}${s.attempt > 1 ? ` · attempt ${s.attempt}` : ""}</span></div>
        <p class="small">${esc(s.message)}</p>
        ${s.sources.length ? `<div class="ag-src">${s.sources.map((x) => { const [c, l] = SRC[x.type] || ["generated", x.type]; return `<div class="tiny">${badge(c, l)} ${esc(x.detail || "")}${x.query ? ` · “${esc(x.query)}”` : ""}${x.candidates_returned != null ? ` · ${x.candidates_returned} candidates` : ""}${x.params ? ` <code>${esc(Object.entries(x.params).map(([k, v]) => `${k}=${Array.isArray(v) ? v.length + " id(s)" : v}`).join(" · "))}</code>` : ""}</div>`; }).join("")}</div>` : ""}</li>`).join("")}
        ${r.status === "queued" && !r.steps.length ? `<li class="st-running"><span>⏳</span> Waiting for the background worker…</li>` : ""}</ol>
      ${ctl ? `<div class="row end">${ctl}</div>` : ""}</details>`;
  }

  // ------------------------------------------------------------------ settings
  function settingsView(body, sum) {
    const s = sum.settings;
    const tg = (k, label, hint, dis = false) => `<label class="check ag-tg"><input type="checkbox" data-set="${k}" ${s[k] ? "checked" : ""} ${dis ? "disabled" : ""}/> <span><b>${label}</b><br><span class="muted small">${hint}</span></span></label>`;
    body.innerHTML = `<div class="card"><h3>👤 My automation</h3>
      ${tg("automation", "Automatic discovery", "Run Qloo-powered discovery whenever I save my profile. Off = paused; nothing runs for me automatically.")}
      ${tg("circle_invites", "Circle invitations", "Let the Circle agent invite me to new Circles. I always choose whether to join.")}
      ${tg("email_notify", "Email me agent updates", s.email_configured ? "Also send agent notifications to my account email." : "Email isn't configured on this server — in-app notifications only.", !s.email_configured)}
      <p class="tiny muted">Turn off discovery consent completely in <a href="#/me">Profile & privacy</a>.</p></div>
      ${sum.moderated_circles.length ? `<div class="card"><h3>⭕ Circles you host</h3>${sum.moderated_circles.map((c) => `<div class="ag-circ row between"><div><b>${esc(c.name)}</b></div>
        <div class="row">${c.is_host ? `<label class="check small"><input type="checkbox" data-cauto="${esc(c.id)}" ${c.auto_plan ? "checked" : ""}/> Auto-plan activities</label>
          <select data-cpol="${esc(c.id)}" aria-label="Approval policy"><option value="host" ${c.approval_policy === "host" ? "selected" : ""}>Host approves</option><option value="auto" ${c.approval_policy === "auto" ? "selected" : ""}>Auto-publish (venue stays "to be confirmed")</option></select>` : ""}
          <button class="btn soft sm" data-plan="${esc(c.id)}">🗓 Plan now</button></div></div>`).join("")}</div>` : ""}`;
    body.querySelectorAll("[data-set]").forEach((i) => i.onchange = async () => {
      try { await capi("/api/agent/settings", { method: "PUT", body: { [i.dataset.set]: i.checked } }); toast("Saved ✓"); } catch (e) { i.checked = !i.checked; toast(e.message, true); }
    });
    body.querySelectorAll("[data-cauto],[data-cpol]").forEach((i) => i.onchange = async () => {
      const id = i.dataset.cauto || i.dataset.cpol;
      try { await capi(`/api/agent/circles/${id}/settings`, { method: "PUT", body: i.dataset.cauto ? { auto_plan: i.checked } : { approval_policy: i.value } }); toast("Saved ✓"); } catch (e) { toast(e.message, true); }
    });
    body.querySelectorAll("[data-plan]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      const r = await capi(`/api/agent/circles/${b.dataset.plan}/plan`, { method: "POST", body: {} });
      if (!r.queued) return toast(r.message, true);
      toast("Planning agent queued ✓"); location.hash = "#/agent/runs";
    }));
  }
})();
