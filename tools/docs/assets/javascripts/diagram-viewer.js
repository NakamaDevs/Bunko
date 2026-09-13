/* Full-window Mermaid inspection. Pointer movement never changes scale. */
(() => {
  'use strict';
  const diagramRoots = new Set();
  const attachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (options) {
    const root = attachShadow.call(this, options);
    {
      diagramRoots.add(root);
      new MutationObserver(enhance).observe(root, {childList: true, subtree: true});
    }
    return root;
  };
  const levels = [1, 1.5, 2, 3, 4, 6];
  function openDiagram(source, trigger) {
    const dialog = document.createElement('dialog');
    dialog.className = 'diagram-dialog';
    dialog.setAttribute('aria-label', 'Fullscreen diagram');
    dialog.innerHTML = '<header><strong>Diagram</strong><span>Double-click to zoom · Shift + double-click to zoom out · Drag to pan</span><button type="button" data-action="out" aria-label="Zoom out">−</button><output aria-live="polite">Fit</output><button type="button" data-action="in" aria-label="Zoom in">+</button><button type="button" data-action="fit">Fit</button><button type="button" data-action="close" aria-label="Close diagram">Close ×</button></header><div class="diagram-viewport" tabindex="0" aria-label="Diagram canvas. Use zoom buttons and drag to pan."><div class="diagram-canvas"></div></div>';
    const viewport = dialog.querySelector('.diagram-viewport');
    const canvas = dialog.querySelector('.diagram-canvas');
    const svg = source.cloneNode(true);
    // Isolate cloned SVG IDs, including Mermaid marker and clip references.
    const prefix = `diagram-${Date.now()}-`;
    const ids = new Map();
    svg.querySelectorAll('[id]').forEach(el => ids.set(el.id, prefix + el.id));
    if (svg.id) ids.set(svg.id, prefix + svg.id);
    [svg, ...svg.querySelectorAll('*')].forEach(el => {
      for (const attr of [...el.attributes]) {
        let value = attr.value;
        if (attr.name === 'id') value = ids.get(value) || value;
        else ids.forEach((replacement, id) => {
          value = value.replaceAll(`url(#${id})`, `url(#${replacement})`);
          if (value === `#${id}`) value = `#${replacement}`;
        });
        el.setAttribute(attr.name, value);
      }
    });
    svg.querySelectorAll('style').forEach(style => {
      let css = style.textContent;
      [...ids].sort((a, b) => b[0].length - a[0].length).forEach(([id, replacement]) => {
        css = css.replaceAll(`#${id}`, `#${replacement}`);
      });
      style.textContent = css;
    });
    canvas.append(svg);
    document.body.append(dialog);
    dialog.showModal();
    const box = source.viewBox.baseVal;
    const width = box.width || source.getBoundingClientRect().width;
    const height = box.height || source.getBoundingClientRect().height;
    svg.style.cssText = `width:${width}px;height:${height}px;max-width:none;display:block`;
    let index = 0, x = 0, y = 0, fit = 1, drag = null, lastDrag = 0;
    function draw() {
      canvas.style.transform = `translate(${x}px,${y}px) scale(${fit * levels[index]})`;
      dialog.querySelector('output').textContent = index ? `${levels[index] * 100}%` : 'Fit';
      dialog.querySelector('[data-action="out"]').disabled = index === 0;
      dialog.querySelector('[data-action="in"]').disabled = index === levels.length - 1;
    }
    function reset() {
      fit = Math.min((viewport.clientWidth - 48) / width, (viewport.clientHeight - 48) / height);
      index = 0;
      x = (viewport.clientWidth - width * fit) / 2;
      y = (viewport.clientHeight - height * fit) / 2;
      draw();
    }
    function zoom(next, cx = viewport.clientWidth / 2, cy = viewport.clientHeight / 2) {
      next = Math.max(0, Math.min(levels.length - 1, next));
      const ratio = levels[next] / levels[index];
      x = cx - (cx - x) * ratio;
      y = cy - (cy - y) * ratio;
      index = next;
      draw();
    }
    dialog.querySelector('header').addEventListener('click', event => {
      const action = event.target.closest('button')?.dataset.action;
      if (action === 'close') dialog.close();
      if (action === 'fit') reset();
      if (action === 'in') zoom(index + 1);
      if (action === 'out') zoom(index - 1);
    });
    viewport.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      drag = {id: event.pointerId, startX: event.clientX, startY: event.clientY, x, y, moved: false};
      viewport.setPointerCapture(event.pointerId);
    });
    viewport.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.id) return;
      const dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
      if (Math.hypot(dx, dy) > 5) drag.moved = true;
      if (drag.moved) { x = drag.x + dx; y = drag.y + dy; draw(); }
    });
    function endDrag() {
      if (drag?.moved) lastDrag = performance.now();
      drag = null;
    }
    viewport.addEventListener('pointerup', endDrag);
    viewport.addEventListener('pointercancel', endDrag);
    viewport.addEventListener('dblclick', event => {
      event.preventDefault();
      if (performance.now() - lastDrag < 500) return;
      const bounds = viewport.getBoundingClientRect();
      const next = event.shiftKey ? index - 1 : (index + 1) % levels.length;
      zoom(next, event.clientX - bounds.left, event.clientY - bounds.top);
    });
    const observer = new ResizeObserver(reset);
    observer.observe(viewport);
    dialog.addEventListener('close', () => {
      observer.disconnect();
      dialog.remove();
      trigger.focus();
    }, {once: true});
    reset();
  }
  function enhance() {
    const diagrams = [...document.querySelectorAll('.mermaid svg')];
    diagramRoots.forEach(root => {
      if (!root.host.isConnected) { diagramRoots.delete(root); return; }
      if (root.host.classList.contains('mermaid')) diagrams.push(...root.querySelectorAll('svg'));
    });
    diagrams.forEach(svg => {
      if (svg.closest('.diagram-dialog')) return;
      const host = svg.getRootNode().host || svg.parentElement;
      if (host.parentElement?.classList.contains('diagram-container')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'diagram-container';
      host.before(wrapper);
      wrapper.append(host);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'diagram-expand';
      button.textContent = '⛶ Fullscreen';
      button.setAttribute('aria-label', 'Open diagram fullscreen');
      button.addEventListener('click', () => openDiagram(svg, button));
      wrapper.append(button);
    });
  }
  function start() {
    new MutationObserver(enhance).observe(document.body, {childList: true, subtree: true});
    enhance();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
