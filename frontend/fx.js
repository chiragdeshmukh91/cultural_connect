/* Culture Connect — interaction layer.
 * Pure progressive enhancement on top of app.js: every effect is optional, wrapped in try/catch,
 * and the app works exactly the same if this file fails to load.
 *  - Live Qloo playground (drag interest bubbles into Qloo -> real /api/interests/resolve call)
 *  - Draggable connection graph, draggable hero stickers with spring-back
 *  - 3D tilt, cursor spotlight, magnetic buttons, click ripples, scroll reveal, scroll progress
 *  - Confetti when a plan is approved
 */
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = window.matchMedia("(pointer: fine)").matches;
  const root = document.documentElement;
  root.classList.add("fx");
  const safe = (fn) => { try { fn(); } catch (e) { console.warn("[fx]", e); } };
  const escx = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  // ------------------------------------------------------------------ scroll progress bar
  safe(() => {
    const bar = document.createElement("div");
    bar.className = "scrollbar-fx";
    document.body.appendChild(bar);
    const upd = () => {
      const h = document.documentElement.scrollHeight - innerHeight;
      bar.style.transform = `scaleX(${h > 0 ? clamp(scrollY / h, 0, 1) : 0})`;
    };
    addEventListener("scroll", upd, { passive: true });
    addEventListener("resize", upd);
    upd();
  });

  // ------------------------------------------------------------------ reveal on scroll
  const io = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
    entries.forEach((en) => {
      if (!en.isIntersecting) return;
      const el = en.target;
      io.unobserve(el);
      el.classList.add("in");
      const d = parseFloat(el.style.getPropertyValue("--d")) || 0;
      setTimeout(() => { el.classList.remove("reveal", "in"); el.style.removeProperty("--d"); }, 750 + d * 1000);
    });
  }, { threshold: 0.08 }) : null;

  function reveal(scope) {
    if (!io || reduce) return;
    const els = scope.querySelectorAll(".card:not([data-fx-r]), .how-step:not([data-fx-r]), .feature:not([data-fx-r]), .trust:not([data-fx-r]), .pg-wrap:not([data-fx-r])");
    let i = 0;
    els.forEach((el) => {
      el.dataset.fxR = "1";
      if (el.closest(".drawer")) return;
      el.classList.add("reveal");
      el.style.setProperty("--d", `${Math.min(i++, 8) * 0.06}s`);
      io.observe(el);
    });
  }

  // ------------------------------------------------------------------ tilt + spotlight + magnetic
  function tilt(scope) {
    if (!finePointer || reduce) return;
    scope.querySelectorAll(".feature, .how-step, .mini, .trust, .hero-img, .ti, .how-ic").forEach((el) => {
      if (el.dataset.fxT) return;
      el.dataset.fxT = "1";
      const max = el.classList.contains("hero-img") ? 5 : 9;
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        el.style.transform = `perspective(700px) rotateX(${(-y * max).toFixed(2)}deg) rotateY(${(x * max).toFixed(2)}deg) translateY(-3px)`;
      });
      el.addEventListener("pointerleave", () => { el.style.transform = ""; });
    });
  }

  function spotlight(scope) {
    if (!finePointer) return;
    scope.querySelectorAll(".card").forEach((el) => {
      if (el.dataset.fxS) return;
      el.dataset.fxS = "1";
      el.classList.add("spot");
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
      });
    });
  }

  function magnetic(scope) {
    if (!finePointer || reduce) return;
    scope.querySelectorAll(".btn.primary").forEach((el) => {
      if (el.dataset.fxM) return;
      el.dataset.fxM = "1";
      el.addEventListener("pointermove", (e) => {
        if (el.disabled) return;
        const r = el.getBoundingClientRect();
        const dx = clamp((e.clientX - (r.left + r.width / 2)) * 0.25, -8, 8);
        const dy = clamp((e.clientY - (r.top + r.height / 2)) * 0.35, -6, 6);
        el.style.translate = `${dx}px ${dy}px`;
      });
      el.addEventListener("pointerleave", () => { el.style.translate = ""; });
    });
  }

  // click ripple on any button (delegated once)
  document.addEventListener("pointerdown", (e) => safe(() => {
    const b = e.target.closest(".btn, .goal, .seg button, .chip.click");
    if (!b || b.disabled || reduce) return;
    const r = b.getBoundingClientRect();
    const s = document.createElement("span");
    s.className = "ripple-fx";
    const d = Math.max(r.width, r.height) * 2;
    s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
    b.appendChild(s);
    setTimeout(() => s.remove(), 650);
  }));

  // ------------------------------------------------------------------ draggable stickers (spring back)
  function stickers(scope) {
    scope.querySelectorAll(".hero-visual .orb, .hero-visual .match, .hero-visual .picks, .hero-visual .float, .facestack img").forEach((el) => {
      if (el.dataset.fxD) return;
      el.dataset.fxD = "1";
      el.classList.add("sticker");
      let sx = 0, sy = 0, on = false;
      el.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        on = true; sx = e.clientX; sy = e.clientY;
        el.classList.add("grabbing"); el.classList.remove("springing");
        el.setPointerCapture(e.pointerId);
        e.preventDefault();
      });
      el.addEventListener("pointermove", (e) => {
        if (!on) return;
        el.style.translate = `${e.clientX - sx}px ${e.clientY - sy}px`;
      });
      const end = () => {
        if (!on) return;
        on = false;
        el.classList.remove("grabbing"); el.classList.add("springing");
        el.style.translate = "";
        setTimeout(() => el.classList.remove("springing"), 750);
      };
      el.addEventListener("pointerup", end);
      el.addEventListener("pointercancel", end);
    });
  }

  // ------------------------------------------------------------------ draggable connection graph
  function graphs(scope) {
    scope.querySelectorAll("svg.graph").forEach((svg) => {
      if (svg.dataset.fxG) return;
      svg.dataset.fxG = "1";
      const vb = svg.viewBox.baseVal;
      const nodes = {};
      svg.querySelectorAll(".gnode").forEach((g) => {
        const c = g.querySelector("circle");
        nodes[g.dataset.node] = { g, x: +c.getAttribute("cx"), y: +c.getAttribute("cy"), r: +c.getAttribute("r"), dx: 0, dy: 0 };
      });
      const lines = [...svg.querySelectorAll("line[data-from]")];
      const pt = (e) => {
        const m = svg.getScreenCTM();
        if (!m) return { x: 0, y: 0 };
        const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
        return { x: p.x, y: p.y };
      };
      const apply = (id) => {
        const n = nodes[id];
        n.g.setAttribute("transform", `translate(${n.dx.toFixed(1)} ${n.dy.toFixed(1)})`);
        lines.forEach((l) => {
          if (l.dataset.from === id) { l.setAttribute("x1", n.x + n.dx); l.setAttribute("y1", n.y + n.dy); }
          if (l.dataset.to === id) { l.setAttribute("x2", n.x + n.dx); l.setAttribute("y2", n.y + n.dy); }
        });
      };
      let drag = null;
      svg.addEventListener("pointerdown", (e) => {
        const g = e.target.closest(".gnode");
        if (!g) return;
        const n = nodes[g.dataset.node];
        const p = pt(e);
        drag = { n, id: g.dataset.node, ox: p.x - n.dx, oy: p.y - n.dy };
        g.classList.add("dragging");
        svg.classList.add("is-dragging");
        svg.setPointerCapture(e.pointerId);
        e.preventDefault();
      });
      svg.addEventListener("pointermove", (e) => {
        if (!drag) return;
        const p = pt(e), n = drag.n;
        n.dx = clamp(p.x - drag.ox, vb.x + n.r - n.x, vb.x + vb.width - n.r - n.x);
        n.dy = clamp(p.y - drag.oy, vb.y + n.r - n.y, vb.y + vb.height - n.r - n.y);
        apply(drag.id);
      });
      const end = () => {
        if (!drag) return;
        drag.n.g.classList.remove("dragging");
        svg.classList.remove("is-dragging");
        drag = null;
      };
      svg.addEventListener("pointerup", end);
      svg.addEventListener("pointercancel", end);
      // double-click resets layout
      svg.addEventListener("dblclick", () => Object.keys(nodes).forEach((id) => { nodes[id].dx = nodes[id].dy = 0; apply(id); }));
    });
  }

  // ------------------------------------------------------------------ live Qloo playground
  const INTERESTS = [["♟️", "Chess"], ["🎵", "Jazz"], ["🌍", "Climate action"], ["🏏", "Cricket"], ["🎨", "Street art"],
    ["💬", "Politics"], ["🩺", "Diabetes"], ["📚", "Poetry"], ["🍳", "Cooking"], ["🎮", "Minecraft"], ["🌱", "Gardening"],
    ["📷", "Photography"], ["🎬", "Bollywood"], ["⚽", "Football"], ["🧘", "Yoga"]];
  const prettyT = (u) => (u || "").split(":").slice(-1)[0].replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  function playground(scope) {
    const pg = scope.querySelector("#pg");
    if (!pg || pg.dataset.fxP) return;
    pg.dataset.fxP = "1";
    const canvas = pg.querySelector("canvas");
    const ctx = canvas.getContext("2d");
    const core = pg.querySelector("#pgCore");
    const out = pg.querySelector("#pgResult");
    let W = 0, H = 0, dpr = 1, raf = 0, coreX = 0, coreY = 0, coreR = 60;
    const bubbles = [];

    const measure = () => {
      const r = pg.getBoundingClientRect();
      W = r.width; H = r.height; dpr = Math.min(2, devicePixelRatio || 1);
      canvas.width = W * dpr; canvas.height = H * dpr;
      canvas.style.width = W + "px"; canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      coreX = W / 2; coreY = H / 2; coreR = core.offsetWidth / 2 || 60;
      bubbles.forEach((b) => { b.x = clamp(b.x, 0, Math.max(0, W - b.w)); b.y = clamp(b.y, 0, Math.max(0, H - b.h)); });
    };

    const spawnPos = (b) => {
      for (let k = 0; k < 40; k++) {
        const x = Math.random() * Math.max(1, W - b.w), y = Math.random() * Math.max(1, H - b.h);
        const cx = x + b.w / 2, cy = y + b.h / 2;
        if (Math.hypot(cx - coreX, cy - coreY) < coreR + b.w / 2 + 20) continue;
        if (bubbles.some((o) => o !== b && Math.hypot(o.x + o.w / 2 - cx, o.y + o.h / 2 - cy) < 90)) continue;
        return [x, y];
      }
      return [Math.random() * Math.max(1, W - b.w), 8];
    };

    const make = (emoji, label, fresh) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "pg-bubble" + (fresh ? " pop" : "");
      el.innerHTML = `<span>${escx(emoji)}</span>${escx(label)}`;
      el.setAttribute("aria-label", `Send ${label} to Qloo`);
      el.style.setProperty("--h", String((bubbles.length * 47) % 360));
      pg.appendChild(el);
      const b = { el, label, emoji, w: el.offsetWidth, h: el.offsetHeight, x: 0, y: 0,
        vx: reduce ? 0 : (Math.random() - 0.5) * 0.5, vy: reduce ? 0 : (Math.random() - 0.5) * 0.5, drag: false, gone: false };
      [b.x, b.y] = spawnPos(b);
      bubbles.push(b);
      bind(b);
      return b;
    };

    const near = (b) => Math.hypot(b.x + b.w / 2 - coreX, b.y + b.h / 2 - coreY) < coreR + 26;

    function bind(b) {
      let sx = 0, sy = 0, ox = 0, oy = 0, moved = 0;
      b.el.addEventListener("pointerdown", (e) => {
        if (b.gone || e.button !== 0) return;
        b.drag = true; moved = 0;
        sx = e.clientX; sy = e.clientY; ox = b.x; oy = b.y;
        b.el.classList.add("grabbing");
        b.el.setPointerCapture(e.pointerId);
        e.preventDefault();
      });
      b.el.addEventListener("pointermove", (e) => {
        if (!b.drag) return;
        const dx = e.clientX - sx, dy = e.clientY - sy;
        moved = Math.max(moved, Math.hypot(dx, dy));
        const nx = clamp(ox + dx, 0, W - b.w), ny = clamp(oy + dy, 0, H - b.h);
        b.vx = (nx - b.x) * 0.35; b.vy = (ny - b.y) * 0.35;
        b.x = nx; b.y = ny;
        core.classList.toggle("hot", near(b));
      });
      const end = () => {
        if (!b.drag) return;
        b.drag = false;
        b.el.classList.remove("grabbing");
        core.classList.remove("hot");
        if (moved < 6 || near(b)) absorb(b);
        if (reduce) { b.vx = 0; b.vy = 0; }
        else { b.vx = clamp(b.vx, -3, 3); b.vy = clamp(b.vy, -3, 3); }
      };
      b.el.addEventListener("pointerup", end);
      b.el.addEventListener("pointercancel", () => { b.drag = false; b.el.classList.remove("grabbing"); core.classList.remove("hot"); });
      b.el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); absorb(b); } });
    }

    function absorb(b) {
      if (b.gone) return;
      b.gone = true;
      b.el.classList.add("absorb");
      b.el.style.transform = `translate(${coreX - b.w / 2}px, ${coreY - b.h / 2}px) scale(.2)`;
      core.classList.remove("pulse"); void core.offsetWidth; core.classList.add("pulse");
      ask(b.label, b.emoji);
      setTimeout(() => {
        b.el.classList.remove("absorb");
        [b.x, b.y] = spawnPos(b);
        b.vx = reduce ? 0 : (Math.random() - 0.5) * 0.6; b.vy = reduce ? 0 : (Math.random() - 0.5) * 0.6;
        b.el.classList.add("pop");
        b.gone = false;
        setTimeout(() => b.el.classList.remove("pop"), 500);
      }, 900);
    }

    let reqId = 0;
    async function ask(label, emoji) {
      const id = ++reqId;
      out.hidden = false;
      out.innerHTML = `<div class="pgr-h"><span class="pgr-e">${escx(emoji)}</span><div><b>“${escx(label)}”</b><small>Asking Qloo…</small></div></div><div class="pgr-load"><i></i><i></i><i></i></div>`;
      try {
        const res = await fetch("/api/interests/resolve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label }) });
        const data = await res.json().catch(() => ({}));
        if (id !== reqId) return;
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const c = (data.candidates || []).slice(0, 4);
        const counts = (data.candidates || []).reduce((a, x) => ((a[x.kind] = (a[x.kind] || 0) + 1), a), {});
        out.innerHTML = `<button class="pgr-x" type="button" aria-label="Close">✕</button>
          <div class="pgr-h"><span class="pgr-e">${escx(emoji)}</span><div><b>“${escx(label)}”</b><small>${(data.candidates || []).length} live Qloo matches</small></div></div>
          <div class="pgr-k">${["entity", "tag", "audience"].map((k) => `<span class="kind ${k}">${k} · ${counts[k] || 0}</span>`).join("")}</div>
          ${c.length ? c.map((x) => `<div class="pgr-row">${x.image ? `<img src="${escx(x.image)}" alt=""/>` : `<span class="pgr-ph">${x.kind === "tag" ? "#" : x.kind === "audience" ? "◎" : "◆"}</span>`}
            <div><b>${escx(x.name)}</b><small>${escx(prettyT(x.type))}</small></div></div>`).join("")
            : `<p class="pgr-empty">No match — try a broader word.</p>`}
          <div class="pgr-f">via /search · /v2/tags · /v2/audiences</div>
          ${window.ccDraftAdd ? `<button class="btn ${window.ccDraftHas && window.ccDraftHas(label) ? "soft" : "primary"} sm pgr-add" type="button" data-label="${escx(label)}" data-emoji="${escx(emoji)}">${window.ccDraftHas && window.ccDraftHas(label) ? "✓ In your draft profile" : "＋ Add to my draft profile"}</button>
            <p class="pgr-note">Saved only in this browser. Nothing is shared or created until you submit your profile.</p>` : ""}`;
      } catch (err) {
        if (id !== reqId) return;
        out.innerHTML = `<button class="pgr-x" type="button" aria-label="Close">✕</button>
          <div class="pgr-h"><span class="pgr-e">⚠️</span><div><b>Qloo didn't answer</b><small>${escx(err.message).slice(0, 120)}</small></div></div>`;
      }
    }
    out.addEventListener("click", (e) => {
      if (e.target.closest(".pgr-x")) out.hidden = true;
      const add = e.target.closest(".pgr-add");
      if (add && window.ccDraftAdd) {
        const ok = window.ccDraftAdd(add.dataset.label, add.dataset.emoji);
        add.textContent = "✓ In your draft profile"; add.classList.remove("primary"); add.classList.add("soft");
        if (ok && typeof toast === "function") toast(`Added “${add.dataset.label}” to your draft — continue when ready`);
      }
    });

    function frame() {
      if (!pg.isConnected) { cancelAnimationFrame(raf); ro && ro.disconnect(); return; }
      ctx.clearRect(0, 0, W, H);
      // soft repulsion + drift
      for (let i = 0; i < bubbles.length; i++) {
        const a = bubbles[i];
        if (a.gone) continue;
        const ax = a.x + a.w / 2, ay = a.y + a.h / 2;
        for (let j = i + 1; j < bubbles.length; j++) {
          const o = bubbles[j];
          if (o.gone) continue;
          const dx = o.x + o.w / 2 - ax, dy = o.y + o.h / 2 - ay, d = Math.hypot(dx, dy) || 1;
          const min = (a.w + o.w) / 2.6;
          if (d < min) {
            const f = ((min - d) / min) * 0.6, fx = (dx / d) * f, fy = (dy / d) * f;
            if (!a.drag) { a.vx -= fx; a.vy -= fy; }
            if (!o.drag) { o.vx += fx; o.vy += fy; }
          }
        }
        if (!a.drag) {
          // keep out of the core unless being dropped
          const cdx = ax - coreX, cdy = ay - coreY, cd = Math.hypot(cdx, cdy) || 1;
          if (cd < coreR + a.w / 2 + 14) { a.vx += (cdx / cd) * 0.35; a.vy += (cdy / cd) * 0.35; }
          a.vx *= 0.985; a.vy *= 0.985;
          if (!reduce) { a.vx += (Math.random() - 0.5) * 0.03; a.vy += (Math.random() - 0.5) * 0.03; }
          const sp = Math.hypot(a.vx, a.vy);
          if (sp > 2.5) { a.vx *= 2.5 / sp; a.vy *= 2.5 / sp; }
          a.x += a.vx; a.y += a.vy;
          if (a.x < 0) { a.x = 0; a.vx = Math.abs(a.vx); }
          if (a.x > W - a.w) { a.x = W - a.w; a.vx = -Math.abs(a.vx); }
          if (a.y < 0) { a.y = 0; a.vy = Math.abs(a.vy); }
          if (a.y > H - a.h) { a.y = H - a.h; a.vy = -Math.abs(a.vy); }
        }
      }
      // constellation lines
      const live = bubbles.filter((b) => !b.gone);
      for (let i = 0; i < live.length; i++) {
        const a = live[i], ax = a.x + a.w / 2, ay = a.y + a.h / 2;
        for (let j = i + 1; j < live.length; j++) {
          const o = live[j], d = Math.hypot(o.x + o.w / 2 - ax, o.y + o.h / 2 - ay);
          if (d < 170) {
            ctx.strokeStyle = `rgba(124,92,255,${(1 - d / 170) * 0.35})`;
            ctx.lineWidth = 1.2;
            ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(o.x + o.w / 2, o.y + o.h / 2); ctx.stroke();
          }
        }
        const dc = Math.hypot(coreX - ax, coreY - ay);
        if (a.drag || dc < 230) {
          const g = ctx.createLinearGradient(ax, ay, coreX, coreY);
          const al = a.drag ? 0.75 : (1 - dc / 230) * 0.45;
          g.addColorStop(0, `rgba(236,72,153,${al})`); g.addColorStop(1, `rgba(124,92,255,${al})`);
          ctx.strokeStyle = g; ctx.lineWidth = a.drag ? 2.2 : 1.4;
          ctx.setLineDash(a.drag ? [6, 6] : []);
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(coreX, coreY); ctx.stroke();
          ctx.setLineDash([]);
        }
        if (!a.gone) a.el.style.transform = `translate(${a.x.toFixed(1)}px, ${a.y.toFixed(1)}px)`;
      }
      raf = requestAnimationFrame(frame);
    }

    const ro = "ResizeObserver" in window ? new ResizeObserver(() => safe(measure)) : null;
    measure();
    const small = W < 600;
    INTERESTS.slice(0, small ? 9 : INTERESTS.length).forEach(([e, l]) => make(e, l));
    ro && ro.observe(pg);
    raf = requestAnimationFrame(frame);

    const form = scope.querySelector("#pgAdd");
    if (form) form.addEventListener("submit", (e) => {
      e.preventDefault();
      const inp = form.querySelector("input");
      const v = (inp.value || "").trim().slice(0, 40);
      if (!v) return;
      const b = make("✨", v, true);
      b.x = clamp(W / 2 - b.w / 2 + (Math.random() - 0.5) * 200, 0, W - b.w); b.y = 10;
      b.vy = reduce ? 0 : 1.5;
      setTimeout(() => b.el.classList.remove("pop"), 500);
      inp.value = "";
      if (bubbles.length > 24) { const old = bubbles.shift(); old.el.remove(); }
    });
  }

  // ------------------------------------------------------------------ confetti
  function confetti() {
    if (reduce) return;
    const c = document.createElement("canvas");
    c.className = "confetti-fx";
    document.body.appendChild(c);
    const ctx = c.getContext("2d");
    const dpr = Math.min(2, devicePixelRatio || 1);
    c.width = innerWidth * dpr; c.height = innerHeight * dpr;
    ctx.scale(dpr, dpr);
    const cols = ["#5b3fd6", "#7c5cff", "#ef4f9a", "#f59e0b", "#22c55e", "#3b82f6", "#14b8a6"];
    const ps = Array.from({ length: 170 }, (_, i) => ({
      x: innerWidth / 2 + (Math.random() - 0.5) * 200, y: innerHeight * 0.35,
      vx: (Math.random() - 0.5) * 14, vy: -Math.random() * 13 - 4, s: 5 + Math.random() * 6,
      r: Math.random() * 6, vr: (Math.random() - 0.5) * 0.3, c: cols[i % cols.length], shape: i % 3,
    }));
    const t0 = performance.now();
    (function tick(t) {
      const el = t - t0;
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      ps.forEach((p) => {
        p.vy += 0.32; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.r += p.vr;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.globalAlpha = Math.max(0, 1 - el / 2800);
        ctx.fillStyle = p.c;
        if (p.shape === 0) ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2);
        else if (p.shape === 1) { ctx.beginPath(); ctx.arc(0, 0, p.s / 2.4, 0, 7); ctx.fill(); }
        else { ctx.font = `${p.s * 2}px serif`; ctx.fillText("✦", 0, 0); }
        ctx.restore();
      });
      if (el < 2900) requestAnimationFrame(tick); else c.remove();
    })(t0);
  }
  let lastHash = location.hash;
  addEventListener("hashchange", () => {
    if (/\/ready$/.test(location.hash) && !/\/ready$/.test(lastHash)) setTimeout(() => safe(confetti), 250);
    lastHash = location.hash;
  });

  // ------------------------------------------------------------------ enhance on every render
  function enhance() {
    const scope = document;
    [reveal, tilt, spotlight, magnetic, stickers, graphs, playground].forEach((f) => safe(() => f(scope)));
  }
  let pending = false;
  const mo = new MutationObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; enhance(); });
  });
  const appEl = document.getElementById("app");
  if (appEl) mo.observe(appEl, { childList: true, subtree: true });
  enhance();
})();
