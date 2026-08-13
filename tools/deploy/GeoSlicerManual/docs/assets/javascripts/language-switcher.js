/*
 * Page-to-page language switching for the multi-language GeoSlicer Manual.
 *
 * Each language is now built as an independent site under /en/ and /pt/ (there is
 * no mkdocs-static-i18n plugin to map a page to its translation anymore). Because
 * both languages share the exact same path structure, we can rewrite the language
 * switcher links at runtime so that switching language keeps you on the SAME page
 * instead of dropping you on the language home.
 *
 * It works for any deployment depth (root, GitHub Pages sub-path, or a mike
 * versioned path such as /GeoSlicerManual/2.8/en/...): we only swap the /en/ or
 * /pt/ path segment and leave everything else untouched.
 */
(function () {
  var LANG_SEGMENT = /\/(en|pt)\//;

  function currentLanguage(pathname) {
    var match = pathname.match(LANG_SEGMENT);
    return match ? match[1] : null;
  }

  function swapLanguage(pathname, targetLang) {
    return pathname.replace(LANG_SEGMENT, "/" + targetLang + "/");
  }

  function updateSwitcherLinks() {
    var pathname = window.location.pathname;
    if (!currentLanguage(pathname)) {
      // Outside a language folder (e.g. the root redirect page): nothing to do.
      return;
    }

    var links = document.querySelectorAll("a[hreflang]");
    Array.prototype.forEach.call(links, function (link) {
      var lang = link.getAttribute("hreflang");
      if (lang !== "en" && lang !== "pt") {
        return;
      }
      link.setAttribute("href", swapLanguage(pathname, lang) + window.location.hash);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", updateSwitcherLinks);
  } else {
    updateSwitcherLinks();
  }
})();
