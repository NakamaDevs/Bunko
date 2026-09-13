/* Opt-in rich code blocks, rendered with @pierre/diffs.
 *
 * Ordinary fences keep the build-time Pygments highlighting, which costs no
 * JavaScript. A fence marked `.codeview` is upgraded in the browser:
 *
 *     ```{.ts .codeview title="aspire/model/routes.mts"}
 *     export const GATEWAY_HTTPS_PORT = 7444;
 *     ```
 *
 * The bundle is served from this site, is fetched only on pages that use a
 * codeview block, and only once one scrolls into view. If anything fails the
 * original highlighted block stays exactly as it was.
 */

(function () {
  "use strict";

  var ROOT = new URL("../", document.currentScript.src).href;
  var BUNDLE = ROOT + "assets/diffs/entry.js";

  /* Markdown aliases on the left, Shiki grammar ids on the right. Anything not
   * listed keeps its Pygments rendering. */
  var LANGUAGES = {
    sh: "shellscript", bash: "shellscript", shell: "shellscript",
    shellscript: "shellscript", console: "shellscript",
    py: "python", python: "python",
    ts: "typescript", mts: "typescript", typescript: "typescript",
    js: "javascript", mjs: "javascript", javascript: "javascript",
    tsx: "tsx", jsx: "jsx", vue: "vue",
    json: "json", yaml: "yaml", yml: "yaml", toml: "toml", ini: "ini",
    md: "markdown", markdown: "markdown",
    html: "html", css: "css", xml: "xml", sql: "sql", diff: "diff",
    docker: "docker", dockerfile: "docker",
    cs: "csharp", csharp: "csharp", go: "go", rs: "rust", rust: "rust",
    java: "java", rb: "ruby", ruby: "ruby", php: "php"
  };

  var EXTENSIONS = {
    shellscript: "sh", python: "py", typescript: "ts", javascript: "js",
    tsx: "tsx", jsx: "jsx", vue: "vue", json: "json", yaml: "yaml",
    toml: "toml", ini: "ini", markdown: "md", html: "html", css: "css",
    xml: "xml", sql: "sql", diff: "diff", docker: "Dockerfile",
    csharp: "cs", go: "go", rust: "rs", java: "java", ruby: "rb", php: "php"
  };

  var library = null;
  var loading = null;
  var mounted = [];

  /* A code block is identified by its filename and its contents, so a comment
   * stays attached when the block moves on the page but detaches when the code
   * itself changes. Matches the anchor shape used by the prose notes. */
  function anchorFor(name, source) {
    return crypto.subtle
      .digest("SHA-256", new TextEncoder().encode("code:" + name + "\n" + source))
      .then(function (buffer) {
        var bytes = new Uint8Array(buffer);
        var hex = "";
        for (var i = 0; i < 6; i++) hex += bytes[i].toString(16).padStart(2, "0");
        return hex;
      });
  }

  function notesFor(anchor) {
    var notes = window.SDLCNotes;
    return notes && notes.reachable ? notes.forAnchor(anchor) : [];
  }

  /* Rendered inside the code block, on the line the comment belongs to. */
  function annotationElement(note) {
    var row = document.createElement("div");
    row.className = "bd-codeview__note";
    var kind = document.createElement("span");
    kind.className = "bd-codeview__note-kind";
    kind.textContent = note.kind;
    var body = document.createElement("span");
    body.className = "bd-codeview__note-body";
    body.textContent = note.body;
    row.appendChild(kind);
    row.appendChild(body);
    return row;
  }

  function theme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate"
      ? "pierre-dark"
      : "pierre-light";
  }

  function languageOf(block) {
    var match = /(?:^|\s)language-([\w+-]+)/.exec(block.className || "");
    return match ? LANGUAGES[match[1].toLowerCase()] : undefined;
  }

  function filenameOf(block, language) {
    var label = block.querySelector(".filename");
    if (label && label.textContent.trim()) return label.textContent.trim();
    return "snippet." + (EXTENSIONS[language] || "txt");
  }

  function sourceOf(block) {
    var code = block.querySelector("pre > code");
    /* Line anchors carry no text, so textContent is the original source. */
    return code ? code.textContent.replace(/\n$/, "") : "";
  }

  function load() {
    if (library) return Promise.resolve(library);
    if (loading) return loading;
    loading = import(BUNDLE).then(function (module) {
      library = module;
      return module;
    });
    return loading;
  }

  function composeLineNote(entry, lineNumber) {
    var notes = window.SDLCNotes;
    if (!notes || !notes.reachable) return;
    var body = window.prompt(
      "Comment on line " + lineNumber + " of " + entry.contents.name
    );
    if (!body || !body.trim()) return;
    var source = window.SDLCPalette && window.SDLCPalette.source();
    notes.save({
      repo: source && source.repository,
      file_path: source && source.path,
      page_path: notes.pagePath(),
      page_title: notes.pageTitle(),
      block_anchor: entry.anchor,
      block_preview: entry.contents.name + ":" + lineNumber,
      heading: entry.contents.name,
      kind: "NOTE",
      body: body.trim(),
      line_number: lineNumber
    }).then(function () {
      return notes.reload();
    }).then(function () {
      redraw(entry);
    });
  }

  function annotationsFor(entry) {
    return notesFor(entry.anchor)
      .filter(function (note) { return note.line_number; })
      /* The component keeps `lineNumber` and `metadata`; other keys are dropped. */
      .map(function (note) { return { lineNumber: note.line_number, metadata: note }; });
  }

  function redraw(entry) {
    entry.file.render({
      file: entry.contents,
      containerWrapper: entry.host,
      lineAnnotations: annotationsFor(entry),
      forceRender: true
    });
  }

  function upgrade(block) {
    var language = languageOf(block);
    if (!language) return;

    var source = sourceOf(block);
    if (!source) return;

    var name = filenameOf(block, language);

    Promise.all([load(), anchorFor(name, source)]).then(function (results) {
      var module = results[0];
      var anchor = results[1];
      return module.preloadHighlighter({
        themes: ["pierre-light", "pierre-dark"],
        langs: [language]
      }).then(function () { return { module: module, anchor: anchor }; });
    }).then(function (ready) {
      var host = document.createElement("div");
      host.className = "bd-codeview";

      var entry = {
        anchor: ready.anchor,
        host: host,
        contents: { name: name, contents: source, lang: language }
      };

      entry.file = new ready.module.File({
        theme: theme(),
        overflow: "wrap",
        renderAnnotation: function (annotation) {
          return annotation.metadata ? annotationElement(annotation.metadata) : undefined;
        },
        onLineNumberClick: function (props) {
          composeLineNote(entry, props.lineNumber);
        }
      });

      if (!entry.file.render({
        file: entry.contents,
        containerWrapper: host,
        lineAnnotations: annotationsFor(entry)
      })) return;

      block.classList.add("bd-codeview-replaced");
      block.parentNode.insertBefore(host, block);
      mounted.push(entry);
    }).catch(function (error) {
      /* Leave the Pygments block in place, but say why in the console. */
      if (window.console) console.warn("codeview:", error && error.message);
    });
  }

  /* A theme change has to re-render, because the highlight is baked in. */
  function watchTheme() {
    var current = theme();
    new MutationObserver(function () {
      if (theme() === current) return;
      current = theme();
      mounted.forEach(function (entry) {
        entry.file.setOptions({ theme: current, overflow: "wrap" });
        redraw(entry);
      });
    }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  }

  function start() {
    var blocks = document.querySelectorAll("div.codeview");
    if (!blocks.length) return;

    if (!("IntersectionObserver" in window)) {
      blocks.forEach(upgrade);
      watchTheme();
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        upgrade(entry.target);
      });
    }, { rootMargin: "400px" });

    blocks.forEach(function (block) { observer.observe(block); });
    watchTheme();
  }

  /* Wait briefly for the notes client so existing comments are drawn with the
   * first render. Without the service the blocks still upgrade, uncommented. */
  function begin() {
    if (window.SDLCNotes && "reachable" in window.SDLCNotes) { start(); return; }
    var started = false;
    function once() {
      if (started) return;
      started = true;
      start();
    }
    document.addEventListener("sdlc-notes-ready", once, { once: true });
    setTimeout(once, 1500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", begin);
  } else {
    begin();
  }
})();
