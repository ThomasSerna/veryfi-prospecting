// DOM exclusivamente sintético: comprueba movimiento delegado sin red ni dependencias.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function motionPage({ reduced = false, precise = true } = {}) {
  function events() {
    const handlers = new Map();
    return {
      addEventListener(name, callback) {
        handlers.set(name, [...(handlers.get(name) || []), callback]);
      },
      dispatch(name, event = {}) {
        for (const callback of handlers.get(name) || []) callback(event);
      },
    };
  }
  const document = { ...events(), hidden: false };
  const reducedQuery = { ...events(), matches: reduced };
  const preciseQuery = { ...events(), matches: precise };
  const frames = new Map();
  let nextFrame = 0;
  const window = {
    ...events(),
    matchMedia: query => query.includes('reduced-motion') ? reducedQuery : preciseQuery,
    requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/motion.js'), 'utf8'), { document, window });
  function surface(tilt = false, box = { left: 10, top: 20, width: 200, height: 100 }) {
    const styles = new Map();
    const target = {
      isConnected: true,
      measurements: 0,
      styles,
      style: { setProperty: (name, value) => styles.set(name, value), removeProperty: name => styles.delete(name) },
      hasAttribute: name => name === 'data-motion-tilt' && tilt,
      getBoundingClientRect() { this.measurements += 1; return box; },
      closest: () => target,
      contains: node => node === target || node?.parent === target,
    };
    return target;
  }
  return {
    document, window, reducedQuery, preciseQuery, frames, surface,
    pointer(type, target, x = 110, y = 70, extra = {}) {
      document.dispatch(type, { target, clientX: x, clientY: y, pointerType: 'mouse', ...extra });
    },
    flush() {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach(callback => callback());
    },
  };
}

test('El seguimiento agrupa movimientos por cuadro y limita la inclinación del bento', () => {
  const page = motionPage();
  const card = page.surface(true);
  const child = { parent: card, closest: () => card };
  page.pointer('pointerover', card);
  page.pointer('pointermove', child, 160, 95);
  page.pointer('pointermove', child, 300, -10);
  assert.equal(page.frames.size, 1);
  assert.equal(card.measurements, 1);
  page.flush();
  assert.equal(card.styles.get('--motion-x'), '200px');
  assert.equal(card.styles.get('--motion-y'), '0px');
  assert.equal(card.styles.get('--motion-rotate-x'), '1.5deg');
  assert.equal(card.styles.get('--motion-rotate-y'), '1.5deg');
  page.pointer('pointerout', child, 0, 0, { relatedTarget: card });
  assert.equal(card.styles.size, 4);
  page.pointer('pointerout', card, 0, 0, { relatedTarget: null });
  assert.equal(card.styles.size, 0);
});

test('Los paneles sustituidos por sondeo reciben los efectos sin reinicializar eventos', () => {
  const page = motionPage();
  const oldCard = page.surface();
  page.pointer('pointerover', oldCard);
  oldCard.isConnected = false;
  page.flush();
  assert.equal(oldCard.styles.size, 0);
  const replacement = page.surface();
  page.pointer('pointermove', replacement, 60, 50);
  page.flush();
  assert.equal(replacement.styles.get('--motion-x'), '50px');
  assert.equal(replacement.styles.get('--motion-y'), '30px');
  assert.equal(replacement.styles.has('--motion-rotate-x'), false);
});

test('Movimiento reducido y puntero táctil retiran seguimiento incluso al cambiar durante la sesión', () => {
  const page = motionPage({ reduced: true });
  const card = page.surface(true);
  page.pointer('pointerover', card);
  assert.equal(page.frames.size, 0);
  page.reducedQuery.matches = false;
  page.reducedQuery.dispatch('change');
  page.pointer('pointermove', card);
  page.flush();
  assert.equal(card.styles.size, 4);
  page.preciseQuery.matches = false;
  page.preciseQuery.dispatch('change');
  assert.equal(card.styles.size, 0);
  page.pointer('pointermove', card);
  assert.equal(page.frames.size, 0);
  page.preciseQuery.matches = true;
  page.preciseQuery.dispatch('change');
  page.pointer('pointermove', card, 110, 70, { pointerType: 'touch' });
  assert.equal(page.frames.size, 0);
});

test('Scroll, resize y pestaña oculta cancelan cuadros pendientes y retiran coordenadas obsoletas', () => {
  const page = motionPage();
  const card = page.surface(true);
  for (const event of ['scroll', 'resize', 'blur']) {
    page.pointer('pointerover', card);
    page.window.dispatch(event);
    assert.equal(page.frames.size, 0);
    assert.equal(card.styles.size, 0);
  }
  page.pointer('pointermove', card);
  page.flush();
  assert.equal(card.styles.size, 4);
  page.document.hidden = true;
  page.document.dispatch('visibilitychange');
  assert.equal(card.styles.size, 0);
  page.pointer('pointermove', card);
  assert.equal(page.frames.size, 0);
});

test('El borde de las superficies cercanas apunta al puntero por el camino más corto y se apaga al alejarse', () => {
  const page = motionPage();
  const near = page.surface();
  const far = page.surface(false, { left: 1000, top: 20, width: 200, height: 100 });
  page.document.querySelectorAll = () => [near, far];
  const background = { closest: () => null };
  page.pointer('pointermove', background, 110, 0);
  page.flush();
  assert.equal(near.styles.get('--motion-glow'), '1');
  assert.equal(near.styles.get('--motion-angle'), '0.0deg');
  assert.equal(near.styles.has('--motion-x'), false);
  assert.equal(far.styles.has('--motion-glow'), false);
  page.pointer('pointermove', background, -20, 70);
  page.flush();
  assert.equal(near.styles.get('--motion-angle'), '-90.0deg');
  page.pointer('pointermove', background, 600, 900);
  page.flush();
  assert.equal(near.styles.has('--motion-glow'), false);
  page.pointer('pointermove', background, 110, 0);
  page.window.dispatch('blur');
  assert.equal(near.styles.has('--motion-glow'), false);
  assert.equal(page.frames.size, 0);
});
