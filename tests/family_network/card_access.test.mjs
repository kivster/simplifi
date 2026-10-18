import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}has(k){return this.fields.has(k);}getAll(k){return this.fields.get(k)||[];}},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.config={mode:'activity',entry_id:'entry'};c.data={timezone:'Europe/London',revision:4,groups:[{id:'child',name:'Child <private>',devices:1,state:'available'}],managed_networks:['family'],networks:{family:{name:'Family'}},rules:[],exceptions:[]};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
test('grant form names the permission boundary and starts unconfirmed',async()=>{
 const c=card();c.api=async action=>action==='list_access_grants'?{access_revision:7,grants:{}}:{users:[{id:'u',name:'<Account>'}]};
 await c.accessView();assert.match(c.rendered.body,/do not restrict the account elsewhere in Home Assistant/);assert.match(c.rendered.body,/mode: access/);
 c.accessForm();assert.match(c.rendered.body,/&lt;Account&gt;/);assert.match(c.rendered.body,/Agent · controls plus household editing/);assert.match(c.rendered.body,/current and future group/);assert.ok(!c.rendered.body.includes('name="confirm" type="checkbox" checked'));
 c._modal=c.rendered.modal;c.form=()=>({reportValidity:()=>true,fields:new Map([['user_id','u'],['scope','watch_rules'],['groups',['child']]])});c.perform=async(s,p)=>{c.sent={s,p};};await c.submit();assert.equal(c.sent,undefined);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['user_id','u'],['scope','watch_rules'],['groups',['child']],['confirm',true]])});await c.submit();assert.equal(c.sent.p.expected_access_revision,7);assert.equal(c.sent.p.groups[0],'child');assert.equal(c.sent.p.all_groups,false);
});
test('scoped card hides editors and read-only controls',()=>{
 const c=card();c.config.mode='access';c.data.scope='read_only';c.data.rules=[{id:'r',name:'Shared',kind:'internet',groups:['child'],networks:[],whole_rule_control:false,enabled:true}];
 let html=c.scopedAccess();assert.ok(!html.includes('data-action="control"'));assert.ok(!html.includes('data-action="rule-options"'));assert.ok(!html.includes('Manage access'));
 c.data.scope='watch_rules';html=c.scopedAccess();assert.match(html,/data-action="rule-options"/);assert.ok(!html.includes('data-action="rule-toggle"'));assert.match(html,/&lt;private&gt;/);
 c.ruleOptions('r');assert.ok(!c.rendered.body.includes('Everyone on this rule'));assert.ok(!c.rendered.footer.includes('Delete rule'));assert.match(c.rendered.body,/Child &lt;private&gt;/);
});
test('scoped refresh uses only the restricted status route',async()=>{
 const c=card();c.config.mode='access';c._hass={};c._generation=1;c.render=()=>{};c.api=async action=>{c.called=action;return {scope:'watch_rules',groups:[],rules:[],changes:[]};};
 await c.refresh();assert.equal(c.called,'access_status');
});
