import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'), {
  HTMLElement:class{},window:{},structuredClone,
  FormData:class {constructor(f){this.fields=f.fields;}get(k){return this.fields.get(k);}getAll(k){return this.fields.get(k)||[];}has(k){return this.fields.has(k);}},
  customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){
 const c=Object.create(Card.prototype);
 c.data={revision:3,timezone:'Europe/London',groups:[{id:'child',name:'Child',devices:2}],managed_networks:['family'],networks:{family:{name:'Family <network>'},work:{name:'Work'}},exceptions:[],rules:[],simulation:true};
 c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};
 c.showError=message=>{c.error=message;};
 return c;
}
test('rule scope offers only managed networks with explicit future-device coverage',()=>{
 const c=card();c.ruleForm();c._step=1;c.change({target:{name:'rule_scope',value:'networks',dataset:{}}});
 assert.match(c.rendered.body,/including unassigned devices and devices that connect later/);
 assert.match(c.rendered.body,/Family &lt;network&gt;/);assert.ok(!c.rendered.body.includes('>Work'));
 c.form=()=>({reportValidity:()=>true,fields:new Map([['networks',['family']],['groups',['child']]])});
 assert.equal(c.captureRule(),true);assert.equal(c._draft.groups.length,0);
 c._step=3;c.drawRule();assert.match(c.rendered.body,/Exceptions affect the whole rule/);
 assert.match(c.rendered.body,/Whole networks: Family &lt;network&gt;/);
});
test('changing scope clears previous targets and empty selections cannot advance',()=>{
 const c=card();c.ruleForm();c._step=1;c._draft.groups=['child'];
 c.change({target:{name:'rule_scope',value:'networks',dataset:{}}});
 assert.equal(c._draft.groups.length,0);
 c.form=()=>({reportValidity:()=>true,fields:new Map()});
 assert.equal(c.captureRule(),false);assert.match(c.error,/Select at least/);
});
test('network restriction does not offer an individual internet allowance',()=>{
 const c=card();c.data.groups[0]={...c.data.groups[0],state:'network_blocked',network_rules:['wide'],reason:'A person’s allowance cannot override them.'};
 assert.ok(!c.personActions(c.data.groups[0]).includes('allow_internet'));
 c.control('child');assert.ok(!c.rendered.body.includes('value="allow_internet"'));
 assert.match(c.rendered.body,/Manage these restrictions from the rule/);
});
test('saving network rule sends network IDs and retains original modal revision',async()=>{
 const c=card();c.ruleForm();c._draft={...c._draft,name:'Whole network',networks:['family'],groups:[]};
 c._modal={kind:'rule',revision:3};c.data.revision=4;
 c.form=()=>({reportValidity:()=>true,fields:new Map([['enabled',true]])});
 c.perform=async(service,payload,title,revision)=>{c.sent={service,payload,revision};};
 // submit routes through run(); record the authenticated action payload.
 c.run=async(service,payload)=>{c.sent={service,payload};};
 c.api=async(service,payload)=>{c.sent={service,payload};return {};};
 c.close=()=>{};c.load=async()=>{};
 await c.submit();
 assert.equal(c.sent.service,'upsert_rule');assert.equal(c.sent.payload.networks[0],'family');assert.equal(c.sent.payload.groups.length,0);assert.equal(c.sent.revision,3);
});
