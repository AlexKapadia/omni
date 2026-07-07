/*
 * Omni landing — scroll-driven reveal motion (progressive enhancement).
 *
 * Contract (see sections.css MOTION CONTRACT):
 *  - Product figures [data-reveal="media"] fade + lift IN as they enter the
 *    viewport and softly fade OUT as they leave — a per-element --p (0..1) that
 *    CSS maps to opacity/translate. This is the "product being used, fading in
 *    and out as you scroll" the brief asks for. Opacity floors at 0.15 in CSS so
 *    content never fully vanishes.
 *  - Copy blocks [data-reveal="copy"] are enter-only: once shown they lock at
 *    full opacity so text never fades while you read it.
 *
 * Guarantees:
 *  - No JS / JS error  -> figures keep their default opacity:1 (nothing hidden).
 *  - prefers-reduced-motion -> we do NOT arm reveals at all; everything is
 *    shown statically (CSS also hard-freezes as a belt-and-braces).
 *  - transform/opacity only, batched in one rAF pass -> 60fps.
 */
(function () {
  'use strict';

  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return; // show end states; do not animate

  var media = [];
  var copy = [];

  function arm() {
    var els = document.querySelectorAll('[data-reveal]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.getAttribute('data-reveal') === 'copy') {
        el.classList.add('reveal-copy');
        copy.push(el);
      } else {
        el.classList.add('reveal');
        media.push(el);
      }
    }
  }

  var ticking = false;
  function update() {
    ticking = false;
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var mid = vh / 2;

    // Figures: symmetric in/out based on how close the element centre is to the
    // viewport centre. Full at centre, tapering toward the edges.
    for (var i = 0; i < media.length; i++) {
      var r = media[i].getBoundingClientRect();
      var c = r.top + r.height / 2;
      var d = Math.abs(c - mid);
      var span = mid + r.height * 0.5; // fully faded once wholly off-screen
      var p = 1 - Math.min(d / (span * 0.92), 1);
      media[i].style.setProperty('--p', p.toFixed(3));
    }

    // Copy: enter-only. Cross ~18% into view -> lock at 1.
    for (var j = copy.length - 1; j >= 0; j--) {
      var rc = copy[j].getBoundingClientRect();
      if (rc.top < vh * 0.85 && rc.bottom > 0) {
        copy[j].style.setProperty('--p', '1');
        copy.splice(j, 1); // done; stop tracking
      }
    }
  }

  function onScroll() {
    if (!ticking) {
      ticking = true;
      window.requestAnimationFrame(update);
    }
  }

  function init() {
    arm();
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
