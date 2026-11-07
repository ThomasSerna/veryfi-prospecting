// DOM exclusivamente sintético: ejercita eventos reales del script sin red ni dependencias.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function navigationPage({ isMobile = false, withPreview = false, reducedMotion = false } = {}) {
  const document = { activeElement: null };
  function element() {
    const handlers = new Map();
    const attributes = new Map();
    return {
      dataset: {}, inert: false, open: false,
      addEventListener(type, callback) {
        handlers.set(type, [...(handlers.get(type) || []), callback]);
      },
      dispatch(type, event = {}) {
        for (const callback of handlers.get(type) || []) callback(event);
      },
      setAttribute: (name, value) => attributes.set(name, value),
      removeAttribute: name => attributes.delete(name),
      getAttribute: name => attributes.get(name) ?? null,
      getBoundingClientRect: () => ({ width: 288 }),
      closest: () => null,
      focus() { document.activeElement = this; },
    };
  }
  const body = element();
  const drawer = element();
  const menu = element();
  const sidebar = element();
  const workspace = element();
  const close = element();
  const backdrop = element();
  const firstLink = element();
  const lastLink = element();
  const focusable = [close, firstLink, lastLink];
  sidebar.contains = target => focusable.includes(target);
  sidebar.querySelectorAll = () => focusable;
  const mobile = { matches: isMobile, addEventListener() {} };
  const preview = element();
  const outputs = {};
  for (const name of ['countries', 'segments', 'max']) {
    outputs[name] = { textContent: '' };
    Object.defineProperty(outputs[name], 'innerHTML', {
      set() { assert.fail('El resumen debe escribir texto, nunca interpretar HTML.'); },
    });
  }
  const choices = [
    { name: 'countries', checked: true, label: ' Colombia ' },
    { name: 'countries', checked: false, label: ' México ' },
    { name: 'segments', checked: true, label: ' FinTech y software ' },
  ];
  choices.forEach(input => { input.closest = () => ({ textContent: input.label }); });
  const maximum = { value: '12' };
  preview.querySelector = selector => selector === '[name="max_companies"]' ? maximum
    : outputs[Object.keys(outputs).find(name => selector === `[data-preview-${name}]`)] ?? null;
  preview.querySelectorAll = selector => choices.filter(input =>
    selector === `input[name="${input.name}"]:checked` && input.checked);
  const events = element();
  Object.assign(document, {
    body,
    addEventListener: events.addEventListener,
    querySelector: selector => ({
      '.menu-toggle': menu, '.navigation-backdrop': backdrop, '.sidebar-close': close,
      '[data-campaign-preview]': withPreview ? preview : null,
    })[selector] ?? null,
    getElementById: id => ({ 'navigation-drawer': drawer, navigation: sidebar, 'workspace-main': workspace })[id] ?? null,
    querySelectorAll: () => [],
  });
  const timers = new Map();
  const pageEvents = element();
  let nextTimer = 0;
  const context = {
    document,
    window: {
      addEventListener: pageEvents.addEventListener,
      matchMedia: query => query === '(max-width: 760px)' ? mobile : { matches: reducedMotion },
      clearTimeout: id => timers.delete(id),
      setTimeout(callback, delay) { timers.set(++nextTimer, { callback, delay }); return nextTimer; },
    },
    navigator: {},
  };
  for (const script of ['app.js', 'navigation.js']) {
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, `../static/js/${script}`), 'utf8'), context);
  }
  return {
    body, drawer, menu, sidebar, workspace, close, backdrop, firstLink, lastLink, document, timers,
    preview, choices, maximum, outputs,
    click(target) {
      target.focus();
      const event = { target, preventDefault() {} };
      target.dispatch('click', event);
      events.dispatch('click', event);
    },
    key(key, shiftKey = false) {
      let prevented = false;
      events.dispatch('keydown', { key, shiftKey, preventDefault() { prevented = true; } });
      return prevented;
    },
    resize(matches) { mobile.matches = matches; },
    restorePage() { pageEvents.dispatch('pageshow', { persisted: true }); },
    finishClosing() {
      for (const [id, timer] of timers) { timers.delete(id); timer.callback(); }
    },
  };
}

for (const isMobile of [false, true]) {
  test(`El menú de ${isMobile ? 'móvil' : 'escritorio'} carga cerrado y aísla el fondo al abrir`, () => {
    const page = navigationPage({ isMobile });
    assert.equal(page.body.dataset.navOpen, 'false');
    assert.equal(page.menu.getAttribute('aria-expanded'), 'false');
    assert.equal(page.drawer.open, false);
    assert.equal(page.sidebar.inert, true);
    assert.equal(page.workspace.inert, false);
    for (const close of [() => page.key('Escape'), () => page.click(page.backdrop), () => page.click(page.close)]) {
      page.click(page.menu);
      assert.equal(page.body.dataset.navOpen, 'true');
      assert.equal(page.drawer.open, true);
      assert.equal(page.sidebar.getAttribute('role'), 'dialog');
      assert.equal(page.sidebar.getAttribute('aria-modal'), 'true');
      assert.equal(page.sidebar.inert, false);
      assert.equal(page.workspace.inert, true);
      assert.equal(page.document.activeElement, page.close);
      close();
      assert.equal(page.body.dataset.navOpen, 'false');
      assert.equal(page.menu.getAttribute('aria-expanded'), 'false');
      assert.equal(page.sidebar.inert, true);
      assert.equal(page.workspace.inert, false);
      assert.equal(page.document.activeElement, page.menu);
      assert.equal(page.sidebar.getAttribute('aria-modal'), null);
      assert.equal([...page.timers.values()][0].delay, 200);
      page.finishClosing();
      assert.equal(page.drawer.open, false);
    }
  });
}

test('Tab y Mayús+Tab circulan dentro del panel sin entrar al fondo', () => {
  const page = navigationPage();
  page.click(page.menu);
  page.lastLink.focus();
  assert.equal(page.key('Tab'), true);
  assert.equal(page.document.activeElement, page.close);
  assert.equal(page.key('Tab', true), true);
  assert.equal(page.document.activeElement, page.lastLink);
  page.firstLink.focus();
  assert.equal(page.key('Tab'), false);
  assert.equal(page.document.activeElement, page.firstLink);
});

test('El cambio de ancho conserva la decisión de abrir y cada carga comienza cerrada', () => {
  const page = navigationPage();
  page.resize(true);
  assert.equal(page.body.dataset.navOpen, 'false');
  assert.equal(page.sidebar.inert, true);
  assert.equal(page.workspace.inert, false);
  page.click(page.menu);
  page.resize(false);
  assert.equal(page.body.dataset.navOpen, 'true');
  assert.equal(page.sidebar.inert, false);
  assert.equal(page.workspace.inert, true);
  assert.equal(navigationPage().body.dataset.navOpen, 'false');
  page.restorePage();
  assert.equal(page.drawer.open, false);
  assert.equal(page.workspace.inert, false);
});

test('Reabrir durante la salida cancela el cierre pendiente', () => {
  const page = navigationPage();
  page.click(page.menu);
  page.click(page.close);
  assert.equal(page.drawer.open, true);
  page.click(page.menu);
  page.finishClosing();
  assert.equal(page.drawer.open, true);
  assert.equal(page.workspace.inert, true);
});

test('Movimiento reducido cierra sin esperar y un enlace operativo también cierra', () => {
  const page = navigationPage({ reducedMotion: true });
  page.click(page.menu);
  page.firstLink.closest = () => page.firstLink;
  page.sidebar.dispatch('click', { target: page.firstLink });
  assert.equal(page.drawer.open, false);
  assert.equal(page.workspace.inert, false);
  assert.equal(page.timers.size, 0);
});

test('El resumen actualiza países, segmentos y máximo como texto de sus etiquetas', () => {
  const page = navigationPage({ withPreview: true });
  assert.equal(page.outputs.countries.textContent, 'Colombia');
  assert.equal(page.outputs.segments.textContent, 'FinTech y software');
  assert.equal(page.outputs.max.textContent, '12');
  page.choices[1].checked = true;
  page.choices[1].label = '<img src=x onerror=alert(1)> etiqueta sintética';
  page.choices[2].checked = false;
  page.maximum.value = '';
  page.preview.dispatch('input');
  assert.equal(page.outputs.countries.textContent, 'Colombia, <img src=x onerror=alert(1)> etiqueta sintética');
  assert.equal(page.outputs.segments.textContent, 'Sin seleccionar');
  assert.equal(page.outputs.max.textContent, 'Sin definir');
  page.choices[0].checked = page.choices[1].checked = false;
  page.preview.dispatch('input');
  assert.equal(page.outputs.countries.textContent, 'Sin seleccionar');
});
