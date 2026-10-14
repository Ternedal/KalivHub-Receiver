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
assert.equal(scripts.length,1);
new (require('node:vm').Script)(scripts[0],{filename:'mic-diagnostic-inline.js'});
console.log('PASS: isolated mic probe static contract and JS syntax');
