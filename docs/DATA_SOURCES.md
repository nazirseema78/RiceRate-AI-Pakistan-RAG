# Data source investigation (verified 2026-11-11)

Each candidate source was checked for: reachability, rice coverage, price type, permission for automated
collection, API availability, authentication, free tier, update frequency and commercial use.
Nothing below is assumed; items that could not be verified are marked as such.

| Source | Status on 2026-11-11 | Rice coverage | Price type | Automated access | Connector |
|---|---|---|---|---|---|
| **Punjab FS&CPD** – fscpdpunjab.gop.pk/Commodities/Prices/ | Reachable (HTTP 200) | "Rice Basmati New (Kg)" only, 41 districts | Government **notified rates** (published as "Notified Rates"; stored as *retail*) | No API. `robots.txt` allows all paths for generic agents (`Content-Signal: search=yes, ai-train=no, use=reference`) | `fscpd_punjab` – **enabled**, polite HTML read (4×/day max), 0 = not reported → skipped |
| **PakDataHub** – pakdatahub.com (re-publishes **AMIS Punjab**) | Reachable; public `/v1/agri/commodities` and `/v1/agri/markets` tested | Paddy Basmati, Paddy IRRI, Paddy Kainat, Rice Basmati 385, Super Basmati New/Old, Rice IRRI, Kainat New/Old; Multan, Muzaffargarh, Bahawalpur, Rahim Yar Khan covered (data to 2026-11-10) | **Wholesale** mandi `fqp` (fair-quality price), PKR per 100 kg | Documented REST API; price endpoints need `X-API-Key` (401 without). **Free plan: 500 calls/month, 10 req/min, 1-year history.** Internal commercial use allowed; *displaying data to your own customers needs the Business plan or a written licence* | `pakdatahub` – implemented from the published docs, **disabled until `PAKDATAHUB_API_KEY` is set**; once/day, ≤9 calls/run. Not exercised live (no key available during development) |
| **World Bank Pink Sheet** – worldbank.org/en/research/commodity-markets | Reachable; monthly workbook downloaded and parsed | Rice Thai 5 %, Thai 25 %, Thai A.1, Viet Namese 5 % (`$/mt`), updated 2026-11-03 (latest month 2026M10) | **Monthly average export benchmarks** (USD/MT) | Free download; World Bank data terms (CC BY 4.0, attribution) | `worldbank_pinksheet` – **enabled**, stored as *historical*, never shown as today's rate |
| **AMIS** – amis.pk | Connection timed out | (Punjab mandi prices) | – | Not verified | Documented only; use PakDataHub |
| **PFSIS** – pfsis.fsp.gov.pk | Connection timed out | Not verified | – | No API documentation found | Documented only |
| **PAR** – par.com.pk/commodities/rice | Reachable, but a JavaScript-only app with copy and right-click disabled | Not verifiable without executing the app | – | No published API or data licence | Documented only; **not scraped**. Use authorised CSV import |

**Not claimed:** none of these sources was verified to publish *real-time intraday* quotations. FS&CPD and
AMIS publish daily, World Bank monthly. The 09:00, 12:00, 15:00 and 18:00 PKT checks only pick up whatever
the sources have published since the last check.

**Karachi buyer quotations and international daily export quotes** have no verified free automated source.
They are covered by clearly labelled synthetic demo data and the authorised CSV import (`data/imports/`).

**Phase 2 (paid):** `backend/services/market_data/providers/commercial.py` is a disabled template. No paid
provider is integrated or claimed.
