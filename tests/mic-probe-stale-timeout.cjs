'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
const callbacks=[],handlers={},elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',disabled:false,style:{},setAttribute(){},addEventListener(t,fn){handlers[id+':'+t]=fn}});return elements.get(id)};
const pending=[];
const sandbox={
 document:{getElementById:el},
 navigator:{mediaDevices:{getUserMedia(){return new Promise(resolve=>pending.push(resolve))}}},
 window:{isSecureContext:true,cast:null,addEventListener(){}},
 setTimeout(fn){callbacks.push(fn);return callbacks.length},
 clearTimeout(){},requestAnimationFrame(){return 1},cancelAnimationFrame(){},
 Uint8Array,Date,Math,Boolean,Number,String
};
vm.runInNewContext(js,sandbox);
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve()};
(async()=>{
 handlers['start:click']();
 assert.equal(pending.length,1);
 callbacks[0]();await flush();
 assert.equal(el('start').disabled,false);
 handlers['start:click']();
 assert.equal(pending.length,2);
 assert.equal(el('start').disabled,true);
 callbacks[0]();await flush();
 assert.equal(el('start').disabled,true,'stale timeout must not cancel active request');
 assert.doesNotMatch(el('status').textContent,/Tidsgrænse/);
 callbacks[1]();await flush();
 assert.equal(el('start').disabled,false);
 console.log('PASS: stale timeout cannot stop newer microphone session');
})().catch(err=>{console.error(err);process.exitCode=1});
