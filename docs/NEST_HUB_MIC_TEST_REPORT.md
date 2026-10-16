# Nest Hub microphone probe — test report

**Date:** __________

**Device / generation:** __________

**Firmware:** __________

**Test Cast App ID (non-secret):** __________

**HTTPS receiver URL:** __________

**Receiver launched as Cast session:** yes / no

**Test button usable:** yes / no

**Secure context:** true / false

**Cast receiver SDK:** true / false

**mediaDevices:** true / false

**getUserMedia:** function / undefined

**Permission outcome:** allowed / denied / timed out / other

**Error name and message (if any):** __________

**Audio tracks:** __________

**Audio track live:** true / false

**Meter frames:** __________

**Peak meter level (0–100):** __________

**Meter changed while speaking:** yes / no

**Microphone stopped after 10 seconds:** yes / no

**Notes:** __________

## Decision

- No API / permission blocked: use an external microphone path; do not attempt to bypass Cast device restrictions.
- Audio stream obtained but meter remains zero: investigate whether audio capture is actually connected before claiming success.
- Moving meter during speech: basic audio capture observed on this device/firmware. Re-test reliability and permissions before any Kaliv integration.

Do not paste Home Assistant tokens, credentials, or raw audio into the report.
