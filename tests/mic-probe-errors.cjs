'use strict';
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
assert.ok(js);
function harness(mediaDevices){
 const handlers={},elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,{
   textContent:'',disabled:false,style:{},setAttribute(){},
   addEventListener(type,fn){handlers[id+':'+type]=fn}
 });return elements.get(id)};
 const sandbox={
   document:{getElementById:el},navigator:{mediaDevices},
   window:{isSecureContext:true,cast:null,addEventListener(){}},
   setTimeout(){return 1},clearTimeout(){},cancelAnimationFrame(){},requestAnimationFrame(){return 1},
   Uint8Array,Date,Math,Number,Boolean,String
 };
 vm.runInNewContext(js,sandbox);
 return {handlers,el};
}
async function flush(){for(let i=0;i<8;i++)await Promise.resolve()}
(async()=>{
  const missing=harness(undefined);
  missing.handlers['start:click']();await flush();
  assert.match(missing.el('status').textContent,/API ikke tilgængelig/);
  assert.equal(missing.el('start').disabled,false);
  let calls=0;
  const denied=harness({getUserMedia(){calls++;return Promise.reject({name:'NotAllowedError',message:'Denied'})}});
  denied.handlers['start:click']();await flush();
  assert.equal(calls,1);
  assert.match(denied.el('status').textContent,/NotAllowedError/);
  assert.equal(denied.el('start').disabled,false);
  console.log('PASS: unavailable API and denied permission fail closed');
})().catch(err=>{console.error(err);process.exitCode=1});
