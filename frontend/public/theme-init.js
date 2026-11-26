/* Initial theme resolution loaded from a same-origin file so strict CSP
 * (`script-src 'self'`) executes it synchronously before the first paint. */
(function () {
  try {
    var root = document.documentElement;
    var desktopPref = null;
    var queryPref = null;

    try {
      var params = new URLSearchParams(window.location.search);
      queryPref = params.get("desktopTheme");
    } catch (_e) {
      queryPref = null;
    }

    if (window.api) {
      try {
        desktopPref = localStorage.getItem("xakumedia_desktop_theme");
      } catch (_e) {
        desktopPref = null;
      }
      if (!desktopPref && (queryPref === "light" || queryPref === "dark" || queryPref === "system")) {
        desktopPref = queryPref;
      }
    }

    var saved = null;
    try {
      saved = localStorage.getItem("xakumedia_theme");
    } catch (_e) {
      saved = null;
    }

    var dark;
    if (desktopPref === "light" || desktopPref === "dark") {
      dark = desktopPref === "dark";
    } else if (desktopPref === "system") {
      dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    } else if (saved === "light" || saved === "dark") {
      dark = saved === "dark";
    } else if (window.api) {
      dark = true;
    } else {
      dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    }

    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
    root.dataset.theme = dark ? "dark" : "light";

    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", dark ? "#0b0c10" : "#f4f5f7");
    }
  } catch (_e) {
    document.documentElement.classList.add("dark");
  }
})();
