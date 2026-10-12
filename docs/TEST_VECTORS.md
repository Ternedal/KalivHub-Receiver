# Receiver test vectors

These vectors define the receiver's intended behavior. They are not evidence of a successful physical Cast test.

## Valid

```json
{"type":"snapshot","version":1,"session_id":"session_a1","sequence":0,"entities":[{"entity_id":"light.stue","name":"Stue","state":"on"}]}
```

Expected: one tile, "Stue", "on".

```json
{"type":"snapshot","version":1,"session_id":"session_a1","sequence":1,"entities":[]}
```

Expected: no tiles, connection remains active.

## Invalid

Each of the following should be ignored:

```json
{"type":"snapshot","version":2,"entities":[]}
{"type":"snapshot","version":1,"session_id":"session_a1","entities":[]}
{"type":"snapshot","version":1,"sequence":1,"entities":[]}
{"type":"snapshot","version":1,"session_id":"session_a1","sequence":0,"entities":[{"entity_id":"light.stue","name":"A","state":"on"},{"entity_id":"light.stue","name":"B","state":"off"}]}
{"type":"snapshot","version":1,"entities":[{"entity_id":"person.someone","name":"Someone","state":"home"}]}
{"type":"snapshot","version":1,"entities":[{"entity_id":"light.stue","name":"<script>alert(1)</script>","state":"on"}]}
```

**Note:** The final script-name example is *allowed as plain text* by the receiver. It must never execute; names are inserted using `textContent`. This is an XSS regression case, not a validation-rejection case.

## Sequence and expiry

1. Accept session `session_a1`, sequence 1.
2. Reject `session_a1`, sequence 1 again.
3. Reject `session_a1`, sequence 0.
4. Reject `session_b2`, sequence 0 while `session_a1` remains live.
5. Wait longer than 45 seconds without new snapshots; the stale tile list should clear.
6. Accept `session_b2`, sequence 0.

The receiver's stale timer runs every 15 seconds, so expiry is observed after approximately 45–60 seconds, not at precisely 45 seconds.
