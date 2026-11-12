# 🌾 RiceRate AI Pakistan — Rice Price Intelligence RAG Chatbot

A free-first rice **price intelligence** assistant for rice mill owners and traders in **Lower Punjab, Pakistan**
(Multan, Muzaffargarh, Bahawalpur, Rahim Yar Khan), with Karachi and international market coverage.

* **Homework:** a complete, executable document-RAG notebook →
  [`notebooks/RiceRate_AI_Pakistan_RAG.ipynb`](notebooks/RiceRate_AI_Pakistan_RAG.ipynb)
* **Application:** FastAPI backend + Streamlit frontend + SQLite price database + ChromaDB vector index,
  with a hybrid **SQL + RAG** chatbot in English and Pakistani Urdu (Roman and Urdu script).

> ⚠️ **Synthetic data notice.** Everything in `data/synthetic/` and `data/documents/` is **fictional
> demonstration data**, labelled `SYNTHETIC` on every file, row, card and chatbot answer. The live
> connectors (Punjab FS&CPD notified rates, World Bank monthly benchmarks) are labelled `LIVE` / `HISTORICAL`.
> The app never relabels an old observation as "today's rate".

---

## 1. What it does

| Page | Content |
|---|---|
| **Market Overview** | Latest available Lower Punjab paddy, finished rice, broken rice and Karachi prices. Each card shows product, variety, grade, market, price, unit, observation date, freshness, source and verification status |
| **Price Comparison** | Multan / Muzaffargarh / Bahawalpur / Rahim Yar Khan vs Karachi, filtered by product type, variety, grade and date. Only identical product + grade + price category are compared, after unit normalisation (PKR/40kg → PKR/kg). Shows PKR and % differences |
| **International Market** | Export (FOB) quotations and World Bank monthly benchmarks (Pakistan, India, Thailand, Vietnam), kept separate from domestic prices, plus commentary and news |
| **RiceRate AI Chatbot** | English and Pakistani Urdu questions; sources and observation dates under every answer; chat history kept for the session |
| **News & Trends** | 7 / 15 / 30-day changes, direction labels (Rising / Falling / Stable / Mixed / Insufficient Data) and the daily market briefing |
| **Data Source Status** | Providers, last attempted / successful refresh, last observation, availability, errors, data type, and a token-protected, rate-limited manual refresh |
| **Settings (Admin)** | Add, test, enable/disable and order the AI models the chatbot uses (free now, paid later), and save data-source API keys. Token-protected; keys stay on the backend |

**Out of scope by design:** inventory, suppliers, CRM, accounting, invoicing, payroll, profit/break-even calculators, production.

## 2. Architecture

```
Streamlit frontend (frontend/)  ── HTTP/JSON only ──►  FastAPI backend (backend/)
                                                         ├─ api/routes.py            REST endpoints + validation
                                                         ├─ services/market_data/    provider interface + adapters, validation, units, ingestion
                                                         ├─ services/analytics/      SQL price queries, comparisons, trends, briefing
                                                         ├─ services/rag/            loaders, chunking, embeddings, ChromaDB, router, chatbot, optional LLM
                                                         ├─ scheduler/               APScheduler 09:00/12:00/15:00/18:00 PKT + file lock
                                                         └─ database/                SQLite schema
                         storage/ricerate.db (SQLite: exact prices)   storage/chroma_db (ChromaDB: report embeddings)
```

* **SQL answers numbers** (latest prices, comparisons, averages, changes, quotations). **RAG answers "why"**
  (reports, news, commentary). Hybrid questions use both, and the answer separates *observed facts* from *interpretation*.
* The optional LLM can never introduce a number: if a generated answer contains a figure that is not in the SQL facts
  or retrieved text, it is discarded and the retrieval-only answer is shown.

### Question router examples

| Question | Route |
|---|---|
| *Aaj Multan mein 1121 paddy ka latest available rate kya hai?* | structured (SQL) |
| *Aaj Punjab aur Karachi ke rice rates mein kya farq hai?* | structured (SQL comparison) |
| *Pichlay 7 din mein 1121 rice ka rate barha hai ya kam hua?* | structured (SQL 7-day change + direction) |
| *Karachi mein rice rates kyun change ho rahay hain?* | hybrid (SQL changes + retrieved reports) |
| *Latest available rice market report ka summary do.* | RAG |

## 3. Data sources (Phase 1, free-first)

The full investigation is in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

| Provider key | Source | Default |
|---|---|---|
| `synthetic_demo` | Fictional demo prices, Karachi buyer quotations and news (`data/synthetic/`) | on |
| `fscpd_punjab` | Punjab FS&CPD daily **notified rates** — "Rice Basmati New" by district (public page, robots.txt allows) | on |
| `worldbank_pinksheet` | World Bank Pink Sheet **monthly** rice benchmarks (Thai 5 %/25 %/A.1, Vietnamese 5 %), CC BY 4.0 | on |
| `pakdatahub` | AMIS Punjab **wholesale** mandi prices (paddy and rice) via PakDataHub API — free plan, needs a key | off until `PAKDATAHUB_API_KEY` is set |
| `csv_import` | Your **authorised** CSV files in `data/imports/` (template: `data/samples/price_import_template.csv`) | on |
| `commercial` | Phase 2 paid-provider template (`MarketDataProvider` interface) — not implemented | off |

AMIS (amis.pk) and PFSIS timed out during verification, and PAR has no API or data licence, so they are
listed on the status page as documented-only. **No CAPTCHA, login or website restriction is bypassed.**

## 4. Windows + VS Code setup (beginner steps)

1. **Install Python 3.12 or newer** from <https://www.python.org/downloads/> and tick *"Add python.exe to PATH"*.
   This project was tested with Python 3.14.
2. **Install Git** from <https://git-scm.com/download/win> and **VS Code** from <https://code.visualstudio.com/>.
3. In VS Code install the **Python** and **Jupyter** extensions (Extensions panel, `Ctrl+Shift+X`).
4. Open the project folder: *File → Open Folder…*, then open a terminal: *Terminal → New Terminal* (PowerShell).
5. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks the script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.
   Then choose the interpreter in VS Code: `Ctrl+Shift+P` → *Python: Select Interpreter* → `.venv`.
6. Install the dependencies (CPU-only PyTorch first, it is much smaller):

   ```powershell
   python -m pip install --upgrade pip
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```

7. Create your local settings file (never commit it):

   ```powershell
   Copy-Item .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Paste the printed value after `ADMIN_TOKEN=` in `.env`. Optionally add a free `PAKDATAHUB_API_KEY`.

## 5. Run it

Use **two terminals**, both with the virtual environment activated and opened in the project folder.

**Terminal 1 — FastAPI backend**

```powershell
uvicorn backend.main:app --reload --port 8000
```

* API docs: <http://127.0.0.1:8000/docs> · Health: <http://127.0.0.1:8000/api/health>
* On first start it loads the synthetic data, checks the enabled live sources, downloads the embedding model
  (~90 MB, once) and builds the vector index in the background. This takes about a minute.

**Terminal 2 — Streamlit frontend**

```powershell
streamlit run frontend/streamlit_app.py
```

Open <http://localhost:8501>. The sidebar shows *"Backend connected"* when the frontend can reach the API.

**Jupyter notebook (homework)**

```powershell
jupyter notebook notebooks/RiceRate_AI_Pakistan_RAG.ipynb
```

Or open the `.ipynb` in VS Code and click **Run All**, with the `.venv` kernel selected. To execute it headless:

```powershell
jupyter nbconvert --to notebook --execute --inplace notebooks/RiceRate_AI_Pakistan_RAG.ipynb
```

**Optional free local LLM.** Install [Ollama](https://ollama.com), run `ollama pull llama3.2`, then set
`LLM_PROVIDER=openai_compatible` in `.env`. Without it, the chatbot and the notebook give retrieval-only,
source-grounded answers.

**Regenerate the synthetic documents:** `python scripts/generate_synthetic_data.py`
**Rebuild the notebook from source:** `python scripts/build_notebook.py`

## 6. Settings: AI models and API keys

Open **Settings (Admin)** in the app and enter your `ADMIN_TOKEN`. There are two tabs:

**AI models (chatbot)**
1. Choose a ready-made template. Free: Ollama (local, no key), Groq, OpenRouter `:free` models, Google Gemini.
   Paid: OpenAI, Anthropic Claude. Or choose *Custom* for any other OpenAI-compatible server.
2. Paste the API key, click **List models** to see the exact model ids the provider offers now, pick one and click **Add**.
3. Open the provider and click **Test connection**. This sends a one-word test message.
4. Set the **priority**: the chatbot tries the lowest number first and falls back to the next one if a provider fails.
   Put free models first and paid ones later as a backup, or switch paid ones off until you need them.
   Adding a paid provider asks for an explicit confirmation.

With no model enabled, the chatbot still answers from the price database and documents (retrieval-only).
Any AI answer that contains a number not found in the sources is rejected, whichever provider produced it.

**Compare models**: type a question (or pick a sample), tick the models, and see each answer side by side with
its time, tier and whether the AI answer was accepted. The retrieval-only answer is shown as the baseline.
Disabled models can be compared too, so you can try a paid model before switching it on.

**Data-source API keys**: PakDataHub (AMIS Punjab wholesale prices) and the Phase 2 paid market-data provider.

Where it is stored: `storage/provider_settings.json` on the backend. The file is git-ignored, like `.env`, so it is never
committed. Values saved there override `.env`. The browser only ever sees the last 4 characters of a key.
Free-tier limits and model names are set by each provider and change over time, so check them on the provider's site.

The same actions are available as API endpoints (admin token required): `GET /api/admin/settings`,
`POST/PUT/DELETE /api/admin/llm/providers[/{id}]`, `POST /api/admin/llm/providers/{id}/test`,
`POST /api/admin/llm/models`, `POST /api/admin/llm/compare`, `PUT /api/admin/data-source-keys`. `GET /api/llm/status` (no token) shows the active order without keys.

**Adding a provider that is not OpenAI-compatible later:** add a new `chat_completion`-style function in
`backend/services/rag/llm.py` and select it by the provider's `preset`. Everything else (storage, fallback order, the
Settings page, the number check) stays the same.

## 7. Scheduled price checks

* APScheduler runs source checks at **09:00, 12:00, 15:00 and 18:00 Pakistan Standard Time** (`SCHEDULER_HOURS`)
  while the backend is running.
* **Duplicate prevention:** with several workers (`uvicorn --workers 4`), only the process that acquires
  `storage/scheduler.lock` starts the scheduler, and a second lock stops manual and scheduled runs from overlapping.
  Duplicate observations are rejected by a content hash.
* A scheduled check **does not guarantee a new price**. If a source has not published, the last observation keeps
  its original timestamp. Per-source politeness windows apply (PakDataHub once/20 h to stay inside 500 calls a month,
  World Bank once a day).
* **Production options**
  * Dedicated scheduler service: set `SCHEDULER_ENABLED=false` for the API and run `python -m backend.scheduler.run`
    as its own long-running service (for example with NSSM on Windows, or systemd / Docker `restart: always` on Linux).
  * Or Windows Task Scheduler: call `python -m backend.scheduler.run --once` at 09:00, 12:00, 15:00 and 18:00.

## 8. API endpoints

`GET /api/health` · `/api/products` · `/api/markets` · `/api/prices/latest` · `/api/prices/history` ·
`/api/prices/compare` · `/api/prices/changes` · `/api/prices/direction` · `/api/karachi/quotations` ·
`/api/international/prices` · `/api/news/latest` · `/api/market/briefing` · `/api/sources/status` ·
`/api/llm/status` · `POST /api/chat` · `POST /api/admin/refresh` (header `X-Admin-Token`, rate-limited) · admin settings endpoints (section 6)

All inputs are validated with Pydantic and FastAPI query constraints, and all SQL uses parameter binding.

## 9. Tests

```powershell
python -m pytest -q                 # 68 automated tests (isolated temp DB, offline embeddings, no network)
python tests/frontend_smoke.py      # needs the backend running: renders all 7 Streamlit pages + one chat round-trip
```

The tests cover API responses, validation, unit conversion, refused currency conversion, missing prices,
timestamps and freshness, history queries, duplicate records, market comparison, RAG loading/chunking/retrieval,
source attribution, synthetic labelling, routing, numeric grounding, admin auth and rate limiting, and provider
failures (a failing connector stores nothing and logs the error).

## 10. Security

* `.env`, databases, vector indexes, logs, virtual environments and `data/imports/` (private business data)
  are git-ignored. `.env.example` contains placeholders only.
* Credentials stay on the backend (`.env` or the git-ignored `storage/provider_settings.json`). API responses only show
  the last 4 characters of a key, and provider error messages are scrubbed of the key.
* External connectors use timeouts, bounded retries, rate limiting and a descriptive User-Agent.
* Retrieved documents and web pages are treated as **untrusted data**: the LLM prompt tells the model to ignore
  instructions inside them, and generated numbers are checked against the sources.

## 11. Project structure

```
frontend/          streamlit_app.py, pages/ (7 pages), components/ (API client, UI)
backend/           main.py, config.py, api/, models/, schemas/, services/{market_data,rag,news,analytics}, database/, scheduler/
notebooks/         RiceRate_AI_Pakistan_RAG.ipynb   (homework notebook, executed)
data/synthetic/    fictional prices, quotations and news used to seed SQLite
data/documents/    fictional PDF / CSV / Excel / TXT reports used by RAG
data/samples/      CSV import template
scripts/           generate_synthetic_data.py, build_notebook.py
tests/             pytest suite + frontend smoke test
docs/              DATA_SOURCES.md
```

## 12. Limitations

* Demo prices are synthetic. Real decisions need verified sources (enable PakDataHub, import authorised broker lists).
* FS&CPD publishes a single rice item (notified retail Basmati), so it is never compared with wholesale or paddy prices.
* No verified free source for Karachi buyer quotations or daily FOB quotes was found. These come from CSV import or synthetic data.
* `all-MiniLM-L6-v2` is English-centric; Roman Urdu is handled through a glossary-based query expansion.
* The app describes observed movements only. It never forecasts prices.
