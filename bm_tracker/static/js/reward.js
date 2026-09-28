/*
 * The reward screen, one line at a time.
 *
 * The order is the point: the rules you triggered, then the total, then the
 * line about you. A total shown first is a number that means nothing yet, and
 * the whole reason for this screen rather than the one-line banner it replaced
 * is that the sequence teaches something.
 *
 * Written as: hide everything, then reveal on a timer. The markup is the
 * finished state, so with this blocked the screen still shows all of it — it
 * just arrives at once rather than in order, which is a far better failure
 * than an empty panel.
 */
(function () {
  "use strict";

  var LINE_MS = 380;
  var GAP_MS = 140;

  function play(panel) {
    var lines = Array.prototype.slice.call(
      panel.querySelectorAll(".reward__line")
    );
    var total = panel.querySelector(".reward__total");
    var said = panel.querySelector(".reward__said");
    var unlocked = panel.querySelector(".reward__unlocked");
    var dismiss = panel.querySelector(".reward__dismiss");

    var everything = lines.concat([total, said, unlocked, dismiss].filter(Boolean));
    everything.forEach(function (el) {
      el.classList.add("reward__pending");
    });

    var delay = 0;
    lines.forEach(function (line) {
      window.setTimeout(function () {
        line.classList.remove("reward__pending");
        line.classList.add("reward__arrive");
      }, delay);
      delay += LINE_MS;
    });

    // The total lands a beat after the last line, on its own.
    delay += GAP_MS;
    if (total) {
      window.setTimeout(function () {
        total.classList.remove("reward__pending");
        total.classList.add("reward__arrive", "reward__arrive--total");
      }, delay);
      delay += 420;
    }
    if (said) {
      window.setTimeout(function () {
        said.classList.remove("reward__pending");
        said.classList.add("reward__arrive");
      }, delay);
      delay += 300;
    }
    if (unlocked) {
      window.setTimeout(function () {
        unlocked.classList.remove("reward__pending");
        unlocked.classList.add("reward__arrive");
      }, delay);
      delay += 260;
    }
    if (dismiss) {
      window.setTimeout(function () {
        dismiss.classList.remove("reward__pending");
        dismiss.classList.add("reward__arrive");
      }, delay);
    }
  }

  function init() {
    var panels = document.querySelectorAll("[data-reward] .reward__panel");
    for (var i = 0; i < panels.length; i++) {
      play(panels[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
