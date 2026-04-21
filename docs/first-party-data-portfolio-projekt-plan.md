# First-Party Data Portfólió Projektterv

## 1. Projektcél és kontextus

Ez a projekt egy end-to-end, first-party adatgyűjtő és feldolgozó rendszer, amely egyszerre szolgálja:

- a gyakorlati tanulást (MarTech engineering, adatpipeline, automatizáció),
- a portfólió építését (demózható, mérhető és dokumentált projekt),
- a homelab alapelvek betartását (szerepkör szerinti labszeparáció, reverse proxy-only kitettség, IaC szemlélet).

A cél egy olyan referenciaimplementáció létrehozása, amelyben a webes user interakciókból strukturált, megbízható first-party adatok keletkeznek, majd ezekből üzletileg értelmezhető insightok és aktivációk jönnek létre.

## 2. Mit jelent itt a first-party data

Ebben a projektben first-party data alatt azokat az adatokat értjük, amelyeket te, a saját felületeiden, saját domain alatt, saját infra komponensekkel gyűjtesz:

- oldalletöltések (`page_view`),
- CTA interakciók (`cta_click`),
- lead form beküldések (`form_submit`),
- kapcsolódó kontextus (UTM paraméterek, referrer, session azonosító, consent státusz).

Fontos elv: a mérés és feldolgozás alapvetően saját collector + saját pipeline mentén történik. Az Umami a későbbi fázisban kiegészítő ellenőrző/visual analytics szerepet kap.

## 3. Célfunkciók (MVP + bővítés)

### 3.1 MVP célfunkciók

- Egy landing oldal, ahol mérhető user útvonal van (visit -> click -> lead).
- Kliensoldali tracking script, amely szabályozott séma szerint küld eventeket.
- Saját Event Collector API endpoint (`POST /v1/events`).
- n8n workflow az adattisztításra, deduplikációra, enrichmentre.
- PostgreSQL adattárolás legalább két réteggel: `raw_events`, `clean_events` (+ opcionálisan `leads`).
- Alap dashboard 4-6 KPI-val és funnel nézetekkel.

### 3.2 Későbbi bővítések

- Umami telepítése és összevetés a saját collector adataival.
- Lead scoring szabályok (pl. forrás + viselkedési pontozás).
- Webhook aktiváció (Slack/Discord/email) magas értékű leadekre.
- Egyszerű adatmegőrzési policy (pl. 180 nap retention).

## 4. Lab szerepkörök szerinti elhelyezés

Az `AGENTS.md` irányelvekhez igazodva:

- `martech-lab`: NPM, CoreDNS, n8n (platform/core komponensek).
- `dokploy-lab`: landing oldal/app, Event Collector API, projekt PostgreSQL, Umami.
- `monitoring-lab`: uptime check, alap monitorozás/riasztás, log konzisztencia.

Ez az elosztás egyszerre tartja tisztán a platform- és alkalmazásszinteket, és jól mutatható portfólió sztorit ad.

## 5. Magas szintű architektúra

1. A user a landing oldalon interakcióba lép.
2. A kliens script eventet küld a saját collector endpointnak.
3. A collector validálja, idempotensen kezeli, majd `raw_events`-be ment.
4. Az n8n feldolgozza az új raw rekordokat (tisztítás, enrichment, dedup).
5. A feldolgozott rekordok `clean_events`/`leads` táblába kerülnek.
6. A dashboard ezekre a táblakeretekre építve KPI-kat és funnelt mutat.
7. (Bővítés) Az Umami párhuzamosan mér webanalitikát validációs célra.

## 6. Adatmodell és event séma

### 6.1 Event taxonomy (kezdő készlet)

- `page_view`
- `cta_click`
- `form_submit`

### 6.2 Javasolt kötelező mezők

- `event_id` (UUID, kliens oldalon generálva)
- `event_name`
- `occurred_at` (ISO timestamp)
- `session_id`
- `anonymous_id` (cookie/local storage alapú)
- `page_url`
- `referrer`
- `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`
- `consent_analytics` (bool)
- `payload` (JSON)

### 6.3 Táblák (minimum)

- `raw_events`: bejövő adatok minimális transzformációval.
- `clean_events`: validált, normalizált, deduplikált sorok.
- `leads` (opcionális, de ajánlott): form submit alapján létrejött lead rekordok.

## 7. Privacy, consent, security alapelvek

- Marketing/analytics event csak érvényes consent után menjen.
- Titkos adatok nem kerülnek repóba, `.env`/secret mechanizmus használata kötelező.
- Publikus kitettség csak NPM-en keresztül, közvetlen host port publikáció kerülendő.
- Konténer image-ek fix taggel vagy digesttel menjenek (`latest` nélkül).
- API oldalon bemeneti validáció + alap rate limiting + idempotencia.

## 8. Technikai megvalósítás (fázisokra bontva)

### Phase 0 - Tervezés és alapdokumentáció (0.5 nap)

Célfeladatok:

- Event taxonomy és adatmezők véglegesítése.
- KPI definíciók (miből, milyen képlettel, milyen időintervallumban mérünk).
- Minimál runbook váz (hiba tünet, ellenőrzés, rollback lépések).

Deliverable:

- Dokumentált séma + KPI lista + kezdeti runbook.

### Phase 1 - Collector MVP (2-3 nap)

Célfeladatok:

- Landing oldalba egyszerű tracking helper bevezetése (`track(eventName, payload)`).
- Event Collector API endpoint kialakítása (`POST /v1/events`).
- Szigorú payload validáció.
- `event_id` alapú idempotens kezelés.
- Mentés PostgreSQL `raw_events` táblába.

Sikerkritériumok:

- Event ingest sikeresség >= 98% tesztforgalom mellett.
- Duplikáció <= 1%.

### Phase 2 - n8n pipeline és adattisztítás (1-2 nap)

Célfeladatok:

- n8n workflow trigger `raw_events` alapján.
- Deduplikáció, normalizálás, UTM enrichment, source/medium származtatás.
- Mentés `clean_events`-be.
- `form_submit` alapján lead rekord és opcionális webhook riasztás.

Sikerkritériumok:

- Feldolgozási késleltetés p95 < 60s.
- Hibás rekordok külön hibacsatornára vagy dead-letter logikába mennek.

### Phase 3 - Dashboard és riportolás (1 nap)

Célfeladatok:

- Funnel kimutatás: visit -> click -> lead.
- UTM bontás (source/medium/campaign).
- Top landing oldalak + conversion mutatók.

Sikerkritériumok:

- 4-6 KPI konzisztensen reprodukálható adatokból.
- Dashboard alkalmas demózásra és portfólió screenshotokra.

### Phase 4 - Umami integráció (0.5-1 nap)

Célfeladatok:

- Umami telepítése `dokploy-lab`-ban, fix image taggel.
- NPM mögötti publikáció.
- Alap pageview/campaign adatok összevetése a saját collectorral.

Sikerkritériumok:

- Van dokumentált módszertan az adateltérések értékeléséhez.
- Kijelölt "source of truth" (javasolt: saját collector).

### Phase 5 - Portfólió packaging (1 nap)

Célfeladatok:

- README: cél, architektúra, komponensek, deploy lépések, használat.
- Backup/restore rövid jegyzet.
- Mini runbook kritikus hibákra.
- Diagram + képernyőképek + mérési eredmények.

Sikerkritériumok:

- Kívülálló számára reprodukálható és értelmezhető projektanyag.

## 9. Könyvtár- és stack standard illeszkedés

Az `AGENTS.md` szerinti javasolt struktúra:

- `/mnt/data/stacks/fp-collector/docker-compose.yml`
- `/mnt/data/stacks/fp-collector/data/`
- `/mnt/data/stacks/umami/docker-compose.yml`
- `/mnt/data/stacks/umami/data/`

Infrastruktúra szabályok:

- `proxy-net` external network csatlakozás a publikus szolgáltatásoknál.
- Inkább `expose`, és csak indokolt esetben `ports`.
- Fájlok tulajdonjoga `/mnt/data/stacks` alatt: `balazs:balazs`.

## 10. KPI-k és mérési keretrendszer

Javasolt kezdő KPI készlet:

- Event ingest success rate
- Duplicate event rate
- Landing -> CTA conversion rate
- CTA -> Lead conversion rate
- Összesített funnel conversion rate
- Source/medium szerinti lead mennyiség

Értékelési szempont:

- Nem csak az abszolút volumen számít, hanem a pipeline megbízhatósága és konzisztenciája is.

## 11. Kockázatok és kezelésük

1. Dupla mérés / inkonzisztens számok
   - Kezelés: egyértelmű "source of truth", metric definíciók rögzítése.
2. Consent logika hiányossága
   - Kezelés: kliensoldali gate + backend oldali ellenőrzés.
3. Event séma drift
   - Kezelés: verziózott séma + strict validation.
4. Pipeline törlés/hibás feldolgozás
   - Kezelés: dead-letter minta + újrafuttatható workflow.

## 12. Dokumentációs minimum (portfólió minőséghez)

Minden releváns stackhez legyen rövid, de használható dokumentáció:

- célfunkció,
- függőségek,
- elérés (belső URL),
- deploy/update lépések,
- backup/restore megjegyzések,
- alap hibaelhárítás.

Külön plusz pont, ha készülsz egy rövid "Design decisions" résszel, ahol leírod a fontos tradeoffokat (pl. miért saját collector a source of truth és miért csak másodlagos az Umami).

## 13. 10 napos javasolt menetrend

- Nap 1: taxonomy, séma, KPI definíciók, runbook váz.
- Nap 2-4: Collector API + DB + kliens tracking MVP.
- Nap 5-6: n8n feldolgozó workflow + dedup/enrichment.
- Nap 7: dashboard és funnel riport.
- Nap 8: Umami telepítés és validáció.
- Nap 9-10: dokumentáció, screenshotok, portfólió polish.

## 14. Definition of Done (DoD)

A projekt akkor tekinthető késznek MVP+portfólió szinten, ha:

- működik az end-to-end adatfolyam (client -> collector -> n8n -> DB -> dashboard),
- van legalább 3 event típus és funnel riport,
- a consent logika ténylegesen érvényesül,
- dokumentáltak a KPI-k és adatforrások,
- van backup/restore jegyzet és mini runbook,
- van bemutatható, rendezett portfólió anyag (README, diagram, képernyőkép).

---

Ez a terv tudatosan az MVP gyors piacra vitelére és a portfólióérték maximalizálására optimalizál: előbb egy stabil saját first-party pipeline, utána Umami mint kiegészítő analytics validációs layer.