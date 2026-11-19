(() => {
  'use strict';

  const sea = document.querySelector('.summary-currents');
  if (!sea) return;
  const motion = window.matchMedia('(any-hover: hover) and (any-pointer: fine) and (prefers-reduced-motion: no-preference) and (forced-colors: none)');
  const radius = 72;
  const maxShift = 7;
  let curves = [];
  let pointer;
  let frame = 0;
  let previous = 0;

  // Subdividir con De Casteljau conserva el trazo original y permite doblar sólo un tramo corto.
  const middle = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const distance = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
  function subdivide(a, b, c, d, points) {
    if (distance(a, b) + distance(b, c) + distance(c, d) <= 28) {
      points.push(...b, ...c, ...d);
      return;
    }
    const ab = middle(a, b), bc = middle(b, c), cd = middle(c, d);
    const left = middle(ab, bc), right = middle(bc, cd), mid = middle(left, right);
    subdivide(a, ab, left, mid, points);
    subdivide(mid, right, cd, d, points);
  }

  function pathData(points) {
    const coords = points.map(value => Math.round(value * 1000) / 1000);
    return 'M' + coords[0] + ' ' + coords[1] + 'C' + coords.slice(2).join(' ');
  }

  function prepare(path) {
    // El dibujo local usa una M absoluta seguida de curvas C.
    const values = path.getAttribute('d').trim().slice(1).trim().split(/[C,\s]+/).map(Number);
    const points = values.slice(0, 2);
    for (let i = 2; i < values.length; i += 6) {
      subdivide(values.slice(i - 2, i), values.slice(i, i + 2), values.slice(i + 2, i + 4), values.slice(i + 4, i + 6), points);
    }
    // La misma subdivisión en reposo evita que el antialiasing cambie lejos del ratón.
    const rest = pathData(points);
    path.setAttribute('d', rest);
    return { path, rest, points, current: points.slice(), bent: false };
  }

  function draw(time) {
    frame = 0;
    const elapsed = previous ? Math.min(time - previous, 64) : 16;
    const ease = 1 - Math.exp(-elapsed / (pointer ? 65 : 95));
    let moving = false;
    for (const curve of curves) {
      const { path, points, current } = curve;
      if (!pointer && !curve.bent) continue;
      let bent = false;
      for (let i = 0; i < points.length; i += 2) {
        const x = points[i], y = points[i + 1];
        const dx = pointer ? x - pointer.x : 0;
        const dy = pointer ? y - pointer.y : 0;
        const fraction = pointer ? Math.hypot(dx, dy) / pointer.radius : 1;
        // t(1-t)² alcanza 4/27 en t=1/3. La separación máxima se mantiene en píxeles de pantalla.
        const force = fraction < 1 ? (27 / 4) * (maxShift / radius) * (1 - fraction) ** 2 : 0;
        const goalX = x + dx * force, goalY = y + dy * force;
        const stepX = goalX - current[i], stepY = goalY - current[i + 1];
        if (Math.abs(stepX) + Math.abs(stepY) > .025) {
          current[i] += ease * stepX;
          current[i + 1] += ease * stepY;
          moving = true;
        } else {
          current[i] = goalX;
          current[i + 1] = goalY;
        }
        if (current[i] !== x || current[i + 1] !== y) bent = true;
      }
      if (bent) {
        path.setAttribute('d', pathData(current));
      } else if (curve.bent) {
        path.setAttribute('d', curve.rest);
      }
      curve.bent = bent;
    }
    previous = moving ? time : 0;
    if (moving) frame = window.requestAnimationFrame(draw);
  }

  function schedule() {
    if (!frame) frame = window.requestAnimationFrame(draw);
  }

  function release() {
    if (!pointer) return;
    pointer = null;
    schedule();
  }

  function reset() {
    window.cancelAnimationFrame(frame);
    frame = previous = 0;
    pointer = null;
    for (const curve of curves) {
      if (!curve.bent) continue;
      curve.path.setAttribute('d', curve.rest);
      curve.current = curve.points.slice();
      curve.bent = false;
    }
  }

  function syncMotion() {
    reset();
    if (motion.matches && !curves.length) curves = Array.from(sea.querySelectorAll('path'), prepare);
  }

  document.addEventListener('pointermove', event => {
    if (!motion.matches || document.hidden || event.pointerType !== 'mouse') return release();
    const box = sea.getBoundingClientRect();
    if (!box.width || event.clientX < box.left || event.clientX >= box.right ||
        event.clientY < box.top || event.clientY >= box.bottom) return release();
    const units = sea.viewBox.baseVal.width / box.width;
    pointer = { x: (event.clientX - box.left) * units, y: (event.clientY - box.top) * units, radius: radius * units };
    schedule();
  }, { passive: true });
  document.documentElement.addEventListener('pointerleave', release);
  document.addEventListener('pointercancel', release);
  document.addEventListener('visibilitychange', reset);
  window.addEventListener('blur', reset);
  window.addEventListener('resize', reset);
  motion.addEventListener('change', syncMotion);
  syncMotion();
})();
