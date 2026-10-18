import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

let Card;
vm.runInNewContext(readFileSync(new URL("../../custom_components/simplifi/frontend/simplifi-card.js", import.meta.url), "utf8"), {
  HTMLElement: class {}, window: {},
  customElements: { get: () => undefined, define: (_name, value) => { Card = value; } },
});
const profile = {
  id: "profile", name: "Family <script>", enabled: true,
  networks: [{ id: "network", name: "Family VLAN" }], client_macs: [],
  schedule: { mode: "ALWAYS" }, safe_search: ["GOOGLE", "BING"],
  categories: ["ADULT"], allow_list: ["example.com"], block_list: ["blocked.example"],
};
function render(protection) {
  const card = Object.create(Card.prototype);
  card.data = { protection, devices: [], timezone: "Europe/London" };
  return card.protectionHTML();
}
test("Readback renders enabled state, targets, SafeSearch and exceptions safely", () => {
  const html = render({ fresh: true, profiles: [profile], observed_at: "2026-10-14T12:00:00Z" });
  for (const value of ["Controller configuration read", "Enabled", "Family VLAN", "GOOGLE, BING", "example.com", "blocked.example", "ADULT", "Last successful read"])
    assert.ok(html.includes(value), value);
  assert.ok(html.includes("Family &lt;script&gt;"));
  assert.ok(!html.includes("Family <script>"));
});
test("Stale readback retains values with explicit last-known and failure labels", () => {
  const html = render({ fresh: false, profiles: [profile], issue: "Connection failed", observed_at: "2026-10-14T12:00:00Z" });
  assert.ok(html.includes("Last-known configuration"));
  assert.ok(html.includes("Last known · Enabled"));
  assert.ok(html.includes("Connection failed"));
  assert.ok(!html.includes("Controller configuration read"));
});
test("Unavailable readback never becomes no profiles or disabled", () => {
  const html = render({ fresh: false, profiles: [], issue: "Connection unavailable" });
  assert.ok(html.includes("Filtering readback unavailable"));
  assert.ok(!html.includes("No content-filtering profiles returned"));
});
test("Confirmed empty readback is displayed as an empty collection", () => {
  const html = render({ fresh: true, profiles: [], observed_at: "2026-10-14T12:00:00Z" });
  assert.ok(html.includes("No content-filtering profiles returned for this site"));
});

test("Polling preserves expanded profiles and domain lists by identity", () => {
  const card = Object.create(Card.prototype);
  let details = [];
  let html = "";
  const content = {
    contains: () => false,
    querySelectorAll: (selector) => selector.endsWith("[open]")
      ? details.filter((item) => item.open) : details,
    set innerHTML(value) {
      html = value;
      details = [...value.matchAll(/data-readback-key="([^"]+)"/g)].map((m) => ({
        dataset: { readbackKey: m[1] }, open: false,
      }));
    },
  };
  Object.assign(card, {
    shadowRoot: { querySelector: () => content }, config: { mode: "filtering" },
    data: { protection: { fresh: true, profiles: [profile] }, devices: [] },
    warnings: () => "", resultHTML: () => "", filtering: () => card.protectionHTML(),
  });
  card.render();
  for (const item of details)
    item.open = ["profile:profile", "profile:allowed"].includes(item.dataset.readbackKey);
  card.data.protection.profiles = [
    { ...profile, id: "other", name: "Other" },
    { ...profile, name: "Updated name", allow_list: ["new.example"] },
  ];
  card.render();
  assert.deepEqual(details.filter((item) => item.open).map((item) => item.dataset.readbackKey),
    ["profile:profile", "profile:allowed"]);
  assert.ok(html.includes("new.example") && html.includes("Updated name"));
  details.forEach((item) => { item.open = false; });
  card.render();
  assert.ok(details.every((item) => !item.open), "A deliberately closed list stays closed");
});
