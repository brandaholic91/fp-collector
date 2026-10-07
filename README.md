# fp-collector

Saját üzemeltetésű first-party eseménygyűjtő: a böngészőtől az adatbázison át a dashboardig minden lépés saját kódban és saját szerveren fut. Portfólió-projekt, referencia-megvalósításnak készült.

**Élő demó:** https://fp.growthframe.hu · **Dashboard:** https://fp.growthframe.hu/dashboard

> Az élő demó adata szinte teljesen szimulált. A forgalmat egy beépített szimulátor gyártja, és minden ilyen esemény `payload`-jában ott a `"simulated": true` mező. A saját látogatásod valódi eseményként kerül be.

## Mit csinál

1. A landing oldal tracker scriptje hozzájárulás után eseményeket küld (`page_view`, `cta_click`, `form_submit`).
2. A collector API ellenőrzi az eseményt, és változtatás nélkül eltárolja a `raw_events` táblában.
3. Egy Python worker feldolgozza a nyers sorokat: forrást rendel hozzájuk, és a `clean_events` táblába írja őket. Az űrlapbeküldésekből `leads` sor lesz.
4. A dashboard a tisztított adatból mutatja a pipeline állapotát, a tölcsért, a napi eseményszámot és a forrás szerinti bontást.

```
Böngésző → tracker.js → Collector API → raw_events → worker → clean_events / leads → Dashboard
```

## A fontosabb tervezési döntések

- **Hozzájárulás nélkül nincs adat.** A tracker a hozzájárulás előtt azonosítót sem hoz létre, az API pedig a `consent_analytics: false` eseményt 403-mal elutasítja, mielőtt bármi az adatbázisba kerülne.
- **Egy esemény csak egyszer számít.** Az `event_id`-t a kliens generálja, az adatbázis egyedi kulccsal védi. Az ismételt küldés nem hiba: a válasz `duplicate`, új sor nem keletkezik.
- **A nyers réteg érintetlen marad.** A `raw_events` azt tárolja, ami beérkezett; a tisztítás és a forrás-hozzárendelés külön táblába megy, így a feldolgozás szabályai utólag változtathatók.
- **A hibás sor nem tűnik el csendben.** Ha a worker egy eseményt nem tud feldolgozni, a hiba szövege a sor `processing_error` mezőjébe kerül, és a dashboard külön számolja.
- **Az adatbázis kívülről nem érhető el.** Portot csak az API nyit, az is csak a reverse proxy felé.
- **A szimulált adat jelölve van.** Demóhoz kell forgalom, de a szimulátor eseményei az adatbázisban is megkülönböztethetők a valóditól.

## Miből áll

| Rész | Technológia | Hol van |
|---|---|---|
| Landing és tracker | statikus HTML, vanilla JavaScript | `api/static/landing/` |
| Collector API | Python, FastAPI, asyncpg, slowapi | `api/main.py`, `api/routes/events.py` |
| Adatbázis | PostgreSQL 16 | `db/init.sql`, `db/migrations/` |
| Worker | Python, asyncpg | `api/worker.py`, `api/pipeline.py` |
| Dashboard | statikus HTML, Chart.js | `api/static/dashboard/`, `api/routes/stats.py` |
| Forgalomszimulátor | Python | `api/simulator.py` |
| Futtatás | Docker Compose | `docker-compose.yml` |

## API

| Végpont | Mit csinál |
|---|---|
| `POST /v1/events` | Egy esemény fogadása. Percenként 100 kérés IP-címenként. |
| `POST /v1/events/batch` | 1–1000 esemény egy kérésben. Csak bekapcsolt `ECOMMERCE_ENABLED` mellett él. |
| `GET /api/stats/health` | Beérkezett, feldolgozásra váró, feldolgozott és hibás események száma |
| `GET /api/stats/funnel` | Látogatás → kattintás → űrlapbeküldés |
| `GET /api/stats/events` | Események száma naponta |
| `GET /api/stats/utm` | Események és leadek forrás szerint |
| `GET /health` | Életjel |

Egy esemény így néz ki:

```json
{
  "event_id": "5b0c4f0e-6a0e-4a53-9d55-0c1d6f5f3a11",
  "event_name": "page_view",
  "occurred_at": "2026-10-07T12:00:00.000Z",
  "session_id": "s-1",
  "anonymous_id": "a-1",
  "page_url": "https://example.com/",
  "referrer": null,
  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "brand_search",
  "consent_analytics": true,
  "payload": {}
}
```

A válasz `202`, a törzse `{"status": "ok"}` vagy `{"status": "duplicate"}`. Hiányzó mező vagy ismeretlen eseménynév esetén `422`.

## E-commerce mód

Az `ECOMMERCE_ENABLED=true` beállítás négy további eseményt enged be: `view_item`, `add_to_cart`, `begin_checkout`, `purchase`. Az élő demón ez ki van kapcsolva.

- **A vásárlás ellenőrzött.** A `purchase` eseménynek kell `order_id`, pozitív `value`, `currency` és `customer_key`; ezekből `orders` sor készül.
- **Az eszközök összekapcsolódnak.** Ha egy eszközről vásárlás történt, a `resolved_events` nézet az eszköz minden eseményéhez a vásárló azonosítóját rendeli, a vásárlás előttiekhez is.
- **A worker kötegelve is tud dolgozni.** A `WORKER_BATCHED=true` beállítással 5000 sort dolgoz fel egy tranzakcióban; ha a köteg elbukik, visszavált soronkénti feldolgozásra.

## Kipróbálás helyben

Docker kell hozzá. Az alábbi parancsok egy önálló példányt indítanak e-commerce móddal; az API a `127.0.0.1:18080` címen érhető el.

```bash
cp .env.world.example .env.world
docker compose -f docker-compose.world.yml up -d --build --wait
curl -s http://127.0.0.1:18080/health
```

Esemény küldése:

```bash
curl -s -X POST http://127.0.0.1:18080/v1/events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"5b0c4f0e-6a0e-4a53-9d55-0c1d6f5f3a11","event_name":"page_view",
       "occurred_at":"2026-10-07T12:00:00Z","session_id":"s-1","anonymous_id":"a-1",
       "page_url":"https://example.com/","consent_analytics":true,"payload":{}}'
```

A dashboard a http://127.0.0.1:18080/dashboard címen nyílik meg. Leállítás az adatok törlésével:

```bash
docker compose -f docker-compose.world.yml down -v
```

A `docker-compose.yml` az éles telepítés leírása: reverse proxy mögé készült, portot nem nyit a gépen, ezért helyi próbára a fenti fájl való.

## Tesztek

85 automata teszt fut egy valódi PostgreSQL ellen: az API ellenőrzései, a duplikációkezelés, a worker mindkét módja, a rendelések és az eszköz-összekapcsolás, a dashboard statisztikái.

```bash
docker run -d --name fp-test-db \
  -e POSTGRES_USER=fpcollector -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=fpcollector_test \
  -p 127.0.0.1:25432:5432 \
  -v "$PWD/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" postgres:16.3

cd api
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

## Amit a demó nem tud

- **Nincs hitelesítés.** A dashboard és a statisztikai végpontok nyilvánosak, mert az adat szimulált. Valódi adatnál ezeket védeni kell.
- **Az űrlap adata a `payload`-ba kerül.** A demóban ez kitalált e-mail-cím; valódi használatnál a személyes adat tárolásáról külön dönteni kell.
- **A hibás sort a worker nem próbálja újra.** A hiba látszik, a javítás kézi.
- **A duplikált kérést nem számolja.** Az ismételt esemény nem kerül be még egyszer, de arról, hogy hány ilyen érkezett, nincs adat.
- **A forrás-hozzárendelés egyszerű.** UTM-paraméterekből, `fbclid`-ből és a hivatkozó oldal nevéből dolgozik; `gclid`-et nem kezel.
