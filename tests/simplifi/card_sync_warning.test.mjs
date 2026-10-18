import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js', import.meta.url), 'utf8'), {
  HTMLElement: class {}, window: {},
  customElements: {get: () => undefined, define: (_name, type) => { Card = type; }},
});

test('an unconfirmed sync explains its actual reason without assuming a read failure', () => {
  const c = Object.create(Card.prototype);
  c.data = {fresh: false, issue: 'Gateway timezone/schedule parity must be confirmed before recurring writes'};
  const html = c.warnings();
  assert.ok(html.includes(c.data.issue));
  assert.match(html, /role="status"/);
  assert.ok(!html.includes('until the gateway can be read'));
  assert.equal(c.disabled, true);
});

test('backend reasons remain text and absent reasons use an honest stale-confirmation fallback', () => {
  const c = Object.create(Card.prototype);
  c.data = {fresh: false, issue: '<img src=x onerror="bad()">'};
  assert.ok(!c.warnings().includes('<img'));
  assert.match(c.warnings(), /&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  for (const issue of [null, '', '  ', {}]) {
    c.data.issue = issue;
    assert.match(c.warnings(), /confirmation is unavailable or stale/);
  }
});

test('current confirmation clears the warning and transport errors retain priority', () => {
  const c = Object.create(Card.prototype);
  c.data = {fresh: true, issue: 'Old sync failure'};
  assert.equal(c.warnings(), '');
  c.data.fresh = false;
  c._error = 'HA connection lost';
  assert.match(c.warnings(), /role="alert"/);
  assert.ok(c.warnings().includes(c._error));
  assert.ok(!c.warnings().includes(c.data.issue));
});
