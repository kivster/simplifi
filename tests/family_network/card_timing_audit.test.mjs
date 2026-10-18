import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={timezone:'Pacific/Auckland',revision:4};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};return c;}
const record={kind:'pause',group_name:'<img src=x onerror=bad()>',expires_at:'2026-10-25T00:30:00Z',captured_rules:[{id:'r',name:'<script>bedtime</script>'}]};
function change(){return {id:'<id>',action:'extend_pause',outcome:'applied',actor:'Admin',target_names:[],requested_at:'2026-10-25T00:00:00Z',details:{timing:{version:1,timezone:'Europe/London',request:{mode:'extend_minutes',value:60},changes:[{id:'e',before:record,after:{...record,expires_at:'2026-10-25T01:30:00Z'}}]}}};}
test('history keeps original timezone and distinguishes repeated clock-change times',()=>{
 const html=card().timingHistoryHTML(change());
 assert.match(html,/Extend by 60 minutes from previous deadline/);
 assert.match(html,/Saved timezone: Europe\/London/);
 assert.match(html,/01:30:00 GMT\+1/);assert.match(html,/01:30:00 GMT(?:\+0)?</);
 assert.match(html,/2026/);assert.match(html,/data-readback-key="timing:&lt;id&gt;"/);
 assert.match(html,/&lt;img/);assert.match(html,/&lt;script&gt;/);assert.ok(!html.includes('<script>'));
 assert.match(html,/Gateway sync results and device tests are separate evidence/);
});
test('indefinite controls and cancellation are distinct and empty diffs are honest',()=>{
 const c=card(),r=change();r.details.timing.request={mode:'remove'};
 r.details.timing.changes=[{id:'e',before:{...record,expires_at:null},after:null}];
 let html=c.timingHistoryHTML(r);
 assert.match(html,/Before: No deadline · until ended/);assert.match(html,/After: No saved temporary control/);
 r.details.timing.changes=[];html=c.timingHistoryHTML(r);assert.match(html,/No saved deadlines or temporary controls changed/);
});
test('old history never borrows a current deadline and keeps existing allowance edit evidence',()=>{
 const c=card();c.data.exceptions=[{expires_at:'2026-10-30T10:00:00Z'}];
 assert.match(c.timingHistoryHTML({action:'pause_internet'}),/not recorded for this older change/);
 assert.equal(c.timingHistoryHTML({action:'sync_now'}),'');
 const html=c.timingHistoryHTML({action:'edit_allowance',details:{previous_deadline:null,expires_at:'2026-10-25T01:30:00Z'}});
 assert.match(html,/Recorded end time changed from Until resumed/);assert.match(html,/Requested timing mode was not recorded/);
 assert.match(c.timingHistoryHTML({details:{timing:{version:2}}}),/require a newer dashboard/);
});
test('default schedule and explicit modes explain requests without inventing finite deadlines',()=>{
 const c=card();for(const [request,expected] of [
  [{mode:'default'},'Default timing for this control'],[{mode:'duration_minutes',value:30},'30 minutes from request'],
  [{mode:'next_window_end',value:true},'Until applicable schedule windows end'],[{mode:'indefinite'},'No deadline · until ended'],
  [{mode:'implicit'},'Temporary controls updated by this change'],[{mode:'expires_at',value:'2026-10-25T00:30:00Z'},'End at 25 Oct 2026, 01:30:00 GMT+1'],
 ]){const r=change();r.details.timing.request=request;assert.ok(c.timingHistoryHTML(r).includes(expected),expected);}
});
test('recent Activity, full change history and linked sync results all show saved timing',async()=>{
 const c=card(),r=change();c.data.changes=[r];c.data.history={};
 // Activity has additional dashboard controls; isolate those unchanged helpers.
 c.accessCard=()=>'';c.updatesCard=()=>'';
 assert.match(c.activity(),/Saved timing details/);
 c.api=async()=>({items:[r]});await c.historyView();assert.match(c.rendered.body,/Saved timing details/);
 c.api=async()=>({items:[],change:r,latest:null});await c.historyView('sync',undefined,'',r.id);assert.match(c.rendered.body,/Saved timing details/);
});
