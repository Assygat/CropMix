/* Small UI behaviours for the hero prototype: mobile menu, button light, scroll reveal. */
(function () {
  "use strict";
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });
    links.addEventListener("click", function (e) {
      if (e.target.closest("a")) { links.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); toggle.setAttribute("aria-label", "Open menu"); }
    });
  }

  // cursor-following light on buttons and research cards
  document.querySelectorAll(".btn, .layer").forEach(function (b) {
    b.addEventListener("pointermove", function (e) {
      var r = b.getBoundingClientRect();
      b.style.setProperty("--mx", (e.clientX - r.left) + "px");
      b.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  // reveal research layers on scroll
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var items = document.querySelectorAll(".layer, .principles, .research-head");
  if (!reduce && "IntersectionObserver" in window) {
    items.forEach(function (el, i) {
      el.style.opacity = "0"; el.style.transform = "translateY(24px)";
      el.style.transition = "opacity .9s cubic-bezier(.16,1,.3,1) " + (i % 3) * 0.08 + "s, transform .9s cubic-bezier(.16,1,.3,1) " + (i % 3) * 0.08 + "s";
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        el.style.opacity = "1"; el.style.transform = "none";
        io.unobserve(el);
        // Once revealed, hand control back to the stylesheet so hover/focus transitions
        // (border colour, glow, background, lift) are not overridden by the inline reveal.
        setTimeout(function () { el.style.transition = ""; el.style.transform = ""; el.style.opacity = ""; }, 1300);
      });
    }, { threshold: 0.15 });
    items.forEach(function (el) { io.observe(el); });
  }
})();
