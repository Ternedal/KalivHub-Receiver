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
