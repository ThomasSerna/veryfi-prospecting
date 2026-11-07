// DOM exclusivamente sintético: ejercita eventos reales del script sin red ni dependencias.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function navigationPage(isMobile = false, withPreview = false) {
  const document = { activeElement: null };
  function element() {
    const handlers = new Map();
    const attributes = new Map();
    return {
      dataset: {}, inert: false, hidden: false,
      addEventListener(type, callback) {
        handlers.set(type, [...(handlers.get(type) || []), callback]);
      },
      dispatch(type, event = {}) {
        for (const callback of handlers.get(type) || []) callback(event);
      },
      setAttribute: (name, value) => attributes.set(name, value),
      getAttribute: name => attributes.get(name) ?? null,
      closest: () => null,
      focus() { document.activeElement = this; },
    };
  }
  const body = element();
  const menu = element();
  const sidebar = element();
  const workspace = element();
  const close = element();
  const backdrop = element();
  const firstLink = element();
  const lastLink = element();
  const focusable = [firstLink, close, lastLink];
  sidebar.contains = target => focusable.includes(target);
  sidebar.querySelectorAll = () => focusable;
  const mobile = { matches: isMobile, addEventListener: (_, callback) => { mobile.change = callback; } };
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
    getElementById: id => ({ navigation: sidebar, 'workspace-main': workspace })[id] ?? null,
    querySelectorAll: () => [],
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), {
    document,
    window: { matchMedia: query => query === '(max-width: 760px)' ? mobile : { matches: false } },
    navigator: {},
  });
  return {
    body, menu, sidebar, workspace, close, backdrop, firstLink, lastLink, document,
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
    resize(matches) { mobile.matches = matches; mobile.change(); },
  };
}

test('Escritorio conserva el espacio de trabajo operable al contraer la navegación', () => {
  const page = navigationPage();
  assert.equal(page.body.dataset.navOpen, 'true');
  assert.equal(page.menu.getAttribute('aria-expanded'), 'true');
  assert.equal(page.sidebar.inert, false);
  assert.equal(page.workspace.inert, false);
  assert.equal(page.backdrop.hidden, true);
  page.click(page.menu);
  assert.equal(page.body.dataset.navOpen, 'false');
  assert.equal(page.menu.getAttribute('aria-expanded'), 'false');
  assert.equal(page.sidebar.inert, true);
  assert.equal(page.workspace.inert, false);
  page.click(page.menu);
  assert.equal(page.sidebar.inert, false);
  assert.equal(page.workspace.inert, false);
});

test('El cajón móvil aísla el foco y devuelve el control al cerrar por sus tres vías', () => {
  const page = navigationPage(true);
  assert.equal(page.sidebar.inert, true);
  assert.equal(page.workspace.inert, false);
  assert.equal(page.backdrop.hidden, true);
  for (const close of [() => page.key('Escape'), () => page.click(page.backdrop), () => page.click(page.close)]) {
    page.click(page.menu);
    assert.equal(page.body.dataset.navOpen, 'true');
    assert.equal(page.sidebar.inert, false);
    assert.equal(page.workspace.inert, true);
    assert.equal(page.backdrop.hidden, false);
    assert.equal(page.document.activeElement, page.close);
    close();
    assert.equal(page.body.dataset.navOpen, 'false');
    assert.equal(page.sidebar.inert, true);
    assert.equal(page.workspace.inert, false);
    assert.equal(page.backdrop.hidden, true);
    assert.equal(page.document.activeElement, page.menu);
  }
});

test('Tab y Mayús+Tab circulan dentro del cajón móvil abierto', () => {
  const page = navigationPage(true);
  page.click(page.menu);
  page.lastLink.focus();
  assert.equal(page.key('Tab'), true);
  assert.equal(page.document.activeElement, page.firstLink);
  assert.equal(page.key('Tab', true), true);
  assert.equal(page.document.activeElement, page.lastLink);
  page.close.focus();
  assert.equal(page.key('Tab'), false);
  assert.equal(page.document.activeElement, page.close);
});

test('El cambio de ancho restablece el cajón móvil y la navegación de escritorio', () => {
  const page = navigationPage();
  page.resize(true);
  assert.equal(page.body.dataset.navOpen, 'false');
  assert.equal(page.sidebar.inert, true);
  assert.equal(page.workspace.inert, false);
  page.click(page.menu);
  page.resize(false);
  assert.equal(page.body.dataset.navOpen, 'true');
  assert.equal(page.sidebar.inert, false);
  assert.equal(page.workspace.inert, false);
  assert.equal(page.backdrop.hidden, true);
});

test('El resumen actualiza países, segmentos y máximo como texto de sus etiquetas', () => {
  const page = navigationPage(false, true);
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
