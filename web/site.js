/* CropMix Twin — shared site behaviour (all public pages).
 * Based on design-preview/main.js: mobile menu, cursor-following light, scroll reveals.
 * Adds: Esc / outside click closes the menu; the intro splash on the home page.
 * Everything is progressive: without this script every page is fully visible and usable. */
(function () {
  "use strict";
  var doc = document.documentElement;
  doc.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- mobile menu ----------
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  function setMenu(open, returnFocus) {
    if (!toggle || !links) return;
    links.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    if (!open && returnFocus) toggle.focus();
  }
  if (toggle && links) {
    toggle.addEventListener("click", function () { setMenu(!links.classList.contains("open")); });
    links.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && links.classList.contains("open")) setMenu(false, true);
    });
    document.addEventListener("click", function (e) {
      if (links.classList.contains("open") && !e.target.closest(".nav")) setMenu(false);
    });
  }

  // ---------- cursor-following light on buttons and cards ----------
  // (only content-page cards; the simulator's .card panels are a different component)
  document.querySelectorAll(".btn, .cards > .card").forEach(function (el) {
    el.addEventListener("pointermove", function (e) {
      var r = el.getBoundingClientRect();
      el.style.setProperty("--mx", (e.clientX - r.left) + "px");
      el.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  // ---------- scroll reveals ----------
  var items = document.querySelectorAll("[data-reveal]");
  if (reduce || !("IntersectionObserver" in window)) {
    items.forEach(function (el) { el.classList.add("is-visible"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        en.target.classList.add("is-visible");
        io.unobserve(en.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    items.forEach(function (el) { io.observe(el); });
  }

  // ---------- table of contents: mark the section currently being read ----------
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a[href^='#']"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    tocLinks.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var visible = {};
    var mark = function () {
      var current = null;
      tocLinks.forEach(function (a) { var id = a.getAttribute("href").slice(1); if (!current && visible[id]) current = a; });
      if (!current) return;
      tocLinks.forEach(function (a) { if (a === current) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current"); });
    };
    var tocIo = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
      mark();
    }, { rootMargin: "-20% 0px -60% 0px" });
    Object.keys(byId).forEach(function (id) { var s = document.getElementById(id); if (s) tocIo.observe(s); });
  }

  // ---------- intro splash (home only) ----------
  // The page head decides whether the intro plays (first visit in this tab session, motion allowed)
  // and sets html.intro-pending, which covers the hero until the splash takes over.
  if (!doc.classList.contains("intro-pending")) return;
  try { sessionStorage.setItem("cmx-intro-seen", "1"); } catch (e) { /* storage blocked: intro may replay */ }

  var splash = document.createElement("div");
  splash.className = "splash";
  splash.innerHTML =
    '<div class="splash-inner" aria-hidden="true">' +
      '<svg class="splash-drop" viewBox="0 0 60 84">' +
        '<defs>' +
          '<clipPath id="splashClip"><path d="M30 3C42 22 56 37 56 54a26 26 0 0 1-52 0C4 37 18 22 30 3Z"/></clipPath>' +
          '<linearGradient id="splashFill" x1="0" y1="0" x2="0" y2="1">' +
            '<stop offset="0" stop-color="#007DFF"/><stop offset=".55" stop-color="#063BCE"/><stop offset="1" stop-color="#001AA4"/>' +
          '</linearGradient>' +
        '</defs>' +
        '<g clip-path="url(#splashClip)"><g class="splash-fill">' +
          '<g class="wave"><path d="M-60 30c10-5 20-5 30 0s20 5 30 0 20-5 30 0 20 5 30 0 20-5 30 0 20 5 30 0V90h-180Z" fill="url(#splashFill)"/></g>' +
          '<g class="wave wave-2"><path d="M-60 34c10-4 20-4 30 0s20 4 30 0 20-4 30 0 20 4 30 0 20-4 30 0 20 4 30 0V90h-180Z" fill="#36B9D6" opacity=".35"/></g>' +
        '</g></g>' +
        '<path class="splash-outline" d="M30 3C42 22 56 37 56 54a26 26 0 0 1-52 0C4 37 18 22 30 3Z"/>' +
      '</svg>' +
      '<p class="splash-word">CropMix<em>Twin</em></p>' +
      '<p class="splash-tag">Every drop matters</p>' +
    '</div>' +
    '<button type="button" class="splash-skip">Skip intro</button>';
  document.body.appendChild(splash);

  var done = false, timer;
  function finish() {
    if (done) return;
    done = true;
    clearTimeout(timer);
    document.removeEventListener("keydown", onKey);
    doc.classList.remove("intro-pending");   // hero entrance animations start now
    splash.classList.add("is-leaving");
    setTimeout(function () { if (splash.parentNode) splash.parentNode.removeChild(splash); }, 1100);
  }
  function onKey(e) { if (e.key === "Escape") finish(); }
  splash.addEventListener("click", finish);
  document.addEventListener("keydown", onKey);
  timer = setTimeout(finish, 1750);
})();
