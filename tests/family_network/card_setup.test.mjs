import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}has(k){return this.fields.has(k);}getAll(k){return this.fields.get(k)||[];}},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={timezone:'Europe/London',revision:4,groups:[{id:'child',name:'Child'}],managed_networks:['family'],networks:{family:{name:'Family'}},devices:[{id:'free',name:'Free <device>',network:'family',group:null},{id:'owned',name:'Other person',network:'family',group:'child'},{id:'outside',name:'Outside',network:'work',group:null}],rules:[],exceptions:[]};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
test('guided device selection excludes other owners and unmanaged networks',()=>{
 const c=card();c.setupForm();c._setupStep=1;c.drawSetup();assert.match(c.rendered.body,/Free &lt;device&gt;/);assert.ok(!c.rendered.body.includes('Other person'));assert.ok(!c.rendered.body.includes('Outside'));
 c._setupDraft.group_id='child';c.drawSetup();assert.match(c.rendered.body,/Other person/);
});
test('suggested schedules are opt-in and preserve explicit overnight/start weekdays',()=>{
 const c=card();c.setupForm();c._setupStep=2;c.drawSetup();assert.ok(!c.rendered.body.includes('name="schedule_0" type="checkbox" checked'));assert.match(c.rendered.body,/Nothing is selected automatically/);assert.match(c.rendered.body,/verified the UniFi timezone/);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['schedule_0',true],['days_0',['0','6']],['start_0','20:30'],['end_0','07:30'],['overnight_0',true]])});
 assert.equal(c.captureSetup(),true);assert.equal(c._setupDraft.schedules.length,1);assert.equal(c._setupDraft.schedules[0].days[1],6);assert.equal(c._setupDraft.schedules[0].overnight,true);assert.equal(c._setupDraft.gateway_timezone_confirmed,false);
});
test('setup save requires confirmation and retains the exact reviewed payload and revision',async()=>{
 const c=card();c.setupForm();c._setupDraft.name='New';c.api=async(s,p)=>({preview_hash:'evidence',revision:4,group:{name:'New'},devices:[],rules:[],timezone:'Europe/London',management:false,note:'Future devices inherit rules'});
 await c.setupReview();c._modal=c.rendered.modal;c.data.revision=9;c.form=()=>({reportValidity:()=>true,fields:new Map()});c.perform=async(s,p,t,r)=>{c.sent={s,p,r};};await c.submit();assert.equal(c.sent,undefined);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['confirm',true]])});await c.submit();assert.equal(c.sent.s,'apply_setup');assert.equal(c.sent.r,4);assert.equal(c.sent.p.preview_hash,'evidence');assert.equal(c.sent.p.configuration.name,'New');
});
