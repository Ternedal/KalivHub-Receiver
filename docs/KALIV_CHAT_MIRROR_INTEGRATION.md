# KalivHub — integration with Kaliv chat clients

## Verified (15 October 2026)
- Local Python bridge `tools/modelrig_cast_bridge.py` authenticates to ModelRig's loopback `/api/v1/chat`.
- Cast receiver acknowledges `SET_STATE` and `SHOW_MESSAGE`.
- Gemma 4 with `think: false` returns visible responses; interactive bridge preserves up to 10 recent turns in process memory.
- **Not yet verified or implemented:** automatic mirroring of Android app conversations, TTS, and streaming on the Nest Hub.

## Recommended integration boundary
The Android app already owns chat session state, SQLite history, streaming, and source selection (rig/cloud). Avoid introducing another independent chat session in the Cast receiver.

1. Android client emits an opt-in `assistant_turn_completed` event **after** its existing chat flow commits the completed answer.
2. A local bridge, authenticated to the client using a separate short-lived pairing secret, receives only the display text and non-sensitive state. The device token and cloud API keys **must never** reach the Cast receiver or Netlify.
3. Bridge sends `SET_STATE` and `SHOW_MESSAGE` over Cast namespace `urn:x-cast:com.kalivhub.micprobe`, with bounded payloads, acknowledgement checks, and reconnection.
4. Keep the bridge off by default; bind any eventual HTTP listener to loopback unless explicit secure LAN pairing and origin controls are implemented.
5. On disconnect, chat must continue normally on Android; Cast is a non-authoritative output mirror.

## Next implementation checkpoint
Implement an opt-in event producer at the actual Android chat completion call site (not in the ModelRig backend, which cannot distinguish sessions or cloud answers). Add a bounded local event transport and end-to-end tests before enabling by default.

## Manual smoke test
```powershell
cd C:\Rig\src\KalivHub-Receiver
git pull --ff-only
py .\tools\modelrig_cast_bridge.py --host 192.168.1.13 --model "gemma4:26b"
```
Type two related prompts; verify `KALIV_DISPLAY` acknowledgements and `idle` after each response. `/reset` clears in-process history; `/exit` disconnects.
