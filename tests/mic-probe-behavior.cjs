'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x=>x[1]).find(Boolean);
assert.ok(js,'inline script exists');
const listeners={};
const elements=new Map();
function element(id){
 if(!elements.has(id))elements.set(id,{textContent:'',disabled:false,style:{},attrs:{},setAttribute(k,v){this.attrs[k]=v},addEventListener(type,cb){listeners[id+':'+type]=cb}});
 return elements.get(id);
}
let resolver,tracksStopped=0,requested=0;
const pending=new Promise(resolve=>{resolver=resolve});
let timerCb;
const ctx={
 document:{getElementById:element},navigator:{mediaDevices:{getUserMedia(){requested++;return pending}}},
 window:{isSecureContext:true,addEventListener(){},cast:null},
 setTimeout(cb){timerCb=cb;return 1},clearTimeout(){},requestAnimationFrame(){return 1},cancelAnimationFrame(){},
 Uint8Array,Date,Math,Boolean,Number,String
};
ctx.window.window=ctx.window;
vm.runInNewContext(js,ctx);
async function flush(){for(let i=0;i<5;i++)await Promise.resolve()}
(async()=>{
 assert.equal(typeof listeners['start:click'],'function');
 listeners['start:click']();
 assert.equal(requested,1);
 assert.equal(element('start').disabled,true);
 assert.equal(typeof timerCb,'function');
 timerCb();await flush();
 assert.equal(element('start').disabled,false);
 resolver({getTracks(){return [{stop(){tracksStopped++}}]}});
 await flush();
 assert.equal(tracksStopped,1,'late microphone permission stream must be stopped');
 assert.equal(element('start').disabled,false);
 console.log('PASS: timeout cancels pending capture and closes late stream');
})().catch(e=>{console.error(e);process.exitCode=1});
