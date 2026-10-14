# Nest Hub microphone probe — isolated experiment

This is an **opt-in experiment**, not a production receiver. The diagnostic is in `mic-diagnostic.html` and is not linked from the existing `index.html`.

## What it tests
- Whether a Cast Web Receiver has `navigator.mediaDevices.getUserMedia`.
- Whether an explicit touch request can obtain an audio stream.
- Whether a local Web Audio analyser sees nonzero microphone samples.

The receiver initializes the official CAF CastReceiverContext. No audio is recorded, uploaded, stored, played, or forwarded to ModelRig. The microphone tracks stop after ten seconds, on Stop, or when the page exits.

## Physical test (not yet performed)
1. Deploy **this branch's** `mic-diagnostic.html` to a reachable **HTTPS** URL, without replacing the production receiver URL. The normal GitHub Pages workflow for `main` does **not** automatically publish this branch.
2. In the Google Cast SDK Developer Console, register that exact HTTPS URL as a **separate Custom Web Receiver application**, and register the Nest Hub as a test device. Obtain its distinct test App ID.
3. Launch that test App ID from an authorized Cast sender on the same network. This is not a normal browser navigation; a Cast session is required.
4. If the test page appears, tap **Test mikrofon (10 sek.)** on the Nest Hub. Note `Sikker kontekst`, `Cast receiver SDK`, `mediaDevices`, `getUserMedia`, permission result/error, and whether the level meter moves when speaking.
5. Stop the test. Do not enter secrets or Home Assistant credentials.

**Interpretation:** API absent means the receiver runtime does not expose it. `NotAllowedError` suggests a permission/policy restriction; `NotFoundError` means no exposed capture device. A successful stream without meter activity is *not* proof of usable audio. A successful moving meter would establish basic capture for this specific device/runtime, not guaranteed production support.

Do not merge this experiment into `main` or replace the existing receiver registration solely to run the test.
