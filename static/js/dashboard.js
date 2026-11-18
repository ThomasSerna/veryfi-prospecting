(() => {
  'use strict';

  function key(node) {
    const identity = node.getAttribute('id') || node.getAttribute('data-key') || (node.getAttribute('class') || '').split(' ')[0];
    return `${node.nodeName}|${identity}`;
  }

  function syncAttributes(node, next) {
    // Un sondeo no debe cerrar un desplegable que la persona acaba de abrir.
    const clientOwned = name => name === 'open' && node.nodeName === 'DETAILS';
    for (const { name } of Array.from(node.attributes)) {
      if (!clientOwned(name) && !next.hasAttribute(name)) node.removeAttribute(name);
    }
    for (const { name, value } of Array.from(next.attributes)) {
      if (!clientOwned(name) && node.getAttribute(name) !== value) node.setAttribute(name, value);
    }
  }

  // Conservar nodos mantiene el foco, las selecciones y el desplazamiento de la tabla.
  function morph(from, to) {
    let cursor = from.firstChild;
    for (const next of Array.from(to.childNodes)) {
      let match = null;
      if (next.nodeType === 1) {
        const wanted = key(next);
        for (let probe = cursor; probe; probe = probe.nextSibling) {
          if (probe.nodeType === 1 && key(probe) === wanted) { match = probe; break; }
        }
      } else if (next.nodeType === cursor?.nodeType) {
        match = cursor;
      }
      if (!match) {
        from.insertBefore(document.importNode(next, true), cursor);
        continue;
      }
      if (match !== cursor && next.nodeType === 1 && next.hasAttribute('data-key')) {
        from.insertBefore(match, cursor);
      } else {
        while (cursor && cursor !== match) {
          const following = cursor.nextSibling;
          cursor.remove();
          cursor = following;
        }
      }
      if (match.nodeType === 1) {
        syncAttributes(match, next);
        morph(match, next);
      } else if (match.nodeValue !== next.nodeValue) {
        match.nodeValue = next.nodeValue;
      }
      cursor = match.nextSibling;
    }
    while (cursor) {
      const following = cursor.nextSibling;
      cursor.remove();
      cursor = following;
    }
  }

  function update(current, next) {
    const active = document.activeElement;
    const showChanges = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const rows = 'tr[data-key]';
    const previous = showChanges && new Map(Array.from(current.querySelectorAll(rows), row => [row, row.textContent]));
    syncAttributes(current, next);
    morph(current, next);
    if (active?.isConnected && active !== document.activeElement) active.focus({ preventScroll: true });
    if (showChanges) {
      current.querySelectorAll(rows).forEach(row => {
        if (previous.get(row) !== row.textContent) {
          row.animate?.([{ backgroundColor: 'color-mix(in srgb, var(--accent) 20%, transparent)' },
            { backgroundColor: 'transparent' }], { duration: 650, easing: 'ease-out' });
        }
      });
    }
  }

  function start() {
    if (!document.querySelector('[data-live-dashboard]') || document.body.dataset.running !== 'true') return;
    const poll = async () => {
      try {
        const response = await fetch(window.location.href, {
          headers: { Accept: 'text/html' }, cache: 'no-store', credentials: 'same-origin',
        });
        if (!response.ok) throw new Error(`Estado ${response.status}`);
        const next = new DOMParser().parseFromString(await response.text(), 'text/html');
        if (!next.querySelector('[data-live-dashboard]')) throw new Error('Resumen ausente');
        document.querySelectorAll('[data-live-region]').forEach(region => {
          const incoming = next.querySelector(`[data-live-region="${region.dataset.liveRegion}"]`);
          if (incoming) update(region, incoming);
        });
        document.body.dataset.running = next.body.dataset.running;
        if (document.body.dataset.running === 'true') window.setTimeout(poll, 2000);
      } catch (_error) {
        // Una lectura fallida conserva la vista actual y se vuelve a consultar.
        window.setTimeout(poll, 5000);
      }
    };
    window.setTimeout(poll, 2000);
  }

  const api = { morph, update };
  if (typeof module === 'object' && module) module.exports = api;
  else {
    window.ProspectingLive = api;
    start();
  }
})();
