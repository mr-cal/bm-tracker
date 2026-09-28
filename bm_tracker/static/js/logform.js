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

  function init() {
    var forms = document.querySelectorAll("[data-log-form]");
    for (var i = 0; i < forms.length; i++) {
      var form = forms[i];
      sync(form);
      form.addEventListener("change", function (event) {
        sync(event.currentTarget);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
