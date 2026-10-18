import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){
 const c=Object.create(Card.prototype);c.config={mode:'family'};c._hass={states:{}};c.time=v=>v;
 const g={id:'child',name:'Child <name>',state:'available',devices:2,connected:1,categories:[],timeline:[],rule_rows:[{rule_id:'r',name:'Apps <rule>',kind:'application',mode:'always_on',enabled:true,state:'restricted',label:'Rule active',targets:[{id:123,name:'Chat <app>',known:true},{id:999,name:'Unknown application (ID 999)',known:false}],covered_devices:2,devices:2,coverage_fresh:true,network_scope:false,person_control:true}]};
 c.data={fresh:true,management:true,revision:2,version:'test',sync:'applied',timezone:'Europe/London',groups:[g],rules:[{id:'r',name:'Apps <rule>',kind:'application',groups:['child'],targets:[123,999],windows:[],enabled:true}],devices:[],exceptions:[],changes:[]};
 return c;
}
test('person card presents all target labels and safe person-scoped options',()=>{
 const c=card();const html=c.person(c.data.groups[0]);
 for(const text of ['Always-on and all-day rules','Apps &lt;rule&gt;','Chat &lt;app&gt;','Unknown application (ID 999)','Always on','2 of 2 managed devices','Rule active','confirm filtering on the device'])assert.ok(html.includes(text),text);
 assert.match(html,/data-id="r"[^>]*data-group="child"/);
 assert.match(html,/aria-label="Options · Apps &lt;rule&gt; · Child &lt;name&gt;"/);
 assert.ok(!html.includes('<app>'));
});
test('all-day, stale, disabled and partial coverage are explicit',()=>{
 const c=card();const g=c.data.groups[0];Object.assign(g.rule_rows[0],{mode:'all_day_today',state:'partial',label:'Some devices restricted',covered_devices:1,coverage_fresh:false,enabled:false});
 const html=c.continuousRules(g);for(const text of ['All day today','1 of 2 managed devices','last-known coverage','Some devices restricted','disabled'])assert.ok(html.includes(text),text);
 assert.equal(c.continuousRules(g,['different-rule']),'');
});
test('network options never acquire a person target and read-only cards show no controls',()=>{
 const c=card();const g=c.data.groups[0];Object.assign(g.rule_rows[0],{network_scope:true,person_control:false});
 const html=c.continuousRules(g);assert.match(html,/Whole-network rule/);assert.match(html,/Network options/);assert.ok(!html.includes('data-group='));
 c.config.mode='access';c.data.scope='read_only';assert.ok(!c.continuousRules(g).includes('data-action='));
 c.data.scope='watch_rules';assert.ok(!c.continuousRules(g).includes('data-action='));
 c.data.rules[0].whole_rule_control=true;assert.match(c.continuousRules(g),/Network options/);
});
test('Watch group controls retain exact person scope and all labels',()=>{
 const c=card();c.config.mode='access';c.data.scope='watch_rules';const html=c.scopedAccess();
 assert.match(html,/Unknown application \(ID 999\)/);assert.match(html,/data-id="r"[^>]*data-group="child"/);
 c.data.scope='read_only';assert.ok(!c.scopedAccess().includes('data-action="rule-options"'));
});
test('continuous internet rules do not claim a timed restriction or override uncertainty',()=>{
 const c=card();const g={state:'scheduled_block',always_on_internet:true};assert.equal(c.accessLabel(g),'Internet rule active');
 assert.equal(c.accessLabel({...g,always_on_internet:false,all_day_internet:true}),'All-day restriction');
 assert.equal(c.accessLabel({...g,state:'unknown'}),'Unable to confirm');
 assert.equal(c.accessLabel({...g,state:'network_blocked'}),'Network restriction');
});
test('Activity keeps the original failure and separately shows later readback',()=>{
 const c=card();c.data.changes=[{id:'change',action:'apply_setup',outcome:'failed',actor:'Admin',target_names:['Child'],requested_at:'2026-10-18T12:00:00Z',sync_evidence:{revision:2,latest:{outcome:'applied',finished_at:'2026-10-18T12:02:00Z'},latest_confirmed:true,last_confirmed_at:'2026-10-18T12:02:00Z'}}];
 const html=c.activity();for(const text of ['Original attempt failed','Later settings readback confirmed','original attempt result is retained','does not prove an expired temporary control ran','revision 2'])assert.ok(html.includes(text),text);
});
test('latest failed or incomplete syncs do not borrow an older success',()=>{
 const c=card();const change={outcome:'failed',sync_evidence:{revision:2,latest:{outcome:'failed',finished_at:'2026-10-18T12:02:00Z'},latest_confirmed:false,last_confirmed_at:'2026-10-18T12:01:00Z'}};
 let html=c.syncEvidenceHTML(change);assert.match(html,/Latest sync: failed/);assert.ok(!html.includes('readback confirmed'));assert.match(html,/Last confirmed readback: 2026-10-18T12:01:00Z/);
 change.sync_evidence.latest.outcome='applied';html=c.syncEvidenceHTML(change);assert.match(html,/Readback confirmation incomplete/);
 change.sync_evidence.latest=null;assert.match(c.syncEvidenceHTML(change),/No retained sync result/);
});
