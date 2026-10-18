import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},structuredClone,
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={revision:4};c.time=v=>v;c.open=(title,body,footer,modal)=>{c._modal=modal;c.rendered={title,body,footer,modal};};return c;}
function health(){return {scope:'On demand only',simulation:false,read_at:'2026-10-18T12:00:00Z',refresh_after_seconds:60,capped:false,devices:[{name:'Controller <script>',model:'Model',state:'ONLINE',fresh:true,status:'available',controller:true,cpu_pct:0,memory_pct:null,load_1:0,load_5:0.1,load_15:0.2,uptime_seconds:0,sampled_at:'2026-10-18T12:00:00Z',sample_age_seconds:0}],requests:{requests:10,failures:1,retries:1,rate_limited:1,in_flight:0,peak_in_flight:4,mean_ms:25,max_ms:40,observed_seconds:60,window_seconds:300,scope:'Own instance only',endpoints:[{method:'GET',endpoint:'/v1/sites/{site}/devices',requests:10,failures:1,retries:1}]}};}
test('gateway samples distinguish real zero from unknown and escape controller labels',()=>{
 const c=card();c.drawGatewayHealth(health());
 assert.match(c.rendered.body,/CPU 0% · Memory Unknown/);
 assert.match(c.rendered.body,/Uptime: 0d 0h 0m/);
 assert.match(c.rendered.body,/Controller &lt;script&gt;/);
 assert.ok(!c.rendered.body.includes('<script>'));
 assert.match(c.rendered.body,/another 60 seconds/);
 assert.match(c.rendered.body,/10 requests · 1 failures/);
 assert.match(c.rendered.body,/scope="col"/);
});
test('unavailable, capped and simulated evidence remains explicit',()=>{
 const c=card();const h=health();h.devices[0]={...h.devices[0],fresh:false,status:'stale',issue:'Read failed <unsafe>'};
 c.drawGatewayHealth({...h,simulation:true,capped:true,returned_devices:64,total_devices:80,device_limit:64,issue:'Last known'});
 assert.match(c.rendered.body,/fictional device samples/);
 assert.match(c.rendered.body,/64 of 80/);
 assert.match(c.rendered.body,/stale/);
 assert.match(c.rendered.body,/Read failed &lt;unsafe&gt;/);
});
test('health fetch is explicit and ordinary refresh leaves the snapshot alone',async()=>{
 const c=card();const calls=[];c.api=async(action,data)=>{calls.push({action,data});return action==='gateway_health'?health():{revision:4};};
 await c.gatewayHealthView();assert.equal(calls[0].action,'gateway_health');assert.equal(calls[0].data.refresh,true);
 c._hass={};c.config={mode:'activity'};c.render=()=>{};
 await c.refresh();await c.refresh();assert.deepEqual(calls.map(x=>x.action),['gateway_health','dashboard_data','dashboard_data']);
 assert.equal(c._modal.kind,'gateway-health');
});
test('a closed health dialog is not reopened by a slow response',async()=>{
 const c=card();let resolve;c.api=()=>new Promise(r=>{resolve=r;});
 const pending=c.gatewayHealthView();const loading=c.rendered;c._modal=null;resolve(health());await pending;
 assert.equal(c.rendered,loading);assert.equal(c._modal,null);
});
test('failed health read provides a retry with escaped error',async()=>{
 const c=card();c.api=async()=>{throw new Error('<unsafe>');};await c.gatewayHealthView();
 assert.match(c.rendered.body,/&lt;unsafe&gt;/);assert.match(c.rendered.footer,/gateway-health/);
});
test('cached role source, partial metrics and dated timezone-aware samples remain explicit',()=>{
 const c=card();const times=[];c.time=(value,day,zone)=>{times.push({day,zone});return value;};
 const h=health();h.devices[0]={...h.devices[0],gateway:true,gateway_source:'ha_unifi_inventory',status:'partial'};
 c.drawGatewayHealth(h);assert.match(c.rendered.body,/Gateway \(HA UniFi inventory\)/);assert.match(c.rendered.body,/Partial sample/);
 assert.equal(times.length,2);assert.ok(times.every(t=>t.day&&t.zone));
});
