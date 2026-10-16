'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('mic-diagnostic.html','utf8');
const js=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
const handlers={},elements=new Map();let stopped=0;
const el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',disabled:false,style:{},setAttribute(){},addEventListener(type,fn){handlers[id+':'+type]=fn}});return elements.get(id)};
const sandbox={
 document:{getElementById:el},
 navigator:{mediaDevices:{getUserMedia:async()=>({getAudioTracks:()=>[],getTracks:()=>[{stop(){stopped++}}]})}},
 window:{isSecureContext:true,cast:null,addEventListener(){}},
 setTimeout(){return 1},clearTimeout(){},cancelAnimationFrame(){},requestAnimationFrame(){return 1},
 Uint8Array,Date,Math,Number,Boolean,String
};
vm.runInNewContext(js,sandbox);
(async()=>{
 handlers['start:click']();
 for(let i=0;i<10;i++)await Promise.resolve();
 assert.equal(stopped,1);
 assert.equal(el('start').disabled,false);
 assert.match(el('status').textContent,/Ingen lydspor/);
 console.log('PASS: empty audio stream is rejected and closed');
})().catch(e=>{console.error(e);process.exitCode=1});
