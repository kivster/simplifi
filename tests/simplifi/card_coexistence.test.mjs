import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{
  HTMLElement:class{},window:{},structuredClone,
  customElements:{get:()=>undefined,define:(_name,value)=>{Card=value;}},
});
const policy=(id='one',extra={})=>({id,name:'Other <script>',ownership:'external',enabled:true,action:'BLOCK',origin:'USER_DEFINED',index:5,source_zone:'Home',destination_zone:'External',internet_destination:true,source:'Home devices',destination:'Ports: 53',conditions:['IPV4_AND_IPV6'],schedule:'Every week · gateway timing not evaluated',matched_groups:['child'],possible_groups:[],order:{section:'beforeSystemDefined',position:2},...extra});
function card(){const c=Object.create(Card.prototype);c.data={groups:[{id:'child',name:'Child <name>'},{id:'other',name:'Other'}],coexistence:{fresh:true,status:'available',observed_at:'2026-10-14T12:00:00Z',policy_count:3,policies:[policy(),policy('own',{ownership:'managed'}),policy('disabled',{enabled:false,matched_groups:['other']})],ordering:{status:'available',pairs:1,read:1},controls:{status:'available',items:[]}}};return c;}
test('policy filters separate independent restrictions, recorded policies, person and search',()=>{
  const c=card();assert.deepEqual(Array.from(c.policyRows(),p=>p.id),['one']);
  c._policyMode='managed';assert.deepEqual(Array.from(c.policyRows(),p=>p.id),['own']);
  c._policyMode='all';c._policyGroup='other';assert.deepEqual(Array.from(c.policyRows(),p=>p.id),['disabled']);
  c._policyGroup='';c._policyQuery='ports: 53';assert.equal(c.policyRows().length,3);
  c._policyQuery='no matching name';assert.equal(c.policyRows().length,0);
  c._policyMode='restrictions';c._policyQuery='';c.data.coexistence.policies.push(policy('drift',{ownership:'drift'}));
  assert.deepEqual(Array.from(c.policyRows(),p=>p.id),['one','drift']);
});
test('read-only policy details escape content and distinguish source match from enforcement',()=>{
  const html=card().coexistenceHTML();
  for(const value of ['Other &lt;script&gt;','Child &lt;name&gt;','2 before system rules','Ports: 53','gateway timing not evaluated','Other conditions and rule precedence still apply','does not override','no policy or ordering changes']) assert.ok(html.includes(value),value);
  assert.ok(!html.includes('<script>'));assert.ok(!html.includes('data-action="rule-toggle"'));
  assert.ok(!html.includes('data-action="quick"'));
});
test('stale and unavailable sources never imply empty or confirmed rule inventories',()=>{
  const c=card();c.data.coexistence.fresh=false;c.data.coexistence.issue='Read failed';
  let html=c.coexistenceHTML();assert.ok(html.includes('Last-known configuration')&&html.includes('Last known · BLOCK'));
  c.data.coexistence.policies=[];c.data.coexistence.observed_at=null;c.data.coexistence.controls={status:'unavailable',items:[],issue:'Source missing'};
  html=c.coexistenceHTML();assert.ok(html.includes('Policy readback unavailable'));assert.ok(html.includes('No current matching rules confirmed'));assert.ok(html.includes('readback unavailable'));assert.ok(!html.includes('0 enabled in HA'));
});
test('pagination exposes every matching rule and labels incomplete ordering',()=>{
  const c=card();c.data.coexistence.policies=Array.from({length:51},(_,i)=>policy(String(i)));c.data.coexistence.policy_count=51;c.data.coexistence.ordering={status:'partial',pairs:2,read:1,failed:1};
  let html=c.coexistenceHTML();assert.ok(html.includes('Showing 50 of 51'));assert.ok(html.includes('Show 50 more'));assert.ok(html.includes('1 of 2 zone pairs · 1 failed'));
  c._policyLimit=100;html=c.coexistenceHTML();assert.ok(html.includes('Showing 51 of 51'));assert.ok(!html.includes('Show 50 more'));
});
test('person snapshot stays explicitly dated and independent from later polling',()=>{
  const c=card();c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.otherPolicies('child');
  assert.ok(c.rendered.body.includes('Snapshot: Configuration read'));
  c.data.coexistence.policies=[];assert.equal(c._policySnapshot.policies.length,3);
  c.otherPolicies('child',false);assert.ok(c.rendered.body.includes('Other &lt;script&gt;'));
  c.otherPolicies('child',true);assert.ok(c.rendered.body.includes('Showing 0 of 0'));
});
test('independent control rows expose HA enablement and unavailable state without granting access',()=>{
  const c=card();c.data.coexistence.controls={status:'available',items:[{name:'External <control>',kind:'Firewall policy',registry_enabled:true,hidden:true,state:'unavailable'}]};
  const html=c.coexistenceHTML();assert.ok(html.includes('1 enabled in HA'));assert.ok(html.includes('External &lt;control&gt;'));assert.ok(html.includes('reported state unavailable · hidden'));assert.ok(html.includes('SimpliFi grants do not restrict them'));
});
