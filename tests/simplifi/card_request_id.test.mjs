import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(
  new URL("../../custom_components/simplifi/frontend/simplifi-card.js", import.meta.url),
  "utf8",
);
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

// Exercise the actual card Save path, replacing only browser/HA boundaries.
function cardWithCrypto(crypto) {
  let Card;
  vm.runInNewContext(source, {
    crypto,
    HTMLElement: class {},
    window: {},
    customElements: {
      get: () => undefined,
      define: (_name, card) => { Card = card; },
    },
  });
  const requests = [];
  const errors = [];
  const button = { disabled: false };
  const card = Object.create(Card.prototype);
  Object.assign(card, {
    config: { entry_id: "test-entry" },
    data: { now: "2026-10-18T12:00:00Z" },
    shadowRoot: { querySelectorAll: () => [button] },
    _hass: {
      callWS: async (request) => {
        requests.push(request);
        return { response: { change: { id: "saved-change" } } };
      },
    },
    refresh: async () => {},
    render: () => {},
    showError: (error) => errors.push(error),
  });
  return { card, requests, errors, button };
}

test("Save uses native randomUUID when available and preserves the request", async () => {
  const id = "f4c5fa3a-0fb0-4f35-82cf-1f3fb240e8d5";
  const crypto = {
    randomUUID() {
      assert.equal(this, crypto);
      return id;
    },
    getRandomValues() { assert.fail("Native UUID should be preferred"); },
  };
  const { card, requests, errors, button } = cardWithCrypto(crypto);
  await card.perform("upsert_group", { name: "Shared", kind: "thing" }, "Save group", 7);
  assert.equal(requests.length, 1);
  const request = JSON.parse(JSON.stringify(requests[0]));
  assert.deepEqual(request, {
    type: "call_service",
    domain: "simplifi",
    service: "upsert_group",
    service_data: {
      entry_id: "test-entry",
      name: "Shared",
      kind: "thing",
      expected_revision: 7,
      request_id: id,
      request_expires_at: "2026-10-18T12:01:00.000Z",
    },
    return_response: true,
  });
  assert.deepEqual(errors, []);
  assert.equal(card._busy, false);
  assert.equal(button.disabled, false);
});

test("Save works without randomUUID, with distinct UUID v4 IDs per action", async () => {
  const { card, requests, errors } = cardWithCrypto({
    getRandomValues: (bytes) => webcrypto.getRandomValues(bytes),
  });
  await card.perform("upsert_group", { name: "Shared", kind: "thing" }, "Save group", 0);
  await card.perform("upsert_group", { name: "Person", kind: "family" }, "Save person", 1);
  assert.deepEqual(errors, []);
  assert.equal(requests.length, 2);
  const ids = requests.map((request) => request.service_data.request_id);
  ids.forEach((id) => assert.match(id, uuidV4));
  assert.notEqual(ids[0], ids[1]);
  assert.equal(card._lastChange.id, "saved-change");
});

test("Fallback sets version and variant bits without discarding other random bits", async () => {
  const crypto = {
    getRandomValues(bytes) {
      assert.equal(this, crypto);
      assert.equal(bytes.length, 16);
      bytes.set(Array.from({ length: 16 }, (_, index) => 240 + index));
      return bytes;
    },
  };
  const { card, requests, errors } = cardWithCrypto(crypto);
  await card.perform("upsert_group", { name: "Shared" }, "Save group", 0);
  assert.deepEqual(errors, []);
  assert.equal(requests[0].service_data.request_id, "f0f1f2f3-f4f5-46f7-b8f9-fafbfcfdfeff");
});

for (const crypto of [undefined, {}]) {
  test(`Missing secure random support (${typeof crypto}) sends no action and re-enables Save`, async () => {
    const { card, requests, errors, button } = cardWithCrypto(crypto);
    await card.perform("upsert_group", { name: "Shared" }, "Save group", 0);
    assert.equal(requests.length, 0);
    assert.equal(errors.length, 1);
    assert.match(errors[0], /supported browser/);
    assert.equal(card._busy, false);
    assert.equal(button.disabled, false);
  });
}

test("command validity follows the server observation and cannot be widened by payload", async () => {
  const {card, requests, errors} = cardWithCrypto(webcrypto);
  card.data.now = "2026-10-25T01:30:00+01:00";
  await card.perform("pause_internet", {group_id:"child", duration_minutes:30,
    request_expires_at:"2099-01-01T00:00:00Z"}, "Pause", 0);
  assert.deepEqual(errors, []);
  assert.equal(requests[0].service_data.request_expires_at, "2026-10-25T00:31:00.000Z");
  assert.equal(requests[0].service_data.duration_minutes, 30);
});

for (const now of [undefined, "bad-time"]) {
  test(`missing server time (${now}) sends no command and restores controls`, async () => {
    const {card, requests, errors, button} = cardWithCrypto(webcrypto);
    card.data.now = now;
    await card.perform("resume_internet", {group_id:"child"}, "Resume", 0);
    assert.equal(requests.length,0);
    assert.match(errors[0], /Refresh SimpliFi/);
    assert.equal(card._busy,false);
    assert.equal(button.disabled,false);
  });
}
