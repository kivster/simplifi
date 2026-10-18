import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}has(k){return this.fields.has(k);}},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.config={mode:'family'};c.data={timezone:'Europe/London',fresh:true,revision:4,groups:[{id:'child',name:'Child <name>',devices:1,state:'available',unblock:{eligible_rules:2,can_unblock:true,allowances:2,timed_allowances:1,indefinite_allowances:1,latest_deadline:'2026-10-18T16:00:00Z'},timeline:[]}],rules:[{id:'shared',name:'Shared rule',groups:['child','other'],networks:[],enabled:true,windows:[],kind:'internet'}],exceptions:[],devices:[],day_start:'2026-10-18T00:00:00Z',day_end:'2026-10-19T00:00:00Z'};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
test('group unblock has explicit scope, future-window and extension explanations',()=>{
 const c=card();assert.match(c.personActions(c.data.groups[0]),/Manage rule allowances/);
 c.unblockForm('child');for(const text of ['category, application and website','Other people, whole-network rules','currently assigned enabled rules','Rules added afterwards still apply','latest end plus the selected minutes','1 without a deadline','Child &lt;name&gt;'])assert.ok(c.rendered.body.includes(text),text);
 assert.match(c.rendered.body,/value="default" selected/);assert.equal(c.rendered.modal.kind,'group-unblock');
});
test('new controls are hidden for read-only users and stale data disables buttons',()=>{
 const c=card();c.config.mode='access';c.data.scope='read_only';assert.ok(!c.scopedAccess().includes('data-action="group-unblock"'));
 c.data.scope='watch_rules';assert.match(c.scopedAccess(),/data-action="group-unblock"/);
 c.data.fresh=false;assert.match(c.unblockButton(c.data.groups[0]),/disabled/);
});
test('unblock actions review exact group, timing and scope before any write',async()=>{
 const c=card();c.unblockForm('child');c._modal={...c.rendered.modal,revision:4};
 c.form=()=>({reportValidity:()=>true,fields:new Map([['service','unblock_group'],['deadline','default'],['reason','Homework']])});
 c.confirm=(title,service,payload,message)=>{c.sent={service,payload,message};c._modal={kind:'confirm'};};c.perform=()=>{throw Error('Must review first');};
 await c.submit();assert.equal(c.sent.service,'unblock_group');assert.equal(c.sent.payload.group_id,'child');assert.equal(c.sent.payload.duration_minutes,undefined);assert.match(c.sent.message,/Only rules naming this person/);assert.equal(c._modal.revision,4);
 c._modal={kind:'group-unblock',id:'child',revision:4};c.form=()=>({reportValidity:()=>true,fields:new Map([['service','extend_group_unblock'],['deadline','30']])});await c.submit();assert.equal(c.sent.payload.duration_minutes,30);assert.match(c.sent.message,/latest deadline plus this duration/);
});
test('end ignores deadline fields and extension accepts minutes only',()=>{
 const c=card();assert.equal(Object.keys(c.deadline(new Map([['deadline','custom']]),'end_group_unblock')).length,0);
 assert.throws(()=>c.deadline(new Map([['deadline','default']]),'extend_group_unblock'),/minute duration/);
 assert.equal(c.deadline(new Map([['deadline','60']]),'extend_group_unblock').duration_minutes,60);
});
test('person rule options cannot silently widen to everyone or another group',async()=>{
 const c=card();await c.click({composedPath:()=>[{dataset:{action:'rule-options',id:'shared',group:'child'}}]});
 assert.ok(!c.rendered.body.includes('Everyone on this rule'));assert.ok(!c.rendered.body.includes('value="other"'));assert.ok(!c.rendered.footer.includes('Delete rule'));assert.equal(c.rendered.modal.group,'child');
 c._modal={...c.rendered.modal,revision:4};c.form=()=>({reportValidity:()=>true,fields:new Map([['service','suspend_rule'],['group_id','other'],['deadline','30']])});
 c.confirm=(title,service,payload,message)=>{c.sent={service,payload,message};c._modal={};};await c.submit();assert.equal(c.sent.payload.group_id,'child');assert.match(c.sent.message,/Child <name>/);
 c.data.rules.push({id:'network',groups:[],networks:['family']});assert.throws(()=>c.ruleOptions('network','child'),/no allowance for that person/);
});
test('person details route own rules to person scope and network rules to shared options',()=>{
 const c=card();c.data.rules.push({id:'wide',name:'Network restriction',kind:'internet',groups:[],affected_groups:['child'],networks:['family'],windows:[],enabled:true});
 c.detail('child');assert.match(c.rendered.body,/data-id="shared"[^>]*data-group="child"/);assert.ok(!/data-id="wide"[^>]*data-group/.test(c.rendered.body));assert.match(c.rendered.body,/Network options/);
});
test('group extension audit describes the shared latest-deadline calculation',()=>{
 const html=card().timingHistoryHTML({id:'c',action:'extend_group_unblock',details:{timing:{version:1,timezone:'Europe/London',request:{mode:'extend_group_minutes',value:15},changes:[]}}});
 assert.match(html,/every timed group allowance by 15 minutes from the latest deadline/);
});
