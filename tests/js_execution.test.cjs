// DOM y respuestas exclusivamente sintéticos; no abre conexiones ni un navegador.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function executionPage(status, isExecuting, { html = '', parsed = null, live = null, main = null, morphing = null } = {}) {
  let submit;
  let active = isExecuting;
  let reloads = 0;
  const calls = [];
  const timers = [];
  const attributes = new Map();
  const button = { tagName: 'BUTTON', disabled: false, getAttribute: () => null };
  const link = {
    tagName: 'A',
    getAttribute: name => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: name => attributes.delete(name),
  };
  const fieldset = { disabled: false };
  const page = { dataset: { running: 'false', statusUrl: '/status/' } };
  const form = {
    action: '/execute/', querySelector: () => null,
    addEventListener: (event, callback) => { if (event === 'submit') submit = callback; },
  };
  const elements = {
    'campaign-page': page, 'execution-form': form, main,
    'campaign-live': live || { querySelector: () => null, querySelectorAll: () => [] },
    'execution-feedback': { replaceChildren() {}, append() {} },
  };
  const context = {
    document: {
      body: { dataset: {} }, activeElement: null,
      querySelector: () => null, addEventListener() {},
      getElementById: id => elements[id] ?? null, createElement: () => ({}),
      querySelectorAll: selector => selector === '[data-idle-only]' ? [button, link]
        : selector === '[data-idle-form] fieldset' ? [fieldset] : [],
    },
    DOMParser: parsed ? class { parseFromString() { return parsed; } } : undefined,
    window: {
      matchMedia: () => ({ matches: false }),
      setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout() {},
      location: { search: '', href: '/campaigns/sintetica/', reload: () => { reloads++; } },
      ...(morphing && { ProspectingLive: morphing }),
    },
    FormData: class { get() { return 'csrf-exclusivamente-sintetico'; } },
    fetch: async url => {
      calls.push(url);
      if (url === '/campaigns/sintetica/') return { ok: true, text: async () => '<main>Página sintética</main>' };
      return { ok: url === '/status/' || status < 400, json: async () => ({
        is_executing: url === '/status/' ? active : isExecuting,
        error_message: 'Respuesta exclusivamente sintética.',
        html: url === '/status/' ? html : '',
      }) };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), context);
  return { button, link, fieldset, page, calls, timers, document: context.document,
    submit: () => submit({ preventDefault() {} }),
    stop: () => { active = false; }, reloads: () => reloads };
}

test('Un rechazo 400 sin ejecución permite corregir y reenviar', async () => {
  const page = executionPage(400, false);
  await page.submit();
  assert.equal(page.button.disabled, false);
  assert.equal(page.fieldset.disabled, false);
  assert.equal(page.link.getAttribute('aria-disabled'), null);
  assert.equal(page.page.dataset.running, 'false');
  assert.deepEqual(page.calls, ['/execute/']);
  assert.equal(page.timers.length, 0);
  await page.submit();
  assert.equal(page.calls.length, 2);
});

test('Un rechazo 409 mantiene el bloqueo, consulta el estado y evita otro envío', async () => {
  const page = executionPage(409, true);
  await page.submit();
  await new Promise(setImmediate);
  assert.equal(page.button.disabled, true);
  assert.equal(page.fieldset.disabled, true);
  assert.equal(page.link.getAttribute('aria-disabled'), 'true');
  assert.equal(page.link.getAttribute('tabindex'), '-1');
  assert.equal(page.page.dataset.running, 'true');
  assert.deepEqual(page.calls, ['/execute/', '/status/']);
  assert.equal(page.timers.length, 1);
  await page.submit();
  assert.equal(page.calls.length, 2);
  page.stop();
  await page.timers.shift()();
  assert.equal(page.reloads(), 1);
  assert.equal(page.timers.length, 0);
});

test('El sondeo compara cada sección en su sitio y, al terminar, actualiza la página sin recargarla', async () => {
  const updates = [];
  const morphing = {
    update: (current, next) => updates.push([current.name, next.name]),
    morph: (current, next) => updates.push([current.name, next.name]),
  };
  const section = name => ({
    name, dataset: { liveSection: name },
    replaceWith() { assert.fail('El sondeo no debe reemplazar secciones que puede comparar.'); },
  });
  const sections = [section('overview'), section('results')];
  const live = { querySelector: () => null, querySelectorAll: selector => selector === '[data-live-section]' ? sections : [] };
  const nextMain = { name: 'main-nuevo', querySelector: selector => selector === '#campaign-page' ? {} : null };
  const parsed = {
    body: { dataset: { running: 'false' } },
    querySelector: selector => {
      const match = /data-live-section="([\w-]+)"/.exec(selector);
      return match ? { name: `${match[1]}-nuevo` } : null;
    },
    getElementById: id => id === 'main' ? nextMain : null,
  };
  const page = executionPage(409, true, { html: '<section>Instantánea sintética</section>', parsed, live, main: { name: 'main' }, morphing });
  await page.submit();
  await new Promise(setImmediate);
  assert.deepEqual(updates, [['overview', 'overview-nuevo'], ['results', 'results-nuevo']]);
  page.stop();
  await page.timers.shift()();
  assert.equal(page.reloads(), 0);
  assert.deepEqual(updates.at(-1), ['main', 'main-nuevo']);
  assert.deepEqual(page.calls, ['/execute/', '/status/', '/status/', '/campaigns/sintetica/']);
  assert.equal(page.document.body.dataset.running, 'false');
  assert.equal(page.timers.length, 0);
});
