import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
let Card;
vm.runInNewContext(readFileSync(new URL("../../custom_components/family_network/frontend/family-network-card.js",import.meta.url),"utf8"),{HTMLElement:class{},window:{},customElements:{get:()=>undefined,define:(_n,c)=>Card=c}});
function card(){
  const c=Object.create(Card.prototype);
  c.data={fresh:true,now:"2026-10-14T12:00:00Z",timezone:"Europe/London",revision:8,groups:[{id:"child",name:"Child"}],managed_networks:["a"],networks:{a:{name:"Family"},b:{name:"Guest"}},rules:[{id:"r",name:"Bedtime"}],exceptions:[{id:"ex",kind:"internet_allow",group:"child",captured:["r"],expires_at:"2026-10-14T14:00:00Z"}],devices:[
    {id:"phone",name:"Phone",mac:"00:11:22:33:44:55",ip:"2001:db8::1",network:"a",group:"child",kind:"wireless",connected:true,last_seen:"2026-10-14T11:59:00Z",uplink_name:"Landing",registrant:"Example Inc",registrant_status:"registered",network_source:"subnet_and_reference",connected_at:"2026-10-14T10:30:00Z"},
    {id:"laptop",name:"Laptop",mac:"02:00:00:00:00:01",ip:"192.0.2.2",network:"b",group:null,kind:"wired",connected:false,last_seen:"2026-10-13T12:00:00Z",registrant_status:"private"}
  ]};
  c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};
  return c;
}
test("combined filters and search use one query path",()=>{
 const c=card();c._filter="assigned";c._networkFilter="a";c._connectionFilter="wireless";c._presenceFilter="online";c._query="landing";
 assert.equal(c.deviceRows().length,1);
 c._query="example inc";assert.equal(c.deviceRows().length,1);
 c._networkFilter="b";assert.equal(c.deviceRows().length,0);
 c._filter="unassigned";c._query="";c._connectionFilter="wired";c._presenceFilter="offline";assert.equal(c.deviceRows()[0].id,"laptop");
 assert.match(c.devices(),/1 of 2 devices/);
});
test("stale presence remains last known and detail evidence is escaped",()=>{
 const c=card();c.data.fresh=false;c.data.devices[0].uplink_name='<img src=x onerror=alert(1)>';
 assert.match(c.devicePresence(c.data.devices[0]),/Last known/);
 c.deviceForm("phone");assert.ok(c.rendered.body.includes("&lt;img"));assert.ok(!c.rendered.body.includes("<img"));
 for(const text of ["Current IP subnet and UniFi reference agree","MAC registrant","Connection started","last known observations"])assert.ok(c.rendered.body.includes(text),text);
 c.deviceForm("laptop");assert.match(c.rendered.body,/Private\/local MAC address/);assert.match(c.rendered.body,/outside managed scope/);
 assert.match(c.rendered.footer,/Forget device/);
});
test("allowance form retains a specific exception and captured rule names",()=>{
 const c=card();c.allowanceForm("ex");
 assert.equal(c.rendered.modal.id,"ex");assert.match(c.rendered.body,/Bedtime/);assert.match(c.rendered.body,/Only the deadline changes/);
 assert.match(c.rendered.body,/datetime-local/);
 c.control("child");assert.match(c.rendered.body,/data-action="allowance-edit" data-id="ex"/);
});
test("allowance submit uses immutable exception identity, ISO time and original revision",async()=>{
 const c=card();c._modal={kind:"allowance",id:"ex",revision:7};
 // Supply a FormData-compatible iterable without a DOM.
 const fields=new Map([["expires_at","2026-10-14T16:45"],["reason","Finish homework"]]);
 c.form=()=>({reportValidity:()=>true,fields});
 const context={HTMLElement:class{},window:{},FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}},customElements:{get:()=>undefined,define:(_n,K)=>{Object.setPrototypeOf(c,K.prototype);}}};
 vm.runInNewContext(readFileSync(new URL("../../custom_components/family_network/frontend/family-network-card.js",import.meta.url),"utf8"),context);
 c.confirm=(title,service,payload)=>{c.sent={service,payload};c._modal={};};
 await c.submit();
 assert.equal(c.sent.service,"edit_allowance");assert.equal(c.sent.payload.exception_id,"ex");assert.match(c.sent.payload.expires_at,/Z$/);assert.equal(c._modal.revision,7);
 assert.equal(c.sent.payload.group_id,undefined);assert.equal(c.sent.payload.captured,undefined);
});
test('current-network identity labels preserve the saved-reservation distinction',()=>{
 const c=card();c.data.devices[0].network_source='current_network_id_reference_differs';c.deviceForm('phone');assert.match(c.rendered.body,/UniFi current connection; saved reference differs/);
 c.data.devices[0].network_source='subnet_and_current_network_id';c.deviceForm('phone');assert.match(c.rendered.body,/Current connection network and IP subnet agree/);
});
