# KalivHub Cast Receiver

Public, static Google Cast Custom Web Receiver for KalivHub. Read-only by default; touch controls appear only when the active sender opts in.

- Receiver page: `index.html`
- GitHub Pages URL (live, deployed from main): `https://ternedal.github.io/KalivHub-Receiver/`
- Custom namespace: `urn:x-cast:dk.kalivhub.lab`
- Snapshot message: `{"type":"snapshot","version":1,"session_id":"session1234","sequence":1,"entities":[{"entity_id":"light.example","name":"Example","state":"on"}]}`
- Never add HA tokens, API credentials, local backend endpoints, or private configuration here.
- The receiver never calls Home Assistant. When the sender that delivered the latest snapshot announces `control_capabilities` (enabled), the receiver can send `control_request` messages (`turn_on`/`turn_off` for `light`/`switch`/`input_boolean`; `set_temperature` in 0.5 °C steps within 5-35 °C for `climate`) back to that sender, which decides whether to execute them.
- The ankh is an inline SVG drawing in `index.html`; the original Kaliv logo asset (Kaliv repo `assets/kaliv-ankh-*.webp`) has not been imported.

## Hosting

GitHub Pages is served from GitHub Actions (**Settings → Pages → Build and deployment → Source: GitHub Actions**). The workflow in `.github/workflows/pages.yml` deploys on pushes to main (and manual dispatch) only after all three receiver tests pass.

After a deployment, verify the HTTPS URL loads. Register that exact URL as a **Custom Web Receiver** in the Google Cast SDK Developer Console and register your Nest Hub as a test device. A working Cast App ID and physical Nest Hub testing are still required.

The local Raspberry Pi retains the Home Assistant token and sends only allowlisted state snapshots through the Cast channel. The static page does not contact HA.

## Receiver contract and security

The custom Cast namespace is `urn:x-cast:dk.kalivhub.lab`. Only messages with `type: "snapshot"`, `version: 1`, and an `entities` array of at most 32 items are rendered. Each snapshot requires `session_id` (8-64 chars, `A-Z a-z 0-9 _ -`) and an integer `sequence` ≥ 0 that must increase within a session; a new `session_id` or sender resets the sequence, and stale/replayed snapshots are ignored. Each entity requires a unique entity ID (`domain.object_id`, object_id `[a-z0-9_]{1,120}`), a display name and a string state (each ≤128 chars, no control characters). Optional: `room` (≤64 chars, default "Andre"; tiles are grouped by room) and, for climate, numeric `current_temperature`/`temperature` (-50..100). After 45 s without a valid snapshot the receiver shows "Forbindelsen er afbrudt" and revokes controls.

Supported domains: `light`, `switch`, `sensor`, `binary_sensor`, `camera` (status only, no stream), `climate`, `cover`, `fan`, `input_boolean`. All names and values are inserted via `textContent`, never HTML. Control requests are sent only to the sender of the latest snapshot, only after it opted in with `{"type":"control_capabilities","version":1,"enabled":true}` while its latest snapshot is less than 45 s old, and are revoked on a new session, a different sender or 45 s without snapshots. This binding is not cryptographic sender authentication.

Example sender payload:

```json
{
  "type": "snapshot",
  "version": 1,
  "session_id": "session1234",
  "sequence": 1,
  "entities": [
    {"entity_id": "sensor.living_room_temperature", "name": "Stuetemperatur", "state": "21.5"},
    {"entity_id": "light.living_room", "name": "Stuelampe", "state": "on"}
  ]
}
```

The receiver does **not** authenticate the sender itself; Cast session access is managed by the Cast platform. Keep sensitive entities out of the sender allowlist. A browser preview loading the Cast SDK is not evidence of a successful physical Nest Hub Cast session.

## Test prerequisites

1. Confirm the page at the URL above loads over HTTPS.
2. Register the HTTPS URL as a Google Cast Custom Web Receiver, and register the physical Nest Hub as a test device.
3. Configure the sender with the issued Cast App ID and the exact namespace.
4. Launch a Cast session and transmit the snapshot payload.
5. Verify device state display, stale-state timeout, and reconnect behavior on the Nest Hub.

No developer registration, Cast App ID, or Nest Hub session is included in this repository.

## Place in Kaliv

The receiver is the visible home surface for Kaliv on a Nest Hub. The sender lives in [KalivHub](https://github.com/Ternedal/KalivHub) (private repository). The receiver itself has no connection to ModelRig or Home Assistant; everything it shows arrives over the Cast channel from the sender. [kaliv.dk/hub.html](https://kaliv.dk/hub.html) is the public description of KalivHub.

Authority across the system is defined in [ModelRig: docs/KALIV_SYSTEM_DEFINITION.md](https://github.com/Ternedal/ModelRig/blob/main/docs/KALIV_SYSTEM_DEFINITION.md). The other repositories are listed in the [Kaliv repository README](https://github.com/Ternedal/Kaliv#relaterede-repositories).

## Tests

Three Node tests cover the inline script: syntax, static validation (DOM, namespace, injection protections) and a behavior harness with a fake DOM and Cast context. Run them locally from the repository root with Node 22:

```bash
node tests/receiver-syntax.cjs && node tests/receiver-static.cjs && node tests/receiver-behavior.cjs
```

`.github/workflows/receiver-js.yml` runs the same tests on every pull request and on pushes to main; `pages.yml` runs them before each deployment.
