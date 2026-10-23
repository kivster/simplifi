import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
let Card;
vm.runInNewContext(readFileSync(new URL("../../custom_components/simplifi/frontend/simplifi-card.js", import.meta.url), "utf8"), {
  HTMLElement: class {}, window: {}, crypto: webcrypto,
  customElements: { get: () => undefined, define: (_name, value) => { Card = value; } },
});
function card() {
  const instance = Object.create(Card.prototype);
  instance.data = { revision: 9, dns_revision: 2, timezone: "Europe/London", now: "2026-10-14T12:00:00Z", groups: [],
    probes: {video: {name: "Video", domains: ["example.org"], enabled: true}}, probe_results: {},
    dns_views: {video: {household: {verdict: "unknown", issues: [], contexts: []}}},
    dns_settings: {enabled:true, household_resolver:"", baseline_resolver:"1.1.1.1", freshness_hours:24, group_resolvers:{}},
    rules:[], devices:[], protection: {fresh:false, profiles:[]}, dns_progress: {running:false}};
  instance.open = (title, body, footer, modal) => { instance.rendered = {title, body, footer, modal}; };
  return instance;
}
test("Filtering offers resolver inheritance and shows running progress without success claims", () => {
  const c = card();
  c.data.dns_progress = {running:true,completed:2,total:8};
  const html = c.filtering();
  for (const text of ["Resolver settings", "Checking 2 of 8", "Needs checking", "network identity", "cannot confirm application blocking"])
    assert.ok(html.includes(text), text);
  assert.ok(html.includes('data-action="dns-all"') && html.includes("disabled"));
});
test("Results show stale evidence explicitly and escape resolver content and errors", () => {
  const c = card();
  const resolver = 'https://dns.example/<script>';
  c.data.dns_views.video.household.contexts = [{resolver,source:"Household default",networks:[],fresh:false,issue:"Settings changed"}];
  const answer = {addresses:["192.0.2.5"],status:"answer",ede:[15]};
  c.data.probe_results.video = {contexts:{a:{resolver,verdict:"blocked",vantage:"Home Assistant", timestamp:"2026-10-14T10:00:00Z",expires_at:"2026-10-14T11:00:00Z",domains:[{domain:"example.org",verdict:"blocked",reason:"Filtered <script>",observed:{A:answer,AAAA:answer},reference:{A:answer,AAAA:answer}}]}}};
  c.probeResults("video");
  const html = c.rendered.body;
  assert.ok(html.includes("Last-known results below are not current"));
  assert.ok(html.includes("Last known · DNS blocked") && html.includes("EDE 15"));
  assert.ok(!html.includes("<script>"));
});
test("Built-in samples can be empty, disabled and restored with immutable category", () => {
  const c = card();
  c.probeForm({id:"video",name:"Video",seed:"video",category:"video",domains:[],enabled:false,removed_seed_domains:["example.org"]});
  assert.ok(c.rendered.body.includes("Restore default samples"));
  assert.ok(c.rendered.body.includes("1 default samples removed"));
  assert.ok(!c.rendered.body.includes('textarea name="domains" required'));
  assert.ok(c.rendered.footer.includes("Disable list"));
});
test("Category details keep configured controls distinct from DNS results", () => {
  const c = card();
  c.data.groups = [{id:"child",name:"Child",categories:[{id:11,slug:"vpn",name:"VPN",label:"Rule active",dns:{label:"DNS resolves",lists:["video"]},rules:[],supported:true,reasons:["Gateway readback current"],scope:"Device traffic is not tested"}],protection:{fresh:true,profiles:[]}}];
  c.categoryDetail("child","vpn");
  const html = c.rendered.body;
  assert.ok(html.includes("Rule active") && html.includes("DNS resolves"));
  assert.ok(html.includes("A DNS answer can coexist with an application-blocking rule"));
  assert.ok(html.includes('data-group="child"'));
});
test("DNS saves use the modal's captured revision even after a newer poll", async () => {
  const c = card();
  c._modal = {dnsRevision:1};
  c.shadowRoot = {querySelectorAll: () => []};
  let payload;
  c.api = async (_service, p) => {payload = p; return {};};
  c.close = () => { c._modal = null; };
  c.refresh = async () => {};
  c.render = () => {};
  c.showError = error => assert.fail(error);
  await c.perform("set_dns_settings", {}, "Save", 9);
  assert.equal(payload.expected_dns_revision,1);
  assert.equal(payload.expected_revision,9);
});
