import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},structuredClone,crypto:{randomUUID:()=> 'request-1'},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={revision:4};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};return c;}
function status(){return {installed:'0.19.0b2',provider:'hacs',hacs_loaded:true,legacy_attention:null,check:{status:'managed_by_hacs',available:null}};}
test('updates hand off to HACS without claiming availability or offering host installation',()=>{
 const c=card();c.drawUpdates(status());assert.equal(c.rendered.title,'SimpliFi updates');
 assert.match(c.rendered.body,/href="\/hacs"/);assert.match(c.rendered.body,/Installed 0.19.0b2/);
 assert.ok(!c.rendered.body.includes('Up to date'));
 for(const action of ['update-preview','update-schedule','update-recovery','update-check']) assert.ok(!(c.rendered.body+c.rendered.footer).includes(action));
});
test('manual installation and retained recovery evidence are clear and escaped',()=>{
 const c=card();c.drawUpdates({...status(),hacs_loaded:false,legacy_attention:'Review <script>old installer</script>'});
 assert.match(c.rendered.body,/HACS is not loaded/);assert.match(c.rendered.body,/&lt;script&gt;/);assert.ok(!c.rendered.body.includes('<script>'));
 assert.ok(!c.rendered.body.includes('href="/hacs"'));
});
test('opening updates only reads the authenticated status action',async()=>{
 const c=card();const calls=[];c.api=async(service)=>{calls.push(service);return status();};await c.updatesView();
 assert.deepEqual(calls,['update_status']);
});
test('unchanged background refresh preserves the open update dialog',async()=>{
 const c=card();c._hass={};c.config={mode:'activity'};c._modal={kind:'updates'};c._updates=status();c.render=()=>{};let draws=0;c.drawUpdates=()=>{draws++;};
 c.api=async()=>({updates:structuredClone(c._updates),revision:5});await c.refresh();assert.equal(draws,0);
 c.api=async()=>({updates:{...c._updates,hacs_loaded:false},revision:5});await c.refresh();assert.equal(draws,1);
});
