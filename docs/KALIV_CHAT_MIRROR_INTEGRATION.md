# KalivHub – automatisk, frivillig spejling af Kaliv-svar

## Status (16. oktober 2026)

**Verificeret fysisk:** Google Nest Hub 2 modtog `SHOW_MESSAGE` og `SET_STATE` fra ModelRig; to sammenhængende chatbeskeder og samtalekontekst virkede. Mikrofonadgang via Cast Web Receiver gav `NotFoundError` og bruges **ikke** til automatisk spejling.

**Automatiske tests er grønne på receiverens tidligere verificerede commit `233a533`, og den nye Android-test-APK er bygget på commit `7475a2b` med en rettet samlet 30-sekunders tidsfrist. Androids exact-head-kontrol er ikke grøn, og hele forbindelsen kræver stadig fysisk validering:** Android sender færdige assistentsvar som autentificerede, afgrænsede events til riggens lokale KalivHub-modtager. Modtageren spejler beskederne på Nest Hub uden et ekstra modelkald.

- [Kaliv Android draft-PR #2206](https://github.com/Ternedal/ModelRig/pull/2206) – branch `feature/kalivhub-android-mirror-optin-20261015`.
- [KalivHub Receiver draft-PR #3](https://github.com/Ternedal/KalivHub-Receiver/pull/3) – branch `test/nest-hub-microphone-probe`.
- Android-test-APK og CodeQL er **PASS** for nyere commit `7475a2b`, inklusive integreret levetidsbegrænsning for køede svar. Den samlede Android-CI kører stadig ved denne dokumentationsopdatering. Exact-head-kontrol var **FAILED** på tidligere head (PR merge-tree ≠ immutable head-tree, og en Stage-B downstream-kontrakt overskred sin tidsgrænse); den nye branches release-gates må ikke omgås. Det påvirker ikke muligheden for at installere den isolerede test-APK.
- Receiver JavaScript, mikrofon-diagnostik, mirror-protokoltests samt Windows-readiness-kontrol: **PASS** på commit `19fce07`, alle tre workflows. [Receiverens CI-kørsler](https://github.com/Ternedal/KalivHub-Receiver/pull/3/checks).
- Ingen merge til `main`; ingen produktions-APK er ændret.

## Test, når riggen tændes igen

**1. Opdater KalivHub-testbranchen.**

```powershell
cd C:\Rig\src\KalivHub-Receiver
git switch test/nest-hub-microphone-probe
git pull --ff-only
```

**2. Kontrollér riggens forudsætninger uden at starte nogen services.**

```powershell
pwsh -NoProfile -File .\tools\test-kalivhub-readiness.ps1
```

Denne kontrol er skrivebeskyttet: Den tjekker Python 3.11+, den installerede PyChromecast-controller, nødvendige filer, eksistensen af en krypteret parringnøgle og om TCP-port 8765 allerede er optaget. Nøglen læses eller vises ikke. Hvis PyChromecast mangler, kan afhængigheden installeres på riggen med `py -m pip install "pychromecast>=13,<15"` – kun når du er ved riggen og ønsker det.

For frivilligt også at afprøve selve TCP-forbindelsen fra riggen til Nest Hub (port 8009) kan du bruge `-CheckCast`. Det beviser kun netværkskontakt, **ikke** at Cast-appen er startet, at beskeden vises eller at mikrofonen fungerer.

**3. Start lokal modtager med én kommando.**

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


Starteren finder som standard selv den lokale IP-adresse, som riggen ville bruge til at nå Nest Hub på `192.168.1.13`; IP-valget udsender **ingen** UDP-datapakke. Den lytter kun på denne specifikke private IPv4-adresse på TCP-port `8765`. Den opretter **ingen** Windows-firewallregel og ændrer ikke riggens ModelRig-worker, Ollama eller produktionsservices.

**Valgfri forbindelse via Tailscale, uden at ændre standardopsætningen:** Hvis telefonen skal kontakte riggens Tailscale-IP i stedet for dens LAN-IP, skal HTTP-modtageren udtrykkeligt lytte på **riggens egen tildelte Tailscale IPv4-adresse**. Ellers vælger auto-bind kun interfacet mod Nest Hub, typisk `192.168.x.x`. Find riggens aktuelle Tailscale IPv4 (eksempelvis `tailscale ip -4` lokalt på riggen), og angiv den eksplicit:

```powershell
# Eksemplet 100.101.50.10 SKAL erstattes med riggens egen Tailscale IPv4.
pwsh -NoProfile -File .\tools\start-kalivhub-mirror.ps1 -BindIp 100.101.50.10 -ShowSecret -SelfTest -ClearAfterSeconds 180
```

Indtast derefter `http://100.101.50.10:8765` i Android-testappens Nest Hub-spejling. Begge enheder skal være på samme autoriserede Tailnet, og Windows Firewall/Tailscale-ACL'er skal tillade **kun den betroede telefon** at nå TCP `8765`. Hjælpescriptet afviser offentlige adresser, værtsnavne, CIDR og `0.0.0.0`. Hvis IP'en ikke tilhører riggen, kan Python-serveren ikke binde til den og stopper uden at åbne en lytter. Nest Hub kan fortsat være på riggens normale LAN på `192.168.1.13`, uafhængigt af telefonens forbindelse til modtageren. Bemærk, at den valgfrie /32-firewallregel bruger profilen *Private*, mens Tailscale-adapterens Windows-profil kan være anderledes; brug ikke en bred, usikker firewallregel for at omgå dette.

Brug kun `-BindIp`, når en **anden, eksplicit privat IP på riggen** skal modtage spejlingsbeskeder. Uden dette flag fortsætter standardens automatiske LAN-valg uændret.

Se efter loglinjen `KalivHub mirror listening on X.X.X.X:8765`; adressen `X.X.X.X` er **riggens** LAN-adresse. Brug denne adresse i Android, ikke Nest Hubs IP. Hvis Windows Firewall blokerer forbindelsen, kan du **frivilligt** oprette en regel, der kun giver telefonens præcise private IPv4-adresse adgang til TCP `8765`. Starteren ændrer aldrig firewallen af sig selv.

Åbn en **separat PowerShell med administratorrettigheder** på riggen. Find telefonens aktuelle IP under Android → Wi-Fi → det tilsluttede netværk → netværksoplysninger (ordlyden varierer). Erstat nedenstående eksempeladresse med telefonens faktiske IP:

```powershell
cd C:\Rig\src\KalivHub-Receiver
# Vis planlagt ændring uden at åbne firewallen:
pwsh -NoProfile -File .\tools\set-kalivhub-firewall.ps1 -PhoneIp 192.168.1.22 -WhatIf
# Anvend kun hvis IP-adressen er korrekt:
pwsh -NoProfile -File .\tools\set-kalivhub-firewall.ps1 -PhoneIp 192.168.1.22
```

Hjælpescriptet accepterer kun én normaliseret privat IPv4-adresse (`/32`) og **kun Windows' Private-netværksprofil**. Det afviser offentlige adresser, værtsnavne, CIDR-subnet og jokertegn. Hvis telefonens IP ændres, kør kommandoen igen med dens nye adresse. Hvis netværksprofilen er Public (fx på nogle Tailscale-adaptere), åbner denne regel ikke automatisk adgang; ændr ikke til offentlig adgang uden en konkret sikkerhedsvurdering. En anden app eller firewallregel kan også påvirke adgang.

Når spejlingen ikke længere skal testes, kan den ene regel fjernes fra samme administrator-PowerShell:

```powershell
pwsh -NoProfile -File .\tools\set-kalivhub-firewall.ps1 -Remove
```

Undgå offentlig portåbning, port-forwarding og bind til `0.0.0.0`.

For at stoppe: tryk Ctrl+C i PowerShell. Serveren kører ikke automatisk som en baggrundsservice. HTTP-listeneren stopper først, og den separate Cast-worker afslutter derefter sit igangværende arbejde og lukker selv Cast-forbindelsen. En igangværende Cast-kald kan forsinke afslutningen kortvarigt; hovedtråden forsøger ikke at lukke forbindelsen samtidig.

**4. Installer isoleret Android-testbuild, når der skal fysisk testes.**

Seneste separat installerbare test-APK kan hentes i [GitHub Actions-build #38966029377](https://github.com/Ternedal/ModelRig/actions/runs/38966029377), commit `7475a2b`. **APK-build og CodeQL er bestået** på denne head; den samlede Android-CI afventer slutstatus. APK'en inkluderer direkte proxy-fri transport og en rettelse, der medregner **tid brugt i Android-køen** i det signerede tidsstempel. Byggejobbet kontrollerer både test-pakkenavn og launcher-etiket. Artefaktet hedder `kalivhub-mirror-android-a425f-test-apk` og indeholder `app-a425f.apk`. GitHub oplyser udløb **30. oktober 2026**. Appens separate id er `dk.ternedal.modelrig.a425f`: den installeres ved siden af normal Kaliv og skal parres med riggen separat. Telefonens test-app hedder **Kaliv TEST · Nest Hub**, så de to apps kan kendes fra hinanden.

I testappen: åbn chatmenuen → **Nest Hub-spejling**. Indtast `http://X.X.X.X:8765` (riggens faktiske LAN-IP), og indsæt samme spejlingsnøgle fra PowerShell. Aktivér og gem.

**5. Kontroller forbindelsen i appen.**

Tryk **Test** i Nest Hub-indstillingerne. `HTTP 202` betyder kun, at riggen har lagt beskeden i kø; det beviser **ikke**, at Nest Hub viste den. Kontrollér både `Cast display acknowledgement received` i riggens konsol og teksten `KalivHub: forbindelsestest` på Nest Hub.

Send derefter to normale chatbeskeder, og prøv gerne cloud, retry og færdig stemmesamtale. Afbryd Nest Hub, og kontrollér at chatten på telefonen stadig virker upåvirket. Test også at beskeder, der blev køet før **Deaktivér** eller en ændring af spejlingsnøgle, ikke vises senere; en besked, der ligger i kø mere end 30 sekunder, skal droppes – både i Android og hos riggens Cast-modtager. Også en langsom Cast-opstart/genforbindelse skal opgive udløbne svar. Allerede påbegyndte HTTP-kald kan dog ikke trækkes tilbage efter de er sendt.

## Fysisk fejlsøgning — i hvilken del af kæden stopper det?

| Observation | Hvad det betyder | Næste sikre kontrol |
| --- | --- | --- |
| `test-kalivhub-readiness.ps1` melder manglende `py`/PyChromecast | Modtagerens Windows-miljø er ikke klart | Find korrekt Python 3.11+ og installer `pychromecast>=13,<15` i **det samme** Python-miljø, som starteren bruger |
| Ingen `KalivHub mirror listening on X.X.X.X:8765` | Riggens HTTP-server kom ikke i gang | Kontrollér traceback, private bind-adresse og at port 8765 ikke er optaget; åbn ikke hele firewallen |
| Android kan ikke nå riggens IP/port | Telefon → rig-netværksstien mangler | Bekræft samme betroede LAN eller gyldig Tailscale-rute, og brug eventuelt den **frivillige /32-firewallregel** |
| HTTP `401` | Forkert spejlingsnøgle, signatur eller urforskel over 60 sekunder | Kontrollér riggens og telefonens automatiske urindstilling samt nøjagtig nøgle; læg ikke nøglen i logs/chat |
| HTTP `400`, `408`, `410`, `413` eller `503` | Ugyldigt/ufuldstændigt, for gammelt, for stort eller købegrænset event | Se statusforklaringerne nedenfor; lad være med at øge grænserne uden konkret årsag |
| HTTP `202`, men ingen `Cast display acknowledgement received` | Modtageren har køet, men Cast er ikke bekræftet | Kontrollér Nest Hub på TCP 8009 med `-CheckCast`, App ID, og at den registrerede receiver faktisk kan vises; lad `-StrictAcks` være slået fra på gammel deployment |
| Cast ACK, men ingen synlig tekst | Cast svarer, men fysisk visning er ikke accepteret | Tjek den rigtige Nest Hub-skærm, receiverens faktiske visning og om indholdet allerede er ryddet |
| Normal Kaliv-chat virker, men intet spejles | Spejling er en frivillig sidekanal | Kontrollér om den **separate** testapp er parret/aktiveret, og at du tester et færdigt assistentsvar |

**Testsekvens:** Først read-only readiness, så signerede rig-`SelfTest`, derefter Androids `Test`-knap, til sidst to almindelige svar og en afbrudt forbindelse. Et HTTP `202` er **aldrig** alene bevis for en vist besked. Giv ikke hemmelige nøgler eller samtaleindhold videre ved fejlsøgning.

## Sikkerhed og diagnose

- Spejlingen er **slået fra som standard** og kan altid deaktiveres i Android.
- Android sender kun færdig assistenttekst; **ikke** brugerspørgsmål, chat-historik, ModelRig-bearertoken eller cloud-API-nøgler. Spejl ikke følsomme svar på delt skærm.
- HMAC-SHA256 autentificerer rå JSON-bytes og Unix-timestamp; der er begrænset tidsvindue, replay-cache, tekstgrænse (2.000 UTF-16-enheder), HTTP-body (16 KiB), op til 16 køede events og begrænset antal HTTP-forbindelser. Android medsender den allerede forbrugte køtid i den signerede tidsfrist. Derfor får en forsinket besked **ikke** nye 30 sekunder, når HTTP-afsendelsen begynder. Både Androids og riggens ventende svar bliver kasseret efter den samlede grænse på ca. 30 sekunder (afrundet konservativt til hele sekunder). Modtageren tæller også dokumenteret transporttid siden eventets signerede tidsstempel med, så et sent ankommet svar ikke får en ny 30-sekunders frist. Riggen kontrollerer også udløb efter Cast-opstart og inden visning; er der under seks sekunder tilbage af tidsfristen, sendes visningskommandoen ikke, da dens kvittering kan tage op til seks sekunder. Den fysiske skærm kan dog ikke styres eller tidsstemples præcist under Cast-netværksfejl.
- Trafikken er **HTTP og ukrypteret** på lokalnettet. Signaturen beskytter ikke svarindhold mod aflæsning på netværket. Android spejler nu med `Proxy.NO_PROXY`, så en eventuel systemproxy på telefonen ikke bruges til at videresende lokale svar. Det krypterer **stadig ikke** dataene; brug kun et betroet LAN, ellers en korrekt HTTPS/VPN-løsning.
- En udløbet besked stoppes inden skærmvisning; hvis receiveren allerede havde fået `thinking`, forsøger broen at nulstille status til `idle` inden frakobling. Det er best effort, og en utilgængelig Cast-enhed kan ikke garanteres nulstillet.
- Cast-broen forsøger en fuld retry **kun** før den har forsøgt at sende `SHOW_MESSAGE`. Efter forsøget kan en mistet kvittering betyde både “vist” og “ikke vist”; broen undlader derfor at gensende den samme assistenttekst. Fejl i `idle` efter bekræftet visning udløser heller ikke en ny visning. Det prioriterer ingen dobbeltvisning over automatisk genafsendelse, når Cast-kvitteringen er tvetydig.
- `GET /healthz` kontrollerer kun, at HTTP-modtageren kører, **ikke** Cast-status.
- `401`: HMAC eller ur passer ikke. `409`: event-ID er allerede modtaget. `410`: signeret besked er allerede 30 sekunder gammel, før den kan køes. `503`: køen eller replay-cache er fuld. `408`: HTTP-body blev ikke modtaget inden den samlede tidsfrist på 5 sekunder. `400`: tvetydige headers, dublerede JSON-felter eller andet ugyldigt input. `413`: ugyldig eller for stor `Content-Length`.
- Hvis DPAPI-nøglen ikke kan dekrypteres, fejler starteren bevidst frem for stille at generere en ny. Re-pair Android efter en bevidst nøglerotation.
- Lokal Python-kontrakttest: `py -m unittest discover -s tests -p test_kalivhub_mirror_server.py -v`.
- Ingen merge eller produktion før komplet CI og fysisk test gennem **Android → rig → Cast → Nest Hub**.

Den ældre `tools/modelrig_cast_bridge.py` er fortsat til frivillig PowerShell-diagnostik og er ikke en del af den automatiske Android-spejling.
