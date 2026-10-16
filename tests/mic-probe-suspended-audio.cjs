'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
const handlers={},els=new Map();
const el=id=>{if(!els.has(id))els.set(id,{textContent:'',disabled:false,style:{},setAttribute(){},addEventListener(type,fn){handlers[id+':'+type]=fn}});return els.get(id)};
let resumed=0,closed=0,stopped=0,read=0;
class AudioContextMock {
 state='suspended';
 async resume(){resumed++;this.state='running'}
 createMediaStreamSource(){return {connect(){},disconnect(){}}}
 createAnalyser(){return {fftSize:1024,getByteTimeDomainData(bytes){read++;bytes.fill(128)}}}
 async close(){closed++}
}
const sandbox={
 document:{getElementById:el},
 navigator:{mediaDevices:{getUserMedia:async()=>({getAudioTracks(){return [{readyState:'live'}]},getTracks(){return [{stop(){stopped++}}]}})}},
 window:{isSecureContext:true,cast:null,AudioContext:AudioContextMock,addEventListener(){}},
 setTimeout(){return 1},clearTimeout(){},requestAnimationFrame(){return 1},cancelAnimationFrame(){},
 Uint8Array,Date,Math,Number,Boolean,String
};
vm.runInNewContext(js,sandbox);
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve()};
(async()=>{
 handlers['start:click']();await flush();
 assert.equal(resumed,1,'suspended audio context must be resumed');
 assert.equal(read,1,'meter should read after resume');
 handlers['stop:click']();await flush();
 assert.equal(stopped,1);
 assert.equal(closed,1);
 assert.equal(el('start').disabled,false);
 console.log('PASS: suspended audio context resumes, meters, and closes');
})().catch(err=>{console.error(err);process.exitCode=1});
