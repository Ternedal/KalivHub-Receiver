# KalivHub Cast Receiver

Public, static **read-only** Google Cast Custom Web Receiver for KalivHub.

- Receiver page: `index.html`
- Intended GitHub Pages URL (once Pages is enabled): `https://ternedal.github.io/KalivHub-Receiver/`
- Custom namespace: `urn:x-cast:dk.kalivhub.lab`
- Snapshot message: `{"type":"snapshot","version":1,"entities":[{"entity_id":"light.example","name":"Example","state":"on"}]}`
- Never add HA tokens, API credentials, local backend endpoints, or private configuration here.
- The receiver is a *display only*. It does not issue Home Assistant commands.
- This initial upload uses a styled text ankh; the original Kaliv logo asset still needs to be imported.

## Enable hosting

In this repository, go to **Settings → Pages → Build and deployment → Source: GitHub Actions**. The workflow in `.github/workflows/pages.yml` deploys the static page on pushes to main.

After deployment, verify the HTTPS URL loads. Register that exact URL as a **Custom Web Receiver** in the Google Cast SDK Developer Console and register your Nest Hub as a test device. A working Cast App ID and physical Nest Hub testing are still required.

The local Raspberry Pi retains the Home Assistant token and sends only allowlisted state snapshots through the Cast channel. The static page does not contact HA.

## Receiver contract and security

The custom Cast namespace is `urn:x-cast:dk.kalivhub.lab`. Only messages with `type: "snapshot"`, `version: 1`, and an `entities` array of at most 32 items are rendered. Each entity requires a valid Home Assistant entity ID, display name, and string state. Optional `sequence` values must increase monotonically, so stale/replayed sequenced snapshots are ignored.

Supported display-only domains: `light`, `switch`, `sensor`, `binary_sensor`, `climate`, `cover`, `fan`, `input_boolean`. All names and values are inserted via `textContent`, never HTML. No control messages are sent from this receiver.

Example sender payload:

```json
{
  "type": "snapshot",
  "version": 1,
  "sequence": 1,
  "entities": [
    {"entity_id": "sensor.living_room_temperature", "name": "Stuetemperatur", "state": "21.5"},
    {"entity_id": "light.living_room", "name": "Stuelampe", "state": "on"}
  ]
}
```

The receiver does **not** authenticate the sender itself; Cast session access is managed by the Cast platform. Keep sensitive entities out of the sender allowlist. A browser preview loading the Cast SDK is not evidence of a successful physical Nest Hub Cast session.

## Test prerequisites

1. Confirm GitHub Pages is deployed at the URL above.
2. Register the HTTPS URL as a Google Cast Custom Web Receiver, and register the physical Nest Hub as a test device.
3. Configure the sender with the issued Cast App ID and the exact namespace.
4. Launch a Cast session and transmit the snapshot payload.
5. Verify device state display, stale-state timeout, and reconnect behavior on the Nest Hub.

No developer registration, Cast App ID, or Nest Hub session is included in this repository.


## Cross-repository documentation (2026-10-23)

- [Kaliv ecosystem and KalivNexus ownership map](docs/KALIV_ECOSYSTEM.md)
- [Subsystem integration acceptance checklist](docs/INTEGRATION_ACCEPTANCE_2026-10-23.md)

These documents distinguish proposed integrations from implemented, tested and released functionality. They do not supersede this repository's operational instructions or evidence gates.
