import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js', import.meta.url), 'utf8'), {
  HTMLElement:class{},window:{},FormData:class{constructor(f){this.f=f.fields;}get(k){return this.f.get(k);}has(k){return this.f.has(k);}},
  customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={revision:7,managed_networks:['dest'],networks:{dest:{name:'Home'}}};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
const configuration={format:'family_network',version:2,configuration:{controller:'https://old',site:'old',networks:['old'],groups:{child:{name:'Child'}}}};
test('restore file reader rejects oversize files before reading and escapes export labels',async()=>{
  const c=card();let read=false;
  c.form=()=>({querySelector:()=>({files:[{size:2000001,text:async()=>{read=true;}}]})});
  await assert.rejects(c.importFile(),/2 MB/);assert.equal(read,false);
  const data=structuredClone(configuration);data.configuration.site='<script>test</script>';
  c.form=()=>({querySelector:()=>({files:[{size:100,text:async()=>JSON.stringify(data)}]})});
  await c.importFile();assert.match(c.rendered.body,/&lt;script&gt;/);assert.ok(!c.rendered.body.includes('<script>'));assert.match(c.rendered.body,/Choose a managed network/);
});
test('restore requires every network mapping before requesting a preview',async()=>{
  const c=card();c._importDraft={configuration,source:configuration.configuration};c.form=()=>({fields:new Map()});let called=false;c.api=async()=>{called=true;};
  await assert.rejects(c.importPreview(),/Map every/);assert.equal(called,false);
});
test('restore save uses reviewed revision and mapping only after explicit confirmation',async()=>{
  const c=card();c._importDraft={configuration,source:configuration.configuration};c.form=()=>({fields:new Map([['network_0','dest']])});
  c.api=async(action,payload)=>{assert.equal(action,'preview_import');assert.equal(payload.network_mapping.old,'dest');return {groups:1,rules:2,timezone:'Europe/London',mapping:{old:'dest'},matched:[],pending:[{mac:'02:00:00:00:00:01',name:'Offline',group:'child'}],dns_resolvers_reset:true,note:'Review',preview_hash:'review',revision:7};};
  await c.importPreview();assert.match(c.rendered.body,/Waiting for discovery/);assert.match(c.rendered.body,/resolvers will be reset/);c._modal=c.rendered.modal;c.data.revision=8;
  c.form=()=>({reportValidity:()=>true,fields:new Map()});c.perform=async(service,payload,title,revision)=>{c.sent={service,payload,revision};};await c.submit();assert.equal(c.sent,undefined);
  c.form=()=>({reportValidity:()=>true,fields:new Map([['confirm',true]])});await c.submit();assert.equal(c.sent.service,'apply_import');assert.equal(c.sent.payload.network_mapping.old,'dest');assert.equal(c.sent.payload.preview_hash,'review');assert.equal(c.sent.revision,7);
});
