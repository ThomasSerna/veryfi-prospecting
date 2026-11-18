(() => {
  'use strict';

  const art = document.querySelector('.spotlight-art');
  if (!art) return;
  const stage = art.parentElement;
  const image = art.querySelector('img');
  const canvas = art.querySelector('canvas');
  const context = canvas.getContext('2d');
  if (!context) return;

  const hover = window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)');
  const { width, height } = canvas;
  // shortcut: silueta calibrada para la imagen actual, volver a trazar si cambia el mapa.
  const land = new Path2D('M438 22 724 20 790 80 855 105 877 150 870 193 927 207 952 248 1008 271 1063 291 1060 333 1027 358 1021 392 992 425 948 435 916 471 880 507 858 538 829 549 814 580 806 615 834 630 805 659 750 650 728 610 734 536 748 463 754 404 741 383 708 364 677 294 680 245 704 211 670 211 639 176 579 160 514 142 469 102Z');
  const water = new Path2D(land);
  water.rect(0, 0, width, height);

  let pixels;
  let target;
  let center;
  let amount = 0;
  let frame = 0;
  let previous = 0;

  function nearRay(x, y, tolerance) {
    for (let row = Math.max(0, y - tolerance); row <= Math.min(height - 1, y + tolerance); row++) {
      for (let col = Math.max(0, x - tolerance); col <= Math.min(width - 1, x + tolerance); col++) {
        const index = 4 * (row * width + col);
        if (pixels[index + 1] - pixels[index] >= 17 && !context.isPointInPath(land, col, row)) return true;
      }
    }
    return false;
  }

  function draw(time) {
    frame = 0;
    const elapsed = previous ? Math.min(time - previous, 32) : 16;
    const goal = target ? 1 : 0;
    amount += (goal - amount) * (1 - Math.exp(-elapsed / 62));
    const settled = Math.abs(goal - amount) < .015;
    if (settled) amount = goal;
    if (target) center = target;
    context.clearRect(0, 0, width, height);

    if (amount) {
      const { x, y, scale } = center;
      const radius = 64 / scale;
      const offset = 5 * amount / scale;
      context.save();
      context.clip(water, 'evenodd');
      context.beginPath();
      context.arc(x, y, radius, 0, 2 * Math.PI);
      context.clip();
      context.translate(offset, -offset * .62);
      context.clip(water, 'evenodd');
      context.drawImage(image, 0, 0, width, height);
      context.translate(-offset, offset * .62);
      const falloff = context.createRadialGradient(x, y, radius * .2, x, y, radius);
      falloff.addColorStop(0, '#000');
      falloff.addColorStop(1, 'transparent');
      context.globalCompositeOperation = 'destination-in';
      context.fillStyle = falloff;
      context.fillRect(x - radius, y - radius, radius * 2, radius * 2);
      context.restore();
    }

    previous = settled ? 0 : time;
    if (!settled) frame = window.requestAnimationFrame(draw);
  }

  function rest() {
    if (frame) window.cancelAnimationFrame(frame);
    if (amount) context.clearRect(0, 0, width, height);
    frame = previous = amount = 0;
    target = center = null;
  }

  stage.addEventListener('pointermove', event => {
    target = null;
    if (hover.matches && event.pointerType === 'mouse' && image.naturalWidth && !art.closest('[data-entering]')) {
      const box = art.getBoundingClientRect();
      const { clientX, clientY } = event;
      if (clientX >= box.left && clientX < box.right && clientY >= box.top && clientY < box.bottom) {
        const scale = Math.max(box.width / width, box.height / height);
        const anchorY = parseFloat(getComputedStyle(image).objectPosition.split(' ')[1]) / 100;
        const x = Math.floor((clientX - box.right + width * scale) / scale);
        const y = Math.floor((clientY - box.top + (height * scale - box.height) * anchorY) / scale);
        if (!context.isPointInPath(land, x, y)) {
          if (!pixels) {
            context.drawImage(image, 0, 0, width, height);
            pixels = context.getImageData(0, 0, width, height).data;
            context.clearRect(0, 0, width, height);
          }
          if (nearRay(x, y, Math.ceil(5 / scale))) target = { x, y, scale };
        }
      }
    }
    if ((target || amount) && !frame) frame = window.requestAnimationFrame(draw);
  });

  stage.addEventListener('pointerleave', () => {
    target = null;
    if (amount && !frame) frame = window.requestAnimationFrame(draw);
  });
  hover.addEventListener('change', rest);
  window.addEventListener('blur', rest);
  window.addEventListener('resize', rest);
  window.addEventListener('scroll', rest, { passive: true });
})();
