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
 * The submit button is disabled as the form goes out, with a
 * spinner, because a second press would start the same POST
 * again and the server cannot tell the two apart. Every outcome
 * replaces the page, so the button is never left disabled.
 */
(function () {
  "use strict";

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

  function init() {
    var forms = document.querySelectorAll("[data-log-form]");
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      sync(form);
      form.addEventListener("change", function (event) {
        sync(event.currentTarget);
      });
      form.addEventListener("submit", function () {
        guard(form);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
