/*
 * The quick-entry countdown.
 *
 * The app's entire scoring design is pushing you to log at the moment it
 * happens: a streak for turning up every day, and a bonus for an entry written
 * within ten minutes of the event. Neither the size of that bonus nor the size
 * of that window appeared anywhere on the form. The time field quietly
 * defaulted to now and you filled in the rest in silence, with no way of knowing
 * the window was closing — which is a bad way to treat the behaviour the whole
 * thing is trying to encourage.
 *
 * The window comes from the `data-quick-window` attribute, which the server
 * fills from the same setting the scorer reads, so the countdown and the score
 * cannot drift apart. The deadline is when the page was served, not when this
 * script ran, so a slow script does not hand out free seconds.
 *
 * "Quick" is measured as an absolute difference, matching `scoring.is_quick`: a
 * user who types 07:00 and submits at 06:57 was close enough.
 */
(function () {
  "use strict";

  var MINUTE = 60;

  function say(el, text, state) {
    if (el.textContent !== text) el.textContent = text;
    if (el.dataset.quickState !== state) el.dataset.quickState = state;
  }

  function update(input, out) {
    var windowMinutes = parseInt(input.getAttribute("data-quick-window"), 10);
    var at = input.getAttribute("data-quick-at");
    if (!windowMinutes || !at) {
      out.hidden = true;
      return;
    }
    var deadline = new Date(at).getTime() + windowMinutes * MINUTE * 1000;
    if (isNaN(deadline)) {
      out.hidden = true;
      return;
    }

    var left = deadline - Date.now();
    if (left <= 0) {
      say(out, "Quick entry bonus expired.", "expired");
      return;
    }

    var minutes = Math.floor(left / (MINUTE * 1000));
    var seconds = Math.floor((left % (MINUTE * 1000)) / 1000);
    if (minutes >= 1) {
      say(out, "Quick entry bonus — " + minutes + "m " + seconds + "s left", "open");
    } else {
      say(out, "Quick entry bonus — " + seconds + "s left", "soon");
    }
  }

  function init() {
    var inputs = document.querySelectorAll("input[data-quick-window]");
    for (var i = 0; i < inputs.length; i++) {
      (function (input) {
        var out = document.querySelector("[data-quick-state]");
        if (!out) return;
        out.hidden = false;
        update(input, out);
        // Once a second is enough: the message only shows whole minutes until
        // the last one, and a tighter timer on a phone costs battery for
        // nothing.
        setInterval(function () { update(input, out); }, 1000);
      })(inputs[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
