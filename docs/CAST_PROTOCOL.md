# KalivHub Cast wire protocol v1

The public receiver is a **read-only display**. All Home Assistant credentials remain on the local controller. The receiver accepts no commands to mutate HA state.

## Custom Cast channel

`urn:x-cast:dk.kalivhub.lab`

Send a JSON object through the Cast custom namespace. Recommended payload:

```json
{
  "type": "snapshot",
  "version": 1,
  "session_id": "boot_20261012_a1b2",
  "sequence": 1,
  "entities": [
    {"entity_id": "light.living_room", "name": "Stue", "state": "on"},
    {"entity_id": "sensor.temperature", "name": "Temperatur", "state": "21.5"}
  ]
}
```

The sender should generate a new random `session_id` on each controller process start and monotonically increment `sequence` for every new snapshot in that session. If the controller reconnects with the same session, it must continue the sequence; a fresh session resets the sequence tracking.

## Receiver validation

- Only `type=snapshot`, `version=1`, and an array of at most 32 entities.
- Allowed domains: `light`, `switch`, `sensor`, `binary_sensor`, `climate`, `cover`, `fan`, `input_boolean`.
- Entity identifiers are lower-case ASCII with underscores and limited length.
- Name and state must be strings of at most 128 characters with no control characters.
- Optional session identifier is 8–64 alphanumeric/underscore/hyphen characters.
- Optional sequence is a nonnegative safe integer and must increase within a session.
- Receiver uses `textContent` (never HTML interpolation) for external names/states.
- A stale snapshot expires after approximately 45 seconds, after which the visible tiles are cleared.

The controller must apply its own explicit allowlist of entities before sending. Receiver-side validation is not an authentication boundary. The Cast channel must not carry HA API tokens or secrets.

## Test gates before release

1. GitHub Pages HTTPS URL loads and is visually usable at 1024×600.
2. Register Custom Web Receiver and physical Nest Hub in Google Cast SDK Console.
3. Cast App ID starts the receiver on the physical device.
4. Valid snapshot appears; invalid, out-of-order, and oversized messages are ignored.
5. Stop the sender: after 45 seconds the receiver clears stale state.
6. Restart sender with new session ID: low sequence numbers work again.
7. No HA credentials or private URLs appear in the public repository or browser traffic.

The published `main` branch is not automatically changed by this development branch.
