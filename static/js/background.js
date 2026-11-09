(() => {
  'use strict';

  const canvas = document.querySelector('.summary-background');
  const panel = document.querySelector('.home-panel');
  if (!canvas || !panel || canvas.dataset.backgroundInitialized) return;
  canvas.dataset.backgroundInitialized = 'true';

  // Shader de https://www.veryfi.com/, consultado el 2026-11-09; se conserva el clamp del hero.
  const fragment = `
precision highp float;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_rand;
uniform bool u_clamp;
float rand_counter = 0.;

float hash(float n) {
  return fract(sin(n)*43758.5453);
}
float random() {
  rand_counter += 0.5;
  return hash(rand_counter);
}
vec2 random_pos() {
  float rand_x = random();
  float rand_y = random();
  return vec2(0.5 - rand_x, 0.5 - rand_y);
}
float circle(vec2 res_ratio, vec2 st, vec2 pos, float radius, float opacity) {
  radius *= sin(u_time * random() + 4232.4 * random());
  radius = max(radius, u_clamp ? 0.8 : 0.4);
  pos *= vec2(sin(u_time * random()) * 2.8, cos(u_time * random()) * 1.4);
  opacity = 0.2 + opacity * random();
  if (u_clamp) {
    radius *= max(0.01, (0.5 - pos.y));
    opacity *= (0.5 - pos.y);
  }
  return max(0., (1. - smoothstep(0., radius, length(st - res_ratio / 2. + pos * res_ratio))) * opacity);
}
float layer(vec2 res_ratio, vec2 st) {
  float c = 0.;
  c += circle(res_ratio, st, vec2(0.0, 0.5), random() / 2.1, 0.4);
  c += circle(res_ratio, st, random_pos(), random() / 2.1, 0.3);
  c += circle(res_ratio, st, random_pos(), random() / 1.4, 0.2);
  c += circle(res_ratio, st, random_pos(), random() / 1.5, 0.1);
  return c;
}
void main() {
  rand_counter = u_rand;
  vec2 st = gl_FragCoord.xy/u_resolution.xy;
  vec2 res_ratio = vec2(u_resolution.x/u_resolution.y, 1);
  st *= res_ratio;
  vec4 color = vec4(23./255., 28./255., 58./255., 1.0);
  vec4 layer1 = vec4(vec3(0., 0.98, 0.42), layer(res_ratio, st));
  vec4 layer2 = vec4(vec3(.28, 1., 0.83), layer(res_ratio, st));
  color = mix(color, layer1, layer1.a);
  color = mix(color, layer2, layer2.a);
  gl_FragColor = color;
}`;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const forced = window.matchMedia('(forced-colors: active)');
  const seed = Math.random();
  const shaders = [];
  let gl = null;
  let program = null;
  let buffer = null;
  let uniforms = null;
  let observer = null;
  let failed = false;
  let inView = false;
  let frame = 0;
  let elapsed = 0;
  let startedAt = null;
  let lastDraw = -Infinity;
  let needsDraw = true;

  function pause() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    if (startedAt !== null) elapsed += performance.now() - startedAt;
    startedAt = null;
  }

  function fail() {
    pause();
    failed = true;
    canvas.hidden = true;
    observer?.disconnect();
    if (!gl) return;
    try {
      if (buffer) gl.deleteBuffer(buffer);
      if (program) gl.deleteProgram(program);
      shaders.forEach(shader => gl.deleteShader(shader));
    } catch (_) { /* Un contexto perdido puede rechazar también la liberación. */ }
  }

  function compile(type, source) {
    const shader = gl.createShader(type);
    if (!shader) throw new Error('No se pudo crear el shader');
    shaders.push(shader);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error('Shader incompatible');
    return shader;
  }

  function initialize() {
    if (program) return true;
    try {
      gl = canvas.getContext('webgl', { alpha: false, antialias: false });
      if (!gl) throw new Error('WebGL no disponible');
      const vertex = compile(gl.VERTEX_SHADER, 'attribute vec2 position; void main() { gl_Position = vec4(position, 0., 1.); }');
      const pixel = compile(gl.FRAGMENT_SHADER, fragment);
      program = gl.createProgram();
      if (!program) throw new Error('No se pudo crear el programa');
      gl.attachShader(program, vertex);
      gl.attachShader(program, pixel);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('Programa incompatible');
      buffer = gl.createBuffer();
      if (!buffer) throw new Error('No se pudo crear el búfer');
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
      gl.useProgram(program);
      const position = gl.getAttribLocation(program, 'position');
      if (position < 0) throw new Error('Atributo de posición no disponible');
      gl.enableVertexAttribArray(position);
      gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
      uniforms = Object.fromEntries(['u_resolution', 'u_time', 'u_rand', 'u_clamp'].map(name => [name, gl.getUniformLocation(program, name)]));
      gl.uniform1f(uniforms.u_rand, seed);
      gl.uniform1i(uniforms.u_clamp, 1);
      return true;
    } catch (_) {
      fail();
      return false;
    }
  }

  function draw(time, now) {
    try {
      const width = Math.max(1, Math.round(window.innerWidth / 15));
      const height = Math.max(1, Math.round(window.innerHeight / 15));
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(uniforms.u_resolution, width, height);
      gl.uniform1f(uniforms.u_time, time * 0.00025);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      if (gl.getError() !== gl.NO_ERROR) throw new Error('Error al dibujar WebGL');
      canvas.hidden = false;
      needsDraw = false;
      lastDraw = now;
    } catch (_) { fail(); }
  }

  function animate(now) {
    frame = 0;
    if (failed || startedAt === null) return;
    if (now - lastDraw >= 1000 / 30) draw(elapsed + now - startedAt, now);
    if (!failed) frame = window.requestAnimationFrame(animate);
  }

  function synchronize() {
    pause();
    if (failed) return;
    if (forced.matches) {
      canvas.hidden = true;
      return;
    }
    if (!inView || document.hidden || !initialize()) return;
    const now = performance.now();
    if (needsDraw || canvas.hidden) draw(elapsed, now);
    if (!failed && !reduced.matches) {
      startedAt = now;
      frame = window.requestAnimationFrame(animate);
    }
  }

  canvas.addEventListener('webglcontextlost', fail);
  document.addEventListener('visibilitychange', synchronize);
  window.addEventListener('resize', () => {
    needsDraw = true;
    if (startedAt === null) synchronize();
  });
  [reduced, forced].forEach(query => query.addEventListener('change', synchronize));
  observer = new IntersectionObserver(entries => {
    inView = entries.some(entry => entry.target === panel && entry.isIntersecting);
    synchronize();
  });
  observer.observe(panel);
})();
