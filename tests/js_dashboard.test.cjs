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

function loadMorph() {
  const context = {
    module: {},
    document: { importNode: (node, deep) => node.cloneNode(deep) },
    window: { matchMedia: () => ({ matches: false }), setTimeout },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/dashboard.js'), 'utf8'), context);
  return context.module.exports.morph;
}

function dashboard({ notice = true, completed = 1, segments = 2, review = 'La revisión se habilita al terminar', style = null } = {}) {
  const feature = h('section', { class: 'home-feature surface is-live', 'data-motion-surface': '', ...(style && { style }) }, [
    h('span', { class: 'progress-figure-value', 'data-value': completed }, [String(completed)]),
    h('div', { class: 'progress-segments' }, Array.from({ length: segments }, (_, index) =>
      h('span', { class: `progress-segment${index < completed ? ' is-done' : ''}`, style: `--i: ${index}` }))),
  ]);
  return h('div', { 'data-live-region': 'dashboard' }, [
    '\n  ',
    ...(notice ? [h('div', { class: 'notice notice-info', role: 'status' }, ['Investigación en curso.']), '\n  '] : []),
    h('div', { class: 'home-bento' }, [feature, h('span', { class: 'home-metric-note' }, [review])]),
    '\n',
  ]);
}

test('Una lectura igual en estructura conserva cada nodo y solo cambia cifras y estados', () => {
  const morph = loadMorph();
  const current = dashboard({ style: '--motion-x: 40px' });
  const feature = current.childNodes[3].childNodes[0];
  const figure = feature.childNodes[0];
  const segments = feature.childNodes[1].childNodes.slice();
  const entered = [];
  morph(current, dashboard({ completed: 2 }), entered);
  assert.equal(current.childNodes[3].childNodes[0], feature);
  assert.equal(feature.childNodes[0], figure);
  assert.deepEqual(feature.childNodes[1].childNodes, segments);
  assert.equal(figure.getAttribute('data-value'), '2');
  assert.equal(figure.childNodes[0].nodeValue, '2');
  assert.equal(segments[1].getAttribute('class'), 'progress-segment is-done');
  // El estilo que escribe el puntero sobrevive si el servidor no envía uno propio.
  assert.equal(feature.getAttribute('style'), '--motion-x: 40px');
  assert.deepEqual(entered, []);
});

test('Al terminar, el aviso sale animado, llegan empresas y enlace nuevos y lo existente no se recrea', async () => {
  const morph = loadMorph();
  const current = dashboard();
  const bento = current.childNodes[3];
  const feature = bento.childNodes[0];
  const indicator = h('span', { class: 'delta-chip', 'data-morph-skip': '' }, ['+1']);
  feature.childNodes[0].insertBefore(indicator, null);
  const notice = current.childNodes[1];
  const link = h('a', { class: 'text-link', href: '/companies/sintetica/' }, ['Revisar siguiente']);
  const entered = [];
  morph(current, dashboard({ notice: false, completed: 3, segments: 4, review: link, style: '--count: 4' }), entered);
  assert.equal(notice.hasAttribute('data-morph-skip'), true);
  assert.equal(notice.animations.length, 1);
  await new Promise(setImmediate);
  assert.equal(notice.parentNode, null);
  assert.equal(current.childNodes.filter(node => node.nodeType === 1)[0], bento);
  assert.equal(bento.childNodes[0], feature);
  assert.equal(feature.getAttribute('style'), '--count: 4');
  assert.equal(feature.childNodes[0].childNodes.includes(indicator), true);
  const added = entered.filter(node => node.nodeType === 1).map(node => node.getAttribute('class'));
  assert.deepEqual(added, ['progress-segment is-done', 'progress-segment', 'text-link']);
  assert.deepEqual(bento.childNodes[1].childNodes.map(node => node.nodeName), ['A']);
  assert.equal(feature.childNodes[1].childNodes.filter(node => node.getAttribute('class').includes('is-done')).length, 3);
});
