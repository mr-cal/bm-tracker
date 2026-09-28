/*
 * Keep a badge's tooltip inside the window.
 *
 * The tooltip is centred on its badge with a CSS transform, which is right in
 * the middle of a row and wrong at either edge: a badge near the left or right
 * margin pushes its tooltip off screen. CSS alone cannot know where the badge
 * ended up, so measure it once the tooltip is shown and pull it back in.
 *
 * Runs on hover and on focus, because a tooltip that only appears for a mouse
 * is not a tooltip, it is a decoration.
 */
(function () {
  "use strict";

  var MARGIN = 8;

  function place(icon) {
    var tip = icon.querySelector(".badge-icon__tip");
    if (!tip) return;

    // Measure at the natural centred position first, then correct.
    tip.style.left = "50%";
    tip.style.transform = "translateX(-50%)";

    var iconBox = icon.getBoundingClientRect();
    var tipBox = tip.getBoundingClientRect();

    var shift = 0;
    if (tipBox.left < MARGIN) {
      shift = MARGIN - tipBox.left;
    } else if (tipBox.right > window.innerWidth - MARGIN) {
      shift = window.innerWidth - MARGIN - tipBox.right;
    }

    // Below the margin there is no sideways room left, so open it downwards
    // rather than shoving it back on top of the badge.
    if (tipBox.width + Math.abs(shift) > window.innerWidth - 2 * MARGIN) {
      tip.style.left = MARGIN + "px";
      tip.style.right = MARGIN + "px";
      tip.style.transform = "none";
      tip.style.maxWidth = "none";
      return;
    }

    if (shift !== 0) {
      tip.style.transform =
        "translateX(calc(-50% + " + shift + "px))";
    }
  }

  function wire(icon) {
    var show = function () {
      place(icon);
    };
    icon.addEventListener("pointerenter", show);
    icon.addEventListener("focus", show);
  }

  function init() {
    var icons = document.querySelectorAll(".badge-icon");
    for (var i = 0; i < icons.length; i++) {
      wire(icons[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
