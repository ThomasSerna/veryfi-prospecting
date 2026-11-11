// Ficha y fuentes exclusivamente sintéticas: prueba el script completo sin red.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function companyPage(hash = '') {
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
  root.querySelector = selector => selector === '.tabs' ? tablist : null;
  const pageEvents = element();
  const location = { hash };
  Object.assign(document, {
    body: element(), addEventListener() {}, createElement: () => element(),
    querySelector: selector => selector === '[data-tabs]' ? root
      : panels.find(panel => selector === `#${panel.id}`) ?? null,
    querySelectorAll: () => [],
    getElementById: id => ({ evidence, 'source-synthetic': source })[id] ?? null,
  });
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), {
    document, navigator: {}, requestAnimationFrame: callback => callback(),
    window: {
      location, matchMedia: () => ({ matches: true }),
      addEventListener: pageEvents.addEventListener,
      history: { replaceState(_state, _title, hash) { location.hash = hash; } },
    },
  });
  return { tabs, panels, evidence, source, location, pageEvents, document };
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
