# Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 1 placeholder landing page (50 lines, one CTA) with a full-featured Hungarian portfolio landing that explains the fp-collector project and demonstrates the tracking pipeline by instrumenting its own interactions.

**Architecture:** Pure frontend replacement of `api/static/landing/index.html`. No backend changes, no new files, no new dependencies. Tailwind CDN + vanilla JS, consistent with Phase 3 dashboard styling. Existing `tracker.js` unchanged; new `onclick`/`onsubmit` hooks call `track()` at 11 CTA sites and 1 form.

**Tech Stack:** HTML5, Tailwind CSS via CDN, vanilla JS (existing tracker.js).

---

## File Map

| File | Action |
|---|---|
| `api/static/landing/index.html` | Complete rewrite: 50 → ~270 lines |
| `api/static/landing/tracker.js` | Unchanged |
| All backend files | Unchanged |

---

## Testing Strategy

No automated tests. The backend is unchanged — pytest scope is unchanged. Every task ends with manual browser verification.

**Dev loop:**
- The stack must be running (`docker-compose up -d`) with a host port mapping to localhost:8000 (either Phase 3's `docker-compose.override.yml` or set `POSTGRES_BIND_IP` + exposed api port via override).
- After editing `api/static/landing/index.html`, copy into the running container:
  ```bash
  docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
  ```
  Static files don't need a restart; a browser reload picks them up.
- Open `http://localhost:8000/` to verify.

---

## Prerequisites

1. Phase 3 is merged to `main`.
2. Docker stack runs locally; api is reachable at `http://localhost:8000/` (via `docker-compose.override.yml` port mapping, gitignored).
3. Before Task 1, clear browser localStorage for `localhost:8000` so the consent banner triggers and is verifiable.

---

## Task 1: Page skeleton — Tailwind setup, header, consent banner, section placeholders

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace the entire file content with the skeleton below**

```html
<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>fp-collector — first-party data pipeline</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen flex flex-col">
  <header class="max-w-6xl w-full mx-auto px-6 pt-8 pb-4 flex items-baseline justify-between">
    <a href="/" class="text-xl font-semibold tracking-tight">fp-collector</a>
    <nav class="flex gap-5 text-sm">
      <a href="/dashboard?utm_source=landing&utm_medium=header&utm_campaign=portfolio_demo"
         onclick="track('cta_click', {label: 'header_dashboard'})"
         class="text-slate-600 hover:text-slate-900">Dashboard</a>
      <a href="https://github.com/placeholder/fp-collector"
         onclick="track('cta_click', {label: 'header_github'})"
         class="text-slate-600 hover:text-slate-900">GitHub</a>
    </nav>
  </header>

  <main class="max-w-6xl w-full mx-auto px-6 flex-1">
    <!-- hero-section -->
    <!-- features-section -->
    <!-- how-it-works-section -->
    <!-- live-promo-section -->
    <!-- contact-section -->
  </main>

  <!-- footer-section -->

  <div id="banner" class="consent-banner fixed bottom-0 left-0 right-0 bg-slate-900 text-white px-6 py-4 flex items-center gap-4 text-sm hidden">
    <span class="flex-1">Ez az oldal saját analytics rendszert használ a felhasználói interakciók mérésére.</span>
    <button onclick="grantConsent(); document.getElementById('banner').classList.add('hidden');"
            class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md">
      Elfogadom
    </button>
  </div>

  <script src="/static/landing/tracker.js"></script>
  <script>
    if (!localStorage.getItem('consent_analytics')) {
      document.getElementById('banner').classList.remove('hidden');
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Open `http://localhost:8000/` in a browser.

Expected:
- Header renders with "fp-collector" logo and two links (Dashboard, GitHub), Tailwind styled.
- Consent banner appears at the bottom on first visit.
- Clicking `Elfogadom` dismisses the banner; localStorage gains `consent_analytics=true`.
- Page is otherwise blank (all sections are HTML comments).
- Browser console clean (except the Tailwind CDN development-use warning).
- After consent, check `raw_events` for a `page_view` row:
  ```bash
  docker-compose exec -T db psql -U fpcollector -d fpcollector -c "SELECT event_name, payload FROM raw_events ORDER BY id DESC LIMIT 3;"
  ```

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): replace placeholder with skeleton (Tailwind + header + consent)"
```

---

## Task 2: Hero section

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- hero-section -->` with:**

```html
    <section class="py-16 md:py-24 text-center">
      <h1 class="text-4xl md:text-5xl font-semibold tracking-tight text-slate-900 max-w-3xl mx-auto">
        First-party data pipeline — saját kezedben az adatod
      </h1>
      <p class="mt-6 text-lg text-slate-600 max-w-2xl mx-auto">
        Egy self-hosted MarTech referencia: collector API, PostgreSQL, n8n feldolgozás és dashboard — minden komponens a saját infrastruktúrádon fut.
      </p>
      <div class="mt-10 flex gap-3 justify-center">
        <a href="/dashboard?utm_source=landing&utm_medium=hero_cta&utm_campaign=portfolio_demo"
           onclick="track('cta_click', {label: 'hero_dashboard'})"
           class="bg-slate-900 hover:bg-slate-800 text-white px-6 py-3 rounded-lg font-medium">
          Dashboard megnyitása
        </a>
        <a href="https://github.com/placeholder/fp-collector"
           onclick="track('cta_click', {label: 'hero_github'})"
           class="bg-white hover:bg-slate-100 text-slate-900 border border-slate-300 px-6 py-3 rounded-lg font-medium">
          GitHub
        </a>
      </div>
    </section>
```

- [ ] **Step 2: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Reload `http://localhost:8000/`. Expected:
- Large centered H1 ("First-party data pipeline — saját kezedben az adatod").
- Subtitle paragraph below.
- Two CTAs: black "Dashboard megnyitása", white "GitHub" with border.
- Click "Dashboard megnyitása": new page loads at `/dashboard?utm_source=landing&utm_medium=hero_cta&utm_campaign=portfolio_demo`. Go back.
- Inspect `raw_events`: two new rows (a `cta_click` with `payload.label = hero_dashboard` and a `page_view` on the dashboard with the UTM values).

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add hero section with primary + secondary CTAs"
```

---

## Task 3: Features section (3 cards)

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- features-section -->` with:**

```html
    <section class="py-12 md:py-16 border-t border-slate-200">
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <button type="button"
                onclick="track('cta_click', {label: 'feature_own_data'})"
                class="bg-white text-left rounded-xl p-6 shadow-sm hover:shadow-md transition-shadow">
          <h3 class="text-lg font-semibold text-slate-900">Saját tulajdonban lévő adat</h3>
          <p class="mt-3 text-sm text-slate-600 leading-relaxed">
            A látogatói eventek a te PostgreSQL-edbe kerülnek, nem egy harmadik fél szerverére. Teljes kontroll a retention, export és törlés felett.
          </p>
        </button>
        <button type="button"
                onclick="track('cta_click', {label: 'feature_self_hosted'})"
                class="bg-white text-left rounded-xl p-6 shadow-sm hover:shadow-md transition-shadow">
          <h3 class="text-lg font-semibold text-slate-900">End-to-end self-hosted</h3>
          <p class="mt-3 text-sm text-slate-600 leading-relaxed">
            Collector API + adatbázis + n8n pipeline + dashboard egyetlen Docker Compose stackben. Nem kell SaaS-előfizetés, nem kell adattovábbítás.
          </p>
        </button>
        <button type="button"
                onclick="track('cta_click', {label: 'feature_consent'})"
                class="bg-white text-left rounded-xl p-6 shadow-sm hover:shadow-md transition-shadow">
          <h3 class="text-lg font-semibold text-slate-900">Consent-első, GDPR-kompatibilis</h3>
          <p class="mt-3 text-sm text-slate-600 leading-relaxed">
            Minden event csak explicit user consent után kerül továbbításra és tárolásra. A consent logic kliens- és szerver-oldalon egyaránt érvényesül.
          </p>
        </button>
      </div>
    </section>
```

- [ ] **Step 2: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Reload. Expected:
- 3 feature cards in a row on desktop (stack on mobile).
- Clicking each card fires a `cta_click` with the correct `payload.label`.
- Verify via psql:
  ```bash
  docker-compose exec -T db psql -U fpcollector -d fpcollector -c "SELECT payload->>'label' AS label, count(*) FROM raw_events WHERE event_name = 'cta_click' GROUP BY label;"
  ```

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add features section (3 value-prop cards)"
```

---

## Task 4: How it works — architecture diagram + explainer

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- how-it-works-section -->` with:**

```html
    <section class="py-12 md:py-16 border-t border-slate-200">
      <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-6">Hogyan működik</h2>

      <div class="bg-white rounded-xl p-6 md:p-8 shadow-sm">
        <div class="flex flex-col md:flex-row items-stretch md:items-center gap-3 md:gap-4">
          <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <div class="text-xs text-slate-500 uppercase tracking-wide">1</div>
            <div class="mt-1 font-medium text-slate-900">Browser</div>
          </div>
          <div class="text-slate-400 text-center md:text-2xl">→</div>
          <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <div class="text-xs text-slate-500 uppercase tracking-wide">2</div>
            <div class="mt-1 font-medium text-slate-900">Collector API</div>
          </div>
          <div class="text-slate-400 text-center md:text-2xl">→</div>
          <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <div class="text-xs text-slate-500 uppercase tracking-wide">3</div>
            <div class="mt-1 font-medium text-slate-900">PostgreSQL</div>
          </div>
          <div class="text-slate-400 text-center md:text-2xl">→</div>
          <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <div class="text-xs text-slate-500 uppercase tracking-wide">4</div>
            <div class="mt-1 font-medium text-slate-900">n8n</div>
          </div>
          <div class="text-slate-400 text-center md:text-2xl">→</div>
          <div class="flex-1 rounded-lg border border-slate-200 bg-slate-50 px-4 py-4 text-center">
            <div class="text-xs text-slate-500 uppercase tracking-wide">5</div>
            <div class="mt-1 font-medium text-slate-900">Dashboard</div>
          </div>
        </div>

        <p class="mt-8 text-slate-600 leading-relaxed">
          A pipeline négy különálló komponensből áll, mindegyik egy jól definiált felelősséggel. Az adat minden lépésben hitelesebb és normalizáltabb formát ölt.
        </p>

        <ul class="mt-6 space-y-3 text-sm text-slate-700 leading-relaxed">
          <li class="flex gap-3">
            <span class="text-slate-400 font-mono">1.</span>
            <span>Kliens-oldali <code class="font-mono text-slate-900">tracker.js</code> a landing oldalon minden user interakciót (page view, CTA kattintás, form submit) strukturált event objektumba csomagol és POST-tolja a collector API-nak.</span>
          </li>
          <li class="flex gap-3">
            <span class="text-slate-400 font-mono">2.</span>
            <span>A FastAPI alapú collector endpoint szigorúan validálja, consent alapján szűri, és idempotensen tárolja a <code class="font-mono text-slate-900">raw_events</code> táblában.</span>
          </li>
          <li class="flex gap-3">
            <span class="text-slate-400 font-mono">3.</span>
            <span>Az n8n workflow 30 másodpercenként dolgozza fel az új sorokat: dedup, source/medium enrichment, form_submit → lead routing.</span>
          </li>
          <li class="flex gap-3">
            <span class="text-slate-400 font-mono">4.</span>
            <span>A dashboard 4 REST endpointról olvassa az aggregált adatokat és real-time megjeleníti a pipeline egészségét és a konverziós tölcsért.</span>
          </li>
        </ul>
      </div>
    </section>
```

- [ ] **Step 2: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Reload. Expected:
- "Hogyan működik" small header.
- Big white card containing: 5 boxes in a horizontal row (desktop) with `→` arrows between; each box has a number badge and component name.
- On mobile (narrow viewport ≤ 768px): the boxes stack vertically, arrows still visible between them (`→` on mobile is OK — the spec accepts either).
- Below: intro paragraph + 4 numbered bullet points.
- No broken layout at either breakpoint.

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add how-it-works section with architecture diagram and explainer"
```

---

## Task 5: Live dashboard promo section

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- live-promo-section -->` with:**

```html
    <section class="py-12 md:py-16 border-t border-slate-200">
      <div class="bg-slate-900 text-white rounded-xl p-8 md:p-12 text-center">
        <h2 class="text-2xl md:text-3xl font-semibold tracking-tight">
          Ez az oldal saját magát méri
        </h2>
        <p class="mt-4 text-slate-300 max-w-2xl mx-auto">
          A fenti interakcióid (page view, kattintás, esetleg űrlap) pár másodpercen belül megjelennek a live dashboardon. Nyisd meg és nézd meg saját magadat.
        </p>
        <a href="/dashboard?utm_source=landing&utm_medium=promo_cta&utm_campaign=portfolio_demo"
           onclick="track('cta_click', {label: 'promo_dashboard'})"
           class="mt-8 inline-block bg-white hover:bg-slate-100 text-slate-900 px-6 py-3 rounded-lg font-medium">
          Dashboard megnyitása
        </a>
      </div>
    </section>
```

- [ ] **Step 2: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Reload. Expected:
- Dark slate-900 card with white heading and subtitle.
- White CTA button.
- Clicking fires `cta_click` with `promo_dashboard` and navigates with UTM.

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add live dashboard promo section"
```

---

## Task 6: Contact form section

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- contact-section -->` with:**

```html
    <section class="py-12 md:py-16 border-t border-slate-200">
      <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-6">Kapcsolat</h2>

      <div class="bg-white rounded-xl p-6 md:p-8 shadow-sm max-w-2xl mx-auto">
        <form id="contact-form" class="space-y-4" onsubmit="handleContactSubmit(event)">
          <div>
            <label for="contact-name" class="block text-sm font-medium text-slate-700 mb-1">Név</label>
            <input type="text" id="contact-name" name="name" required
                   class="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
          </div>
          <div>
            <label for="contact-email" class="block text-sm font-medium text-slate-700 mb-1">Email</label>
            <input type="email" id="contact-email" name="email" required
                   class="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
          </div>
          <div>
            <label for="contact-message" class="block text-sm font-medium text-slate-700 mb-1">Üzenet</label>
            <textarea id="contact-message" name="message" required rows="4"
                      class="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"></textarea>
          </div>
          <button type="submit"
                  class="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium">
            Küldés
          </button>
        </form>

        <div id="contact-success" class="hidden text-slate-700 py-4">
          Köszönjük, az üzenet eventje bekerült a pipeline-ba. Nézd meg a dashboardot a lead megjelenéséért.
        </div>

        <p class="mt-4 text-xs text-slate-400 leading-relaxed">
          Ez egy demo form a tracking pipeline bemutatására — valódi kapcsolatfelvételhez használd a footerben található elérhetőségeket.
        </p>
      </div>
    </section>
```

- [ ] **Step 2: Add the `handleContactSubmit` function**

Add a new `<script>` block between the existing `<script src="/static/landing/tracker.js"></script>` line and the existing consent-banner script block. So it sits after `tracker.js` loads but before the banner visibility check. The final sequence near the bottom of `<body>` should read:

```html
  <script src="/static/landing/tracker.js"></script>
  <script>
    function handleContactSubmit(event) {
      event.preventDefault();
      const payload = {
        name: document.getElementById('contact-name').value,
        email: document.getElementById('contact-email').value,
        message: document.getElementById('contact-message').value,
      };
      track('form_submit', payload);
      document.getElementById('contact-form').classList.add('hidden');
      document.getElementById('contact-success').classList.remove('hidden');
    }
  </script>
  <script>
    if (!localStorage.getItem('consent_analytics')) {
      document.getElementById('banner').classList.remove('hidden');
    }
  </script>
```

- [ ] **Step 3: Copy into container and verify**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Reload. Expected:
- Contact form with three fields (Név, Email, Üzenet) and blue Küldés button.
- Submit the form with test values (e.g., "Test Name", "test@example.com", "test message").
- Form disappears; success message appears: "Köszönjük, az üzenet eventje bekerült a pipeline-ba..."
- Disclaimer text is visible below in slate-400.
- Verify in DB:
  ```bash
  docker-compose exec -T db psql -U fpcollector -d fpcollector -c "SELECT event_name, payload FROM raw_events WHERE event_name = 'form_submit' ORDER BY id DESC LIMIT 1;"
  ```
  Expected payload: `{"name": "Test Name", "email": "test@example.com", "message": "test message"}`.

- [ ] **Step 4: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add contact form with tracking-demo submit handler"
```

---

## Task 7: Footer + final end-to-end smoke test

**Files:**
- Modify: `api/static/landing/index.html`

- [ ] **Step 1: Replace `<!-- footer-section -->` with:**

```html
  <footer class="max-w-6xl w-full mx-auto px-6 py-10 mt-8 border-t border-slate-200">
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <div class="font-medium text-slate-900">Holik Balázs</div>
        <div class="text-sm text-slate-500">Marketing engineer</div>
      </div>
      <nav class="flex gap-5 text-sm">
        <a href="https://github.com/placeholder"
           onclick="track('cta_click', {label: 'footer_github'})"
           class="text-slate-600 hover:text-slate-900">GitHub</a>
        <a href="https://www.linkedin.com/in/placeholder"
           onclick="track('cta_click', {label: 'footer_linkedin'})"
           class="text-slate-600 hover:text-slate-900">LinkedIn</a>
        <a href="mailto:holikbalazs@gmail.com"
           onclick="track('cta_click', {label: 'footer_email'})"
           class="text-slate-600 hover:text-slate-900">Email</a>
      </nav>
    </div>
    <div class="mt-6 text-xs text-slate-400">
      © 2026 fp-collector. First-party data, tiszta forrásból.
    </div>
  </footer>
```

- [ ] **Step 2: Copy into container and final smoke test**

```bash
docker cp api/static/landing/index.html $(docker-compose ps -q api):/app/static/landing/index.html
```

Clear localStorage in the browser DevTools (Application → Storage → Clear site data), then reload `http://localhost:8000/`.

End-to-end verification:
1. Consent banner appears. Click `Elfogadom`. Banner disappears.
2. Scroll through all sections: Header → Hero → Features → How it works → Live dashboard promo → Contact form → Footer.
3. All 11 CTAs respond to click. For each one, either navigation happens (dashboard/GitHub) or just a tracking event fires (feature cards).
4. Submit the contact form. Form replaced by success message.
5. Navigate to `http://localhost:8000/dashboard`. Check the UTM breakdown table — `landing / hero_cta` (or whichever preset you chose) should appear with events > 0.
6. Mobile viewport (DevTools device toolbar at 375px): full page layout stacks correctly, no horizontal overflow.

Check the final DB state:

```bash
docker-compose exec -T db psql -U fpcollector -d fpcollector -c "
SELECT event_name, count(*) FROM raw_events GROUP BY event_name;
SELECT payload->>'label' AS label, count(*) FROM raw_events WHERE event_name = 'cta_click' GROUP BY label ORDER BY count(*) DESC;
SELECT count(*) FROM leads;
"
```

Expected: `page_view` ≥ 1, `cta_click` > 0 with diverse labels, `form_submit` ≥ 1, `leads` ≥ 1 (once n8n processes the form).

- [ ] **Step 3: Commit**

```bash
git add api/static/landing/index.html
git commit -m "feat(landing): add footer and complete end-to-end smoke test"
```

---

## Final Verification

- [ ] **Landing page renders all 7 sections without layout breaks at both desktop and mobile viewports.**

- [ ] **11 tracking events are reachable: page_view auto, 11 cta_click labels across header/hero/features/promo/footer, 1 form_submit with name+email+message payload.**

- [ ] **Full automated test suite still passes (no Python changes, but confirm no regression):**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/ -v
```

Expected: all Phase 1–3 tests pass.

Landing page is complete when all three verifications pass.
