(() => {
  'use strict';

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const precise = window.matchMedia('(hover: hover) and (pointer: fine)');
  const properties = ['--motion-x', '--motion-y', '--motion-rotate-x', '--motion-rotate-y'];
  let surface = null;
  let bounds = null;
  let point = null;
  let frame = 0;

  function reset() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    if (surface) properties.forEach(name => surface.style.removeProperty(name));
    surface = bounds = point = null;
  }

  function update(event) {
    if (reduced.matches || !precise.matches || document.hidden || event.pointerType === 'touch') {
      reset();
      return;
    }
    const target = event.target?.closest?.('[data-motion-surface]');
    if (!target?.isConnected) {
      reset();
      return;
    }
    if (target !== surface) {
      reset();
      surface = target;
      bounds = surface.getBoundingClientRect();
    }
    point = { x: event.clientX, y: event.clientY };
    if (frame) return;
    frame = window.requestAnimationFrame(() => {
      frame = 0;
      if (!surface?.isConnected || document.hidden) {
        reset();
        return;
      }
      const x = Math.max(0, Math.min(bounds.width, point.x - bounds.left));
      const y = Math.max(0, Math.min(bounds.height, point.y - bounds.top));
      surface.style.setProperty('--motion-x', `${x}px`);
      surface.style.setProperty('--motion-y', `${y}px`);
      if (surface.hasAttribute('data-motion-tilt')) {
        surface.style.setProperty('--motion-rotate-x', `${(0.5 - y / (bounds.height || 1)) * 2.4}deg`);
        surface.style.setProperty('--motion-rotate-y', `${(x / (bounds.width || 1) - 0.5) * 2.4}deg`);
      }
    });
  }

  document.addEventListener('pointerover', update);
  document.addEventListener('pointermove', update);
  document.addEventListener('pointerout', event => {
    if (surface && !surface.contains(event.relatedTarget)) reset();
  });
  document.addEventListener('visibilitychange', reset);
  window.addEventListener('blur', reset);
  window.addEventListener('resize', reset);
  window.addEventListener('scroll', reset, { passive: true, capture: true });
  reduced.addEventListener('change', reset);
  precise.addEventListener('change', reset);
})();
