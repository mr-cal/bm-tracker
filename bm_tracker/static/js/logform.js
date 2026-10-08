/*
 * The log form.
 *
 * "Nothing today" and the seven Bristol types are one question, and the per-BM
 * fields — spicy, urgent, effort, time — do not apply to a day with no bowel
 * movements in it. Choosing "Nothing today" greys them out.
 *
 * Greying is done with `disabled` on the fieldset rather than a class, because
 * `disabled` is the honest statement: those controls genuinely do not apply,
 * so they should not be submitted and should not be reachable by Tab.
 *
 * This is a convenience, not the rule. The server ignores the per-BM fields
 * when the choice is "nothing", so the form is correct with this script
 * blocked, and a stale tab that posts spicy food alongside an empty day records
 * an empty day.
 *
 * A tab left open overnight is the same story with a worse ending: the
 * date and time were pre-filled when the page rendered, so the morning's
 * BM is posted with last night's values, and the server cannot tell that
 * from a deliberate backfill — backfilling any past day is a feature. So
 * when the tab comes back after more than ten minutes away, the fields the
 * reader has not touched are re-stamped with the current wall clock in the
 * account's own timezone. Touched fields are never second-guessed, and the
 * field being edited is left alone. A tab that stayed visible the whole
 * time is the one case no client event covers.
 *
 * The submit button is disabled as the form goes out, with a
 * spinner, because a second press would start the same POST
 * again and the server cannot tell the two apart. Every outcome
 * replaces the page, so the button is never left disabled.
 */
(function () {
  "use strict";

  // Ten minutes, then a returning tab is assumed stale rather than
  // paused mid-decision. Below it, the pre-filled clock is still close
  // enough to now to leave alone.
  var STALE_AFTER_MS = 10 * 60 * 1000;

  // When the script ran, a few milliseconds after the server rendered
  // the pre-filled values.
  var renderedAt = Date.now();

  function sync(form) {
    var nothing = form.querySelector('input[name="choice"][value="nothing"]:checked');
    var bm = form.querySelector('input[name="choice"][value^="bm:"]:checked');
    var sections = form.querySelectorAll("[data-bm-only]");

    for (var i = 0; i < sections.length; i++) {
      sections[i].disabled = !!nothing;
    }

    // The time field is required, so a day logged as empty must not be blocked
    // by an empty time input that can never be filled in.
    var time = form.querySelector('input[type="time"]');
    if (time) time.required = !nothing;

    var submit = form.querySelector(".log-form__submit");
    if (submit) {
      submit.textContent = nothing ? "Log an empty day" : "Log it";
    }

    // Nothing chosen yet: the per-BM fields stay enabled, since the default
    // first card is a Bristol type and the form is not in a valid state until
    // something is tapped. Disabling them here would grey out the whole form on
    // arrival, which reads as broken.
    form.dataset.choice = nothing ? "nothing" : bm ? "bm" : "unanswered";
  }

  // One press, one log. A second press while the first is still
  // in flight would start the same POST again, and the server
  // cannot tell the two apart — there is no id to dedupe on.
  // Disabling on submit is safe because every outcome replaces
  // the page: a success redirects, and a rejection re-renders
  // the form, so a fresh render always brings a fresh button.
  function guard(form) {
    var submit = form.querySelector(".log-form__submit");
    if (submit) {
      submit.disabled = true;
      var spinner = document.createElement("span");
      spinner.className = "spinner-border spinner-border-sm";
      spinner.setAttribute("role", "status");
      spinner.setAttribute("aria-hidden", "true");
      submit.textContent = " Logging…";
      submit.prepend(spinner);
    }
    form.setAttribute("aria-busy", "true");
  }

  // The account's zone, not the browser's: a Chicago account on a
  // London-set browser still stamps a Chicago day. formatToParts with an
  // explicit timeZone keeps the values independent of the reader's locale.
  function wallClock(zone) {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23"
    }).formatToParts(new Date());
    var value = {};
    for (var i = 0; i < parts.length; i++) {
      value[parts[i].type] = parts[i].value;
    }
    return {
      date: value.year + "-" + value.month + "-" + value.day,
      time: value.hour + ":" + value.minute
    };
  }

  function setIfUntouched(form, selector, value, touched) {
    var field = form.querySelector(selector);
    // A touched field is a decision the reader made, and the one
    // being edited is not yours to rewrite under the cursor.
    if (!field || touched.has(field) || document.activeElement === field) {
      return;
    }
    field.value = value;
  }

  function restampIfStale(form, touched) {
    if (Date.now() - renderedAt < STALE_AFTER_MS) {
      return;
    }
    var zone = form.getAttribute("data-timezone");
    if (!zone) {
      return;
    }
    var now = wallClock(zone);
    setIfUntouched(form, 'input[type="date"]', now.date, touched);
    setIfUntouched(form, 'input[type="time"]', now.time, touched);
  }

  function markTouched(form, touched) {
    var fields = [
      form.querySelector('input[type="date"]'),
      form.querySelector('input[type="time"]')
    ];
    for (var i = 0; i < fields.length; i++) {
      if (!fields[i]) {
        continue;
      }
      fields[i].addEventListener("input", function (event) {
        touched.add(event.currentTarget);
      });
      fields[i].addEventListener("change", function (event) {
        touched.add(event.currentTarget);
      });
    }
  }

  function init() {
    var forms = document.querySelectorAll("[data-log-form]");
    var watched = [];
    for (var i = 0; i < forms.length; i++) {
      var touched = new Set();
      sync(forms[i]);
      forms[i].addEventListener("change", function (event) {
        sync(event.currentTarget);
      });
      forms[i].addEventListener("submit", function (event) {
        guard(event.currentTarget);
      });
      markTouched(forms[i], touched);
      watched.push({ form: forms[i], touched: touched });
    }
    // The tab coming back is the one reliable sign that a form left
    // open overnight has gone stale. Timers are throttled in hidden
    // tabs, so a timeout alone would fire late.
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState !== "visible") {
        return;
      }
      for (var i = 0; i < watched.length; i++) {
        restampIfStale(watched[i].form, watched[i].touched);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
