/* Theme switcher. Loaded in <head> so the saved theme applies before first paint (no flash).
   Purely visual: it only sets <html data-theme> and remembers the choice in this browser. */
(function () {
  "use strict";
  var KEY = "cc_theme";
  var DEFAULT = "sunset";
  var THEMES = [
    { id: "sunset", name: "Sunset Pop", note: "Bold, bright, high energy", sw: ["#FF5A1F", "#E11D74", "#FFC93C"], meta: "#FFF4E8" },
    { id: "editorial", name: "Warm Editorial", note: "Cream, coral and serif", sw: ["#F36D55", "#7467E8", "#F7F3EC"], meta: "#F7F3EC" },
    { id: "classic", name: "Classic", note: "The original lavender look", sw: ["#5b3fd6", "#ef4f9a", "#f1edfd"], meta: "#f1edfd" }
  ];
  function find(id) { for (var i = 0; i < THEMES.length; i++) if (THEMES[i].id === id) return THEMES[i]; return null; }
  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function apply(id) {
    var t = find(id) || find(DEFAULT);
    document.documentElement.setAttribute("data-theme", t.id);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute("content", t.meta);
    var menu = document.getElementById("themeMenu");
    if (menu) menu.querySelectorAll("[data-theme-id]").forEach(function (b) {
      b.setAttribute("aria-checked", b.getAttribute("data-theme-id") === t.id ? "true" : "false");
    });
    return t.id;
  }
  apply(saved());

  function set(id) {
    var applied = apply(id);
    try { localStorage.setItem(KEY, applied); } catch (e) { /* private mode: theme still applies for this visit */ }
  }
  window.ccTheme = { set: set, list: THEMES.map(function (t) { return t.id; }) };

  function mount() {
    var nav = document.querySelector(".topnav");
    if (!nav || document.getElementById("themeBtn")) return;
    var wrap = document.createElement("div");
    wrap.className = "th-wrap";
    var cur = document.documentElement.getAttribute("data-theme");
    wrap.innerHTML =
      '<button type="button" class="th-btn" id="themeBtn" aria-haspopup="true" aria-expanded="false" aria-controls="themeMenu" title="Change theme">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 0 18c1 0 1.6-.8 1.6-1.6 0-.5-.2-.8-.5-1.2-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4-4-7.5-9-7.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>' +
      '<circle cx="7.5" cy="11" r="1.4" fill="currentColor"/><circle cx="10.5" cy="7" r="1.4" fill="currentColor"/><circle cx="15" cy="7.5" r="1.4" fill="currentColor"/></svg>' +
      '<span class="th-lbl">Theme</span></button>' +
      '<div class="th-menu" id="themeMenu" role="menu" hidden><p class="th-h">Choose a look</p>' +
      THEMES.map(function (t) {
        return '<button type="button" role="menuitemradio" data-theme-id="' + t.id + '" aria-checked="' + (t.id === cur) + '">' +
          '<span class="th-sw">' + t.sw.map(function (c) { return '<i style="background:' + c + '"></i>'; }).join("") + "</span>" +
          '<span class="th-t"><b>' + t.name + "</b><small>" + t.note + "</small></span>" +
          '<span class="th-ok" aria-hidden="true">✓</span></button>';
      }).join("") + "</div>";
    nav.appendChild(wrap);
    var btn = wrap.querySelector("#themeBtn"), menu = wrap.querySelector("#themeMenu");
    function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (open) { var on = menu.querySelector('[aria-checked="true"]'); if (on) on.focus(); }
    });
    menu.addEventListener("click", function (e) {
      var b = e.target.closest("[data-theme-id]");
      if (!b) return;
      set(b.getAttribute("data-theme-id"));
      close(); btn.focus();
    });
    document.addEventListener("click", function (e) { if (!wrap.contains(e.target)) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !menu.hidden) { close(); btn.focus(); } });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
