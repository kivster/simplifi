import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},structuredClone,
 FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}getAll(k){return this.fields.get(k)||[];}has(k){return this.fields.has(k);}},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.config={mode:'rules'};c.data={fresh:true,timezone:'Europe/London',revision:4,groups:[{id:'child',name:'Child'}],rules:[{id:'r',name:'Bedtime',kind:'internet',groups:['child'],networks:[],enabled:true,windows:[],targets:[],target_names:[]}],exceptions:[],quarantine_rule:{enabled:true,paused:false,expires_at:null,can_control:true,can_toggle:true}};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
test('quarantine leads Rules and only exposes valid pause controls',()=>{
 const c=card();let html=c.rules();assert.ok(html.indexOf('Unknown-device quarantine')<html.indexOf('Bedtime'));assert.match(html,/data-id="indefinite"/);assert.ok(!html.includes('Resume quarantine'));
 c.data.quarantine_rule.paused=true;html=c.quarantineCard();assert.match(html,/when resumed manually/);assert.match(html,/Resume quarantine/);assert.ok(!html.includes('Extend 30'));
 c.data.quarantine_rule.expires_at='2026-10-14T20:00:00Z';assert.match(c.quarantineCard(),/Extend 30 min/);
 c.data.quarantine_rule.enabled=false;html=c.quarantineCard();assert.match(html,/Disabled/);assert.ok(!html.includes('quarantine-control'));assert.match(html,/Manage quarantine/);
});
test('quarantine actions use fixed services and require review',async()=>{
 const c=card();c.confirm=(title,service,payload)=>{c.sent={service,payload};};
 for(const [id,service,duration] of [['pause','suspend_quarantine',30],['indefinite','suspend_quarantine',undefined],['resume','resume_quarantine',undefined],['extend','extend_quarantine_suspension',30]]){
  await c.click({composedPath:()=>[{dataset:{action:'quarantine-control',id},textContent:id}]});
  assert.equal(c.sent.service,service);assert.equal(c.sent.payload.duration_minutes,duration);assert.equal(c.sent.payload.group_id,undefined);if(id==='indefinite')assert.equal(c.sent.payload.indefinite,true);
 }
});
test('scoped quarantine never exposes administration or unauthorized controls',()=>{
 const c=card();c.config.mode='access';c.data.scope='watch_rules';c.data.quarantine_rule.can_toggle=false;
 let html=c.scopedAccess();assert.match(html,/quarantine-control/);assert.ok(!html.includes('Manage quarantine'));
 c.data.scope='read_only';c.data.quarantine_rule.can_control=false;html=c.scopedAccess();assert.ok(!html.includes('quarantine-control'));assert.match(html,/Unknown-device quarantine/);
 delete c.data.quarantine_rule;assert.ok(!c.scopedAccess().includes('Unknown-device quarantine'));
});
test('existing rule editors preserve immutable fields and explain retained exceptions',()=>{
 const c=card();c.ruleForm(c.data.rules[0]);assert.match(c.rendered.body,/<select name="rule_kind" disabled/);assert.match(c.rendered.footer,/Delete rule/);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['name','Renamed']]),querySelectorAll:()=>[]});assert.equal(c.captureRule(),true);assert.equal(c._draft.kind,'internet');
 c.change({target:{name:'rule_kind',value:'domain',dataset:{}}});assert.equal(c._draft.kind,'internet');
 c._step=1;c.drawRule();assert.match(c.rendered.body,/<select name="rule_scope" disabled/);
 c.change({target:{name:'rule_scope',value:'networks',dataset:{}}});assert.equal(c._draftScope,'groups');
 c._step=3;c.drawRule();assert.match(c.rendered.body,/Editing keeps current exceptions/);
});
test('rule cards show captured group allowances and disable exception options when off',()=>{
 const c=card();c.data.exceptions=[{id:'ex',kind:'internet_allow',group:'child',captured:['r'],expires_at:null}];
 assert.match(c.ruleCard(c.data.rules[0]),/internet allow · Child · until resumed/);
 c.data.rules[0].enabled=false;assert.match(c.ruleCard(c.data.rules[0]),/data-action="rule-options" data-id="r" disabled/);
});
test('indefinite allowances can receive a chosen end without an epoch date',()=>{
 const c=card();c.data.exceptions=[{id:'ex',kind:'rule_allow',rule:'r',captured:['r'],expires_at:null}];c.allowanceForm('ex');assert.match(c.rendered.body,/until ended/);assert.ok(!c.rendered.body.includes('1970'));
 assert.equal(Object.keys(c.deadline(new Map([['deadline','default']]),'allow_rule')).length,0);
 assert.equal(c.deadline(new Map([['deadline','indefinite']]),'allow_rule').indefinite,true);
});
