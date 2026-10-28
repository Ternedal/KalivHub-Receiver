// Voice display channel (kaliv_voice_status / kaliv_voice_text, ModelRig #2299).
// Contract: Receiver #8 comment 6480304891. The phone is the voice sender; HA
// snapshots may come from another sender (the PC mirror) at the same time.
// Voice is display-only, bound to its own sender and session, and released on
// the voice sender's disconnect or after VOICE_IDLE_MS without voice messages.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(x=>x[1]).find(x=>x.trim());
assert.ok(script,'inline script exists');
const initialText={subtitle:html.match(/<p id="subtitle">([^<]*)<\/p>/)[1]};
assert.ok(initialText.subtitle.length>0,'harness reads the default subtitle from index.html');
const initialSmall=Object.fromEntries([...html.matchAll(/<button id="([^"]+)"[^>]*>(?:(?!<\/button>)[\s\S])*?<small>([^<]*)<\/small>/g)].map(m=>[m[1],m[2]]));
function element(id='',tagName='DIV'){
 const attributes={};
 return {id,tagName,children:[],dataset:{},className:'',textContent:initialText[id]||'',onclick:null,onkeydown:null,style:{},
  classList:{_v:new Set(),add(x){this._v.add(x)},remove(x){this._v.delete(x)},contains(x){return this._v.has(x)}},
  setAttribute(k,v){attributes[k]=v},getAttribute(k){return attributes[k]||null},append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},
  getClientRects(){return []},getBoundingClientRect(){return {left:0,right:0,top:0,bottom:0}},click(){this.onclick?.()},
  querySelector(){return this.small||(this.small=Object.assign(element('small'),{textContent:initialSmall[id]||''}))}};
}
const DISCONNECTED='senderdisconnected';
function harness(){
 const ids=new Map();const get=id=>{if(!ids.has(id))ids.set(id,element(id));return ids.get(id)};
 const listeners={},events={},sent=[];let now=100000;let scheduledTick=null;
 const ctx={addCustomMessageListener(ns,fn){listeners[ns]=fn},addEventListener(type,fn){events[type]=fn},sendCustomMessage(ns,to,data){sent.push({ns,to,data})},start(){}};
 const DateMock=class extends Date{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
 const context={document:{getElementById:get,createElement:tag=>element('',tag.toUpperCase()),addEventListener(){}},window:{cast:{framework:{}}},
  cast:{framework:{CastReceiverContext:{getInstance:()=>ctx},system:{EventType:{SENDER_DISCONNECTED:DISCONNECTED}}}},Date:DateMock,setInterval(fn){scheduledTick=fn},console,Math};
 vm.runInNewContext(script,context,{filename:'receiver-inline.js'});
 const receive=(data,senderId)=>listeners['urn:x-cast:dk.kalivhub.lab']({data,senderId});
 let seq=0;
 const snapshot=(senderId='pc-mirror',session_id='hasession1')=>receive({type:'snapshot',version:1,sequence:++seq,session_id,entities:[{entity_id:'light.kitchen',name:'Kitchen',state:'off'}]},senderId);
 let n=0;const id=()=>'00000000-0000-4000-8000-'+String(++n).padStart(12,'0');
 const status=(phase,senderId='phone',session_id='voicesess1',extra={})=>{const message_id=id();receive(Object.assign({type:'kaliv_voice_status',version:1,session_id,message_id,phase},extra),senderId);return message_id};
 const text=(t,senderId='phone',session_id='voicesess1',extra={})=>{const message_id=id();receive(Object.assign({type:'kaliv_voice_text',version:1,session_id,message_id,role:'assistant',text:t},extra),senderId);return message_id};
 const acks=()=>sent.filter(x=>x.data.type==='kaliv_voice_ack');
 return {get,receive,snapshot,status,text,acks,sent,
  subtitle:()=>get('subtitle').textContent,
  setNow:v=>{now=v},advance:ms=>{now+=ms},tick:()=>scheduledTick?.(),
  disconnect:senderId=>events[DISCONNECTED]?.({senderId})};
}
const DEFAULT=initialText.subtitle;
const MIN=60000;

{ // PC mirror sends HA snapshots while the phone sends voice: both are shown.
 const h=harness();
 h.snapshot('pc-mirror');
 const m=h.status('listening','phone');
 assert.equal(h.subtitle(),'Lytter på telefonen','phone voice accepted while the PC mirror is the snapshot sender');
 assert.deepEqual(h.acks().map(a=>[a.to,a.data.message_id,a.data.phase,a.data.session_id]),[['phone',m,'listening','voicesess1']],'status acknowledged to the phone only');
 assert.equal(h.get('indicator').className,'ready','HA connection unaffected');
}
{ // Voice never grants or changes HA control rights.
 const h=harness();
 h.snapshot('pc-mirror');h.status('listening','phone');
 h.receive({type:'control_capabilities',version:1,enabled:true},'phone');
 assert.equal(h.get('devices').querySelector('small').textContent,'Kun visning','the voice sender cannot enable HA controls');
 h.receive({type:'control_capabilities',version:1,enabled:true},'pc-mirror');
 assert.equal(h.get('devices').querySelector('small').textContent,'Tryk for at styre','the snapshot sender still can');
 h.text('Svar','phone');
 assert.equal(h.get('devices').querySelector('small').textContent,'Tryk for at styre','voice text does not revoke HA controls');
}
{ // An unrelated third sender cannot take over a bound voice session.
 const h=harness();
 h.status('thinking','phone');
 h.status('listening','intruder');
 h.text('Hijack','intruder','voicesess1');
 assert.equal(h.subtitle(),'Kaliv tænker','foreign status and text rejected');
 assert.ok(h.acks().every(a=>a.to==='phone'),'nothing is acknowledged to the intruder');
}
{ // Text rules.
 const h=harness();
 h.text('Før status','phone');
 assert.equal(h.subtitle(),DEFAULT,'text before any status rejected');
 h.status('speaking','phone');
 const ok=h.text('Kaliv siger hej','phone');
 assert.equal(h.subtitle(),'Kaliv siger hej');
 assert.deepEqual(h.acks().slice(-1).map(a=>[a.to,a.data.message_id,a.data.kind,a.data.role]),[['phone',ok,'text','assistant']],'applied text acknowledged');
 const before=h.acks().length;
 h.text('x'.repeat(4001),'phone');
 h.text('   ','phone');
 h.text('Forkert session','phone','othersess9');
 h.text('Forkert rolle','phone','voicesess1',{role:'system'});
 h.text(42,'phone');
 h.text('Fra PC','pc-mirror');
 h.text('Ugyldigt id','phone','voicesess1',{message_id:'nope'});
 h.text('Ny version','phone','voicesess1',{version:2});
 assert.equal(h.subtitle(),'Kaliv siger hej','oversized, blank, wrong-session, wrong-role, non-string, foreign, bad-id and wrong-version text rejected');
 assert.equal(h.acks().length,before,'no ack for a rejected message');
 h.text('x'.repeat(4000),'phone');
 assert.equal(h.subtitle().length,4000,'4000 characters is still accepted');
}
{ // Status rules.
 const h=harness();
 h.status('singing','phone');
 h.status('listening','phone','bad!');
 h.status('listening','phone','voicesess1',{message_id:'1234'});
 h.status('listening','phone','voicesess1',{version:2});
 h.receive({type:'kaliv_voice_status',version:1,session_id:'voicesess1',message_id:'00000000-0000-4000-8000-000000000099',phase:'idle'},'');
 assert.equal(h.subtitle(),DEFAULT,'unknown phase, bad session, bad message id, wrong version and empty sender rejected');
 assert.equal(h.acks().length,0);
 h.status('listening','intruder');
 assert.equal(h.subtitle(),'Lytter på telefonen','rejected attempts did not bind anyone, so a valid status still binds');
}
{ // The same sender may start a new session; old-session text is then stale.
 const h=harness();
 h.status('idle','phone','voicesessA');
 h.status('listening','phone','voicesessB');
 h.text('Gammel','phone','voicesessA');
 assert.equal(h.subtitle(),'Lytter på telefonen','text from the replaced session rejected');
 h.text('Ny','phone','voicesessB');
 assert.equal(h.subtitle(),'Ny');
}
{ // HA snapshot sender/session rotation does not interrupt voice.
 const h=harness();
 h.snapshot('pc-mirror','hasession1');h.status('speaking','phone');
 h.snapshot('pc-mirror','hasession2');
 h.snapshot('pc-mirror-restarted','hasession3');
 h.text('Stadig her','phone');
 assert.equal(h.subtitle(),'Stadig her','voice survives HA sender and session changes');
}
{ // A stale HA connection does not release voice; voice has its own clock.
 const h=harness();
 h.snapshot('pc-mirror');h.status('speaking','phone');
 h.advance(46000);h.tick();
 assert.equal(h.get('indicator').className,'stale','HA is stale');
 h.text('Svar efter HA-timeout','phone');
 assert.equal(h.subtitle(),'Svar efter HA-timeout','voice still bound after the HA stale tick');
}
{ // Voice inactivity releases voice and clears the transcript while HA stays healthy.
 const h=harness();
 h.snapshot('pc-mirror');h.status('speaking','phone');h.text('Privat svar','phone');
 for(let i=0;i<10;i++){h.advance(30000);h.snapshot('pc-mirror');h.tick()}  // 5 min of live HA, no voice
 assert.equal(h.subtitle(),'Privat svar','not released at exactly 5 minutes');
 h.advance(1000);h.snapshot('pc-mirror');h.tick();
 assert.equal(h.subtitle(),DEFAULT,'transcript cleared after 5 minutes without voice messages');
 assert.equal(h.get('indicator').className,'ready','HA stays healthy');
 h.text('Sen tekst','phone');
 assert.equal(h.subtitle(),DEFAULT,'text after expiry needs a new status');
 h.status('listening','phone-reconnected');
 assert.equal(h.subtitle(),'Lytter på telefonen','a new sender can bind after expiry');
}
{ // Expiry is also honoured when a message arrives before the next tick.
 const h=harness();
 h.status('idle','phone');
 h.advance(5*MIN+1);
 h.status('listening','phone-new');
 assert.equal(h.subtitle(),'Lytter på telefonen','expired binding released on arrival');
}
{ // The voice sender's disconnect releases voice at once; other disconnects do not.
 const h=harness();
 h.snapshot('pc-mirror');h.status('speaking','phone');h.text('Svar','phone');
 h.disconnect('pc-mirror');
 assert.equal(h.subtitle(),'Svar','another sender disconnecting leaves voice alone');
 h.disconnect('phone');
 assert.equal(h.subtitle(),DEFAULT,'transcript cleared when the phone disconnects');
 h.status('thinking','phone-2');
 assert.equal(h.subtitle(),'Kaliv tænker','the reconnected phone (new sender id) binds');
 h.text('Fra gammel forbindelse','phone');
 assert.equal(h.subtitle(),'Kaliv tænker','the old sender id is no longer bound');
}
console.log('Receiver voice display checks OK');
