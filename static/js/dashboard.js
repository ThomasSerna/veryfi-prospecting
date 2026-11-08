(() => {
  'use strict';

  // Actualización viva: la entrada se reproduce una vez y el sondeo actualiza en su sitio, sin reiniciarla.
  const EASE = 'cubic-bezier(.16, 1, .3, 1)';
  // Los destellos usan el acento de la paleta (`--accent` en app.css) con la opacidad indicada.
  const accent = alpha => `color-mix(in srgb, var(--accent) ${alpha}%, transparent)`;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const motionless = () => reduced.matches;

  function key(node) {
    if (node.nodeType !== 1) return `#${node.nodeType}`;
    const name = node.getAttribute('id') || node.getAttribute('data-key') || (node.getAttribute('class') || '').split(' ')[0];
    return `${node.nodeName}|${name}`;
  }

  // Nodos propios del cliente (indicadores, cifras flotantes, salidas en curso) quedan fuera de la comparación.
  function significant(node) {
    while (node && node.nodeType === 1 && node.hasAttribute('data-morph-skip')) node = node.nextSibling;
    return node;
  }

  // Atributos que decide el cliente: el puntero escribe `style`, quien lee abre un desplegable
  // y la entrada termina una sola vez; el servidor no los revierte.
  function owned(node, name) {
    return name === 'data-entering' || (name === 'open' && node.nodeName === 'DETAILS');
  }

  function syncAttributes(node, next) {
    for (const { name } of Array.from(node.attributes)) {
      // `style` solo se sustituye cuando el servidor lo envía.
      if (name !== 'style' && !owned(node, name) && !next.hasAttribute(name)) node.removeAttribute(name);
    }
    for (const { name, value } of Array.from(next.attributes)) {
      if (!owned(node, name) && node.getAttribute(name) !== value) node.setAttribute(name, value);
    }
  }

  function enter(node, order) {
    if (node.nodeType !== 1 || !node.animate) return;
    if (motionless()) {
      node.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: 'ease-out' });
      return;
    }
    const delay = Math.min(order, 10) * 70;
    if (node.classList.contains('progress-segment')) {
      node.animate([
        { opacity: 0, transform: 'scaleX(.15)' },
        { opacity: 1, transform: 'none' },
      ], { duration: 620, delay, easing: EASE, fill: 'backwards' });
      return;
    }
    // Una empresa nueva sube a su fila y conserva un instante la luz del descubrimiento.
    if (node.nodeName === 'TR') {
      node.animate([
        { opacity: 0, transform: 'translateY(12px)', backgroundColor: accent(16) },
        { opacity: 1, transform: 'none', backgroundColor: accent(10), offset: 0.35 },
        { opacity: 1, transform: 'none', backgroundColor: 'transparent' },
      ], { duration: 1600, delay, easing: 'cubic-bezier(.22, 1, .36, 1)', fill: 'backwards' });
      return;
    }
    node.animate([
      { opacity: 0, filter: 'blur(6px)', transform: 'translateY(8px)' },
      { opacity: 1, filter: 'blur(0)', transform: 'none' },
    ], { duration: 520, delay, easing: EASE, fill: 'backwards' });
  }

  // Una tabla que llega entera presenta sus filas en cascada en lugar de aparecer como un bloque.
  function entrance(entered) {
    let order = 0;
    for (const node of entered) {
      if (node.nodeType !== 1) continue;
      const rows = node.nodeName === 'TR' ? [] : Array.from(node.querySelectorAll?.('tr[data-key]') || []);
      if (!rows.length) {
        enter(node, order++);
        continue;
      }
      node.animate?.([{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: 'ease-out' });
      rows.forEach(row => enter(row, order++));
    }
  }

  function leave(node) {
    if (node.nodeType !== 1 || !node.animate || motionless()) {
      node.remove();
      return;
    }
    node.setAttribute('data-morph-skip', '');
    if (node.nodeName === 'TR') {
      const exit = node.animate([
        { opacity: 1, transform: 'none' },
        { opacity: 0, transform: 'translateX(-14px)' },
      ], { duration: 240, easing: 'cubic-bezier(.4, 0, .2, 1)', fill: 'forwards' });
      exit.finished.then(() => node.remove(), () => node.remove());
      return;
    }
    const { height } = node.getBoundingClientRect();
    node.style.overflow = 'hidden';
    const exit = node.animate([
      { opacity: 1, height: `${height}px` },
      { opacity: 0, height: '0px', marginTop: '0px', marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px', filter: 'blur(4px)' },
    ], { duration: 320, easing: 'cubic-bezier(.4, 0, .2, 1)', fill: 'forwards' });
    exit.finished.then(() => node.remove(), () => node.remove());
  }

  // Compara por clave y en orden: conserva los nodos existentes, así su foco, estado y animaciones siguen intactos.
  function morph(from, to, entered) {
    let cursor = significant(from.firstChild);
    for (const next of Array.from(to.childNodes)) {
      let match = null;
      if (cursor && next.nodeType !== 1) {
        if (cursor.nodeType === next.nodeType) match = cursor;
      } else if (next.nodeType === 1) {
        const wanted = key(next);
        for (let probe = cursor; probe; probe = significant(probe.nextSibling)) {
          if (probe.nodeType === 1 && key(probe) === wanted) { match = probe; break; }
        }
        // Un nodo con `data-key` que cambió de orden se traslada; los que quedan entre ambos no se recrean.
        if (match && match !== cursor && next.hasAttribute('data-key')) {
          from.insertBefore(match, cursor);
          syncAttributes(match, next);
          morph(match, next, entered);
          continue;
        }
      }
      if (!match) {
        const node = document.importNode(next, true);
        from.insertBefore(node, cursor);
        entered.push(node);
        continue;
      }
      while (cursor && cursor !== match) {
        const following = significant(cursor.nextSibling);
        leave(cursor);
        cursor = following;
      }
      if (match.nodeType === 1) {
        syncAttributes(match, next);
        morph(match, next, entered);
      } else if (match.nodeValue !== next.nodeValue) {
        match.nodeValue = next.nodeValue;
      }
      cursor = significant(match.nextSibling);
    }
    while (cursor) {
      const following = significant(cursor.nextSibling);
      leave(cursor);
      cursor = following;
    }
  }

  function snapshot(root) {
    return {
      values: new Map(Array.from(root.querySelectorAll('[data-delta]'), node => [node, Number(node.dataset.value)])),
      done: new Set(root.querySelectorAll('.progress-segment.is-done')),
      swaps: new Map(Array.from(root.querySelectorAll('[data-live-swap]'), node => [node, node.textContent.trim()])),
      live: matches(root, '.is-live'),
      rows: new Map(Array.from(root.querySelectorAll('[data-key]'), node => [node, { top: node.getBoundingClientRect().top, text: node.textContent }])),
    };
  }

  function matches(root, selector) {
    return Boolean(root.matches?.(selector) || root.querySelector(selector));
  }

  function materialize(node) {
    node.animate?.(motionless()
      ? [{ opacity: 0.2 }, { opacity: 1 }]
      : [
        { opacity: 0, filter: 'blur(6px)', transform: 'translateY(6px) scale(.97)' },
        { opacity: 1, filter: 'blur(0)', transform: 'none' },
      ], { duration: motionless() ? 220 : 520, easing: EASE });
  }

  function chip(node, delta) {
    const badge = document.createElement('span');
    badge.className = 'delta-chip';
    badge.setAttribute('aria-hidden', 'true');
    badge.setAttribute('data-morph-skip', '');
    badge.textContent = `+${delta}`;
    node.append(badge);
    const frames = motionless()
      ? [{ opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }]
      : [
        { opacity: 0, transform: 'translateY(8px) scale(.8)' },
        { opacity: 1, transform: 'translateY(0) scale(1)', offset: 0.18 },
        { opacity: 1, transform: 'translateY(-4px)', offset: 0.78 },
        { opacity: 0, transform: 'translateY(-14px)' },
      ];
    const animation = badge.animate?.(frames, { duration: 1900, easing: 'cubic-bezier(.22, 1, .36, 1)' });
    if (animation) animation.finished.then(() => badge.remove(), () => badge.remove());
    else window.setTimeout(() => badge.remove(), 1900);
  }

  function flash(segment, order) {
    segment.animate?.([
      { filter: 'brightness(1)', boxShadow: '0 0 0 0 transparent' },
      { filter: 'brightness(1.7)', boxShadow: `0 0 22px 3px ${accent(60)}`, offset: 0.3 },
      { filter: 'brightness(1)', boxShadow: '0 0 0 0 transparent' },
    ], { duration: 1200, delay: order * 110, easing: 'ease-out' });
  }

  // Una fila cuyo contenido cambió se ilumina y se apaga: el color explica el cambio también sin movimiento.
  function glow(row) {
    row.animate?.([
      { backgroundColor: accent(14) },
      { backgroundColor: 'transparent' },
    ], { duration: motionless() ? 900 : 1600, easing: 'ease-out' });
  }

  // Señala solo lo que cambió entre dos lecturas: cifras, empresas terminadas, estados y orden de filas.
  function signal(root, before) {
    before.swaps.forEach((text, node) => {
      if (node.isConnected && node.textContent.trim() !== text) materialize(node);
    });
    before.values.forEach((value, node) => {
      const delta = Number(node.dataset.value) - value;
      if (node.isConnected && delta > 0) chip(node, delta);
    });
    let order = 0;
    root.querySelectorAll('.progress-segment.is-done').forEach(segment => {
      if (!before.done.has(segment)) flash(segment, order++);
    });
    const bar = root.querySelector('.progress-segments');
    if (before.live && bar && !matches(root, '.is-live') && !motionless()) {
      bar.animate?.([
        { backgroundPosition: '160% 0', opacity: 1 },
        { backgroundPosition: '-60% 0', opacity: 1 },
      ], { duration: 1400, delay: order * 110, easing: 'cubic-bezier(.65, 0, .35, 1)', pseudoElement: '::after' });
    }
    // FLIP: cada fila conservada parte de donde estaba y se desliza a su nuevo puesto.
    before.rows.forEach((was, row) => {
      if (!row.isConnected) return;
      const shift = was.top - row.getBoundingClientRect().top;
      if (Math.abs(shift) > 1 && !motionless()) {
        row.animate?.([{ transform: `translateY(${shift}px)` }, { transform: 'none' }], { duration: 560, easing: EASE });
      }
      if (row.textContent !== was.text) glow(row);
    });
  }

  // Actualiza una región con la versión del servidor y anima solo sus diferencias.
  function update(current, next) {
    const before = snapshot(current);
    const entered = [];
    syncAttributes(current, next);
    morph(current, next, entered);
    entrance(entered);
    signal(current, before);
  }

  function apply(root, next) {
    const before = snapshot(root);
    const entered = [];
    document.querySelectorAll('[data-live-region]').forEach(region => {
      const incoming = next.querySelector(`[data-live-region="${region.dataset.liveRegion}"]`);
      if (incoming) morph(region, incoming, entered);
    });
    document.body.dataset.running = next.body?.dataset.running === 'true' ? 'true' : 'false';
    entrance(entered);
    signal(root, before);
  }

  // La entrada CSS solo afecta a lo que existe al cargar; lo que llega por sondeo usa sus propias señales.
  function settle(root) {
    const finite = (root.getAnimations?.({ subtree: true }) || [])
      .filter(animation => Number.isFinite(animation.effect?.getComputedTiming?.().endTime));
    Promise.allSettled(finite.map(animation => animation.finished))
      .then(() => root.removeAttribute('data-entering'));
  }

  function start() {
    document.querySelectorAll('[data-entering]').forEach(settle);
    const root = document.querySelector('[data-live-dashboard]');
    if (!root || document.body.dataset.running !== 'true') return;
    const poll = async () => {
      try {
        const response = await fetch(window.location.href, {
          headers: { Accept: 'text/html' }, cache: 'no-store', credentials: 'same-origin',
        });
        if (!response.ok) throw new Error(`Estado ${response.status}`);
        const next = new DOMParser().parseFromString(await response.text(), 'text/html');
        if (!next.querySelector('[data-live-dashboard]')) throw new Error('Resumen ausente');
        apply(root, next);
        if (document.body.dataset.running === 'true') window.setTimeout(poll, 2000);
      } catch (_error) {
        // Una lectura fallida no altera resultados; se vuelve a consultar.
        window.setTimeout(poll, 5000);
      }
    };
    window.setTimeout(poll, 2000);
  }

  // Las pruebas sin navegador cargan el módulo para ejercitar la comparación con un DOM sintético;
  // en la página, la campaña reutiliza `update` para su propio sondeo.
  const api = { morph, update };
  if (typeof module === 'object' && module) module.exports = api;
  else {
    window.ProspectingLive = api;
    start();
  }
})();
