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
 const listeners={};const sent=[];let now=100000;const ctx={addCustomMessageListener(ns,fn){listeners[ns]=fn},sendCustomMessage(ns,to,data){sent.push({ns,to,data})},start(){}};
 const DateMock=class extends Date{constructor(...a){super(...(a.length?a:[now]))}static now(){return now}};
 const context={document:{getElementById:get,createElement:()=>element(),addEventListener(){}},window:{cast:{framework:{}}},cast:{framework:{CastReceiverContext:{getInstance:()=>ctx}}},Date:DateMock,setInterval(){},console,Math};
 vm.runInNewContext(script,context,{filename:'receiver-inline.js'});
 const receive=(data,senderId='sender-1')=>listeners['urn:x-cast:dk.kalivhub.lab']({data,senderId});
 const snapshot=(sequence,session_id='session1234',state='off')=>receive({type:'snapshot',version:1,sequence,session_id,entities:[{entity_id:'light.kitchen',name:'Kitchen',state}]});
 return {get,receive,snapshot,sent,setNow:v=>{now=v},tick:()=>{ /* trigger stale through new Date requires interval callback */}};
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
 h.snapshot(1,'another123','on');assert.equal(h.get('tiles').children[0].children[1].textContent,'on','new session accepted');assert.equal(h.get('tiles').children[0].getAttribute('role'),null,'new session revokes controls');
}
console.log('Receiver behavior checks OK');
