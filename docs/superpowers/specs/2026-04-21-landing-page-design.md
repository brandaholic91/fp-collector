# fp-collector Landing Page Technical Design

**Date:** 2026-04-21
**Status:** Approved

## 1. Scope

Replaces the Phase 1 placeholder landing page (50-line minimal hero + one CTA) at `/` with a full portfolio landing page that:

1. Explains the fp-collector project to a portfolio visitor (what it is, how it works, why first-party).
2. Demonstrates the tracking pipeline by instrumenting its own interactions — page view, 11 CTA clicks, and a form submit all flow through the live pipeline to the dashboard.

The backend is unchanged. No new API endpoints, no new Python code, no new database schema. This is a pure frontend replacement of `api/static/landing/index.html`.

## 2. Tech Choices

| Concern | Choice |
|---|---|
| Layout | Single-page, vertical scroll (~4–5 screens tall) |
| Styling | Tailwind CSS via CDN (same as dashboard) |
| Design language | Slate + blue-600 accent (consistent with dashboard) |
| Language | Hungarian |
| Tracking | Existing `tracker.js` (Phase 1), new `track()` call sites only |
| Architecture diagram | Tailwind boxes + unicode arrows (no SVG, no external image) |
| Contact form | 3 fields, tracking-demo only (no real email delivery) |
| Responsive | Mobile-first via Tailwind `md:` breakpoints |

Rationale: keep the architecture consistent with Phase 3's dashboard (Tailwind CDN, vanilla JS, no build step). A separate framework or additional tooling would fracture the project's single FastAPI-as-static-server model for zero gain.

## 3. Page Structure

Single-page vertical layout. Sections top to bottom:

```
┌────────────────────────────────────────────────────────────┐
│  Header: fp-collector logó          [Dashboard] [GitHub]   │
├────────────────────────────────────────────────────────────┤
│  Hero: tagline, subtitle, primary + secondary CTA          │
├────────────────────────────────────────────────────────────┤
│  Features: 3 value-prop cards                              │
├────────────────────────────────────────────────────────────┤
│  How it works: architecture diagram + 4-bullet explainer   │
├────────────────────────────────────────────────────────────┤
│  Live dashboard promo: "this page tracks itself" + CTA     │
├────────────────────────────────────────────────────────────┤
│  Contact form: name + email + message + disclaimer         │
├────────────────────────────────────────────────────────────┤
│  Footer: author, GitHub / LinkedIn / email links           │
└────────────────────────────────────────────────────────────┘
```

No in-page navigation menu — the page is short enough for natural scroll. The header's two links point to `/dashboard` and the external GitHub URL.

## 4. Copy (Hungarian)

### 4.1 Hero

- **H1:** `First-party data pipeline — saját kezedben az adatod`
- **Subtitle:** `Egy self-hosted MarTech referencia: collector API, PostgreSQL, n8n feldolgozás és dashboard — minden komponens a saját infrastruktúrádon fut.`
- **Primary CTA:** `Dashboard megnyitása` → `/dashboard?utm_source=landing&utm_medium=hero_cta&utm_campaign=portfolio_demo`
- **Secondary CTA:** `GitHub` → placeholder URL (filled in during implementation)

### 4.2 Features (three cards, `grid-cols-1 md:grid-cols-3`)

| Title | Description |
|---|---|
| `Saját tulajdonban lévő adat` | `A látogatói eventek a te PostgreSQL-edbe kerülnek, nem egy harmadik fél szerverére. Teljes kontroll a retention, export és törlés felett.` |
| `End-to-end self-hosted` | `Collector API + adatbázis + n8n pipeline + dashboard egyetlen Docker Compose stackben. Nem kell SaaS-előfizetés, nem kell adattovábbítás.` |
| `Consent-első, GDPR-kompatibilis` | `Minden event csak explicit user consent után kerül továbbításra és tárolásra. A consent logic kliens- és szerver-oldalon egyaránt érvényesül.` |

Each card is clickable (whole card is a `<button>` or clickable `<div>` with `onclick` → `track('cta_click', { label: '...' })`). No navigation target; the click is purely for tracking demo.

### 4.3 How it works — architecture diagram

Five-box horizontal flow (wraps to vertical on mobile):

```
[Browser] → [Collector API] → [PostgreSQL] → [n8n] → [Dashboard]
```

Each box: white background, rounded-xl, shadow-sm, slate-200 border, small label inside (the component name). Arrows between boxes are unicode `→` characters (rotated to `↓` on mobile, or use a CSS arrow via `md:` breakpoint).

Below the diagram, a short paragraph and four bullets:

> A pipeline négy különálló komponensből áll, mindegyik egy jól definiált felelősséggel. Az adat minden lépésben hitelesebb és normalizáltabb formát ölt.

- `Kliens-oldali tracker.js a landing oldalon minden user interakciót (page view, CTA kattintás, form submit) strukturált event objektumba csomagol és POST-tolja a collector API-nak.`
- `A FastAPI alapú collector endpoint szigorúan validálja, consent alapján szűri, és idempotensen tárolja a raw_events táblában.`
- `Az n8n workflow 30 másodpercenként dolgozza fel az új sorokat: dedup, source/medium enrichment, form_submit → lead routing.`
- `A dashboard 4 REST endpointról olvassa az aggregált adatokat és real-time megjeleníti a pipeline egészségét és a konverziós tölcsért.`

### 4.4 Live dashboard promo

- **H2:** `Ez az oldal saját magát méri`
- **Subtitle:** `A fenti interakcióid (page view, kattintás, esetleg űrlap) pár másodpercen belül megjelennek a live dashboardon. Nyisd meg és nézd meg saját magadat.`
- **CTA:** `Dashboard megnyitása` → `/dashboard?utm_source=landing&utm_medium=promo_cta&utm_campaign=portfolio_demo`

### 4.5 Contact form

- **H2:** `Kapcsolat`
- Three fields:
  - `Név` — `<input type="text" required>`
  - `Email` — `<input type="email" required>`
  - `Üzenet` — `<textarea required>`
- **Submit button:** `Küldés`
- **On submit:**
  - Fire `track('form_submit', { name, email, message })`.
  - Do NOT POST to any endpoint other than `/v1/events` (which `track()` already handles).
  - Show success state inline: `Köszönjük, az üzenet eventje bekerült a pipeline-ba. Nézd meg a dashboardot a lead megjelenéséért.` Replace the form body with this message.
- **Disclaimer below the form** (small, slate-400):
  `Ez egy demo form a tracking pipeline bemutatására — valódi kapcsolatfelvételhez használd a footerben található elérhetőségeket.`

### 4.6 Footer

- Author name + role: `Holik Balázs — Marketing engineer`
- Three links:
  - `GitHub` → placeholder URL
  - `LinkedIn` → placeholder URL
  - `Email` → `mailto:holikbalazs@gmail.com`
- Small copyright line: `© 2026 fp-collector. First-party data, tiszta forrásból.`

## 5. Event Tracking Map

Every interaction fires through the existing `tracker.js`. No changes to `tracker.js`. The page only adds new `onclick` / `onsubmit` handlers calling `track(eventName, payload)`.

### 5.1 Automatic

- `page_view` — fires on page load after consent (built into `tracker.js`).

### 5.2 CTA click (11 distinct labels)

| Location | `payload.label` |
|---|---|
| Header — Dashboard link | `header_dashboard` |
| Header — GitHub link | `header_github` |
| Hero — Primary CTA | `hero_dashboard` |
| Hero — Secondary (GitHub) | `hero_github` |
| Feature card 1 (Saját tulajdon) | `feature_own_data` |
| Feature card 2 (Self-hosted) | `feature_self_hosted` |
| Feature card 3 (Consent) | `feature_consent` |
| Live dashboard promo CTA | `promo_dashboard` |
| Footer — GitHub | `footer_github` |
| Footer — LinkedIn | `footer_linkedin` |
| Footer — Email | `footer_email` |

### 5.3 Form submit

- `track('form_submit', { name: <value>, email: <value>, message: <value> })`
- Payload written to `raw_events.payload` JSONB, then to `leads.payload` via n8n.

### 5.4 UTM demo trick

Internal links to `/dashboard` include UTM query parameters:

- From hero Primary CTA: `?utm_source=landing&utm_medium=hero_cta&utm_campaign=portfolio_demo`
- From live dashboard promo CTA: `?utm_source=landing&utm_medium=promo_cta&utm_campaign=portfolio_demo`
- Header Dashboard link: `?utm_source=landing&utm_medium=header&utm_campaign=portfolio_demo`

`tracker.js` already reads `utm_*` from `window.location.search` on page load, so the dashboard's own `page_view` inherits the UTM and shows up in the UTM breakdown table. This is a self-referential demo — the landing teaches the dashboard, who produced the traffic.

## 6. File Changes

| File | Action |
|---|---|
| `api/static/landing/index.html` | Complete rewrite: 50 → ~250-300 lines |
| `api/static/landing/tracker.js` | Unchanged |
| All backend files | Unchanged |

No new files. No Python changes. No database changes.

## 7. Testing Strategy

No automated tests — the backend is unchanged, so pytest scope is unchanged. Manual browser verification:

1. `http://localhost:8000/` loads with Tailwind styling applied (white cards, slate background, blue-600 accent buttons).
2. Consent banner appears on first visit (fresh localStorage); dismiss via `Elfogadom`.
3. `page_view` event appears in `raw_events` within 1–2 seconds of consent.
4. All 11 CTAs, when clicked, write a `cta_click` event with the expected `payload.label`.
5. Form submit produces a `form_submit` event; the form body is replaced with the success message inline.
6. Navigate from hero CTA to `/dashboard` — the dashboard's `page_view` carries `utm_source=landing` and appears in the UTM breakdown row (once n8n processes it).
7. Mobile viewport (375px, 768px): layout wraps gracefully; architecture diagram stacks vertically; feature cards stack.

## 8. Security

- No app-level auth; the landing is public (same as Phase 1).
- No PII stored beyond what the form user explicitly submits.
- Consent gate from Phase 1 remains intact: no tracking until `localStorage.consent_analytics === 'true'`.
- No external scripts besides Tailwind CDN (no analytics, no ads, no trackers).

## 9. Out of Scope

- **Real email delivery from the contact form.** The form is explicit tracking demo; footer has real contact channels.
- **A/B testing infrastructure.** Single page variant only.
- **SEO optimization (meta tags, OG images).** Could be a small follow-up; not required for portfolio demo.
- **Animation / scroll effects.** Clean static layout only.
- **Blog / additional pages.** Single-page landing only.
- **English or bilingual version.** Hungarian only (explicit decision).
