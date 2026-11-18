// DOM exclusivamente sintético: ejercita eventos reales del script sin red ni dependencias.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function navigationPage({ withPreview = false, withDropdowns = false } = {}) {
  const document = { activeElement: null };
  function element() {
    const handlers = new Map();
    const attributes = new Map();
    return {
      dataset: {}, open: false,
      addEventListener(type, callback) {
        handlers.set(type, [...(handlers.get(type) || []), callback]);
      },
      dispatch(type, event = {}) {
        for (const callback of handlers.get(type) || []) callback(event);
      },
      setAttribute: (name, value) => attributes.set(name, value),
      removeAttribute: name => attributes.delete(name),
      getAttribute: name => attributes.get(name) ?? null,
      closest: () => null,
      focus() { document.activeElement = this; },
    };
  }
  const body = element();
  const outsideLink = element();
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
  const dropdowns = [element(), element()];
  const summaries = [element(), element()];
  const downloadLink = element();
  dropdowns.forEach((dropdown, index) => {
    dropdown.closest = () => dropdown;
    dropdown.contains = target => target === summaries[index] || (index === 1 && target === downloadLink);
    dropdown.querySelector = () => summaries[index];
  });
  downloadLink.closest = selector => selector === 'a[aria-disabled="true"]'
    ? (downloadLink.getAttribute('aria-disabled') === 'true' ? downloadLink : null)
    : selector === 'a:not([aria-disabled="true"])' && downloadLink.getAttribute('aria-disabled') !== 'true'
      ? downloadLink : null;
  Object.assign(document, {
    body,
    addEventListener: events.addEventListener,
    querySelector: selector => selector === '[data-campaign-preview]' && withPreview ? preview : null,
    getElementById: () => null,
    querySelectorAll: selector => withDropdowns && selector === '.filter-choice details[open], .download-menu[open]'
      ? dropdowns.filter(dropdown => dropdown.open) : [],
  });
  const context = {
    document,
    window: { matchMedia: () => ({ matches: false }) },
    navigator: {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), context);
  return {
    outsideLink, document,
    preview, choices, maximum, outputs,
    dropdowns, summaries, downloadLink,
    openDropdown(index) {
      dropdowns[index].open = true;
      events.dispatch('toggle', { target: dropdowns[index] });
    },
    click(target) {
      target.focus();
      let prevented = false;
      const event = { target, preventDefault() { prevented = true; } };
      target.dispatch('click', event);
      events.dispatch('click', event);
      return prevented;
    },
    key(key) { events.dispatch('keydown', { key }); },
  };
}

test('Descargas y filtros cierran al elegir, señalar fuera o pulsar Escape; una opción deshabilitada no descarga', () => {
  const page = navigationPage({ withDropdowns: true });
  page.openDropdown(0);
  page.openDropdown(1);
  assert.equal(page.dropdowns[0].open, false);
  page.summaries[1].focus();
  page.key('Escape');
  assert.equal(page.dropdowns[1].open, false);
  assert.equal(page.document.activeElement, page.summaries[1]);
  page.openDropdown(1);
  page.click(page.outsideLink);
  assert.equal(page.dropdowns[1].open, false);
  page.openDropdown(1);
  page.downloadLink.setAttribute('aria-disabled', 'true');
  assert.equal(page.click(page.downloadLink), true);
  assert.equal(page.dropdowns[1].open, true);
  page.downloadLink.removeAttribute('aria-disabled');
  assert.equal(page.click(page.downloadLink), false);
  assert.equal(page.dropdowns[1].open, false);
  assert.equal(page.document.activeElement, page.summaries[1]);
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
