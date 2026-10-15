# KalivHub: automatisk spejling af Kaliv-svar

## Status – 15. oktober 2026

Fysisk testet: Nest Hub 2 viser SET_STATE og SHOW_MESSAGE efter ModelRig-chat; to samtaleture med hukommelse bestået.

Implementeret, men ikke fysisk testet: Android-spejling og lokal LAN-modtager. Android-koden ligger i draft PR https://github.com/Ternedal/ModelRig/pull/2206 på feature/kalivhub-android-mirror-optin-20261015. Python-modtageren ligger i tools/kalivhub_mirror_server.py på test/nest-hub-microphone-probe. Ingen produktion-main er ændret.

Android-spejlingen er slået FRA som standard. Den sender kun færdig assistenttekst, ikke brugerens spørgsmål, samtalehistorik eller ModelRig/cloud-adgangsnøgler. Et separat HMAC-secret bruges til signering og lagres krypteret på Android.

Kun et betroet privat netværk! HTTP-signaturen autentificerer, men KRYPTERER IKKE teksten. Undgå følsomme svar på delt skærm. Den lokale modtager har anti-replay, 2000 UTF-16 tegnbegrænsning, bundet body og kø. HTTP 202 betyder kun lagt i kø; Cast-kvitteringen logges særskilt.

## Opsætning til næste fysiske testsession (IKKE nødvendigt at tænde riggen nu)

1. Opdater KalivHub-Receiver på test/nest-hub-microphone-probe med git pull --ff-only.
2. Kør nedenstående i PowerShell på riggen. Vælg riggens private LAN-IP til --bind, IKKE Nest Hubs IP:

    $bytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $env:KALIVHUB_MIRROR_SECRET = [Convert]::ToHexString($bytes).ToLowerInvariant()
    Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress

3. Vis nøglen KUN på din egen maskine med `$env:KALIVHUB_MIRROR_SECRET`. Gem den tilfældigt genererede nøgle sikkert til at indsætte i Android-appens Nest Hub-spejling-indstillinger. Undlad at dele den i chat/GitHub. Nøglen er kun i PowerShell-miljøet så længe sessionen varer.
4. Start den lokale modtager (udskift YOUR_RIG_LAN_IP):

    py .\tools\kalivhub_mirror_server.py --cast-host 192.168.1.13 --bind YOUR_RIG_LAN_IP --port 8765 --allow-lan

5. Begræns indgående TCP 8765 til telefonens/private LAN med Windows-firewall. Brug ikke 0.0.0.0.
6. Installer senere test-APK'en fra GitHub Actions: den bruger det separate Android-id `dk.ternedal.modelrig.a425f`, så den ikke overskriver Kaliv-produktionsappen. Den skal parres med riggen særskilt. Vælg Nest Hub-spejling i chat-menuen, angiv http://YOUR_RIG_LAN_IP:8765, samme separate nøgle, og aktivér.
7. Brug først **Test**-knappen i Android-indstillingerne: appen bekræfter kun om riggens HTTP-modtager lagde beskeden i kø; kontrollér separat at Nest Hub faktisk viser 'KalivHub: forbindelsestest'.
8. Send en normal chatbesked og bekræft fysisk visning samt 'Cast display acknowledgement received' i rigkonsollen. Gentag med to ture, cloud, retry, voice og Nest Hub offline. Chat på telefonen skal fortsætte selv hvis displayet fejler.

## Fejlfinding og gates

- GET /healthz betyder kun at den lokale HTTP-modtager kører; det siger intet om Cast.
- HTTP 401: forkert secret/ur/signeret body. 409: duplicate. 503: køen fuld.
- Kør offline-tests: py -m unittest discover -s tests -p test_kalivhub_mirror_server.py -v.
- Android: cd android; .\gradlew.bat :app:compileDebugKotlin :app:testDebugUnitTest.
- Ingen merge/main/release uden grøn CI, review og fysisk telefon → rig → Nest Hub accepttest.

Den gamle tools/modelrig_cast_bridge.py er fortsat til frivillig PowerShell-diagnostik, men Android-spejlingen foretager ingen ekstra LLM-kald.