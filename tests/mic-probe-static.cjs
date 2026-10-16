'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const html = fs.readFileSync('mic-diagnostic.html','utf8');
for (const expected of [
 'cast_receiver_framework.js','CastReceiverContext.getInstance()',
 'receiver.start(options)','getUserMedia({audio:true,video:false})',
 'getAudioTracks()','createMediaStreamSource(stream)',
 'stream.getTracks().forEach(t=>t.stop())',
 'setTimeout(', '10000', "addEventListener('pagehide'"
]) assert.ok(html.includes(expected), 'Missing required probe behavior: '+expected);
assert.ok(!/fetch\s*\(|XMLHttpRequest|WebSocket|MediaRecorder|sendMessage\s*\(/.test(html), 'Unexpected network or recording API');
assert.ok(!/https?:\/\/(?!www\.gstatic\.com\/cast\/sdk\/libs\/caf_receiver\/v3\/cast_receiver_framework\.js)/.test(html), 'Unexpected external URL');
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).filter(Boolean);
assert.match(html,/request_id:requestId/, 'New receiver must reflect correlated Cast command IDs');
assert.match(html,/requestId===\x27string\x27/, 'Echo only valid optional request IDs');
assert.equal(scripts.length,1);
new (require('node:vm').Script)(scripts[0],{filename:'mic-diagnostic-inline.js'});
// Exercise the actual listener, rather than trusting source-string checks.
const vm = require('node:vm');
const nodes = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, {
    textContent: '', disabled: false, style: {},
    classList: { toggle() {} }, setAttribute() {}, addEventListener() {}
  });
  return nodes.get(id);
};
const outgoing = [];
let controlListener;
const castReceiver = {
  addCustomMessageListener(_ns, callback) { controlListener = callback; },
  sendCustomMessage(_ns, _recipient, message) { outgoing.push(message); },
  start() {}
};
const context = {
  document: { getElementById: element },
  navigator: { mediaDevices: {} },
  window: {
    cast: { framework: {
      CastReceiverContext: { getInstance: () => castReceiver },
      CastReceiverOptions: class {}
    } },
    isSecureContext: true,
    addEventListener() {}
  },
  console, Math, Date, Uint8Array, Boolean, Number, String,
  setTimeout() {}, clearTimeout() {},
  requestAnimationFrame() {}, cancelAnimationFrame() {}
};
vm.runInNewContext(scripts[0], context, {filename:'cast-ack-receiver.js'});
assert.equal(typeof controlListener, 'function');

const requestId = 'a'.repeat(32);
controlListener({data:{type:'SET_STATE',state:'thinking',request_id:requestId}});
assert.equal(outgoing.at(-1).type, 'KALIV_STATE');
assert.equal(outgoing.at(-1).state, 'thinking');
assert.equal(outgoing.at(-1).result, 'updated');
assert.equal(outgoing.at(-1).request_id, requestId);
controlListener({data:{type:'SHOW_MESSAGE',text:'Hej 😀',request_id:requestId}});
assert.equal(outgoing.at(-1).type, 'KALIV_DISPLAY');
assert.equal(outgoing.at(-1).result, 'shown');
assert.equal(outgoing.at(-1).request_id, requestId);
assert.equal(outgoing.at(-1).length, 'Hej 😀'.length);
assert.equal(element('kaliv-message').textContent,'Hej 😀');
controlListener({data:{type:'CLEAR_MESSAGE',request_id:requestId}});
assert.equal(outgoing.at(-1).result, 'cleared');
assert.equal(outgoing.at(-1).request_id, requestId);
controlListener({data:{type:'SET_STATE',state:'idle'}});
assert.equal(Object.hasOwn(outgoing.at(-1),'request_id'), false,
  'Legacy Cast senders must receive an uncorrelated ACK');
controlListener({data:{type:'SHOW_MESSAGE',text:'Hej',request_id:'malformed'}});
assert.equal(Object.hasOwn(outgoing.at(-1),'request_id'), false,
  'Malformed request IDs must not be echoed');
console.log('PASS: real Cast state/display/clear listener echoes only valid request IDs');
console.log('PASS: isolated mic probe static contract and JS syntax');
