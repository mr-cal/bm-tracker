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

  /*
   * Opening the drawer has to do two things `:target` cannot.
   *
   * Locking the page: with the panel sliding in from the left, a touch on the
   * scrim scrolled the list *behind* it, and the drawer appeared frozen while
   * the page moved under it.
   *
   * Marking the rest of the page inert: a screen reader tabbing out of the
   * open drawer walked straight back into the content behind, which was
   * invisible behind the scrim. `inert` is the one attribute that removes
   * everything under it from the tab order and the accessibility tree at
   * once, rather than fiddling with tabindex on a dozen elements.
   */
  var lock = null;

  function setLocked(locked) {
    if (lock) lock.remove();
    lock = null;
    if (!locked) return;

    var scrollY = window.scrollY;
    var style = document.body.style;
    style.overflow = "hidden";
    style.position = "fixed";
    style.top = -scrollY + "px";
    style.width = "100%";

    var main = document.querySelector("main");
    var topbar = document.querySelector(".app-topbar");
    var tabs = document.querySelector(".app-tabs");
    [main, topbar, tabs].forEach(function (el) {
      if (el) el.setAttribute("inert", "");
    });

    var unlock = function () {
      style.overflow = "";
      style.position = "";
      style.top = "";
      style.width = "";
      [main, topbar, tabs].forEach(function (el) {
        if (el) el.removeAttribute("inert");
      });
      window.scrollTo(0, scrollY);
    };
    document.addEventListener("bm:unlock", unlock, { once: true });
    lock = { remove: unlock };
  }

  function sync() {
    setLocked(isOpen());
  }

  function close() {
    if (!isOpen()) return;
    document.dispatchEvent(new CustomEvent("bm:unlock"));
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

  // The hash changes whether the drawer was opened, closed by the scrim, or
  // dismissed with the back button.
  window.addEventListener("hashchange", sync);
  window.addEventListener("pageshow", sync);

  // Following a link inside the drawer should close it, or the new page opens
  // with the drawer still covering it.
  document.addEventListener("click", function (event) {
    var link = event.target.closest ? event.target.closest(".app-drawer__panel a") : null;
    if (link && isOpen()) close();
  });
})();
