'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
const listeners={},els=new Map();
const element=id=>{if(!els.has(id))els.set(id,{textContent:'',disabled:false,style:{},setAttribute(){},addEventListener(type,fn){listeners[id+':'+type]=fn}});return els.get(id)};
let resolveCapture,stops=0;
const sandbox={
 document:{getElementById:element},
 navigator:{mediaDevices:{getUserMedia(){return new Promise(resolve=>{resolveCapture=resolve})}}},
 window:{isSecureContext:true,cast:null,addEventListener(){}},
 setTimeout(){return 1},clearTimeout(){},requestAnimationFrame(){return 1},cancelAnimationFrame(){},
 Uint8Array,Date,Math,Boolean,Number,String
};
vm.runInNewContext(js,sandbox);
async function flush(){for(let i=0;i<12;i++)await Promise.resolve()}
(async()=>{
 listeners['start:click']();
 assert.equal(element('start').disabled,true);
 listeners['stop:click']();
 await flush();
 assert.equal(element('start').disabled,false);
 resolveCapture({getTracks(){return [{stop(){stops++}}]}});
 await flush();
 assert.equal(stops,1,'stream granted after Stop must be closed');
 assert.equal(element('start').disabled,false);
 assert.equal(element('stop').disabled,true);
 console.log('PASS: explicit Stop before permission grant closes late stream');
})().catch(e=>{console.error(e);process.exitCode=1});
