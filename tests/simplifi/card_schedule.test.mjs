import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/simplifi/frontend/simplifi-card.js',import.meta.url),'utf8'),{HTMLElement:class{},window:{},customElements:{get:()=>undefined,define:(_n,c)=>Card=c}});
function card(start,end){
 const c=Object.create(Card.prototype);c.data={timezone:'Europe/London',day_start:start,day_end:end,revision:1,rules:[],devices:[],groups:[{id:'g',name:'Test family',state:'available',timeline:[]}]};
 c.personActions=()=>'';c.open=(title,body)=>{c.body=body;};return c;
}
test('repeated clock times have distinct visible and accessible UTC offsets',()=>{
 const c=card('2026-10-24T23:00:00Z','2026-10-26T00:00:00Z');
 const first=c.timelineTime('2026-10-25T00:10:00Z'),second=c.timelineTime('2026-10-25T01:10:00Z');
 assert.match(first,/01:10 GMT\+1/);assert.match(second,/01:10 GMT(?:\+0)?$/);assert.notEqual(first,second);
 c.data.groups[0].timeline=[{rule_id:'r',name:'Short restriction',start:'2026-10-25T00:10:00Z',end:'2026-10-25T00:20:00Z'},{rule_id:'r',name:'Short restriction',start:'2026-10-25T01:10:00Z',end:'2026-10-25T01:20:00Z'}];
 c.detail('g');assert.match(c.body,/aria-label="Short restriction 01:10 GMT\+1 to 01:20 GMT\+1"/);assert.match(c.body,/aria-label="Short restriction 01:10 GMT(?:\+0)? to 01:20 GMT(?:\+0)?"/);assert.match(c.body,/Clock change today/);
});
test('elapsed timeline midpoint labels account for 23 and 25 hour days',()=>{
 const fall=card('2026-10-24T23:00:00Z','2026-10-26T00:00:00Z');assert.equal(fall.timelineMiddle(),'11:30');
 const spring=card('2026-03-29T00:00:00Z','2026-03-29T23:00:00Z');assert.equal(spring.timelineMiddle(),'12:30');assert.equal(spring.timelineEnd(spring.data.day_end),'24:00');
});
test('ordinary days retain concise local times and noon midpoint',()=>{
 const c=card('2026-10-13T23:00:00Z','2026-10-14T23:00:00Z');assert.equal(c.timelineTime('2026-10-14T09:00:00Z'),'10:00');assert.equal(c.timelineMiddle(),'12:00');c.detail('g');assert.doesNotMatch(c.body,/Clock change today/);
});
