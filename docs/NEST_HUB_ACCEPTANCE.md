# KalivHub receiver acceptance checklist

Use this checklist when the Google Cast App ID is available. Keep `main` unchanged until a physical test passes.

## Display (Nest Hub 2: 1024 × 600)

- [ ] Header, clock, greeting, logo, and three touch controls all fit without scrolling.
- [ ] Touch controls are large enough to use from arm's length.
- [ ] Device panel can open and close; tiles do not overflow.
- [ ] Correct local clock, daypart greeting, and Danish text.
- [ ] The original Kaliv logo replaces the temporary Unicode ankh before visual sign-off.

## Transport and safety

- [ ] Valid allowlisted snapshot updates only read-only tiles.
- [ ] Invalid JSON and unknown protocol versions are ignored.
- [ ] More than 32 entities is rejected.
- [ ] Duplicate entity IDs are rejected.
- [ ] HTML in name/state is shown as text, not executed.
- [ ] Out-of-order sequence is rejected.
- [ ] Unexpected session switch while connection is live is rejected.
- [ ] After >45 seconds without a snapshot, state clears.
- [ ] A new session ID after expiry can start at sequence 0.
- [ ] No HA token or secret is embedded in public receiver files.
- [ ] No Home Assistant service call or action is exposed by the receiver.

## Deployment

- [ ] GitHub Pages HTTPS loads on desktop.
- [ ] Pages workflow succeeds on main.
- [ ] Google Cast Custom Web Receiver URL matches the deployed URL.
- [ ] Nest Hub is registered as a test device and rebooted if needed.
- [ ] Sender uses namespace `urn:x-cast:dk.kalivhub.lab`.
- [ ] Receiver launches and receives a real snapshot.

## Caveats

A GitHub Pages page loading in a desktop browser **does not** prove a Cast session is established. The SDK can initialize without a physical Cast sender. These are manual physical acceptance tests, not automated pass results.
