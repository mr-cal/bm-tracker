/*
 * The calendar and clock buttons.
 *
 * The native `input[type=date]` and `input[type=time]` pickers are the best
 * calendars and clocks on any given device — on a phone they are the OS's own,
 * with the user's locale, their date formats and their accessibility settings
 * already applied. Replacing either with a JavaScript picker would mean
 * reimplementing all of that, worse.
 *
 * Both fields get the same treatment, which they did not have. The date had a
 * drawn button and the time kept the user agent's own indicator, so one icon
 * opened a calendar and the other looked like it should and did not. The
 * asymmetry was ours, not the browser's.
 *
 * What we do replace is the *chrome*. The user agent draws the picker
 * indicator, and it draws it differently per engine, with a font that is not
 * always present — which is how this field ended up showing an empty box. So
 * the native indicator is hidden and this button stands in for it, and the
 * button calls `showPicker()` to open the real one.
 *
 * `showPicker()` needs a user gesture and throws if the picker is already open,
 * so every path is guarded. Where it is unsupported the input still takes focus
 * and the user can type a date, or use the arrow keys.
 */
(function () {
  "use strict";

  function openPicker(input) {
    if (typeof input.showPicker === "function") {
      try {
        input.showPicker();
        return;
      } catch (error) {
        // Throws without a user gesture, or when already open. Fall through.
      }
    }
    input.focus();
  }

  function wire(button) {
    var id = button.getAttribute("aria-controls");
    var input = id ? document.getElementById(id) : null;
    if (!input) return;

    button.addEventListener("click", function () {
      openPicker(input);
    });

    // The button is a control over a text field; keyboard users expect the
    // field itself to respond too, and the button to be reachable by Tab.
    input.addEventListener("keydown", function (event) {
      // Alt+Down is the convention for "open the calendar" in a date field.
      if (event.altKey && event.key === "ArrowDown") {
        event.preventDefault();
        openPicker(input);
      }
    });
  }

  function init() {
    var buttons = document.querySelectorAll("[data-picker-toggle]");
    for (var i = 0; i < buttons.length; i++) {
      wire(buttons[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
