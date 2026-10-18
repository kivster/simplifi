import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
let Card;
vm.runInNewContext(readFileSync(new URL('../../custom_components/family_network/frontend/family-network-card.js',import.meta.url),'utf8'),{
 HTMLElement:class{},window:{},FormData:class{constructor(form){this.fields=form.fields;}get(k){return this.fields.get(k);}has(k){return this.fields.has(k);}},
 customElements:{get:()=>undefined,define:(_n,c)=>Card=c}
});
function card(){const c=Object.create(Card.prototype);c.data={timezone:'Europe/London',revision:4};c.open=(title,body,footer,modal)=>{c.rendered={title,body,footer,modal};};c.showError=e=>{c.error=e;};return c;}
test('sync history retains cursor and escapes failure messages',async()=>{
 const c=card();c.api=async(s,p)=>{c.called={s,p};return {items:[{id:'run',started_at:'2026-10-14T12:00:00Z',revision:4,outcome:'failed',issue:'<script>bad</script>',writes:{create:0,update:1,delete:0}}],next_cursor:'run'};};
 await c.historyView('sync','previous','failed');assert.equal(c.called.s,'activity_history');assert.equal(c.called.p.before_id,'previous');assert.equal(c._historyNext,'run');
 assert.match(c.rendered.body,/&lt;script&gt;/);assert.ok(!c.rendered.body.includes('<script>'));assert.match(c.rendered.footer,/Older/);
});
test('recovery never offers attachment for changed or duplicate policies',async()=>{
 const c=card();c.api=async()=>({revision:4,observed_at:'2026-10-14T12:00:00Z',drift:[],operations:[{operation_id:'op',action:'create',revision:4,created_at:'2026-10-14T11:00:00Z',candidate_id:null,can_close_absent:false,message:'Multiple matches',requested_policy:{name:'<img>'}}]});
 await c.recoveryView();assert.ok(!c.rendered.body.includes('Review resolution'));assert.match(c.rendered.body,/&lt;img&gt;/);assert.match(c.rendered.body,/never close an absent or unchanged request while UniFi may still be processing/);
});
test('unchanged update recovery explains late effects and requires independent completion',async()=>{
 const c=card();const row={operation_id:'op',action:'update',preview_hash:'proof',candidate_id:null,can_close_not_applied:true,policy_id:'<policy>',message:'Unchanged does not mean finished'};
 c.api=async()=>({revision:3,observed_at:'2026-10-14T12:00:00Z',drift:[],operations:[row]});
 await c.recoveryView();assert.match(c.rendered.body,/Review resolution/);
 c.recoveryForm('op');assert.equal(c.rendered.title,'Confirm request ended without a change');
 assert.match(c.rendered.body,/delayed request override your newer settings/);assert.match(c.rendered.body,/&lt;policy&gt;/);
 assert.match(c.rendered.body,/finished without changing this policy/);
 c._modal=c.rendered.modal;c.form=()=>({reportValidity:()=>true,fields:new Map([['reason','Checked completion'],['confirm',true]])});
 c.perform=async(s,p,t,r)=>{c.sent={s,p,r};};await c.submit();assert.equal(c.sent,undefined);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['reason','Checked completion'],['confirm',true],['request_finished',true]])});
 await c.submit();assert.equal(c.sent.s,'resolve_operation');assert.equal(c.sent.p.decision,'confirm_not_applied');assert.equal(c.sent.p.preview_hash,'proof');assert.equal(c.sent.r,3);
});
test('absent recovery requires both acknowledgement fields and submits original evidence',async()=>{
 const c=card();const row={operation_id:'op',preview_hash:'proof',candidate_id:null,message:'No match'};
 c._recovery={revision:3,operations:[row]};c.recoveryForm('op');assert.match(c.rendered.body,/incorrect confirmation can create a duplicate policy/);
 c._modal=c.rendered.modal;c.form=()=>({reportValidity:()=>true,fields:new Map([['reason','Checked controller'],['confirm',true]])});
 c.perform=async(s,p,t,r)=>{c.sent={s,p,r};};await c.submit();assert.equal(c.sent,undefined);
 c.form=()=>({reportValidity:()=>true,fields:new Map([['reason','Checked controller'],['confirm',true],['request_finished',true]])});
 await c.submit();assert.equal(c.sent.s,'resolve_operation');assert.equal(c.sent.p.preview_hash,'proof');assert.equal(c.sent.p.decision,'confirm_absent');assert.equal(c.sent.r,3);
});
test('linked sync history keeps original failure and separately shows the latest matching result',async()=>{
 const c=card();c.api=async(s,p)=>{c.called={s,p};return {change:{id:'c',action:'pause_internet',actor:'<admin>',outcome:'failed',requested_at:'2026-10-14T12:00:00Z'},items:[],latest:{outcome:'applied',finished_at:'2026-10-14T12:02:00Z'},next_cursor:'older'};};
 await c.historyView('sync',undefined,'failed','c');
 assert.equal(c.called.p.change_id,'c');assert.equal(c._historyChangeId,'c');assert.equal(c.rendered.title,'Sync results');
 for(const text of ['Original result:','Attempt failed','Latest sync for these settings:','applied','expired temporary action','&lt;admin&gt;']) assert.ok(c.rendered.body.includes(text),text);
 assert.ok(!c.rendered.body.includes('name="history_kind"'));assert.match(c.rendered.footer,/All history/);
});
test('history links survive pagination and outcome filtering and clear for all history',async()=>{
 const c=card();let calls=[];c.api=async(s,p)=>{calls.push(p);return {items:[],next_cursor:'next'};};
 await c.click({composedPath:()=>[{dataset:{action:'history-change',id:'change'}}]});
 await c.click({composedPath:()=>[{dataset:{action:'history-older'}}]});
 await c.click({composedPath:()=>[{dataset:{action:'history-newest'}}]});
 assert.ok(calls.every(p=>p.change_id==='change'));assert.equal(calls[1].before_id,'next');assert.equal(calls[2].before_id,undefined);
 c.form=()=>({elements:{history_outcome:{value:'failed'}}});
 c.change({target:{name:'history_outcome',dataset:{}}});await Promise.resolve();
 assert.equal(calls.at(-1).change_id,'change');assert.equal(calls.at(-1).outcome,'failed');
 await c.click({composedPath:()=>[{dataset:{action:'history'}}]});
 assert.equal(calls.at(-1).change_id,undefined);assert.equal(c._historyChangeId,undefined);
});
test('DNS and grant records never offer unrelated policy sync links',()=>{
 const c=card();const base={id:'id',action:'pause_internet',outcome:'failed',requested_at:'2026-10-14T12:00:00Z'};
 assert.match(c.historyChangeButton(base),/aria-label="View sync results/);
 assert.equal(c.historyChangeButton({...base,dns_revision:0}),'');assert.equal(c.historyChangeButton({...base,access_revision:0}),'');
 assert.equal(c.historyChangeButton({...base,outcome:'recovery_recorded'}),'');
 assert.match(c.historyChangeButton({...base,id:'<id>'}),/data-id="&lt;id&gt;"/);
});
test('missing retained syncs never claim a recovered or applied action',async()=>{
 const c=card();c.api=async()=>({items:[],change:{id:'c',action:'pause_internet',outcome:'failed',requested_at:'2026-10-14T12:00:00Z'},latest:null});
 await c.historyView('sync',undefined,'','c');
 assert.match(c.rendered.body,/No sync results are retained for this change/);assert.match(c.rendered.body,/This does not confirm success/);
 assert.ok(!c.rendered.body.includes('Latest sync for these settings:'));
});
