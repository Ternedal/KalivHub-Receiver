const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const html = fs.readFileSync('index.html', 'utf8');
const matches = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
const inline = matches.map(m => m[1]).filter(s => s.trim());
assert.equal(inline.length, 1, 'Expected exactly one inline receiver script');
new vm.Script(inline[0], { filename: 'receiver-inline.js' });
console.log('Receiver inline JavaScript syntax OK');
