// Dos curvas sintéticas permiten medir el desplazamiento sin navegador ni proveedores.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/js/summary-map.js'), 'utf8');

function mapPage(scale = 1) {
  const curves = [72, 240].map(y => {
    const original = `M0 ${y} C128 ${y} 256 ${y} 384 ${y}`;
    return { d: original, getAttribute() { return this.d; }, setAttribute(_, d) { this.d = d; } };
  });
  const box = { left: 10, top: 20, width: 384 * scale, height: 300 * scale };
  const sea = {
    viewBox: { baseVal: { width: 384 } },
    getBoundingClientRect: () => ({ ...box, right: box.left + box.width, bottom: box.top + box.height }),
    querySelectorAll: () => curves,
  };
  const document = Object.assign(new EventTarget(), {
    documentElement: new EventTarget(), querySelector: () => sea,
  });
  const media = Object.assign(new EventTarget(), { matches: true });
  const frames = new Map();
  let nextId = 0;
  let time = 0;
  const window = Object.assign(new EventTarget(), {
    matchMedia: () => media,
    requestAnimationFrame(callback) { frames.set(++nextId, callback); return nextId; },
    cancelAnimationFrame(id) { frames.delete(id); },
  });
  vm.runInNewContext(source, { document, window });
  const resting = curves.map(curve => curve.d);
  function tick() {
    assert.equal(frames.size, 1);
    const [[id, callback]] = frames;
    frames.delete(id);
    callback(time += 16);
  }
  function hover(pointerType = 'mouse') {
    document.dispatchEvent(Object.assign(new Event('pointermove'), {
      pointerType, clientX: box.left + 192 * scale, clientY: box.top + 72 * scale - 24,
    }));
  }
  function settle() {
    for (let i = 0; frames.size && i < 150; i++) tick();
    assert.equal(frames.size, 0, 'El mapa en reposo debe dejar de solicitar fotogramas');
  }
  return { curves, resting, document, media, frames, hover, settle, tick };
}

for (const scale of [.5, 1.5]) {
  test(`Las curvas se apartan pocos píxeles y recuperan su trazo a escala ${scale}`, () => {
    const { curves: [near, far], resting, document, hover, settle, tick } = mapPage(scale);
    function shifts() {
      const coords = near.d.slice(1).trim().split(/[C,\s]+/).map(Number);
      const offsets = [];
      // La cúbica horizontal tiene controles equidistantes también después de subdividirla.
      for (let i = 0; i < coords.length; i += 2) {
        const x = 384 * i / (coords.length - 2);
        const y = (coords[i + 1] - 72) * scale;
        assert.ok(y >= 0, 'La curva debe alejarse del puntero situado encima');
        const offset = Math.hypot((coords[i] - x) * scale, y);
        if (Math.abs(x - 192) * scale > 72) assert.equal(offset, 0);
        offsets.push(offset);
      }
      return Math.max(...offsets);
    }
    hover();
    tick();
    const first = shifts();
    settle();
    const peak = shifts();
    assert.ok(first > 0 && first < peak);
    assert.ok(peak > 6 && peak <= 7.002, `Separación máxima en píxeles CSS: ${peak}`);
    assert.equal(far.d, resting[1]);
    document.documentElement.dispatchEvent(new Event('pointerleave'));
    tick();
    const returning = shifts();
    assert.ok(returning > 0 && returning < peak);
    settle();
    assert.equal(near.d, resting[0]);
  });
}

test('El tacto conserva el mapa estático y un cambio de preferencia cancela el movimiento', () => {
  const { curves, resting, media, frames, hover, tick } = mapPage();
  hover('touch');
  assert.equal(frames.size, 0);
  hover();
  tick();
  assert.notEqual(curves[0].d, resting[0]);
  media.matches = false;
  media.dispatchEvent(new Event('change'));
  hover();
  assert.equal(frames.size, 0);
  assert.equal(curves[0].d, resting[0]);
});

test('El dibujo local contiene corrientes abiertas con coordenadas cúbicas absolutas', () => {
  const svg = fs.readFileSync(path.join(__dirname, '../templates/components/_summary_currents.svg'), 'utf8');
  const paths = [...svg.matchAll(/<path\b[^>]*\bd="([^"]+)"/g)];
  assert.ok(paths.length > 1);
  for (const [, d] of paths) {
    assert.match(d, /^M/);
    const [start, ...cubics] = d.slice(1).split('C').map(group => group.trim().split(/[,\s]+/).map(Number));
    assert.equal(start.length, 2);
    assert.ok(start.every(Number.isFinite) && cubics.length > 0);
    assert.ok(cubics.every(points => points.length % 6 === 0 && points.every(Number.isFinite)));
  }
});
