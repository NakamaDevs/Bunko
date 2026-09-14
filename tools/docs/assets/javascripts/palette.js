/* SDLC documentation command palette.
 *
 * The theme already binds Cmd/Ctrl+K to full-text search and Cmd/Ctrl+J to the
 * dark-mode toggle, so this palette takes the editor bindings instead:
 *
 *   Cmd/Ctrl+P        jump to a page or a heading
 *   Cmd/Ctrl+Shift+P  run an action
 *   >                 switch to actions from inside the palette
 *
 * Cmd+P normally prints. "Print this page" is offered as an action so nothing
 * is lost. The jump index is fetched once, on first open.
 */

(function () {
  "use strict";

  var ROOT = new URL("../", document.currentScript.src).href;
  var INDEX_URL = ROOT + "assets/palette-index.json";
  var RECENT_KEY = "sdlc-palette-recent";
  var PINS_KEY = "sdlc-palette-pins";
  var LIMIT = 60;
  var PAGE = 0;

  var data = null;      // resolved index payload
  var loading = null;   // in-flight fetch
  var mode = "go";      // "go" or "do"
  var items = [];       // rendered rows
  var active = 0;
  var root, input, list, hint;

  /* ---------- storage ---------- */

  function read(key) {
    try {
      var raw = localStorage.getItem(key);
      var value = raw ? JSON.parse(raw) : [];
      return Array.isArray(value) ? value : [];
    } catch (error) {
      return [];
    }
  }

  function write(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value.slice(0, 40)));
    } catch (error) {
      /* Private windows and blocked site data are not an error here. */
    }
  }

  function currentPage() {
    var title = (document.title || "").split(" - ")[0].trim();
    var url = location.pathname.replace(new URL(ROOT).pathname, "");
    return { t: title, u: url + location.hash };
  }

  function remember() {
    var page = currentPage();
    if (!page.t) return;
    var recent = read(RECENT_KEY).filter(function (entry) { return entry.u !== page.u; });
    recent.unshift(page);
    write(RECENT_KEY, recent.slice(0, 12));
  }

  function pinned() { return read(PINS_KEY); }

  function togglePin() {
    var page = currentPage();
    var pins = pinned();
    var kept = pins.filter(function (entry) { return entry.u !== page.u; });
    write(PINS_KEY, kept.length === pins.length ? [page].concat(pins) : kept);
  }

  function isPinned() {
    var here = currentPage().u;
    return pinned().some(function (entry) { return entry.u === here; });
  }

  /* ---------- fuzzy match ---------- */

  /* Subsequence match, scoring word starts and runs so "reno" finds Release notes. */
  function score(text, query) {
    var haystack = text.toLowerCase();
    var index = 0;
    var total = 0;
    var run = 0;
    for (var i = 0; i < query.length; i++) {
      var found = haystack.indexOf(query[i], index);
      if (found < 0) return -1;
      var boundary = found === 0 || /[\s\-_/›.]/.test(haystack[found - 1]);
      run = found === index ? run + 1 : 0;
      total += (boundary ? 12 : 2) + run * 4 - Math.min(found - index, 12);
      index = found + 1;
    }
    return total - haystack.length * 0.05;
  }

  function highlight(text, query) {
    var fragment = document.createDocumentFragment();
    if (!query) { fragment.appendChild(document.createTextNode(text)); return fragment; }
    var haystack = text.toLowerCase();
    var index = 0;
    var plain = "";
    for (var i = 0; i < query.length; i++) {
      var found = haystack.indexOf(query[i], index);
      if (found < 0) break;
      plain += text.slice(index, found);
      if (plain) { fragment.appendChild(document.createTextNode(plain)); plain = ""; }
      var mark = document.createElement("b");
      mark.textContent = text[found];
      fragment.appendChild(mark);
      index = found + 1;
    }
    fragment.appendChild(document.createTextNode(text.slice(index)));
    return fragment;
  }

  /* ---------- actions ---------- */

  /* The theme leaves every radio unchecked while it follows the media query, so
   * the reliable toggle is the one visible label, the same control a reader
   * clicks in the header. */
  function themeToggle() {
    var labels = document.querySelectorAll('label[for^="__palette_"]');
    for (var i = 0; i < labels.length; i++) {
      if (getComputedStyle(labels[i]).display !== "none") { labels[i].click(); return; }
    }
    var current = document.body.getAttribute("data-md-color-scheme");
    var inputs = document.querySelectorAll('input[name="__palette"]');
    for (var j = 0; j < inputs.length; j++) {
      if (inputs[j].getAttribute("data-md-color-scheme") !== current) {
        inputs[j].click();
        return;
      }
    }
  }

  /* The Markdown path is carried on page entries; a URL alone cannot recover it. */
  function sourcePath() {
    if (!data || !data.entries) return null;
    var here = location.pathname
      .replace(new URL(ROOT).pathname, "")
      .replace(/[#?].*$/, "");
    for (var i = 0; i < data.entries.length; i++) {
      var entry = data.entries[i];
      if (entry[0] === PAGE && entry[2] === here && entry[4]) return entry[4];
    }
    return null;
  }

  function sourceUrl() {
    var source = data && data.sources && data.sources[sourcePath()];
    return source && source.url || null;
  }

  /* The review tool shares the gateway with the documentation; served any other
   * way it is a separate loopback port. */
  function reviewBase() {
    return location.origin.replace(/\/\/docs\./, "//review.");
  }

  /* Open a documentation page's own Markdown in the review tool. */
  function reviewUrl(options) {
    var path = sourcePath();
    if (!path) return null;
    var url = new URL(reviewBase() + "/");
    var source = data.sources[path];
    if (!source) return null;
    url.searchParams.set("repo", source.repository);
    url.searchParams.set("path", source.path);
    if (options && options.edit) url.searchParams.set("edit", "1");
    if (options && options.match) url.searchParams.set("match", options.match.slice(0, 120));
    return url.href;
  }

  /* A selection tells the review tool which part of the page to open at. */
  function selectedText() {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed) return "";
    return selection.toString().trim().split("\n")[0];
  }

  function actions() {
    var list = [
      { title: "Toggle light and dark theme", note: "Theme", run: themeToggle },
      { title: "Print this page", note: "View", run: function () { window.print(); } },
      {
        title: isPinned() ? "Unpin this page" : "Pin this page",
        note: "Palette",
        run: togglePin
      },
      {
        title: "Copy link to this page",
        note: "Share",
        run: function () { navigator.clipboard && navigator.clipboard.writeText(location.href); }
      },
      { title: "Open full-text search", note: "View", run: function () { openSearch(); } }
    ];

    var source = sourceUrl();
    if (source) {
      list.push({ title: "Open this page on GitHub", note: "Source", href: source });
    }
    var quote = selectedText();
    var review = reviewUrl({ edit: true, match: quote });
    if (review) {
      list.push({
        title: quote
          ? "Edit this section in the review tool"
          : "Edit this page in the review tool",
        note: "Review",
        href: review
      });
    }
    (data && data.repositories || []).forEach(function (entry) {
      list.push({ title: "Repository: " + entry[0], note: "Source", href: entry[1] });
    });
    (data && data.applications || []).forEach(function (entry) {
      list.push({ title: "Local app: " + entry[0], note: "Aspire", href: entry[1] });
    });
    return list;
  }

  function openSearch() {
    var toggle = document.querySelector('[data-md-toggle="search"]');
    if (toggle) { toggle.checked = true; }
    var field = document.querySelector(".md-search__input");
    if (field) { setTimeout(function () { field.focus(); }, 20); }
  }

  /* ---------- results ---------- */

  function linearMatch(query) {
    var match = /\b([a-z]{2,5})-(\d{1,6})\b/i.exec(query);
    if (!match || !data || !data.linear) return null;
    var key = match[1].toUpperCase() + "-" + match[2];
    return {
      title: "Open Linear " + key,
      note: "Linear",
      href: "https://linear.app/" + data.linear + "/issue/" + key
    };
  }

  function results(query) {
    if (mode === "do") {
      var candidates = actions();
      var extra = linearMatch(query);
      if (extra) candidates.unshift(extra);
      if (!query) return candidates.slice(0, LIMIT);
      return rank(candidates, query, function (item) { return item.title + " " + item.note; });
    }

    if (!query) {
      var recents = read(RECENT_KEY).map(function (entry) {
        return { title: entry.t, note: "Recent", href: ROOT + entry.u };
      });
      var pins = pinned().map(function (entry) {
        return { title: entry.t, note: "Pinned", href: ROOT + entry.u };
      });
      return pins.concat(recents).slice(0, LIMIT);
    }

    if (!data) return [];
    var rows = data.entries.map(function (entry) {
      return {
        title: entry[1],
        note: entry[3] || (entry[0] === PAGE ? "Page" : "Section"),
        href: ROOT + entry[2],
        section: entry[0] !== PAGE
      };
    });
    var found = rank(rows, query, function (item) { return item.title; });
    var issue = linearMatch(query);
    if (issue) found.unshift(issue);
    return found;
  }

  function rank(rows, query, key) {
    var needle = query.toLowerCase().replace(/\s+/g, "");
    var scored = [];
    for (var i = 0; i < rows.length; i++) {
      var value = score(key(rows[i]), needle);
      if (value >= 0) scored.push({ item: rows[i], value: value });
    }
    scored.sort(function (a, b) { return b.value - a.value; });
    return scored.slice(0, LIMIT).map(function (entry) { return entry.item; });
  }

  /* ---------- rendering ---------- */

  function render() {
    var query = input.value.replace(/^>\s*/, "").trim();
    items = results(query);
    active = 0;
    list.textContent = "";

    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "bd-palette__empty";
      empty.textContent = data || mode === "do" ? "No matches." : "Loading index…";
      list.appendChild(empty);
      return;
    }

    items.forEach(function (item, index) {
      var row = document.createElement("li");
      row.className = "bd-palette__item" + (index === 0 ? " is-active" : "");
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", index === 0 ? "true" : "false");

      var label = document.createElement("span");
      label.className = "bd-palette__label" + (item.section ? " is-section" : "");
      label.appendChild(highlight(item.title, query.toLowerCase().replace(/\s+/g, "")));

      var note = document.createElement("span");
      note.className = "bd-palette__note";
      note.textContent = item.note || "";

      row.appendChild(label);
      row.appendChild(note);
      row.addEventListener("click", function () { choose(index); });
      row.addEventListener("mousemove", function () { focusRow(index); });
      list.appendChild(row);
    });
  }

  function focusRow(index) {
    var rows = list.children;
    if (!rows[index] || index === active) return;
    if (rows[active]) {
      rows[active].classList.remove("is-active");
      rows[active].setAttribute("aria-selected", "false");
    }
    active = index;
    rows[active].classList.add("is-active");
    rows[active].setAttribute("aria-selected", "true");
    rows[active].scrollIntoView({ block: "nearest" });
  }

  function choose(index) {
    var item = items[index];
    if (!item) return;
    close();
    if (item.run) { item.run(); return; }
    if (!item.href) return;
    if (/^https?:/.test(item.href) && item.href.indexOf(location.origin) !== 0) {
      window.open(item.href, "_blank", "noopener");
    } else {
      location.href = item.href;
    }
  }

  /* ---------- shell ---------- */

  function build() {
    root = document.createElement("div");
    root.className = "bd-palette";
    root.hidden = true;
    root.innerHTML =
      '<div class="bd-palette__scrim" data-close></div>' +
      '<div class="bd-palette__panel" role="dialog" aria-modal="true" aria-label="Command palette">' +
      '<div class="bd-palette__field">' +
      '<span class="bd-palette__prompt"></span>' +
      '<input class="bd-palette__input" type="text" autocomplete="off" spellcheck="false">' +
      "</div>" +
      '<ul class="bd-palette__list" role="listbox"></ul>' +
      '<div class="bd-palette__hint"></div>' +
      "</div>";
    document.body.appendChild(root);

    input = root.querySelector(".bd-palette__input");
    list = root.querySelector(".bd-palette__list");
    hint = root.querySelector(".bd-palette__hint");

    root.querySelector("[data-close]").addEventListener("click", close);
    input.addEventListener("input", function () {
      if (input.value.charAt(0) === ">" && mode !== "do") { setMode("do"); }
      else if (input.value.charAt(0) !== ">" && mode === "do") { setMode("go"); }
      render();
    });
    input.addEventListener("keydown", onKey);
  }

  function setMode(next) {
    mode = next;
    root.querySelector(".bd-palette__prompt").textContent = next === "do" ? ">" : "→";
    hint.textContent = next === "do"
      ? "Enter to run · type without > to jump to a page"
      : "Enter to open · type > for actions · ⌘K for full-text search";
  }

  function onKey(event) {
    if (event.key === "ArrowDown") { event.preventDefault(); focusRow(Math.min(active + 1, items.length - 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); focusRow(Math.max(active - 1, 0)); }
    else if (event.key === "Enter") { event.preventDefault(); choose(active); }
    else if (event.key === "Escape") { event.preventDefault(); close(); }
  }

  /* The index is also loaded on behalf of other pages' controls, which ask for
   * it before the palette itself has ever been opened, so drawing the results
   * is conditional on the palette existing. */
  function load() {
    if (data) return Promise.resolve(data);
    if (loading) return loading;
    loading = fetch(INDEX_URL)
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) { data = payload || { entries: [] }; })
      .catch(function () { data = { entries: [] }; })
      .then(function () {
        if (root) render();
        return data;
      });
    return loading;
  }

  function open(next) {
    if (!root) build();
    setMode(next);
    root.hidden = false;
    document.body.classList.add("bd-palette-open");
    input.value = next === "do" ? ">" : "";
    render();
    load();
    input.focus();
  }

  function close() {
    if (!root) return;
    root.hidden = true;
    document.body.classList.remove("bd-palette-open");
  }

  function isOpen() { return root && !root.hidden; }

  document.addEventListener("keydown", function (event) {
    var meta = event.metaKey || event.ctrlKey;
    if (!meta) return;
    var key = event.key.toLowerCase();

    if (key === "p") {
      event.preventDefault();
      event.stopPropagation();
      if (isOpen()) { close(); return; }
      open(event.shiftKey ? "do" : "go");
      return;
    }

    /* The theme ships a Cmd+J binding that toggles a `dark` class on <body>.
     * The classic stylesheet switches on data-md-color-scheme and defines no
     * `.dark` rules, so that binding does nothing. Drive the real control
     * instead, and clear the class the theme leaves behind. */
    if (key === "j") {
      event.preventDefault();
      event.stopPropagation();
      themeToggle();
      setTimeout(function () { document.body.classList.remove("dark"); }, 0);
    }
  }, true);

  /* First visit only: adopt the reader's system preference. Once they choose a
   * theme the stored value wins, so this never fights an explicit choice. The
   * theme renders its palette control after this script runs, so wait for it. */
  /* The theme writes its own palette key on every load, so it cannot tell a
   * first visit from a returning one. Keep a separate marker for that. */
  var SEEN_KEY = "sdlc-theme-seen";

  function firstVisit() {
    try {
      if (localStorage.getItem(SEEN_KEY)) return false;
      localStorage.setItem(SEEN_KEY, "1");
      return true;
    } catch (error) {
      return false;
    }
  }

  function whenPaletteReady(callback, attempt) {
    attempt = attempt || 0;
    var labels = document.querySelectorAll('label[for^="__palette_"]');
    var ready = false;
    for (var i = 0; i < labels.length; i++) {
      if (getComputedStyle(labels[i]).display !== "none") { ready = true; break; }
    }
    if (ready) { callback(); return; }
    if (attempt > 30) return;
    setTimeout(function () { whenPaletteReady(callback, attempt + 1); }, 100);
  }

  function applySystemPreference() {
    if (!firstVisit()) return;
    if (!window.matchMedia || !window.matchMedia("(prefers-color-scheme: dark)").matches) return;
    whenPaletteReady(function () {
      if (document.body.getAttribute("data-md-color-scheme") === "slate") return;
      themeToggle();
    });
  }

  /* Shared with javascripts/annotations.js, which offers the same jump from a
   * comment on a block. */
  window.SDLCPalette = {
    sourcePath: sourcePath,
    source: function () { return data && data.sources && data.sources[sourcePath()]; },
    reviewUrl: reviewUrl,
    ready: function () { return load(); }
  };

  applySystemPreference();
  remember();
})();
