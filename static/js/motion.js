(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const precise = window.matchMedia('(hover: hover) and (pointer: fine)');
  const properties = ['--motion-x', '--motion-y', '--motion-rotate-x', '--motion-rotate-y'];
  // Distancia a la que el borde de una superficie empieza a orientarse hacia el puntero.
  const PROXIMITY = 96;
  const TILT = 3;
  const angles = new WeakMap();
  const glowing = new Set();
  let surface = null;
  let bounds = null;
  let point = null;
  let frame = 0;

  function release() {
    if (surface) properties.forEach(name => surface.style.removeProperty(name));
    surface = bounds = null;
  }

  function dim() {
    glowing.forEach(card => card.style.removeProperty('--motion-glow'));
    glowing.clear();
  }

  function reset() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    release();
    dim();
    point = null;
  }

  // Cada superficie cercana orienta su brillo hacia el puntero por el camino angular más corto.
  function glow() {
    for (const card of document.querySelectorAll?.('[data-motion-surface]') || []) {
      const box = card === surface && bounds ? bounds : card.getBoundingClientRect();
      const near = point.x > box.left - PROXIMITY && point.x < box.left + box.width + PROXIMITY
        && point.y > box.top - PROXIMITY && point.y < box.top + box.height + PROXIMITY;
      if (!near) {
        if (glowing.delete(card)) card.style.removeProperty('--motion-glow');
        continue;
      }
      const target = Math.atan2(point.y - box.top - box.height / 2, point.x - box.left - box.width / 2) * 180 / Math.PI + 90;
      const previous = angles.get(card) ?? target;
      const angle = previous + ((((target - previous) % 360) + 540) % 360) - 180;
      angles.set(card, angle);
      card.style.setProperty('--motion-angle', `${angle.toFixed(1)}deg`);
      card.style.setProperty('--motion-glow', '1');
      glowing.add(card);
    }
  }

  function update(event) {
    if (reduced.matches || !precise.matches || document.hidden || event.pointerType === 'touch') {
      reset();
      return;
    }
    const target = event.target?.closest?.('[data-motion-surface]') || null;
    if (target !== surface) {
      release();
      if (target?.isConnected) {
        surface = target;
        bounds = surface.getBoundingClientRect();
      }
    }
    point = { x: event.clientX, y: event.clientY };
    if (frame) return;
    frame = window.requestAnimationFrame(() => {
      frame = 0;
      if (document.hidden || !point) {
        reset();
        return;
      }
      // El sondeo puede sustituir la superficie señalada; la siguiente la recibe sin reiniciar eventos.
      if (surface && !surface.isConnected) release();
      if (surface) {
        const x = Math.max(0, Math.min(bounds.width, point.x - bounds.left));
        const y = Math.max(0, Math.min(bounds.height, point.y - bounds.top));
        surface.style.setProperty('--motion-x', `${x}px`);
        surface.style.setProperty('--motion-y', `${y}px`);
        if (surface.hasAttribute('data-motion-tilt')) {
          surface.style.setProperty('--motion-rotate-x', `${(0.5 - y / (bounds.height || 1)) * TILT}deg`);
          surface.style.setProperty('--motion-rotate-y', `${(x / (bounds.width || 1) - 0.5) * TILT}deg`);
        }
      }
      glow();
    });
  }

  document.addEventListener('pointerover', update);
  document.addEventListener('pointermove', update);
  document.addEventListener('pointerout', event => {
    if (surface && !surface.contains(event.relatedTarget)) release();
    if (!event.relatedTarget) dim();
  });
  document.addEventListener('visibilitychange', reset);
  window.addEventListener('blur', reset);
  window.addEventListener('resize', reset);
  window.addEventListener('scroll', reset, { passive: true, capture: true });
  reduced.addEventListener('change', reset);
  precise.addEventListener('change', reset);
})();
