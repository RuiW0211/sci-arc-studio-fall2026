// Light / dark for the site's pages (user, 2026-10-10). A page opens in the system theme; once the reader switches it
// (the ◐ button) on any page, the other pages follow for the rest of the visit (sessionStorage: a new visit follows
// the system again). Loaded in <head>, before the page is drawn, so there is no flash of the other theme.
(function () {
  var KEY = "angelsknoll-theme";
  var root = document.documentElement;
  try {
    var saved = sessionStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  } catch (e) { /* storage blocked: the system theme */ }
  function isDark() {
    return root.dataset.theme === "dark" || (!root.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  }
  document.addEventListener("DOMContentLoaded", function () {
    var b = document.getElementById("themeToggle");
    if (!b) return;
    b.addEventListener("click", function () {
      var next = isDark() ? "light" : "dark";
      root.dataset.theme = next;
      try { sessionStorage.setItem(KEY, next); } catch (e) { /* this page only */ }
    });
  });
})();
