'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const source=fs.readFileSync('mic-diagnostic.html');
const packaged=fs.readFileSync('dist/index.html');
assert.deepEqual(packaged,source,'packaged receiver must match diagnostic source byte-for-byte');
const html=packaged.toString('utf8');
assert.match(html,/KalivHub · Mikrofon-diagnose/);
assert.doesNotMatch(html,/Home Assistant|access_token|Authorization:\s*Bearer/i);
console.log('PASS: isolated diagnostic artifact matches source; sha256='+crypto.createHash('sha256').update(packaged).digest('hex'));
