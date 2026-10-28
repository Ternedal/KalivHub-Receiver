# Mikrofon til Kaliv, når Nest Hub ikke kan levere den — designnotat

**Status:** design. Intet her er implementeret, og intet er testet på hardware. Dato: 28. oktober 2026.

## Anbefaling

1. **MVP: telefonen er mikrofonen, og Nest Hub er kun skærm.** Det kræver ingen ny kode i stemmestien. Kæden findes allerede som kode: Kaliv på telefonen optager, ModelRig svarer, og svaret spejles til Hubben (ModelRig #2206 + KalivHub-Receiver #3). Det, der mangler, er den fysiske test.
2. **V1, kun hvis du vil kunne tale håndfrit i rummet:** en USB-mikrofon ved riggen med en fysisk tryk-for-at-tale-knap. En lille klient på riggen sender optagelsen til workerens eksisterende stemmeendpoint og viser svaret gennem den eksisterende spejling. Den bruger lokal model som standard.
3. **V2: vækkeord (wake word)** kun efter en særskilt beslutning. Det betyder en mikrofon, der lytter hele tiden.
4. **Fravalgt:** Nest Hubs egen mikrofon. Cast-receiveren får ingen optageenhed (`NotFoundError`).

Begrundelse: MVP'en giver den samme brugeroplevelse (tal → svar på skærmen) med det, der allerede er bygget. V1 køber kun én ting: at du ikke skal have telefonen i hånden. Den gevinst skal du selv vurdere, før der bygges noget.

## 1. Formål

Kaliv skal kunne høre dig og vise svaret på Nest Hub. Hubbens mikrofon er ikke tilgængelig for vores receiver. Notatet afgør derfor, hvor lyden skal komme fra, uden at ændre ModelRigs stemmesti eller cloud-politik.

## 2. Hvad ved vi?

| | Påstand | Grundlag |
| --- | --- | --- |
| **Verificeret** | Nest Hub 2 viser `SHOW_MESSAGE` og `SET_STATE` fra riggen | Fysisk test 16/10, `docs/KALIV_CHAT_MIRROR_INTEGRATION.md` |
| **Verificeret (dokumenteret)** | `getUserMedia` i Cast-receiveren giver `NotFoundError` | Samme note. `docs/NEST_HUB_MIC_TEST_REPORT.md` er **ikke udfyldt**, så firmware og detaljer mangler |
| **Verificeret i kode** | Stemmestien er `POST /api/v1/voice/converse/stream` (backend → worker `/voice/converse/stream`). Den tager 16 kHz mono WAV som base64 og svarer i NDJSON: `transcript`, `chunk` med lyd, `done`/`error` | `worker/app/main_impl.py`, `android/.../net/ModelRigClient.kt` |
| **Verificeret i kode** | ASR (faster-whisper) og TTS (Piper/VoiceRig) kører på riggen. Kun LLM-trinnet kan gå til cloud | Samme fil, docstring og kode |
| **Verificeret i kode** | Workeren sender kun den aktuelle besked til cloud, ikke tidligere stemmehistorik | `tests/worker_voice_cloud_history_wire.py`, `VoiceCloudHistoryPrivacyTest.kt` |
| **Verificeret i kode** | Stream-endpointet sletter turens midlertidige lydfiler, også når klienten afbryder | `rmtree` i `finally`, `/voice/converse/stream` |
| **Verificeret i kode** | Cloud-nøglen følger med fra telefonen pr. forespørgsel og gemmes ikke på riggen | `ConverseUploadReq` |
| **Antagelse** | En USB-mikrofon på 1–3 meters afstand giver en brugbar dansk WER | Ikke målt. Måles med `scripts/voice_baseline.py` (se testplanen) |
| **Gæt** | Nest Hub kan afspille Kalivs TTS-lyd i vores receiver | Usikkert. Receiveren kører HTTPS, riggen serverer HTTP, så mixed content blokerer sandsynligvis. Det er ikke undersøgt |

## 3. Muligheder

| | Mulighed | Ny kode | Privatliv | Vurdering |
| --- | --- | --- | --- | --- |
| A | **Telefonens mikrofon** + Hub som skærm | Ingen i stemmestien | Optager kun, når du trykker i appen | **MVP** |
| B | **USB-mikrofon på riggen** + fysisk tryk-for-at-tale-knap | Lille klient på riggen | Optager kun, mens knappen holdes | **V1**, kun efter beslutning |
| C | Mikrofon-array (fx ReSpeaker) + vækkeord | Klient + vækkeord-motor | Lytter hele tiden | **V2**, kræver særskilt beslutning |
| D | Nest Hubs mikrofon i receiveren | — | — | **Fravalgt:** `NotFoundError` |
| E | Telefonen som altid-lyttende rummikrofon | App-ændring | Lytter hele tiden, og telefonens batteri | Fravalgt: C er bedre, hvis det skal være altid-lyttende |

## 4. Arkitektur

**MVP (A), bygget men ikke fysisk testet:**

```text
Telefon (Kaliv) ── optag 16 kHz ──► ModelRig backend ──► worker: ASR → LLM → TTS
      ▲                                                     │
      └──────────── svar + lyd (NDJSON) ◄───────────────────┘
      │
      └─ færdigt svar, signeret ──► riggens spejling (/v1/events) ──► CastSender ──► Nest Hub (skærm)
```

**V1 (B), forslag:**

```text
USB-knap ─► rig-mic-klient ─► optag mens knappen holdes (16 kHz mono)
                │
                ├─► worker 127.0.0.1 /voice/converse/stream  (loopback, lokal model)
                │        └─ chunk-lyd ─► riggens højttaler
                │
                └─► færdigt svar, signeret ─► spejlingen 127.0.0.1 /v1/events ─► CastSender ─► Nest Hub
```

Bevidste valg i V1:

- **Én ejer af Cast.** Klienten sender svaret som et almindeligt signeret `assistant_complete`-event til spejlingen, ligesom telefonen gør. Den taler ikke selv med Hubben. Så gælder HMAC, levetiden på 30 sekunder, højst én visning, opstartsreglen og pausen efter fejl uændret.
- **Loopback til workeren.** Klienten kører på riggen og kalder workeren på `127.0.0.1`, ligesom `scripts/voice_baseline.py`. Der er intet nyt netværksendpoint og ingen device-token.
- **Lokal model som standard.** Riggen har ingen cloud-nøgle, fordi den i dag kommer fra telefonen. En nøgle gemt på riggen er ekstern dataoverførsel og kræver din godkendelse.
- **Lyd ud via riggens højttaler.** TTS-lyd på Hubben er et åbent spørgsmål (se afsnit 2) og hører ikke med i V1.
- **Ingen `listening`-tilstand på Hubben i V1.** Spejlingen kender i dag kun færdige svar (thinking → vis → idle). "Lytter…" på skærmen kræver en ny event-type i spejlingsprotokollen. Den kommer først med V1.1.

## 5. Grænseflader

- **MVP:** ingen nye grænseflader.
- **V1:** ingen nye grænseflader i ModelRig. Klienten bruger:
  - `POST http://127.0.0.1:<worker>/voice/converse/stream` med `{"audio_base64", "language": "da"}` og uden `llm_api_key`;
  - `POST http://<spejlingens bind-adresse>:8765/v1/events` med signeret `{"version":1,"type":"assistant_complete","event_id","text"}`. Formatet er det samme som telefonens og `post_signed_selftest`. Adressen er den, starteren logger (`KalivHub mirror listening on X.X.X.X:8765`), altså riggens LAN-IP. **Ikke `127.0.0.1:8765`:** der lytter VoiceRig-sidecaren, som ModelRig-workeren bruger til TTS (`VOICERIG_TTS_URL`). På Windows binder spejlingen nu eksklusivt, så en konflikt fejler ved opstart i stedet for at dele porten.
- **Spejlingsnøglen i V1:** klienten læser DPAPI-nøglen som samme Windows-bruger, ligesom starteren gør. Den logges aldrig.

## 6. Privatliv og cloud-politik

- **Ingen optagelse uden knap.** I B optages der kun, mens knappen holdes nede. Der er ingen buffer før tryk og ingen lyd på disk ud over turens midlertidige fil, som workeren selv sletter.
- **Cloud-politikken håndhæves stadig i workeren:** kun den aktuelle besked, aldrig historik. V1 sender dog slet intet til cloud, så længe riggen ikke har en nøgle.
- **Delt skærm:** svaret vises på en skærm, andre kan se. Det er det samme forbehold som for spejlingen i dag.
- **Altid-lyttende (C/E)** kræver din eksplicitte beslutning, før der skrives kode.

## 7. MVP → V1 → V2

| Fase | Indhold | Forudsætning |
| --- | --- | --- |
| **MVP** | A: fysisk test af telefon → rig → Hub | Riggen tændt og dig til stede. #2206 og #3 forbliver test-builds |
| **V1** | B: rig-mic-klient (optag, kald worker, send til spejling, afspil lokalt) med offline-tests | Din beslutning om håndfri brug. Valg af mikrofon og knap |
| **V1.1** | `listening` på Hubben via ny spejlings-event | V1 i brug |
| **V2** | C: vækkeord | Særskilt beslutning om altid-lyttende |

## 8. Testplan

- **MVP (fysisk):** først to almindelige svar fra telefonen. Bekræft `Cast display acknowledgement received` og at teksten er synlig. Afbryd derefter Hubben (åbn en anden app) og bekræft, at næste svar genstarter receiveren, mens automatisk rydning lader den anden app være.
- **Mikrofonkvalitet før V1 bygges:** optag de 20 faste fraser fra `eval/voice_baseline_manifest.v1.json` med USB-mikrofonen på den rigtige afstand. Kør `scripts/voice_baseline.py` og sammenlign WER/CER med telefonens optagelser. Er USB-mikrofonen tydeligt dårligere, stopper V1 der.
- **V1 offline:** falsk worker (NDJSON-fixture) og falsk spejling. Test:
  - at intet optages uden knap;
  - at der ikke sendes `llm_api_key`;
  - at én tur giver ét event;
  - at worker-fejl (501/502/503) ikke giver et event;
  - at turen afbrydes, når knappen slippes før svar.
- **V1 fysisk:** 10 ture i rummet med lys/støj som normalt. Registrér WER, tid til første lyd og om svaret blev vist.

## 9. Risici og åbne spørgsmål

- **Placering:** står riggen i det rum, hvor du vil tale? Ellers bliver B til en USB-forlænger på tværs af stuen, og så er telefonen den bedste mikrofon.
- **Akustik:** afstand og efterklang kan gøre WER markant værre end med telefonen. Det skal måles før V1 bygges, ikke efter.
- **Windows-lydenheder:** valg af den rigtige optageenhed skal være eksplicit (ID, ikke "standard"), ellers kan en webcam-mikrofon blive brugt i stedet.
- **Lyd på Hubben:** ukendt (se afsnit 2). Uden den kommer stemmen fra riggen og teksten fra Hubben.
- **Port 8765 bruges to steder:** spejlingen og VoiceRig har samme standardport. Det går i dag, fordi starteren binder spejlingen til LAN-IP'en og VoiceRig til `127.0.0.1`. En fast, særskilt port til spejlingen ville fjerne tvetydigheden. Det ændrer dog Android-opsætningen og firewall-scriptet, så det skal aftales, før det ændres.
- **Musik og video på Hubben:** et nyt svar tager i dag skærmen fra en anden app. Om det er ønsket, afgøres efter den fysiske test (se `KALIV_CHAT_MIRROR_INTEGRATION.md`).

## 10. Næste skridt

1. **Fysisk MVP-test** (kræver dig og riggen). Udfyld samtidig `docs/NEST_HUB_MIC_TEST_REPORT.md` med `NotFoundError`-observationen, firmware og dato, så fravalget af Hub-mikrofonen er dokumenteret.
2. **Din beslutning:** vil du have håndfri brug (V1)? Hvis nej, er MVP slutpunktet.
3. **Kun ved ja:** mål USB-mikrofonen med `voice_baseline.py`. Først derefter skrives en V1-PR med rig-mic-klienten.
