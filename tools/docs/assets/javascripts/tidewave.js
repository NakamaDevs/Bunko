/* Load the Tidewave toolbar from the review dev server when the gateway serves it. */
(() => {
  'use strict';
  const root = document.querySelector('meta[name="sdlc:tidewave-root"]')?.content;
  if (!root || document.querySelector('meta[name="tidewave:config"]')) return;
  fetch('/tidewave/config').then(response => response.ok ? response.json() : null).then(tidewave => {
    if (!tidewave) return;
    const meta = document.createElement('meta');
    meta.name = 'tidewave:config';
    meta.content = JSON.stringify({tidewave, root, wsl_distro: null, host_path: null, framework: {}});
    document.head.append(meta);
    const script = document.createElement('script');
    script.type = 'module';
    script.async = true;
    script.src = 'https://tidewave.ai/tc/toolbar.js';
    document.head.append(script);
  }).catch(() => {});
})();
