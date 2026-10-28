'use strict';
// Kaliv display protocol v1: the receiver must behave exactly as protocol/kaliv-display-v1.json says.
// The Python sender is checked against the same file in tests/test_kaliv_display_contract.py.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const contract = JSON.parse(fs.readFileSync('protocol/kaliv-display-v1.json', 'utf8'));
const html = fs.readFileSync('mic-diagnostic.html', 'utf8');
const script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(Boolean);
assert.ok(html.includes(`'${contract.namespace}'`), 'receiver uses the contract namespace');

const nodes = new Map();
const element = id => {
  if (!nodes.has(id)) nodes.set(id, {textContent: '', disabled: false, style: {}, classList: {toggle() {}},
    setAttribute() {}, addEventListener() {}});
  return nodes.get(id);
};
const outgoing = [];
let listener;
const castReceiver = {addCustomMessageListener(ns, cb) { assert.equal(ns, contract.namespace); listener = cb; },
  sendCustomMessage(_ns, _to, message) { outgoing.push(message); }, start() {}};
vm.runInNewContext(script, {
  document: {getElementById: element}, navigator: {mediaDevices: {}},
  window: {cast: {framework: {CastReceiverContext: {getInstance: () => castReceiver}, CastReceiverOptions: class {}}},
    isSecureContext: true, addEventListener() {}},
  console, Math, Date, Uint8Array, Boolean, Number, String, setTimeout() {}, clearTimeout() {},
  requestAnimationFrame() {}, cancelAnimationFrame() {}
});
const id = 'b'.repeat(32);
const send = data => { listener({data: {...data, request_id: id}}); return outgoing.at(-1); };

for (const state of contract.states) {
  const ack = send({type: 'SET_STATE', state});
  assert.deepEqual([ack.type, ack.result, ack.state, ack.request_id], [contract.commands.SET_STATE.ack, 'updated', state, id], state);
  assert.notEqual(element('kaliv-state').textContent, '', `state ${state} has display text`);
  const status = send({type: 'GET_DISPLAY_STATUS'});
  assert.equal(status.type, contract.commands.GET_DISPLAY_STATUS.ack);
  assert.equal(status.state, state, 'status reflects the last state');
  assert.equal(status.protocol, contract.version);
}
for (const bad of ['', 'Idle', 'talking', null, 7]) {
  assert.equal(send({type: 'SET_STATE', state: bad}).result, 'invalid', `state ${bad} is rejected`);
}
const limit = contract.max_text_utf16_units;
assert.equal(send({type: 'SHOW_MESSAGE', text: 'x'.repeat(limit)}).result, 'shown');
assert.equal(send({type: 'SHOW_MESSAGE', text: 'x'.repeat(limit + 1)}).result, 'invalid');
const shown = send({type: 'SHOW_MESSAGE', text: 'Hej 😀'});
assert.deepEqual([shown.type, shown.result, shown.length], [contract.commands.SHOW_MESSAGE.ack, 'shown', 'Hej 😀'.length]);
let status = send({type: 'GET_DISPLAY_STATUS'});
assert.deepEqual([status.has_message, status.length], [true, 'Hej 😀'.length]);
const cleared = send({type: 'CLEAR_MESSAGE'});
assert.deepEqual([cleared.type, cleared.result], [contract.commands.CLEAR_MESSAGE.ack, 'cleared']);
status = send({type: 'GET_DISPLAY_STATUS'});
assert.deepEqual([status.state, status.has_message, status.length], ['idle', false, 0]);
assert.equal(send({type: 'SHOW_DIAGNOSTICS', visible: true}).type, contract.commands.SHOW_DIAGNOSTICS.ack);

for (const unknown of ['SPEAK', 'show_message', undefined]) {
  const ack = send({type: unknown});
  assert.deepEqual([ack.type, ack.result, ack.request_id],
    [contract.unknown_command_ack.type, contract.unknown_command_ack.result, id], `unknown ${unknown} is reported`);
}
for (const [command, spec] of Object.entries(contract.commands)) {
  assert.ok(html.includes(`type==='${command}'`), `receiver handles ${command}`);
  for (const result of spec.results) assert.ok(html.includes(`result:'${result}'`), `${command} can answer ${result}`);
}
console.log('PASS: receiver matches Kaliv display protocol v1 (states, acks, status, limits, unknown commands)');
