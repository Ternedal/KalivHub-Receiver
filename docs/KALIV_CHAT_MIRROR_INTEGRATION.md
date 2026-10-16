# KalivHub – automatisk, frivillig spejling af Kaliv-svar

## Status (16. oktober 2026)

**Verificeret fysisk:** Google Nest Hub 2 modtog `SHOW_MESSAGE` og `SET_STATE` fra ModelRig; to sammenhængende chatbeskeder og samtalekontekst virkede. Mikrofonadgang via Cast Web Receiver gav `NotFoundError` og bruges **ikke** til automatisk spejling.

**Implementeret og offline-testet på tidligere commits, men nyeste sikkerhedsrettelser afventer CI og fysisk validering:** Android sender færdige assistentsvar som autentificerede, afgrænsede events til riggens lokale KalivHub-modtager. Modtageren spejler beskederne på Nest Hub uden et ekstra modelkald.

- [Kaliv Android draft-PR #2206](https://github.com/Ternedal/ModelRig/pull/2206) – branch `feature/kalivhub-android-mirror-optin-20261015`.
- [KalivHub Receiver draft-PR #3](https://github.com/Ternedal/KalivHub-Receiver/pull/3) – branch `test/nest-hub-microphone-probe`.
- Android-test-APK, Android-kompilering/enhedstests og CodeQL er **PASS** for udviklingskoden; exact-head-merge-kontrollen er fortsat ikke grøn, fordi udviklingsbranchen er bagefter den løbende `main`. Det påvirker ikke brugen af den isolerede test-APK og begrunder, at PR'en fortsat er draft.
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
pwsh -NoProfile -File .\tools\start-kalivhub-mirror.ps1 -ShowSecret -SelfTest
```

Windows-starteren opretter en separat tilfældig 256-bit HMAC-nøgle første gang og gemmer den krypteret via Windows DPAPI (`CurrentUser`) på `%LOCALAPPDATA%\KalivHub\mirror-secret.dpapi`. Senere genstarter som **samme Windows-bruger** anvender den samme nøgle. Den kan vises lokalt med `-ShowSecret`, men må aldrig kopieres ind i GitHub, chat eller logs.

**Cast-kvitteringer:** Den nye receiver-kilde kan sende et tilfældigt kommando-ID retur, så sene kvitteringer ikke forveksles med nye beskeder. Den nuværende Netlify-deployment er ikke automatisk opdateret af ændringer på testbranchen; Python-senderen understøtter stadig kvitteringer uden ID. Først når den nye receiver er deployet og fysisk testet, kan korrelerede kvitteringer regnes som aktiv beskyttelse.

**Valgfri streng kvitteringstilstand – først EFTER receiver-opgradering:**
Brug `-StrictAcks` på `start-kalivhub-mirror.ps1`, hvis Cast Web Receiver er deployet med ekko af `request_id`. Så accepteres kun kvitteringer, der matcher den aktuelle kommando, også umiddelbart efter genforbindelse. Funktionen er **slået fra som standard** for fortsat at understøtte den gamle deployment. Brug den ikke med den nuværende gamle Netlify-receiver: selvtesten vil ellers fejle efter 6 sekunders ACK-timeout. Ingen scripts ændrer Netlify-konfiguration automatisk.


Med `-SelfTest` sender starteren én HMAC-signeret HTTP-testbesked via riggens faktiske lokale endpoint. Kig efter `Startup HTTP self-test queued` og derefter `Cast display acknowledgement received`. Kontrollér samtidig teksten **KalivHub: forbindelsestest fra riggen** på Nest Hub. En HTTP 202-kvittering alene beviser ikke skærmvisning; den fysiske kvittering kommer separat. `-SelfTest` er frivillig og sender intet uden flaget.

**Valgfri skærmrydning:** Hvis du ønsker, at Nest Hub automatisk skal fjerne den viste tekst efter tre minutter uden nye svar, starter du i stedet med:

```powershell
pwsh -NoProfile -File .\tools\start-kalivhub-mirror.ps1 -ShowSecret -SelfTest -ClearAfterSeconds 180
```

Standardværdien er `0` (ingen automatisk rydning), og funktionen ændrer ikke gamle appsvar, medmindre den vælges aktivt. Rydningen sendes via modtagerens eksisterende `CLEAR_MESSAGE`-kommando, som kræver en separat Cast-kvittering. Funktionen er best effort: Hvis Nest Hub er offline, kan den viste tekst ikke nødvendigvis fjernes, før forbindelsen er tilbage.


Starteren finder selv den lokale IP-adresse, som riggen ville bruge til at nå Nest Hub på `192.168.1.13`; IP-valget udsender **ingen** UDP-datapakke. Den åbner kun denne specifikke private IPv4-adresse på TCP-port `8765`. Den opretter **ingen** Windows-firewallregel og ændrer ikke riggens ModelRig-worker, Ollama eller produktionsservices.

Se efter loglinjen `KalivHub mirror listening on X.X.X.X:8765`; adressen `X.X.X.X` er **riggens** LAN-adresse. Brug denne adresse i Android, ikke Nest Hubs IP. Hvis Windows-firewall blokerer forbindelsen, tillad kun TCP `8765` fra telefonen/det betroede private net (begræns gerne til telefonens IP). Undgå offentlig portåbning, port-forwarding og `0.0.0.0`.

For at stoppe: tryk Ctrl+C i PowerShell. Serveren kører ikke automatisk som en baggrundsservice. HTTP-listeneren stopper først, og den separate Cast-worker afslutter derefter sit igangværende arbejde og lukker selv Cast-forbindelsen. En igangværende Cast-kald kan forsinke afslutningen kortvarigt; hovedtråden forsøger ikke at lukke forbindelsen samtidig.

**3. Installer isoleret Android-testbuild, når der skal fysisk testes.**

Seneste verificerede, separat installerbare test-APK kan hentes i [GitHub Actions-build #38861729114](https://github.com/Ternedal/ModelRig/actions/runs/38861729114), commit `cc5467a3`. Byggejobbet kontrollerede både korrekt test-pakkenavn og launcher-etiket. Artefaktet hedder `kalivhub-mirror-android-a425f-test-apk` og indeholder `app-a425f.apk`. GitHub har oplyst udløb **30. oktober 2026**. Appens separate id er `dk.ternedal.modelrig.a425f`: den installeres ved siden af normal Kaliv og skal parres med riggen separat. Telefonens test-app hedder **Kaliv TEST · Nest Hub**, så de to apps kan kendes fra hinanden.

I testappen: åbn chatmenuen → **Nest Hub-spejling**. Indtast `http://X.X.X.X:8765` (riggens faktiske LAN-IP), og indsæt samme spejlingsnøgle fra PowerShell. Aktivér og gem.

**4. Kontroller forbindelsen i appen.**

Tryk **Test** i Nest Hub-indstillingerne. `HTTP 202` betyder kun, at riggen har lagt beskeden i kø; det beviser **ikke**, at Nest Hub viste den. Kontrollér både `Cast display acknowledgement received` i riggens konsol og teksten `KalivHub: forbindelsestest` på Nest Hub.

Send derefter to normale chatbeskeder, og prøv gerne cloud, retry og færdig stemmesamtale. Afbryd Nest Hub, og kontrollér at chatten på telefonen stadig virker upåvirket. Test også at beskeder, der blev køet før **Deaktivér** eller en ændring af spejlingsnøgle, ikke vises senere; en besked, der ligger i kø mere end 30 sekunder, skal droppes – både i Android og hos riggens Cast-modtager. Også en langsom Cast-opstart/genforbindelse skal opgive udløbne svar. Allerede påbegyndte HTTP-kald kan dog ikke trækkes tilbage efter de er sendt.

## Sikkerhed og diagnose

- Spejlingen er **slået fra som standard** og kan altid deaktiveres i Android.
- Android sender kun færdig assistenttekst; **ikke** brugerspørgsmål, chat-historik, ModelRig-bearertoken eller cloud-API-nøgler. Spejl ikke følsomme svar på delt skærm.
- HMAC-SHA256 autentificerer rå JSON-bytes og Unix-timestamp; der er begrænset tidsvindue, replay-cache, tekstgrænse (2.000 UTF-16-enheder), HTTP-body (16 KiB), op til 16 køede events og begrænset antal HTTP-forbindelser. Både Androids og riggens ventende svar bliver kasseret efter 30 sekunder. Modtageren tæller også dokumenteret transporttid siden eventets signerede tidsstempel med, så et sent ankommet svar ikke får en ny 30-sekunders frist. Riggen kontrollerer også udløb efter Cast-opstart og inden visning.
- Trafikken er **HTTP og ukrypteret** på lokalnettet. Signaturen beskytter ikke svarindhold mod aflæsning på netværket. Android spejler nu med `Proxy.NO_PROXY`, så en eventuel systemproxy på telefonen ikke bruges til at videresende lokale svar. Det krypterer **stadig ikke** dataene; brug kun et betroet LAN, ellers en korrekt HTTPS/VPN-løsning.
- En udløbet besked stoppes inden skærmvisning; hvis receiveren allerede havde fået `thinking`, forsøger broen at nulstille status til `idle` inden frakobling. Det er best effort, og en utilgængelig Cast-enhed kan ikke garanteres nulstillet.
- Cast-broen forsøger en fuld retry **kun** før den har forsøgt at sende `SHOW_MESSAGE`. Efter forsøget kan en mistet kvittering betyde både “vist” og “ikke vist”; broen undlader derfor at gensende den samme assistenttekst. Fejl i `idle` efter bekræftet visning udløser heller ikke en ny visning. Det prioriterer ingen dobbeltvisning over automatisk genafsendelse, når Cast-kvitteringen er tvetydig.
- `GET /healthz` kontrollerer kun, at HTTP-modtageren kører, **ikke** Cast-status.
- `401`: HMAC eller ur passer ikke. `409`: event-ID er allerede modtaget. `410`: signeret besked er allerede 30 sekunder gammel, før den kan køes. `503`: køen eller replay-cache er fuld. `408`: HTTP-body blev ikke modtaget inden den samlede tidsfrist på 5 sekunder. `400`: tvetydige headers, dublerede JSON-felter eller andet ugyldigt input. `413`: ugyldig eller for stor `Content-Length`.
- Hvis DPAPI-nøglen ikke kan dekrypteres, fejler starteren bevidst frem for stille at generere en ny. Re-pair Android efter en bevidst nøglerotation.
- Lokal Python-kontrakttest: `py -m unittest discover -s tests -p test_kalivhub_mirror_server.py -v`.
- Ingen merge eller produktion før komplet CI og fysisk test gennem **Android → rig → Cast → Nest Hub**.

Den ældre `tools/modelrig_cast_bridge.py` er fortsat til frivillig PowerShell-diagnostik og er ikke en del af den automatiske Android-spejling.
