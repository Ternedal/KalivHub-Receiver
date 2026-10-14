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

## Build artifact and HTTPS hosting

The branch-specific workflow `.github/workflows/mic-probe.yml` runs static checks and uploads a **seven-day** GitHub Actions artifact named `kalivhub-nest-mic-probe`. It contains `index.html`, copied from `mic-diagnostic.html`. Download it from the workflow run's **Artifacts** section. This is **not** a public URL.

Host that `index.html` at a dedicated HTTPS origin/path (for example a separate static hosting project) before registering it with Cast. Do **not** point the existing production Cast App ID at the diagnostic or enable GitHub Pages on this branch in a way that replaces the production deployment.

The diagnostic is deliberately self-contained: it needs no Home Assistant, ModelRig, local tokens, or other project files. The Cast SDK is loaded from Google's documented CDN.

## Results checklist

Record the Nest Hub generation, firmware version, Cast test App ID (non-secret), whether the receiver launched, whether the test button was usable, `mediaDevices` / `getUserMedia` results, any DOMException name, and whether the meter visibly changed when speaking. Do not copy credentials into bug reports.

**Limitations:** GitHub CI validates only source shape and syntax; it cannot verify microphone permissions or hardware capture. A successful desktop-browser run does not establish Nest Hub support. A timeout during the browser permission prompt is not proof that capture is unsupported.

## Evidence to capture

At the end of a successful stream, the diagnostic reports the number of local audio-meter frames and its highest measured level (0–100). A zero peak with frames present suggests silence or inaccessible audio; it is not proof of a functioning microphone. Record these two numbers along with the stream's live-track result. The report contains no audio samples.

## Quickest manual launch path

After registering the **separate** diagnostic receiver App ID, a local machine with Python and `pychromecast` can launch it without Home Assistant or ModelRig. The diagnostic sender is intentionally kept separate from the production sender. Run `python -m pip install pychromecast` and use `python tools/launch_mic_probe.py --app-id YOUR_TEST_APP_ID --host NEST_HUB_IP`. The receiver URL must already be hosted and registered; this script cannot register Cast apps, enable GitHub Pages, or grant microphone permissions.

Only run on a trusted local network. The sender does not transmit credentials or audio.
