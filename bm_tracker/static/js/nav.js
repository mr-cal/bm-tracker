/*
 * The navigation drawer.
 *
 * Open and close are pure CSS (`:target` on `#nav`), so the drawer works with no
 * JavaScript at all. This adds the two things CSS cannot do: Escape to close,
 * and returning focus to the button that opened it — which matters because a
 * dialog that steals focus and never gives it back strands a keyboard user at
 * the top of the document.
 */
(function () {
  "use strict";

  function isOpen() {
    return window.location.hash === "#nav";
  }

  function close() {
    if (!isOpen()) return;
    // Replace rather than push, so Back does not reopen the drawer.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    } else {
      window.location.hash = "";
    }
    var toggle = document.querySelector("[data-nav-toggle]");
    if (toggle) toggle.focus();
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });

  // Following a link inside the drawer should close it, or the new page opens
  // with the drawer still covering it.
  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest(".app-drawer__panel a") : null;
    if (link && isOpen()) close();
  });
})();
