'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
const handlers={},els=new Map(),frames=[];
const el=id=>{if(!els.has(id))els.set(id,{textContent:'',disabled:false,style:{},setAttribute(k,v){this[k]=v},addEventListener(type,fn){handlers[id+':'+type]=fn}});return els.get(id)};
let reads=0,closed=0,stopped=0;
class AudioContextMock {
 state='running';
 createMediaStreamSource(){return {connect(){},disconnect(){}}}
 createAnalyser(){return {fftSize:1024,getByteTimeDomainData(values){reads++;values.fill(128)}}}
 async close(){closed++}
}
const sandbox={
 document:{getElementById:el},
 navigator:{mediaDevices:{getUserMedia:async()=>({getAudioTracks(){return [{readyState:'live'}]},getTracks(){return [{stop(){stopped++}}]}})}},
 window:{isSecureContext:true,cast:null,AudioContext:AudioContextMock,addEventListener(){}},
 setTimeout(){return 1},clearTimeout(){},requestAnimationFrame(fn){frames.push(fn);return frames.length},cancelAnimationFrame(){},
 Uint8Array,Date,Math,Number,Boolean,String
};
vm.runInNewContext(js,sandbox);
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve()};
(async()=>{
 handlers['start:click']();await flush();
 assert.equal(reads,1);
 const oldFrame=frames[0];
 handlers['stop:click']();await flush();
 assert.equal(stopped,1);assert.equal(closed,1);
 handlers['start:click']();await flush();
 assert.equal(reads,2);
 oldFrame();
 assert.equal(reads,2,'old meter callback must not sample newer stream');
 assert.equal(el('start').disabled,true);
 handlers['stop:click']();await flush();
 console.log('PASS: old meter frame cannot sample a new session');
})().catch(e=>{console.error(e);process.exitCode=1});
