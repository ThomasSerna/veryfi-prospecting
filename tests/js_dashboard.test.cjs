// DOM exclusivamente sintético: el sondeo del resumen actualiza en su sitio, sin red ni navegador.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class FakeNode {
  constructor(nodeType, nodeName, nodeValue = null) {
    Object.assign(this, { nodeType, nodeName, nodeValue, parentNode: null, childNodes: [], attrs: new Map(), style: {}, animations: [] });
  }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(child => child.textContent).join(''); }
  get attributes() { return Array.from(this.attrs, ([name, value]) => ({ name, value })); }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] || null; }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  removeAttribute(name) { this.attrs.delete(name); }
  hasAttribute(name) { return this.attrs.has(name); }
  insertBefore(node, reference) {
    node.remove();
    this.childNodes.splice(reference ? this.childNodes.indexOf(reference) : this.childNodes.length, 0, node);
    node.parentNode = this;
    return node;
  }
  remove() {
    if (this.parentNode) this.parentNode.childNodes.splice(this.parentNode.childNodes.indexOf(this), 1);
    this.parentNode = null;
  }
  cloneNode(deep) {
    const copy = new FakeNode(this.nodeType, this.nodeName, this.nodeValue);
    this.attrs.forEach((value, name) => copy.attrs.set(name, value));
    if (deep) this.childNodes.forEach(child => copy.insertBefore(child.cloneNode(true), null));
    return copy;
  }
  getBoundingClientRect() { return { height: 24 }; }
  animate(frames) {
    this.animations.push(frames);
    return { finished: Promise.resolve() };
  }
}

function h(name, attributes = {}, children = []) {
  const node = new FakeNode(1, name.toUpperCase());
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  children.forEach(child => node.insertBefore(typeof child === 'string' ? new FakeNode(3, '#text', child) : child, null));
  return node;
}

function loadLive(reducedMotion = false) {
  const context = {
    module: {},
    document: { importNode: (node, deep) => node.cloneNode(deep) },
    window: { matchMedia: () => ({ matches: reducedMotion }), setTimeout },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8'), context);
  return context.module.exports;
}

function dashboard({ completed = 1, total = 2, reviewing = false } = {}) {
  return h('div', { 'data-live-region': 'dashboard' }, [
    h('div', { class: 'review-spread' }, [
      h('section', { class: 'review-lead' }, [
        h('h1', { id: 'lead-title' }, [reviewing ? 'Empresa sintética' : 'Colombia']),
        ...(reviewing ? [h('p', { class: 'lead-identity' }, ['Colombia'])] : []),
        h('a', { class: 'button review-action', href: reviewing ? '/companies/sintetica/' : '/campaigns/sintetica/' },
          [reviewing ? 'Retomar revisión' : 'Seguir investigación']),
      ]),
      h('section', { class: 'campaign-print' }, [
        h('progress', { value: completed, max: total }),
      ]),
    ]),
  ]);
}

test('Al terminar, el sondeo conserva el control y actualiza su acción, empresa y progreso', () => {
  const { morph } = loadLive();
  const current = dashboard();
  const [lead, ledger] = current.firstChild.childNodes;
  const action = lead.childNodes[1];
  const progress = ledger.firstChild;
  morph(current, dashboard({ reviewing: true, completed: 3, total: 3 }));
  assert.equal(current.firstChild.firstChild, lead);
  assert.equal(lead.firstChild.firstChild.nodeValue, 'Empresa sintética');
  assert.equal(lead.childNodes[1].firstChild.nodeValue, 'Colombia');
  assert.equal(lead.childNodes[2], action);
  assert.equal(action.firstChild.nodeValue, 'Retomar revisión');
  assert.equal(action.getAttribute('href'), '/companies/sintetica/');
  assert.equal(ledger.firstChild, progress);
  assert.equal(progress.getAttribute('value'), '3');
  assert.equal(progress.getAttribute('max'), '3');
});

function table(order, labels = {}) {
  return h('tbody', {}, order.flatMap(id => ['\n  ', h('tr', { 'data-key': id }, [
    h('td', {}, [labels[id] || `Empresa sintética ${id}`]),
  ])]).concat('\n'));
}

test('Una empresa que sube en el orden se traslada sin recrear las filas que deja atrás', () => {
  const { morph } = loadLive();
  const current = table(['a', 'b', 'c']);
  const rows = Object.fromEntries(current.childNodes.filter(node => node.nodeType === 1)
    .map(node => [node.getAttribute('data-key'), node]));
  morph(current, table(['c', 'a', 'b'], { c: 'Empresa sintética c · Alta' }));
  const order = current.childNodes.filter(node => node.nodeType === 1);
  assert.deepEqual(order.map(node => node.getAttribute('data-key')), ['c', 'a', 'b']);
  assert.deepEqual(order, [rows.c, rows.a, rows.b]);
  assert.equal(rows.c.childNodes[0].childNodes[0].nodeValue, 'Empresa sintética c · Alta');
});

test('Solo un cambio de fila recibe énfasis y se respeta el movimiento reducido', () => {
  for (const reducedMotion of [false, true]) {
    const { update } = loadLive(reducedMotion);
    const current = table(['a', 'b']);
    const rows = current.childNodes.filter(node => node.nodeName === 'TR');
    current.querySelectorAll = () => rows;
    update(current, table(['a', 'b'], { b: 'Cambio sintético' }));
    assert.deepEqual(rows.map(row => row.animations.length), [0, reducedMotion ? 0 : 1]);
    assert.equal(rows[1].firstChild.firstChild.nodeValue, 'Cambio sintético');
  }
});

test('El servidor conserva un desplegable abierto por la persona', () => {
  const { morph } = loadLive();
  const details = h('details', { class: 'budget-details', open: '' }, [h('summary', {}, ['Cuentas'])]);
  const page = h('div', { id: 'campaign-page' }, [details]);
  const current = h('main', {}, [page]);
  const incoming = h('main', {}, [h('div', { id: 'campaign-page' }, [
    h('details', { class: 'budget-details' }, [h('summary', {}, ['Cuentas'])]),
  ])]);
  morph(current, incoming);
  assert.equal(current.childNodes[0], page);
  assert.equal(page.childNodes[0], details);
  assert.equal(details.hasAttribute('open'), true);
});

test('El sondeo actualiza su región y se detiene al finalizar la ejecución', async () => {
  const root = h('div', { 'data-live-region': 'dashboard' }, [h('span', {}, ['0'])]);
  root.dataset = { liveRegion: 'dashboard' };
  root.querySelectorAll = () => [];
  root.querySelector = () => null;
  const timers = [];
  let polls = 0;
  const document = {
    body: { dataset: { running: 'true' } },
    querySelector: () => root,
    querySelectorAll: selector => selector === '[data-live-region]' ? [root] : [],
    importNode: (node, deep) => node.cloneNode(deep),
  };
  const context = {
    document,
    window: {
      location: { href: 'http://127.0.0.1/synthetic/' },
      matchMedia: () => ({ matches: false }),
      setTimeout: callback => timers.push(callback),
    },
    fetch: async () => ({ ok: true, text: async () => 'Respuesta exclusivamente sintética' }),
    DOMParser: class {
      parseFromString() {
        polls++;
        const next = h('div', { 'data-live-region': 'dashboard' }, [h('span', {}, [String(polls)])]);
        return { body: { dataset: { running: polls === 1 ? 'true' : 'false' } }, querySelector: () => next };
      }
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8'), context);
  await timers.shift()();
  await timers.shift()();
  assert.equal(root.firstChild.firstChild.nodeValue, '2');
  assert.equal(timers.length, 0);
});
