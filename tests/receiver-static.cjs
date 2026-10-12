const fs = require('node:fs');
const assert = require('node:assert/strict');
const html = fs.readFileSync('index.html','utf8');
const js = html.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(js, 'inline receiver script exists');
new (require('node:vm').Script)(js);
for (const id of ['clock','connection','indicator','panel','tiles','devices','assistant','rest','back']) {
  assert.match(html, new RegExp('id="'+id+'"'), 'element '+id);
}
assert.match(html,/cast_receiver_framework\.js/);
assert.match(html,/urn:x-cast:dk\.kalivhub\.lab/);
assert.match(html,/textContent=item\.name/);
assert.match(html,/textContent=item\.state/);
assert.doesNotMatch(html,/innerHTML\s*=/);
assert.doesNotMatch(html,/https?:\/\/(?:homeassistant|192\.168\.|10\.|172\.16\.)/);
assert.match(html,/data\.entities\.length>MAX_ENTITIES/);
assert.match(html,/lastSeq/);
console.log('Receiver static validation passed (syntax, DOM, namespace, injection protections).');
