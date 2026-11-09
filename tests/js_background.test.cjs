// DOM y WebGL sintéticos: verifica el ciclo decorativo sin red ni GPU.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/js/background.js'), 'utf8');

function harness(options = {}) {
  const listeners = new Map();
  const events = target => ({
    addEventListener(name, callback) { listeners.set(`${target}:${name}`, callback); },
  });
  const frames = new Map();
  const draws = [];
  const shaders = [];
  const deleted = [];
  const uniforms = {};
  const media = new Map();
  let now = 0;
  let nextFrame = 0;
  let randomCalls = 0;
  let contexts = 0;
  let observer;
  const gl = {
    VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
    ARRAY_BUFFER: 5, STATIC_DRAW: 6, FLOAT: 7, TRIANGLES: 8, NO_ERROR: 0,
    createShader: type => ({ type }),
    shaderSource(shader, text) { shaders.push({ type: shader.type, text }); },
    compileShader() {},
    getShaderParameter: () => !options.compileFailure,
    createProgram: () => ({}),
    attachShader() {}, linkProgram() {},
    getProgramParameter: () => !options.linkFailure,
    createBuffer: () => ({}),
    bindBuffer() {}, bufferData() {}, useProgram() {},
    getAttribLocation: () => 0,
    enableVertexAttribArray() {}, vertexAttribPointer() {},
    getUniformLocation: (_, name) => name,
    uniform1f(name, value) { uniforms[name] = value; },
    uniform1i(name, value) { uniforms[name] = value; },
    uniform2f(name, x, y) { uniforms[name] = [x, y]; },
    viewport() {},
    drawArrays() {
      if (options.drawThrows) throw new Error('GPU sintética no disponible');
      draws.push({ ...uniforms, at: now, hiddenDuringDraw: canvas.hidden });
    },
    getError: () => options.drawError ? 1282 : 0,
    deleteShader: () => deleted.push('shader'),
    deleteProgram: () => deleted.push('program'),
    deleteBuffer: () => deleted.push('buffer'),
  };
  const canvas = {
    ...events('canvas'), dataset: {}, hidden: true, width: 300, height: 150,
    getContext(type, settings) {
      contexts++;
      assert.equal(type, 'webgl');
      assert.equal(settings.alpha, false);
      if (options.contextThrows) throw new Error('Contexto sintético bloqueado');
      return options.noContext ? null : gl;
    },
  };
  const panel = {};
  const document = {
    ...events('document'), hidden: false,
    querySelector: selector => selector === '.summary-background' ? canvas : panel,
  };
  const window = {
    ...events('window'), innerWidth: 1500, innerHeight: 900,
    matchMedia(query) {
      const key = query.includes('reduced-motion') ? 'reduced' : query.includes('forced-colors') ? 'forced' : 'touch';
      const result = { ...events(key), matches: Boolean(options[key]) };
      media.set(key, result);
      return result;
    },
    requestAnimationFrame(callback) {
      frames.set(++nextFrame, callback);
      return nextFrame;
    },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  const math = Object.create(Math);
  math.random = () => { randomCalls++; return 0.375; };
  const context = vm.createContext({
    document, window, Math: math, performance: { now: () => now },
    IntersectionObserver: class {
      constructor(callback) { observer = callback; }
      observe(target) { assert.equal(target, panel); }
      disconnect() {}
    },
  });
  const run = () => vm.runInContext(source, context);
  run();
  return {
    canvas, document, window, draws, shaders, deleted, frames, run,
    get randomCalls() { return randomCalls; },
    get contexts() { return contexts; },
    clock(time) { now = time; },
    visible(value) { observer([{ target: panel, isIntersecting: value }]); },
    hidden(value) { document.hidden = value; listeners.get('document:visibilitychange')(); },
    media(key, value) { media.get(key).matches = value; listeners.get(`${key}:change`)(); },
    resize(width, height) {
      window.innerWidth = width;
      window.innerHeight = height;
      listeners.get('window:resize')();
    },
    lost() { listeners.get('canvas:webglcontextlost')(); },
    step(time) {
      now = time;
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach(callback => callback(time));
      assert.ok(frames.size <= 1, 'Solo debe existir un ciclo de animación');
    },
  };
}

test('Inicia una vez al entrar en pantalla y conserva shader, clamp y semilla del original', () => {
  const h = harness();
  assert.equal(h.contexts, 0);
  assert.equal(h.canvas.hidden, true);
  h.visible(true);
  assert.equal(h.draws[0].hiddenDuringDraw, true);
  assert.equal(h.canvas.hidden, false);
  assert.equal(h.draws[0].u_rand, 0.375);
  assert.equal(h.draws[0].u_clamp, 1);
  const fragment = h.shaders.find(shader => shader.type === 2).text;
  assert.match(fragment, /smoothstep\(0\., radius/);
  assert.match(fragment, /rand_counter \+= 0\.5/);
  assert.match(fragment, /vec4\(23\.\/255\., 28\.\/255\., 58\.\/255\., 1\.0\)/);
  assert.match(fragment, /vec3\(0\., 0\.98, 0\.42\)/);
  assert.match(fragment, /vec3\(\.28, 1\., 0\.83\)/);
  assert.equal((fragment.match(/c \+= circle/g) || []).length, 4);
  h.run();
  h.visible(true);
  h.step(40);
  h.resize(900, 600);
  h.step(80);
  assert.equal(h.randomCalls, 1);
  assert.equal(h.contexts, 1);
  assert.ok(h.draws.every(draw => draw.u_rand === 0.375));
  assert.equal(h.frames.size, 1);
});

test('Limita dibujos a 30 fps y avanza a la velocidad original solo durante tiempo activo', () => {
  const h = harness();
  h.visible(true);
  [16, 32, 34, 50, 68, 100].forEach(time => h.step(time));
  assert.deepEqual(h.draws.map(draw => draw.at), [0, 34, 68]);
  assert.equal(h.draws[2].u_time, 68 * 0.00025);
  h.hidden(true);
  assert.equal(h.frames.size, 0);
  h.clock(10000);
  h.hidden(false);
  h.step(10034);
  assert.equal(h.draws.at(-1).u_time, 134 * 0.00025);
  h.clock(10050);
  h.visible(false);
  assert.equal(h.frames.size, 0);
  h.clock(20000);
  h.visible(true);
  h.step(20034);
  assert.equal(h.draws.at(-1).u_time, 184 * 0.00025);
});

test('Redimensiona a viewport/15 sin DPR, con mínimo un píxel y sin reiniciar semilla', () => {
  const h = harness();
  h.visible(true);
  assert.equal(h.canvas.width, 100);
  assert.equal(h.canvas.height, 60);
  h.resize(1001, 701);
  h.step(40);
  assert.equal(h.canvas.width, 67);
  assert.equal(h.canvas.height, 47);
  assert.deepEqual(Array.from(h.draws.at(-1).u_resolution), [67, 47]);
  h.resize(0, 1);
  h.step(80);
  assert.equal(h.canvas.width, 1);
  assert.equal(h.canvas.height, 1);
  assert.equal(h.randomCalls, 1);
});

test('Movimiento reducido: composición estática, redibujo al cambiar tamaño y reacción a preferencias', () => {
  const h = harness({ reduced: true });
  h.visible(true);
  assert.equal(h.draws.length, 1);
  assert.equal(h.frames.size, 0);
  h.clock(10000);
  h.resize(900, 600);
  assert.equal(h.draws.length, 2);
  assert.equal(h.draws[1].u_time, 0);
  assert.equal(h.frames.size, 0);
  h.media('reduced', false);
  h.step(10040);
  assert.equal(h.draws.at(-1).u_time, 40 * 0.00025);
  h.media('reduced', true);
  assert.equal(h.frames.size, 0);
  h.clock(20000);
  h.resize(1200, 800);
  assert.equal(h.draws.at(-1).u_time, 40 * 0.00025);
});

test('El puntero táctil conserva el movimiento de las dos capas del fondo', () => {
  const h = harness({ touch: true });
  h.visible(true);
  h.step(40);
  assert.equal(h.frames.size, 1);
  assert.equal(h.draws.length, 2);
  assert.equal(h.draws[1].u_time, 40 * 0.00025);
  assert.equal(h.draws[0].u_rand, h.draws[1].u_rand);
});

test('Colores forzados oculta y detiene, incluida la activación y desactivación posterior', () => {
  const h = harness({ forced: true });
  h.visible(true);
  assert.equal(h.contexts, 0);
  assert.equal(h.canvas.hidden, true);
  assert.equal(h.frames.size, 0);
  h.clock(10000);
  h.media('forced', false);
  assert.equal(h.canvas.hidden, false);
  h.step(10040);
  h.media('forced', true);
  assert.equal(h.canvas.hidden, true);
  assert.equal(h.frames.size, 0);
  h.clock(20000);
  h.media('forced', false);
  assert.equal(h.draws.at(-1).u_time, 40 * 0.00025);
  assert.equal(h.contexts, 1);
});

for (const failure of ['noContext', 'contextThrows', 'compileFailure', 'linkFailure', 'drawThrows', 'drawError']) {
  test(`${failure}: conserva el fondo habitual sin dibujar o reintentar`, () => {
    const h = harness({ [failure]: true });
    h.visible(true);
    assert.equal(h.canvas.hidden, true);
    assert.equal(h.frames.size, 0);
    h.visible(false);
    h.visible(true);
    h.resize(1200, 800);
    assert.equal(h.contexts, 1);
    assert.equal(h.frames.size, 0);
    if (!['noContext', 'contextThrows'].includes(failure)) assert.ok(h.deleted.includes('shader'));
  });
}

test('La pérdida del contexto oculta el canvas y cancela el único ciclo sin recuperarlo', () => {
  const h = harness();
  h.visible(true);
  h.step(40);
  h.lost();
  assert.equal(h.canvas.hidden, true);
  assert.equal(h.frames.size, 0);
  assert.deepEqual(h.deleted, ['buffer', 'program', 'shader', 'shader']);
  h.hidden(true);
  h.hidden(false);
  h.visible(true);
  h.resize(800, 600);
  h.step(80);
  assert.equal(h.draws.length, 2);
  assert.equal(h.contexts, 1);
});
