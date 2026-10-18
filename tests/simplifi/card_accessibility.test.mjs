import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js', import.meta.url), 'utf8'), {
  HTMLElement: class {}, window: {}, queueMicrotask,
  customElements: {get: () => undefined, define: (_name, type) => { Card = type; }},
});

// Model DOM replacement on polling, plus the native dialog's queued close event.
function fixture() {
  const c = Object.create(Card.prototype);
  let content, closeEvent;
  const root = {activeElement: null, addEventListener() {},
    querySelector: selector => selector === '#content' ? content : dialog};
  const button = (id, action = 'control', disabled = false) => ({
    tagName: 'BUTTON', dataset: {action, id}, disabled, isConnected: true,
    focus() { root.activeElement = this; },
  });
  const dialogButton = button('', 'close');
  const dialog = {open: false, shell: {},
    addEventListener(_event, handler) { closeEvent = handler; },
    querySelector(selector) { return selector === '.dialog-shell' ? this.shell : dialogButton; },
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
  Object.defineProperty(root, 'innerHTML', {set() {
    content = {buttons: [button('person-1'), button('person-2')],
      contains(node) { return this.buttons.includes(node); },
      querySelectorAll(selector) { return selector === 'button' ? this.buttons : []; },
      focus() { root.activeElement = this; },
      set innerHTML(_value) {
        this.buttons.forEach(b => { b.isConnected = false; });
        this.buttons = this.buttons.map(b => button(b.dataset.id, b.dataset.action, b.disabled));
      },
    };
  }});
  c.shadowRoot = root; c.config = {mode: 'family'};
  c.data = {revision: 1, fresh: true}; c.family = () => '';
  c.render();
  return {c, root, dialog, get content() { return content; },
    dispatchClose: () => closeEvent(), button};
}

test('Escape returns to the correct person after background DOM replacement', async () => {
  const f = fixture(), opener = f.content.buttons[1];
  opener.focus(); f.c.open('Person controls', 'form'); await Promise.resolve();
  f.c.render();
  assert.equal(opener.isConnected, false);
  f.dialog.close(); f.dispatchClose();
  assert.equal(f.root.activeElement, f.content.buttons[1]);
  assert.equal(f.root.activeElement.dataset.id, 'person-2');
});

test('pointer-opened dialogs retain their invoker when the browser does not focus clicked buttons', async () => {
  const f = fixture(), opener = f.content.buttons[1];
  f.c.control = () => f.c.open('Person controls', 'form');
  assert.equal(f.root.activeElement, null);
  await f.c.click({composedPath: () => [opener]});
  await Promise.resolve();
  f.c.render();
  f.dialog.close(); f.dispatchClose();
  assert.equal(f.root.activeElement, f.content.buttons[1]);
  assert.equal(f.root.activeElement.dataset.id, 'person-2');
});

test('explicit Cancel restores focus after its render and multi-step dialogs keep the original invoker', async () => {
  const f = fixture(); f.content.buttons[0].focus();
  f.c.open('Controls', 'form'); await Promise.resolve();
  f.c.open('Review', 'review'); await Promise.resolve();
  f.c.close(); f.dispatchClose();
  assert.equal(f.root.activeElement, f.content.buttons[0]);
  assert.equal(f.c._focusBefore, null);
});

test('removed or disabled invokers return to the dashboard, not another person', async () => {
  for (const disabled of [false, true]) {
    const f = fixture(); f.content.buttons[0].focus();
    f.c.open('Controls', 'form'); await Promise.resolve(); f.c.render();
    if (disabled) f.content.buttons[0].disabled = true;
    else f.content.buttons.shift();
    f.dialog.close(); f.dispatchClose();
    assert.equal(f.root.activeElement, f.content);
  }
});

test('late close events do not clear a newly opened dialog or steal its focus', async () => {
  const f = fixture(); f.content.buttons[0].focus();
  f.c.open('Controls', 'form'); await Promise.resolve();
  f.c.close(); f.content.buttons[1].focus();
  f.c.open('Other person', 'form', '', {kind: 'other'}); await Promise.resolve();
  const focus = f.root.activeElement; f.dispatchClose();
  assert.equal(f.root.activeElement, focus); assert.equal(f.c._modal.kind, 'other');
});

test('background focus matches the complete action, including duration and service', () => {
  const f = fixture();
  const quick = f.button('person-1', 'quick'); quick.dataset.service = 'pause'; quick.dataset.duration = '30';
  const wrong = f.button('person-1', 'quick'); wrong.dataset.service = 'allow'; wrong.dataset.duration = '30';
  f.content.buttons = [wrong, quick];
  assert.equal(f.c.focusButton(f.content, {...quick.dataset}), quick);
  assert.equal(f.c.focusButton(f.content, {action: 'quick', id: 'person-1'}), undefined);
});

test('repeated controls expose their target and preserve visible text and custom labels', () => {
  const c = Object.create(Card.prototype);
  c.data = {groups: [{id: 'person', name: 'A & "B"'}], rules: [{id: 'rule', name: 'Bedtime'}], devices: [{id: 'device', name: 'Tablet'}], probes: {video: {name: 'Video'}}};
  for (const action of ['detail', 'assign-group', 'quick', 'control'])
    assert.match(c.button('More', action, 'person'), /aria-label="More · A &amp; &quot;B&quot;"/);
  for (const action of ['rule-edit', 'rule-options', 'rule-toggle'])
    assert.match(c.button('Edit', action, 'rule'), /aria-label="Edit · Bedtime"/);
  assert.match(c.button('Details & assign', 'device', 'device'), /aria-label="Details &amp; assign · Tablet"/);
  for (const action of ['dns', 'probe-results', 'probe-edit'])
    assert.match(c.button('Results', action, 'video'), /aria-label="Results · Video"/);
  const custom = c.button('Edit', 'group-edit', 'person', 'aria-label="Custom label"');
  assert.equal((custom.match(/aria-label=/g) || []).length, 1);
  assert.match(custom, /aria-label="Custom label"/);
  assert.ok(!c.button('Refresh', 'refresh').includes('aria-label'));
});
