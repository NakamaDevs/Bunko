/* Reading-time notes for the documentation site.
 *
 * Hovering a block of content shows a marker in the left gutter. Adding a note
 * anchors it to that block by a hash of the block's heading trail and its
 * normalized text, so the note survives edits elsewhere on the page. Notes are
 * held by the local notes service; when it is not running the page is untouched
 * and no marker appears.
 *
 * Start the service with:  mise run workspace:start
 */

(function () {
  "use strict";

  /* Through the Aspire gateway the notes service shares this origin under
   * /notes. Served any other way it is a separate loopback port. */
  var API = location.origin + "/notes";
  var BLOCKS = "p, li, pre, blockquote, table, h2, h3, h4, .mermaid";
  var KINDS = ["TODO", "QUESTION", "FIXME", "NOTE"];

  var root, notes = [], byAnchor = {};
  var panel, panelList, panelCount, headerButton, allNotes = [];
  var scope = "page";        // "page" or "all"
  var SCOPE_KEY = "sdlc-notes-scope";
  var OPEN_KEY = "sdlc-notes-panel";

  function pagePath() {
    var base = document.querySelector('link[rel="canonical"]');
    return location.pathname;
  }

  /* The heading carries a permalink character that must not enter the title. */
  function pageTitle() {
    var heading = document.querySelector(".md-content h1");
    if (heading) return heading.textContent.replace(/¶/g, "").trim();
    return (document.title || "").split(" - ")[0].trim();
  }

  /* Some blocks are rendered inside a wrapper that clips or decorates them. The
   * marker belongs on the wrapper, or it is cut off by the wrapper's scrolling.
   * The anchor is still computed from the block's own text. */
  function markerHost(block) {
    return block.closest(".md-typeset__scrollwrap, .diagram-container") || block;
  }

  /* The heading trail plus the block text identifies a block across edits. */
  function headingFor(block) {
    var node = block;
    while (node) {
      if (/^H[1-4]$/.test(node.tagName)) return node.textContent.replace(/¶$/, "").trim();
      node = node.previousElementSibling || node.parentElement;
      if (node && node.classList && node.classList.contains("md-content")) break;
    }
    return "";
  }

  function normalize(text) {
    return text.replace(/\s+/g, " ").trim().toLowerCase();
  }

  function anchorFor(block) {
    var payload = headingFor(block) + "\n" + normalize(block.textContent || "");
    return crypto.subtle
      .digest("SHA-256", new TextEncoder().encode(payload))
      .then(function (buffer) {
        var bytes = new Uint8Array(buffer);
        var hex = "";
        for (var i = 0; i < 6; i++) hex += bytes[i].toString(16).padStart(2, "0");
        return hex;
      });
  }

  /* ---------- service ---------- */

  function load() {
    return fetch(API + "?page=" + encodeURIComponent(pagePath()))
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) {
        notes = (payload && payload.notes) || [];
        byAnchor = {};
        notes.forEach(function (note) {
          (byAnchor[note.block_anchor] = byAnchor[note.block_anchor] || []).push(note);
        });
        return true;
      })
      .catch(function () { return false; });
  }

  /* Every open note, for the panel's "all pages" scope. */
  function loadAll() {
    return fetch(API)
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (payload) { allNotes = (payload && payload.notes) || []; })
      .catch(function () { allNotes = []; });
  }

  function save(note) {
    return fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(note)
    }).then(function (response) { return response.json(); });
  }

  function resolve(id) {
    return fetch(API + "/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolved: true })
    });
  }

  /* ---------- markers ---------- */

  function decorateAll(scope) {
    scope.querySelectorAll(BLOCKS).forEach(function (block) {
      if (!markerHost(block).hasAttribute("data-bd-anchor")) decorate(block);
    });
  }

  function decorate(block) {
    var host = markerHost(block);
    if (host.hasAttribute("data-bd-anchor")) return;
    anchorFor(block).then(function (anchor) {
      /* Marked with attributes, never classes: the theme styles tables and
       * other blocks with :not([class]) selectors, which a added class breaks. */
      host.setAttribute("data-bd-anchor", anchor);
      /* The composer quotes the block, not the wrapper. */
      host.bdBlock = block;
      var existing = byAnchor[anchor] || [];
      if (existing.length) host.setAttribute("data-bd-count", String(existing.length));
    });
  }

  function openComposer(host, quote) {
    var block = host.bdBlock || host;
    var anchor = host.getAttribute("data-bd-anchor");
    if (!anchor) return;
    close();
    hideSelectionButton();

    root = document.createElement("div");
    root.className = "bd-note";
    var existing = byAnchor[anchor] || [];

    var list = existing.map(function (note) {
      return '<li class="bd-note__row"><span class="bd-note__kind">' + note.kind +
        '</span><span class="bd-note__body"></span>' +
        '<button class="bd-note__resolve" data-id="' + note.id + '">Resolve</button></li>';
    }).join("");

    var section = headingFor(block);
    root.innerHTML =
      '<div class="bd-note__head">' +
      (quote ? "Note on the selected text" : "Note on this block") +
      '<button class="bd-note__edit" type="button" hidden>Edit file</button>' +
      "</div>" +
      '<div class="bd-note__where"></div>' +
      (quote ? '<blockquote class="bd-note__quote"></blockquote>' : "") +
      (list ? '<ul class="bd-note__list">' + list + "</ul>" : "") +
      '<div class="bd-note__form">' +
      '<select class="bd-note__select">' +
      KINDS.map(function (k) { return '<option value="' + k + '">' + k + "</option>"; }).join("") +
      "</select>" +
      '<textarea class="bd-note__input" rows="3" placeholder="What should change here?"></textarea>' +
      '<div class="bd-note__actions">' +
      '<button class="bd-note__cancel">Cancel</button>' +
      '<button class="bd-note__save">Save note</button></div></div>';

    document.body.appendChild(root);

    /* Note bodies are user text and are set as text, never as markup. */
    var bodies = root.querySelectorAll(".bd-note__body");
    existing.forEach(function (note, index) {
      if (bodies[index]) bodies[index].textContent = note.body;
    });

    /* Page and section are content, and are set as text, never as markup. */
    var where = root.querySelector(".bd-note__where");
    where.textContent = section ? pageTitle() + " › " + section : pageTitle();

    var quoted = root.querySelector(".bd-note__quote");
    if (quoted) quoted.textContent = quote;

    var box = host.getBoundingClientRect();
    root.style.top = window.scrollY + box.top + "px";

    /* A comment often is an edit. Offer the file itself, opened at this text. */
    var edit = root.querySelector(".bd-note__edit");
    if (window.SDLCPalette) {
      var target = quote || (block.textContent || "").trim().split("\n")[0];
      window.SDLCPalette.ready().then(function () {
        var href = window.SDLCPalette.reviewUrl({ edit: true, match: target });
        if (!href) return;
        edit.hidden = false;
        edit.addEventListener("click", function () {
          window.open(href, "_blank", "noopener");
        });
      }).catch(function () { /* without the index there is no file to offer */ });
    }

    root.querySelector(".bd-note__cancel").addEventListener("click", close);
    root.querySelector(".bd-note__input").focus();
    root.querySelectorAll(".bd-note__resolve").forEach(function (button) {
      button.addEventListener("click", function () {
        resolve(button.getAttribute("data-id")).then(refresh);
      });
    });
    root.querySelector(".bd-note__save").addEventListener("click", function () {
      var body = root.querySelector(".bd-note__input").value.trim();
      if (!body) return;
      var source = window.SDLCPalette && window.SDLCPalette.source();
      save({
        repo: source && source.repository,
        file_path: source && source.path,
        page_path: pagePath(),
        page_title: pageTitle(),
        block_anchor: anchor,
        /* A quoted note records what was selected; otherwise the block opening. */
        block_preview: (quote || block.textContent || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 240),
        heading: headingFor(block),
        kind: root.querySelector(".bd-note__select").value,
        body: body
      }).then(refresh);
    });
  }

  function close() {
    if (root && root.parentNode) root.parentNode.removeChild(root);
    root = null;
  }

  function refresh() {
    close();
    return load().then(function () {
      document.querySelectorAll("[data-bd-anchor]").forEach(function (block) {
        block.removeAttribute("data-bd-count");
        var existing = byAnchor[block.getAttribute("data-bd-anchor")] || [];
        if (existing.length) block.setAttribute("data-bd-count", String(existing.length));
      });
      if (scope === "all") return loadAll().then(renderPanel);
      renderPanel();
      return undefined;
    });
  }

  /* ---------- comments panel ---------- */

  /* A bare-letter shortcut must never fire while the reader is writing. */
  function isTyping(target) {
    if (!target) return false;
    if (target.isContentEditable) return true;
    return /^(input|textarea|select)$/i.test(target.tagName || "");
  }

  function stored(key, fallback) {
    try {
      var value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function remember(key, value) {
    try { localStorage.setItem(key, value); } catch (error) { /* not fatal */ }
  }

  function buildPanel() {
    panel = document.createElement("aside");
    panel.className = "bd-panel";
    panel.innerHTML =
      '<div class="bd-panel__head">' +
      '<span class="bd-panel__title">Comments</span>' +
      '<button class="bd-panel__close" type="button" aria-label="Hide comments">✕</button>' +
      '<div class="bd-panel__scope" role="group" aria-label="Scope">' +
      '<button type="button" data-scope="page">This page</button>' +
      '<button type="button" data-scope="all">All pages</button>' +
      "</div></div>" +
      '<ul class="bd-panel__list"></ul>';
    document.body.appendChild(panel);
    document.body.classList.add("bd-panel-docked");

    panelList = panel.querySelector(".bd-panel__list");
    panel.querySelector(".bd-panel__close").addEventListener("click", function () {
      setPanelOpen(false);
    });

    panel.querySelectorAll("[data-scope]").forEach(function (button) {
      button.addEventListener("click", function () {
        setScope(button.getAttribute("data-scope"));
      });
    });

    buildHeaderButton();
    setPanelOpen(stored(OPEN_KEY, "1") === "1");
    setScope(stored(SCOPE_KEY, "page"));
  }

  /* The sidebar is opened from the header, beside search and the theme toggle. */
  function buildHeaderButton() {
    var header = document.querySelector(".md-header__inner");
    if (!header) return;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "bd-header-button md-header__button";
    button.title = "Comments (press c)";
    button.setAttribute("aria-label", "Toggle comments");
    button.innerHTML =
      '<span class="bd-header-button__label">Comments</span>' +
      '<span class="bd-header-button__count">0</span>';
    button.addEventListener("click", function () {
      setPanelOpen(!panel.classList.contains("is-open"));
    });
    header.appendChild(button);

    panelCount = button.querySelector(".bd-header-button__count");
    headerButton = button;
  }

  function setPanelOpen(open) {
    panel.classList.toggle("is-open", open);
    document.body.classList.toggle("bd-panel-open", open);
    if (headerButton) {
      headerButton.classList.toggle("is-active", open);
      headerButton.setAttribute("aria-expanded", String(open));
    }
    remember(OPEN_KEY, open ? "1" : "0");
  }

  function setScope(next) {
    scope = next === "all" ? "all" : "page";
    remember(SCOPE_KEY, scope);
    panel.querySelectorAll("[data-scope]").forEach(function (button) {
      button.classList.toggle("is-active", button.getAttribute("data-scope") === scope);
    });
    if (scope === "all") loadAll().then(renderPanel);
    else renderPanel();
  }

  /* A repository comment belongs to the review tool, not to a page here. */
  function isRepositoryNote(note) {
    return Boolean(note.repo) && (note.page_path || "").indexOf("review:") === 0;
  }

  function renderPanel() {
    if (!panel) return;
    var rows = scope === "all" ? allNotes : notes;
    /* The header badge always counts this page, whatever the panel shows. */
    if (panelCount) panelCount.textContent = String(notes.length);
    panelList.textContent = "";

    if (!rows.length) {
      var empty = document.createElement("li");
      empty.className = "bd-panel__empty";
      empty.textContent = scope === "all"
        ? "No open comments anywhere."
        : "No comments on this page. Select some text to add one.";
      panelList.appendChild(empty);
      return;
    }

    rows.forEach(function (note) {
      var row = document.createElement("li");
      row.className = "bd-panel__item";

      var head = document.createElement("div");
      head.className = "bd-panel__meta";

      var kind = document.createElement("span");
      kind.className = "bd-panel__kind";
      kind.textContent = note.kind;
      head.appendChild(kind);

      /* In "all pages" scope every comment says where it came from. */
      if (scope === "all") {
        var where = document.createElement("span");
        where.className = "bd-panel__where";
        where.textContent = isRepositoryNote(note)
          ? note.repo + " · " + (note.file_path || "")
          : note.page_title || note.page_path;
        head.appendChild(where);
      }

      if (note.line_number) {
        var line = document.createElement("span");
        line.className = "bd-panel__line";
        line.textContent = "L" + note.line_number;
        head.appendChild(line);
      }

      var body = document.createElement("p");
      body.className = "bd-panel__body-text";
      body.textContent = note.body;

      var quote = document.createElement("p");
      quote.className = "bd-panel__quote";
      quote.textContent = note.block_preview || "";

      var actions = document.createElement("div");
      actions.className = "bd-panel__actions";

      if (!isRepositoryNote(note)) {
        var go = document.createElement("button");
        go.type = "button";
        go.className = "bd-panel__go";
        go.textContent = scope === "all" && note.page_path !== pagePath() ? "Open page" : "Show";
        go.addEventListener("click", function () { focusNote(note); });
        actions.appendChild(go);
      } else {
        var tag = document.createElement("span");
        tag.className = "bd-panel__tag";
        tag.textContent = "Repository";
        actions.appendChild(tag);
      }

      var done = document.createElement("button");
      done.type = "button";
      done.className = "bd-panel__resolve";
      done.textContent = "Resolve";
      done.addEventListener("click", function () {
        resolve(note.id).then(function () {
          return scope === "all" ? loadAll().then(refresh) : refresh();
        });
      });
      actions.appendChild(done);

      row.append(head, body);
      if (note.block_preview) row.appendChild(quote);
      row.appendChild(actions);
      panelList.appendChild(row);
    });
  }

  /* Scroll to the commented block, or open the page that holds it. */
  function focusNote(note) {
    if (note.page_path && note.page_path !== pagePath()) {
      location.href = note.page_path + "?note=" + note.id;
      return;
    }
    var block = document.querySelector('[data-bd-anchor="' + note.block_anchor + '"]');
    if (!block) return;
    block.scrollIntoView({ behavior: "smooth", block: "center" });
    block.classList.add("bd-flash");
    setTimeout(function () { block.classList.remove("bd-flash"); }, 1600);
  }

  /* Arriving from another page's panel, land on the comment that was clicked. */
  function focusRequestedNote() {
    var requested = new URLSearchParams(location.search).get("note");
    if (!requested) return;
    var note = notes.filter(function (entry) { return String(entry.id) === requested; })[0];
    if (note) setTimeout(function () { focusNote(note); }, 300);
  }

  /* ---------- selecting text ---------- */

  var selectionButton;

  function hideSelectionButton() {
    if (selectionButton) selectionButton.hidden = true;
  }

  /* The block a selection sits in, so a quoted note still has a stable anchor. */
  function blockOf(node) {
    var element = node.nodeType === 1 ? node : node.parentElement;
    while (element && !element.hasAttribute?.("data-bd-anchor")) {
      element = element.parentElement;
    }
    return element;
  }

  function showSelectionButton(content) {
    var selection = window.getSelection();
    if (!selection || selection.isCollapsed) { hideSelectionButton(); return; }

    var quote = selection.toString().trim();
    if (quote.length < 2) { hideSelectionButton(); return; }

    var range = selection.getRangeAt(0);
    var block = blockOf(range.commonAncestorContainer);
    if (!block || !content.contains(block)) { hideSelectionButton(); return; }

    if (!selectionButton) {
      selectionButton = document.createElement("button");
      selectionButton.className = "bd-select-note";
      selectionButton.type = "button";
      selectionButton.textContent = "Comment";
      /* mousedown would clear the selection before the handler runs. */
      selectionButton.addEventListener("mousedown", function (event) { event.preventDefault(); });
      document.body.appendChild(selectionButton);
    }

    selectionButton.onclick = function () { openComposer(block, quote); };

    var box = range.getBoundingClientRect();
    selectionButton.hidden = false;
    selectionButton.style.top = window.scrollY + box.top - 38 + "px";
    selectionButton.style.left = window.scrollX + box.left + "px";
  }

  function start() {
    var content = document.querySelector(".md-content__inner, .md-content");
    if (!content) return;
    decorateAll(content);

    /* Diagrams are drawn after this runs, and the diagram viewer wraps them
     * later still, so late content has to be picked up when it appears. */
    var pending;
    new MutationObserver(function () {
      window.clearTimeout(pending);
      pending = window.setTimeout(function () { decorateAll(content); }, 200);
    }).observe(content, { childList: true, subtree: true });

    buildPanel();
    renderPanel();
    focusRequestedNote();
    content.addEventListener("click", function (event) {
      var block = event.target.closest("[data-bd-anchor]");
      if (!block) return;
      /* The gutter marker sits in the block's left padding. */
      if (event.clientX > block.getBoundingClientRect().left) return;
      event.preventDefault();
      openComposer(block);
    });
    /* Selecting text anywhere in the page offers a comment on that quote. */
    document.addEventListener("selectionchange", function () {
      window.clearTimeout(showSelectionButton.timer);
      showSelectionButton.timer = window.setTimeout(function () {
        showSelectionButton(content);
      }, 120);
    });
    document.addEventListener("scroll", hideSelectionButton, { passive: true });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        close();
        hideSelectionButton();
        return;
      }

      /* A bare letter, like the theme's own f/s and n/p bindings. Every useful
       * modifier combination with C is taken by the browser's developer tools. */
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.code !== "KeyC") return;
      if (isTyping(event.target)) return;
      event.preventDefault();
      setPanelOpen(!panel.classList.contains("is-open"));
    });
    document.body.classList.add("bd-notes-ready");
  }

  /* Shared with javascripts/codeview.js so code comments use one service,
   * one composer, and one worklist. */
  window.SDLCNotes = {
    api: API,
    pagePath: pagePath,
    pageTitle: pageTitle,
    save: save,
    resolve: resolve,
    /* Notes for this page, already loaded, grouped by the block they anchor to. */
    forAnchor: function (anchor) { return byAnchor[anchor] || []; },
    reload: function () { return load(); }
  };

  /* A page containing <div data-bunko-notes></div> lists every open note, live,
   * grouped by the page or file it belongs to. */
  function renderIndex(container, reachable) {
    container.textContent = "";
    if (!reachable) {
      container.appendChild(paragraph("The notes service is not running. Start Bunko to list open notes."));
      return;
    }
    if (!allNotes.length) {
      container.appendChild(paragraph("No open notes. Select some text on any page to add one."));
      return;
    }
    var groups = {};
    var order = [];
    var counts = {};
    allNotes.forEach(function (note) {
      var key = titleFor(note) + " " + (isRepositoryNote(note) ? "" : note.page_path);
      if (!groups[key]) { groups[key] = []; order.push(key); }
      groups[key].push(note);
      counts[note.kind] = (counts[note.kind] || 0) + 1;
    });
    var summary = Object.keys(counts).sort().map(function (kind) { return counts[kind] + " " + kind; }).join(", ");
    container.appendChild(paragraph(allNotes.length + " open (" + summary + ") across " + order.length +
      (order.length === 1 ? " page." : " pages.")));
    order.sort().forEach(function (key) {
      var first = groups[key][0];
      var heading = document.createElement("h2");
      if (isRepositoryNote(first)) {
        heading.textContent = titleFor(first);
      } else {
        var link = document.createElement("a");
        link.href = first.page_path;
        link.textContent = titleFor(first);
        heading.appendChild(link);
      }
      container.appendChild(heading);
      var table = document.createElement("table");
      var header = table.createTHead().insertRow();
      ["Kind", "Note", "Block"].forEach(function (label) {
        var cell = document.createElement("th");
        cell.textContent = label;
        header.appendChild(cell);
      });
      var body = table.createTBody();
      groups[key].forEach(function (note) {
        var preview = (note.block_preview || "").slice(0, 90);
        var where = isRepositoryNote(note) ? "L" + (note.line_number || "")
          : (note.heading ? note.heading + " — " : "") + preview + (preview ? "…" : "");
        var row = body.insertRow();
        [note.kind, note.body, where].forEach(function (text) { row.insertCell().textContent = text; });
      });
      var wrapper = document.createElement("div");
      wrapper.className = "md-typeset__table";
      wrapper.appendChild(table);
      container.appendChild(wrapper);
    });
  }

  function titleFor(note) {
    return isRepositoryNote(note) ? note.repo + " · " + (note.file_path || "") : note.page_title || note.page_path;
  }

  function paragraph(text) {
    var element = document.createElement("p");
    element.textContent = text;
    return element;
  }

  /* The service is optional: without it the page stays exactly as it is. */
  load().then(function (reachable) {
    window.SDLCNotes.reachable = reachable;
    document.dispatchEvent(new CustomEvent("sdlc-notes-ready", { detail: { reachable: reachable } }));
    if (reachable) start();
    var index = document.querySelector("[data-bunko-notes]");
    if (index) (reachable ? loadAll() : Promise.resolve()).then(function () { renderIndex(index, reachable); });
  });
})();
