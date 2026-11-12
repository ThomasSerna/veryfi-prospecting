// Ficha y fuentes exclusivamente sintéticas: prueba el script completo sin red.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function companyPage(hash = '', { running = false, disabled = false } = {}) {
  const document = { activeElement: null };
  function element(id) {
    const attributes = new Map();
    const handlers = new Map();
    return {
      id, dataset: {}, hidden: false, open: false,
      style: { removeProperty(name) { delete this[name]; } },
      setAttribute: (name, value) => attributes.set(name, value),
      getAttribute: name => attributes.get(name) ?? null,
      addEventListener(type, callback) { handlers.set(type, callback); },
      dispatch(type, event = {}) { handlers.get(type)?.(event); },
      append() {}, getBoundingClientRect: () => ({}),
      querySelector: () => null, querySelectorAll: () => [],
      closest: () => null, animate() {},
      focus() { document.activeElement = this; },
      scrollIntoView() { this.scrolled = true; },
    };
  }
  const panels = [element('summary'), element('contacts')];
  const tabs = panels.map(panel => {
    const tab = element(`tab-${panel.id}`);
    tab.setAttribute('href', `#${panel.id}`);
    return tab;
  });
  const evidence = element('evidence');
  const source = element('source-synthetic');
  const tablist = element();
  tablist.querySelectorAll = () => tabs;
  const root = element();
  const confirmation = element('employment-synthetic');
  const ancestor = element('contact-checks');
  const field = element('source-url');
  confirmation.matches = selector => selector === 'details' || selector === 'details[data-actionable]';
  confirmation.contains = target => [field, confirmation].includes(target);
  confirmation.parentElement = { closest: () => ancestor };
  confirmation.querySelector = selector => {
    assert.ok(selector.includes(':not(:disabled)'));
    return disabled ? null : field;
  };
  const channelConfirmation = element('channel-synthetic-0');
  Object.assign(channelConfirmation, {
    matches: confirmation.matches, querySelector: confirmation.querySelector,
  });
  root.contains = target => [confirmation, channelConfirmation].includes(target);
  const link = element();
  link.setAttribute('href', '#employment-synthetic');
  link.closest = selector => selector === '[data-confirmation-link]' ? link : null;
  root.querySelector = selector => selector === '.tabs' ? tablist
    : selector === '[data-confirmation-link][href="#employment-synthetic"]:not([aria-disabled="true"])'
      && link.getAttribute('aria-disabled') !== 'true' ? link : null;
  const cancel = element();
  cancel.closest = selector => selector === '[data-close-confirmation]' ? cancel
    : selector === 'details[data-actionable]' ? confirmation : null;
  const pageEvents = element();
  const location = { hash };
  Object.assign(document, {
    body: element(), addEventListener() {}, createElement: () => element(),
    querySelector: selector => selector === '[data-tabs]' ? root
      : panels.find(panel => selector === `#${panel.id}`) ?? null,
    querySelectorAll: () => [],
    getElementById: id => ({ evidence, 'source-synthetic': source,
      'employment-synthetic': confirmation, 'channel-synthetic-0': channelConfirmation })[id] ?? null,
  });
  document.body.dataset.running = String(running);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), {
    document, navigator: {}, requestAnimationFrame: callback => callback(),
    window: {
      location, matchMedia: () => ({ matches: true }),
      addEventListener: pageEvents.addEventListener,
      history: { replaceState(_state, _title, hash) { location.hash = hash; } },
    },
  });
  return { tabs, panels, evidence, source, location, pageEvents, document,
    root, confirmation, channelConfirmation, ancestor, field, link, cancel };
}

test('Las fuentes se abren desde su enlace sin convertirlas en una tercera pestaña', () => {
  const page = companyPage('#evidence');
  assert.equal(page.evidence.open, true);
  assert.equal(page.tabs.length, 2);
  assert.equal(page.panels[0].hidden, false);
  assert.equal(page.panels[1].hidden, true);
});

test('Una referencia guardada abre las fuentes y desplaza al hecho citado', () => {
  const page = companyPage('#source-synthetic');
  assert.equal(page.evidence.open, true);
  assert.equal(page.source.scrolled, true);
  assert.equal(page.panels[0].hidden, false);
});

test('Abrir una fuente desde Contactos conserva el contexto de la persona', () => {
  const page = companyPage('#contacts');
  page.location.hash = '#source-synthetic';
  page.pageEvents.dispatch('hashchange');
  assert.equal(page.evidence.open, true);
  assert.equal(page.panels[1].hidden, false);
  assert.equal(page.source.scrolled, true);
});

test('El teclado alterna únicamente Resumen y Contactos y conserva el foco', () => {
  const page = companyPage();
  page.tabs[0].dispatch('keydown', { key: 'ArrowRight', preventDefault() {} });
  assert.equal(page.document.activeElement, page.tabs[1]);
  assert.equal(page.location.hash, '#contacts');
  assert.equal(page.panels[1].hidden, false);
  page.tabs[1].dispatch('keydown', { key: 'ArrowRight', preventDefault() {} });
  assert.equal(page.document.activeElement, page.tabs[0]);
  assert.equal(page.location.hash, '#summary');
});

test('Confirmar empleo abre el formulario y sus detalles, y enfoca el primer campo editable', () => {
  const page = companyPage();
  page.root.dispatch('click', { target: page.link, preventDefault() {} });
  assert.equal(page.root.dataset.confirmationsEnhanced, 'true');
  assert.equal(page.confirmation.open, true);
  assert.equal(page.ancestor.open, true);
  assert.equal(page.confirmation.scrolled, true);
  assert.equal(page.document.activeElement, page.field);
  assert.equal(page.panels[1].hidden, false);
  assert.equal(page.location.hash, '#employment-synthetic');
  page.confirmation.open = false;
  page.root.dispatch('click', { target: page.link, preventDefault() {} });
  assert.equal(page.confirmation.open, true);
});

test('Los enlaces guardados de empleo y canal abren Contactos y el formulario correspondiente', () => {
  for (const hash of ['#employment-synthetic', '#channel-synthetic-0']) {
    const page = companyPage(hash);
    assert.equal(page.panels[1].hidden, false);
    assert.equal(page.document.activeElement, page.field);
    assert.equal(hash.startsWith('#employment') ? page.confirmation.open : page.channelConfirmation.open, true);
  }
});

test('Una investigación en curso bloquea la apertura por enlace y por hash', () => {
  const page = companyPage('#employment-synthetic', { running: true });
  page.root.dispatch('click', { target: page.link, preventDefault() {} });
  assert.equal(page.confirmation.open, false);
  assert.equal(page.document.activeElement, null);
});

test('Los enlaces deshabilitados y los eventos ya atendidos no abren una confirmación', () => {
  const page = companyPage();
  page.link.setAttribute('aria-disabled', 'true');
  page.root.dispatch('click', { target: page.link, preventDefault() {} });
  assert.equal(page.confirmation.open, false);
  page.link.setAttribute('aria-disabled', 'false');
  page.root.dispatch('click', { target: page.link, defaultPrevented: true, preventDefault() {} });
  assert.equal(page.confirmation.open, false);
});

test('Los campos deshabilitados quedan fuera del foco al mostrar una confirmación no elegible', () => {
  const page = companyPage('#channel-synthetic-0', { disabled: true });
  assert.equal(page.channelConfirmation.open, true);
  assert.equal(page.document.activeElement, null);
});

test('Cancelar pliega el formulario sin guardar ni borrar sus datos y devuelve el foco a la acción', () => {
  const page = companyPage('#employment-synthetic');
  page.field.value = 'Fuente sintética pendiente de guardar';
  let prevented = false;
  page.root.dispatch('click', { target: page.cancel, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(page.confirmation.open, false);
  assert.equal(page.document.activeElement, page.link);
  assert.equal(page.field.value, 'Fuente sintética pendiente de guardar');
  assert.equal(page.location.hash, '#employment-synthetic');
});

test('Plegar con el resumen devuelve el foco si iba a quedar dentro de un formulario oculto', () => {
  const page = companyPage('#employment-synthetic');
  page.confirmation.open = false;
  page.root.dispatch('toggle', { target: page.confirmation });
  assert.equal(page.document.activeElement, page.link);
});

test('El cierre de otro formulario no roba el foco fuera de sus detalles', () => {
  const page = companyPage('#employment-synthetic');
  page.tabs[1].focus();
  page.confirmation.open = false;
  page.root.dispatch('toggle', { target: page.confirmation });
  assert.equal(page.document.activeElement, page.tabs[1]);
});
