# KalivHub – automatisk, frivillig spejling af Kaliv-svar

## Status (16. oktober 2026)

**Verificeret fysisk:** Google Nest Hub 2 modtog `SHOW_MESSAGE` og `SET_STATE` fra ModelRig; to sammenhængende chatbeskeder og samtalekontekst virkede. Mikrofonadgang via Cast Web Receiver gav `NotFoundError` og bruges **ikke** til automatisk spejling.

**Implementeret og CI-testet, men endnu ikke fysisk valideret:** Android sender færdige assistentsvar som autentificerede, afgrænsede events til riggens lokale KalivHub-modtager. Modtageren spejler beskederne på Nest Hub uden et ekstra modelkald.

- [Kaliv Android draft-PR #2206](https://github.com/Ternedal/ModelRig/pull/2206) – branch `feature/kalivhub-android-mirror-optin-20261015`.
- [KalivHub Receiver draft-PR #3](https://github.com/Ternedal/KalivHub-Receiver/pull/3) – branch `test/nest-hub-microphone-probe`.
- Android-kompilering, enhedstests, CodeQL, exact-head-kvalificering og separat test-APK: **PASS** på PR-head `e19bca5`.
- Receiver JavaScript, mikrofon-diagnostik og mirror-protokoltests: **PASS** på tidligere head; kontroller seneste workflow-status ved senere ændringer.
- Ingen merge til `main`; ingen produktions-APK er ændret.

## Test, når riggen tændes igen

**1. Opdater KalivHub-testbranchen.**

```powershell
cd C:\Rig\src\KalivHub-Receiver
git switch test/nest-hub-microphone-probe
git pull --ff-only
```

**2. Start lokal modtager med én kommando.**

```powershell
pwsh -NoProfile -File .\tools\start-kalivhub-mirror.ps1 -ShowSecret
```

Windows-starteren opretter en separat tilfældig 256-bit HMAC-nøgle første gang og gemmer den krypteret via Windows DPAPI (`CurrentUser`) på `%LOCALAPPDATA%\KalivHub\mirror-secret.dpapi`. Senere genstarter som **samme Windows-bruger** anvender den samme nøgle. Den kan vises lokalt med `-ShowSecret`, men må aldrig kopieres ind i GitHub, chat eller logs.

Starteren finder selv den lokale IP-adresse, som riggen ville bruge til at nå Nest Hub på `192.168.1.13`; IP-valget udsender **ingen** UDP-datapakke. Den åbner kun denne specifikke private IPv4-adresse på TCP-port `8765`. Den opretter **ingen** Windows-firewallregel og ændrer ikke riggens ModelRig-worker, Ollama eller produktionsservices.

Se efter loglinjen `KalivHub mirror listening on X.X.X.X:8765`; adressen `X.X.X.X` er **riggens** LAN-adresse. Brug denne adresse i Android, ikke Nest Hubs IP. Hvis Windows-firewall blokerer forbindelsen, tillad kun TCP `8765` fra telefonen/det betroede private net (begræns gerne til telefonens IP). Undgå offentlig portåbning, port-forwarding og `0.0.0.0`.

For at stoppe: tryk Ctrl+C i PowerShell. Serveren kører ikke automatisk som en baggrundsservice.

**3. Installer isoleret Android-testbuild, når der skal fysisk testes.**

Seneste verificerede test-APK kan hentes i [GitHub Actions-build #38813378802](https://github.com/Ternedal/ModelRig/actions/runs/38813378802). Artefaktet hedder `kalivhub-mirror-android-a425f-test-apk` og indeholder `app-a425f.apk`. GitHub har oplyst udløb **29. oktober 2026**. Appens separate id er `dk.ternedal.modelrig.a425f`: den installeres ved siden af normal Kaliv og skal parres med riggen separat.

I testappen: åbn chatmenuen → **Nest Hub-spejling**. Indtast `http://X.X.X.X:8765` (riggens faktiske LAN-IP), og indsæt samme spejlingsnøgle fra PowerShell. Aktivér og gem.

**4. Kontroller forbindelsen i appen.**

Tryk **Test** i Nest Hub-indstillingerne. `HTTP 202` betyder kun, at riggen har lagt beskeden i kø; det beviser **ikke**, at Nest Hub viste den. Kontrollér både `Cast display acknowledgement received` i riggens konsol og teksten `KalivHub: forbindelsestest` på Nest Hub.

Send derefter to normale chatbeskeder, og prøv gerne cloud, retry og færdig stemmesamtale. Afbryd Nest Hub, og kontrollér at chatten på telefonen stadig virker upåvirket.

## Sikkerhed og diagnose

- Spejlingen er **slået fra som standard** og kan altid deaktiveres i Android.
- Android sender kun færdig assistenttekst; **ikke** brugerspørgsmål, chat-historik, ModelRig-bearertoken eller cloud-API-nøgler. Spejl ikke følsomme svar på delt skærm.
- HMAC-SHA256 autentificerer rå JSON-bytes og Unix-timestamp; der er begrænset tidsvindue, replay-cache, beskedstørrelse (2.000 UTF-16-enheder), op til 16 køede events og begrænset antal HTTP-forbindelser.
- Trafikken er **HTTP og ukrypteret** på lokalnettet. Signaturen beskytter ikke svarindhold mod aflæsning på netværket. Brug kun betroet LAN, ellers en korrekt HTTPS/VPN-løsning.
- `GET /healthz` kontrollerer kun, at HTTP-modtageren kører, **ikke** Cast-status.
- `401`: HMAC eller ur passer ikke. `409`: event-ID er allerede modtaget. `503`: køen eller replay-cache er fuld. `408`: langsom/uafsluttet HTTP-body.
- Hvis DPAPI-nøglen ikke kan dekrypteres, fejler starteren bevidst frem for stille at generere en ny. Re-pair Android efter en bevidst nøglerotation.
- Lokal Python-kontrakttest: `py -m unittest discover -s tests -p test_kalivhub_mirror_server.py -v`.
- Ingen merge eller produktion før komplet CI og fysisk test gennem **Android → rig → Cast → Nest Hub**.

Den ældre `tools/modelrig_cast_bridge.py` er fortsat til frivillig PowerShell-diagnostik og er ikke en del af den automatiske Android-spejling.
