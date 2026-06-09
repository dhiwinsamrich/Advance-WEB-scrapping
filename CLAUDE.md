# Anti-Fail WebScraper — CLAUDE.md

## What This Project Is

A full-stack web scraping + sitemap auditing platform.

- **Backend**: FastAPI server with a hybrid scraping engine (Requests → Selenium fallback) and a sitemap auditor that cross-references BFS-crawled URLs against the site's XML sitemap with SEO checks.
- **Frontend**: Next.js 16 dashboard with two tabs — Web Scraper and Sitemap Audit — each backed by live WebSocket log streaming.

---

## Project Structure

```
Webscraping/
├── backend/
│   ├── scraper/
│   │   ├── config.py             # Loads .env into Config class
│   │   ├── logger.py             # JSON formatter, per-session rotating log files
│   │   ├── utils.py              # URL normalization, random user-agent
│   │   ├── driver_manager.py     # Headless Chrome factory with anti-detection flags
│   │   ├── scraper.py            # Static (Requests) + dynamic (Selenium) strategies
│   │   ├── parser.py             # BeautifulSoup HTML → ExtractedContent dataclass
│   │   ├── crawler.py            # BFS orchestrator — manages queue, depth, dedup
│   │   ├── sitemap_parser.py     # Sitemap discovery + gzip/XML parsing
│   │   ├── sitemap_auditor.py    # Audit orchestration, SEO checks, AuditReport
│   │   └── main.py               # CLI entry point (direct run without server)
│   ├── server.py                 # FastAPI app — scraper + audit endpoints
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env / .env.example
│   ├── logs/                     # scrape_<id>.log, audit_<id>.log, audit_<id>_report.json
│   └── tests/
│       ├── __init__.py
│       └── test_sitemap_auditor.py
│
├── web-ui/
│   ├── app/
│   │   ├── page.tsx              # Renders Dashboard
│   │   ├── layout.tsx
│   │   └── docs/page.tsx
│   ├── components/
│   │   ├── dashboard.tsx         # Main component with Scraper / Sitemap Audit tabs
│   │   ├── audit-panel.tsx       # Sitemap audit UI (config, live logs, report)
│   │   └── ui/                   # Shadcn primitives: button, card, input
│   ├── lib/utils.ts              # cn() Tailwind merge helper
│   ├── next.config.ts
│   └── .env.local
│
├── README.md
├── DEPLOYMENT.md
└── Local_Run.txt
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend language | Python 3.10+ |
| API framework | FastAPI + Uvicorn |
| Static scraping | `requests` + `BeautifulSoup4` |
| Dynamic scraping | `selenium` 4.x + Headless Chrome |
| Driver management | `webdriver-manager` |
| Anti-detection | `fake-useragent` |
| Config | `python-dotenv` |
| Testing | `pytest` + `pytest-mock` |
| Frontend framework | Next.js 16.1.1 (App Router) |
| UI language | TypeScript 5, React 19 |
| Styling | Tailwind CSS 4 |
| Icons | Lucide React |
| Component primitives | Radix UI + CVA |

---

## How to Run

### Backend (local)
```bash
cd backend
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

### Run tests
```bash
cd backend
pytest tests/ -v
```

### Frontend (local)
```bash
cd web-ui
npm install
npm run dev
# Open http://localhost:3000
```

### Docker (backend)
```bash
cd backend
docker build -t webscraper-backend .
docker run -p 8000:8000 webscraper-backend
```

### Environment Variables

**`backend/.env`**
```
BASE_URL=https://example.com
MAX_DEPTH=2
HEADLESS_MODE=True
PAGE_LOAD_TIMEOUT=30
SCRIPT_TIMEOUT=30
IMPLICIT_WAIT=10
LOG_LEVEL=INFO
LOG_DIR=logs
```

**`web-ui/.env.local`**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Architecture — How It Works

### Scraping Pipeline

```
POST /start
  └─ background thread (daemon)
       └─ Crawler.start()  [BFS queue]
            ├─ Scraper.scrape_url()    [static: requests]
            │    └─ returns None on 403/non-200 or error
            └─ if None or JS indicators → Scraper.scrape_dynamic()  [Selenium]
                 └─ parse_html() → ExtractedContent dataclass
                      └─ logged as JSON → logs/scrape_<session_id>.log
```

### Sitemap Audit Pipeline

```
POST /audit
  └─ background thread (daemon)
       └─ SitemapAuditor.run()
            ├─ discover_sitemap_urls()    [robots.txt → /sitemap.xml fallback]
            ├─ parse_sitemap()            [handles urlset + sitemapindex, gzip, BOM]
            ├─ _crawl_bfs()              [reuses Scraper, optional Selenium fallback]
            ├─ ThreadPoolExecutor        [fetch page metadata concurrently]
            │    └─ _fetch_page_info()  [status, noindex, canonical, redirects]
            ├─ Set comparison            [covered / missing / orphaned]
            ├─ SEO checks               [noindex_in_sitemap, canonical_mismatch]
            ├─ _check_hygiene()         [duplicates, URL count, missing lastmod]
            └─ AuditReport → logs/audit_<id>_report.json
```

### API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/start` | POST | Start crawl in background thread |
| `/stop` | POST | Signal crawler to stop |
| `/status` | GET | Poll `is_running`, `current_url`, `logs_path` |
| `/download` | GET | Parse session log → return cleaned JSON array |
| `/logs` | WebSocket | Tail-follow active session log in real time |
| `/audit` | POST | Start sitemap audit |
| `/audit/stop` | POST | Signal auditor to stop |
| `/audit/status` | GET | Poll audit `is_running`, `session_id` |
| `/audit/report` | GET | Download JSON audit report |
| `/audit/logs` | WebSocket | Tail-follow active audit log |

### Session Model

Both scraper and auditor use UUID8 session IDs. A per-session rotating file handler is added to the relevant loggers at start and removed on cleanup. WebSocket endpoints dynamically pick up the latest log file path — they do not capture it once at connection time.

### Threading Safety

A `threading.Lock` (`_status_lock`, `_audit_lock`) guards all reads/writes to the global `ScraperStatus` and `AuditStatus` objects. Daemon threads mean they are killed on server shutdown without blocking.

---

## Sitemap Auditor Details

### `sitemap_parser.py`
- `discover_sitemap_urls(base_url, session)` — robots.txt `Sitemap:` lines first, falls back to `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`
- `_fetch_raw(url, session)` — detects gzip by magic bytes `0x1F 0x8B` **or** `.gz` URL suffix, decompresses transparently regardless of `Content-Type`
- `_decode_xml(raw)` — strips UTF-8/16/32 BOM, reads encoding from XML declaration
- `parse_sitemap(url, session, visited, depth)` — recurses into `<sitemapindex>` children, guarded by `MAX_SITEMAP_DEPTH=5` and a `visited` set against cycles

### `sitemap_auditor.py`
- `audit_normalize_url(url, strip_query)` — stricter than `utils.normalize_url`: collapses default ports, strips trailing slashes on non-root paths, optionally drops query string
- `SitemapAuditor._crawl_bfs()` — uses `Scraper` (not `Crawler`) so it can collect normalised visited URLs as a Python set; optionally starts Selenium for SPA detection
- `SitemapAuditor._fetch_page_info(url)` — concurrent per-page checks: HTTP status, redirect chain, `X-Robots-Tag`, `<meta name="robots">`, `<link rel="canonical">`
- `AuditReport.to_table()` / `.to_json()` — human-readable text table and machine-readable JSON; `exit_code=1` on FAIL for CI integration

### Verdict FAIL conditions
Any of: orphaned URLs, noindex in sitemap, canonical mismatches, over 50k URL limit, duplicate `<loc>` entries, any non-200 sitemap entries.

---

## Design Decisions Worth Preserving

- **Hybrid strategy**: Try `requests` first (fast), fall back to Selenium only on `None` return. Never force Selenium unless necessary — startup cost is 2-4s.
- **Session-scoped log files**: Each run writes to its own `*_<session_id>.log`. Prevents mixed-session output and makes history browsable.
- **JSON log format**: Log lines are JSON objects. The `/download` endpoint exploits this without a database — it filters for `message == "Extracted content"` entries.
- **`_stop_event` flag**: Crawler and auditor check the flag at queue-pop time, ensuring Selenium is always cleaned up via `finally: cleanup()`.
- **`Scraper` reuse in auditor**: The auditor uses `Scraper` (HTTP + parse layer), not `Crawler` (BFS + logging orchestrator). This keeps the auditor's crawl result as a plain Python set, not a side-effect in a log file.
- **CORS restricted to known origins**: Don't widen the `origins` list without a reason.

---

## Conventions

- All log entries use `extra={}` kwargs — `JSONFormatter` picks them up as top-level fields.
- `ExtractedContent` is a dataclass; use `asdict()` before logging or returning from the API.
- URL deduplication uses `normalize_url()` (scraper) or `audit_normalize_url()` (auditor — stricter). Always normalise before inserting into visited sets.
- `Scraper.__init__` accepts an optional `session: requests.Session` argument — pass the auditor's shared session to avoid creating duplicate sessions.
- Frontend API calls use `process.env.NEXT_PUBLIC_API_URL` — never hardcode `localhost:8000` in component code.
- The UI uses `cn()` from `lib/utils.ts` for all Tailwind class merging.

---

## Deployment

| Service | Target | Notes |
|---|---|---|
| Backend | Render / Railway / any Docker host | Must support headless Chrome — use the Dockerfile |
| Frontend | Vercel | Set `NEXT_PUBLIC_API_URL` to deployed backend URL |

CORS in `server.py` must include the production frontend URL. Currently set to `https://advance-web-scrapping.vercel.app`.

---

## What to Tackle Next (priority order)

1. URL validation on `/start` and `/audit` — reject non-http/https inputs
2. `robots.txt` `Crawl-delay` respect in the auditor's BFS loop
3. Rate limiting on the API (prevent concurrent scrape + audit from exhausting memory)
4. Persist `current_log_file` to disk so it survives server restarts (currently lost on restart)
5. Add a `conftest.py` with shared session fixtures for tests
