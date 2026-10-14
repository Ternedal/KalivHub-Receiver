const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(x=>x[1]).find(x=>x.trim());
assert.ok(script,'inline script exists');
function element(id=''){
 const attributes={};const el={id,children:[],dataset:{},className:'',textContent:'',onclick:null,onkeydown:null,style:{},classList:{_v:new Set(),add(x){this._v.add(x)},remove(x){this._v.delete(x)},contains(x){return this._v.has(x)}},
 setAttribute(k,v){attributes[k]=v},getAttribute(k){return attributes[k]||null},append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},getClientRects(){return []},getBoundingClientRect(){return {left:0,right:0,top:0,bottom:0}},click(){this.onclick?.()},querySelector(){return this.small||(this.small=element('small'))}};return el;
}
function harness(){
 const ids=new Map();const get=id=>{if(!ids.has(id))ids.set(id,element(id));return ids.get(id)};
 const listeners={};const sent=[];let now=100000;let scheduledTick=null;let deliveryFailure=false;let deferredFailure=null;let delayedReject=null;const ctx={addCustomMessageListener(ns,fn){listeners[ns]=fn},sendCustomMessage(ns,to,data){sent.push({ns,to,data});if(deliveryFailure)return {catch(fn){fn(new Error('offline'))}};if(deferredFailure)return {catch(fn){delayedReject=fn}}},start(){}};
 const DateMock=class extends Date{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
 const context={document:{getElementById:get,createElement:()=>element(),addEventListener(){}},window:{cast:{framework:{}}},cast:{framework:{CastReceiverContext:{getInstance:()=>ctx}}},Date:DateMock,setInterval(fn){scheduledTick=fn},console,Math};
 vm.runInNewContext(script,context,{filename:'receiver-inline.js'});
 const receive=(data,senderId='sender-1')=>listeners['urn:x-cast:dk.kalivhub.lab']({data,senderId});
 const snapshot=(sequence,session_id='session1234',state='off')=>receive({type:'snapshot',version:1,sequence,session_id,entities:[{entity_id:'light.kitchen',name:'Kitchen',state}]});
 return {get,receive,snapshot,sent,setNow:v=>{now=v},failDelivery:v=>{deliveryFailure=v},deferFailure:v=>{deferredFailure=v},rejectDelayed:()=>delayedReject?.(new Error('offline')),tick:()=>scheduledTick?.()};
}
{
 const h=harness();h.receive({type:'control_capabilities',version:1,enabled:true});assert.equal(h.get('devices').querySelector('small').textContent,'Kun visning','capabilities alone cannot enable controls');
 h.snapshot(1);h.receive({type:'control_capabilities',version:1,enabled:true});assert.equal(h.get('tiles').children[0].getAttribute('role'),'button');
 h.get('tiles').children[0].click();assert.equal(h.sent.length,1);assert.equal(h.sent[0].data.action,'turn_on');
 h.get('tiles').children[0].click();assert.equal(h.sent.length,1,'repeated tap suppressed');
 h.snapshot(2,'session1234','on');h.get('tiles').children[0].click();assert.equal(h.sent.length,2,'confirmed state permits next tap');assert.equal(h.sent[1].data.action,'turn_off');
 h.snapshot(3,'session1234','on');h.setNow(116000);h.get('tiles').children[0].click();assert.equal(h.sent.length,3,'pending timeout permits retry');
}
{
 const h=harness();h.snapshot(1);h.receive({type:'control_capabilities',version:1,enabled:true});h.snapshot(1,'session1234','on');assert.equal(h.get('tiles').children[0].textContent,'');assert.equal(h.get('tiles').children[0].children[1].textContent,'off','duplicate sequence ignored');
 h.snapshot(2,'bad!','on');assert.equal(h.get('tiles').children[0].children[1].textContent,'off','invalid session rejected');
 h.receive({type:'snapshot',version:1,entities:[{entity_id:'light.kitchen',name:'Kitchen',state:'on'}]});assert.equal(h.get('tiles').children[0].children[1].textContent,'off','unsequenced snapshot rejected');
 h.snapshot(1,'another123','on');assert.equal(h.get('tiles').children[0].children[1].textContent,'on','new session accepted');assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'new session revokes controls');
}
{
 const h=harness();h.snapshot(1);h.receive({type:'control_capabilities',version:1,enabled:true});
 assert.equal(h.get('tiles').children[0].getAttribute('role'),'button');
 h.get('tiles').children[0].click();
 assert.equal(h.sent.length,1,'control request pending before timeout');
 h.setNow(146000);h.tick();
 assert.equal(h.get('indicator').className,'stale','timeout marks connection stale');
 assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'stale snapshot revokes control');
 h.receive({type:'control_capabilities',version:1,enabled:true});
 assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'capabilities alone cannot re-enable stale controls');
 h.snapshot(2);h.receive({type:'control_capabilities',version:1,enabled:true});
 assert.equal(h.get('tiles').children[0].getAttribute('role'),'button','fresh snapshot restores controls');
 h.get('tiles').children[0].click();
 assert.equal(h.sent.length,2,'reconnection clears pending controls from expired session');
}
{
 const h=harness();h.snapshot(1);
 h.receive({type:'control_capabilities',version:1,enabled:true},'different-sender');
 assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'other sender cannot enable controls');
 h.receive({type:'control_capabilities',version:1,enabled:true},'sender-1');
 assert.equal(h.get('tiles').children[0].getAttribute('role'),'button','snapshot sender can enable controls');
 h.receive({type:'control_capabilities',version:1,enabled:false},'different-sender');
 assert.equal(h.get('tiles').children[0].getAttribute('role'),'button','foreign sender cannot revoke active controls');
 h.receive({type:'snapshot',version:1,sequence:1,session_id:'other12345',entities:[{entity_id:'light.kitchen',name:'Kitchen',state:'on'}]},'different-sender');
 assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'sender switch revokes controls');
}
{
 const h=harness();h.snapshot(1);h.receive({type:'control_capabilities',version:1,enabled:true});
 h.failDelivery(true);h.get('tiles').children[0].click();
 assert.equal(h.sent.length,1);
 assert.equal(h.get('connection').textContent,'Kunne ikke sende kommando','asynchronous failure is visible');
 h.failDelivery(false);h.get('tiles').children[0].click();
 assert.equal(h.sent.length,2,'failed delivery does not lock out retries');
}
{
 const h=harness();h.snapshot(1);
 const duplicate={entity_id:'light.kitchen',name:'Kitchen',state:'on'};
 h.receive({type:'snapshot',version:1,session_id:'session1234',sequence:2,entities:[duplicate,duplicate]});
 assert.equal(h.get('tiles').children.length,1,'duplicate entity IDs rejected');
 assert.equal(h.get('tiles').children[0].children[1].textContent,'off','invalid snapshot does not overwrite state');
 h.snapshot(2,'session1234','on');
 assert.equal(h.get('tiles').children[0].children[1].textContent,'on','rejected snapshot does not advance sequence');
}
{
 const h=harness();h.snapshot(1);
 h.receive({type:'snapshot',version:1,session_id:'session1234',sequence:2,entities:[{entity_id:'light.kitchen',name:'Bad\\u0085Name',state:'on'}]});
 assert.equal(h.get('tiles').children[0].children[1].textContent,'off','C1 control character rejected');
 h.snapshot(2,'session1234','on');
 assert.equal(h.get('tiles').children[0].children[1].textContent,'on','rejected text does not advance sequence');
}
{
 const h=harness();h.snapshot(1);h.receive({type:'control_capabilities',version:1,enabled:true});
 h.deferFailure(true);h.get('tiles').children[0].click();
 h.setNow(146000);h.tick();
 h.rejectDelayed();
 assert.equal(h.get('connection').textContent,'Forbindelsen er afbrudt','late delivery failure cannot overwrite disconnect status');
 h.snapshot(2);h.receive({type:'control_capabilities',version:1,enabled:true});
 h.rejectDelayed();
 assert.equal(h.get('connection').textContent,'Forbundet · 1 enheder','late failure cannot overwrite recovered status');
}
{
 const h=harness();
 h.get('devices').click();
 assert.equal(h.get('panel').getAttribute('aria-hidden'),'false','devices opens panel');
 assert.equal(h.get('devices').getAttribute('aria-expanded'),'true','devices exposes expanded state');
 h.get('assistant').click();
 assert.equal(h.get('panel').getAttribute('aria-hidden'),'true','assistant closes panel for accessibility');
 assert.equal(h.get('devices').getAttribute('aria-expanded'),'false','assistant resets expanded state');
}
{
 const h=harness();
 h.receive({type:'snapshot',version:1,sequence:1,session_id:'session1234',entities:[
  {entity_id:'light.kitchen',name:'Køkkenlys',state:'on',room:'Køkken'},
  {entity_id:'sensor.bedroom',name:'Temperatur',state:'21',room:'Soveværelse'},
  {entity_id:'light.bedroom',name:'Lampe',state:'off',room:'Soveværelse'}
 ]});
 assert.equal(h.get('tiles').children.length,3,'room grouping retains all tiles');
 assert.equal(h.get('tiles').children[0].dataset.room,'Køkken','first room heading');
 assert.equal(h.get('tiles').children[1].dataset.room,'Soveværelse','second room heading');
 assert.equal(h.get('tiles').children[2].dataset.room,undefined,'room heading not repeated');
}
{
 const h=harness();
 h.receive({type:'snapshot',version:1,sequence:1,session_id:'session1234',entities:[
  {entity_id:'climate.living',name:'Varme',state:'heat',room:'Stue',current_temperature:21,temperature:23}
 ]});
 const tile=h.get('tiles').children[0];
 assert.equal(tile.children[2].textContent,'Nu 21 °C · Mål 23 °C','climate current and target shown');
 assert.equal(tile.getAttribute('role'),null,'climate control remains read-only');
}
{
 const h=harness();
 h.receive({type:'snapshot',version:1,sequence:1,session_id:'session1234',entities:[
  {entity_id:'camera.front_door',name:'Hoveddør',state:'idle',room:'Entré'}
 ]});
 const tile=h.get('tiles').children[0];
 assert.equal(tile.dataset.room,'Entré','camera grouped in assigned room');
 assert.match(tile.children[2].textContent,/livevisning kræver sikker streamforbindelse/,'camera stream limitation visible');
 assert.equal(tile.getAttribute('role'),null,'camera is not an unsafe control');
}
console.log('Receiver behavior checks OK');
