# PKHosting Renewal Cleanup & TECHi Scraper

Assessment submission for TechAbout Python Developer role.

---

## Setup

### Requirements
- **Python 3.10+** (tested with 3.14)
- **OS:** Windows (also compatible with macOS/Linux)

### Installation

```bash
pip install pytest requests beautifulsoup4 lxml
```

No other dependencies are needed. All core logic uses the Python standard library.

### Project Structure

```
renewals_raw.csv        # Input data (self created)
clean.py                # Part A – renewal cleaning pipeline
parsers.py              # Reusable date, money, and domain parsers
techi_audit.py          # Part B – TECHi.com metadata scraper
tests/
  __init__.py
  test_parsers.py       # Offline pytest tests for parsers
clean.csv               # Output – cleaned renewals
issues.csv              # Output – issue log
techi_articles.csv      # Output – scraped article metadata
NOTES.md                # Analysis and judgement documentation
README.md               # This file
.techi_cache/           # Disk cache for scraper (auto-created)
```

---

## Part A — Renewal Cleaning

### Usage

```bash
python clean.py renewals_raw.csv
```

### Outputs

| File         | Purpose                                              |
|--------------|------------------------------------------------------|
| `clean.csv`  | 33 normalised, deduplicated renewal records          |
| `issues.csv` | 95 logged issues (every change, drop, merge, flag)   |
| stdout       | Human-readable summary with row counts and statuses  |

### clean.csv Columns

| Column               | Type    | Description                        |
|----------------------|---------|------------------------------------|
| `record_id`          | string  | Original record identifier         |
| `customer_id`        | string  | Customer identifier                |
| `canonical_domain`   | string  | Normalised domain (lowercase, no www/protocol) |
| `service`            | string  | Service type (Hosting, VPS, SSL, Domain .pk)   |
| `billing_cycle_months` | int   | Billing cycle in months            |
| `amount_pkr`         | float   | Amount in PKR (or raw numeric for flagged records) |
| `registered_on`      | date    | ISO 8601 registration date         |
| `renews_on`          | date    | ISO 8601 renewal date              |
| `status`             | string  | One of: active, cancelled, flagged |
| `contact_email`      | string  | Contact email address              |

### issues.csv Columns

| Column        | Description                                    |
|---------------|------------------------------------------------|
| `record_id`   | Which record the issue belongs to              |
| `field`       | Which field was affected                       |
| `raw_value`   | The original value before processing           |
| `problem`     | Description of the issue                       |
| `action_taken`| What the cleaner did about it                  |

---

## Part B — TECHi Scraper

### Usage

```bash
python techi_audit.py
```

### URL Discovery

1. Fetches `https://techi.com/robots.txt`
2. Extracts the `Sitemap:` directive → `https://www.techi.com/sitemap_index.xml`
3. Parses the sitemap index to find `post-sitemap*.xml` child sitemaps
4. Parses child sitemaps to collect article URLs
5. Filters to likely article URLs (single-slug paths, no category/tag/tool pages)
6. Selects up to 20 URLs

No article paths are hardcoded. Discovery is entirely driven by the sitemap.

### robots.txt Handling

- Fetched and parsed using `urllib.robotparser.RobotFileParser`
- Every article URL is checked with `can_fetch()` before scraping
- If robots.txt cannot be fetched, the scraper aborts rather than blindly scraping

### Rate Limiting

- **1.0 second delay** between HTTP requests (deterministic `time.sleep`)
- Sequential processing only — no parallel requests
- 429 responses trigger an additional 5-second backoff

### User-Agent

```
PKHostingAuditBot/1.0 (TechAbout assessment project; contact: techi-audit@pkhosting-demo.example)
```

Identifies the project and provides a contact identifier. Does not impersonate a browser.

### Disk Cache

- **Location:** `.techi_cache/` in the project root
- **Behaviour:** All HTTP responses (robots.txt, sitemaps, article pages) are cached on first fetch
- **Cache key:** SHA-256 hash of the URL (first 16 chars)
- **Index:** `.techi_cache/index.json` maps URLs to cache filenames for debugging
- **Clearing:** Delete the `.techi_cache/` directory to force re-fetch

Subsequent runs are near-silent — no network requests if the cache is populated.

### Failure Handling

The scraper handles gracefully:
- Timeout, connection error, DNS error
- HTTP 404, 403, 429, 5xx
- Malformed HTML
- Missing title, author, category, date
- Unexpected date formats

One bad page does not crash the run. Missing metadata is represented as empty strings.

### Metadata Extraction

Priority order:
1. **JSON-LD** (`@type: Article`) — most reliable for headline, datePublished, author, articleSection
2. **Open Graph meta tags** — fallback for title, date, author
3. **`<title>` tag** — final fallback for title
4. **Breadcrumb JSON-LD** — fallback for category

**Author handle:** Extracted from the author URL pattern `/@handle/` exposed by the site. Not fabricated from display names.

**Dates:** ISO datetime strings (e.g., `2026-08-19T23:24:43.152Z`) are normalised to `YYYY-MM-DD`. Relative dates (e.g., "6 days ago") are resolved against the current datetime.

---

## Decisions

### Date Ambiguity
Slash-separated dates where both values ≤ 12 are defaulted to DD/MM/YYYY (Pakistan locale). See [NOTES.md](NOTES.md) §1.

### Deduplication
R011 and R011b are exact duplicates after normalisation (same customer, domain, service, amount, dates). R011 is kept, R011b is dropped. See [NOTES.md](NOTES.md) §2.

### USD Handling
R019 (`$45.00`) is flagged rather than converted. No exchange rate is invented. See [NOTES.md](NOTES.md) §3.

### Ambiguous Currency
R020f (`PKR 4,600.00 USD`) mentions both currencies. Flagged for human review.

### Cancelled/Refund
R018 is kept in clean.csv with status `cancelled` for audit trail but excluded from the renewal revenue total.

### Free/Waived
R020d (`Free`) and R020e (`Waived`) are set to 0.00 PKR and included as active renewals.

### Garbled Amount
R020c (`PKR —500`) contains an em-dash (U+2014), not a minus sign. The amount is unparseable and set to empty.

---

## Data Quality

### Anomalies Beyond the Brief

| Anomaly                      | Records          | Handling                                |
|------------------------------|------------------|-----------------------------------------|
| ISO datetime with time       | R011c            | Time portion stripped                   |
| Dot-separated dates          | R011b            | Parsed as DD.MM.YYYY                    |
| Ordinal suffix in dates      | R011d            | `25th August 2026` → `2026-08-25`      |
| Rs. with /- suffix           | R016             | `Rs.2,500/-` → 2500.0                  |
| European decimal notation    | R020b            | `12.500,00` → 12500.00                 |
| Em-dash in amount            | R020c            | Flagged as garbled                      |
| No-space PKR prefix          | R020             | `PKR12000` → 12000.0                   |
| Mixed-case statuses          | R003             | Normalised to lowercase                 |
| Placeholder dates            | R015b (N/A), R015c (TBD) | Set to empty              |

---

## Testing

```bash
pytest -q
```

All 63 tests pass. Tests are fully offline — no network requests.

### Test Coverage

| Module         | Tests                                                       |
|----------------|-------------------------------------------------------------|
| Date parser    | ISO, slash (ambiguous/unambiguous), dot, named-month, ordinal, relative, impossible, blank, placeholders |
| Money parser   | PKR symbols, Rs., commas, decimals, USD, parentheses, Free/Waived, European format, garbled, blank |
| Domain parser  | Protocol, www, uppercase, trailing slash, paths, whitespace, subdomains, blank |
| CSV edge cases | Specific values from renewals_raw.csv                       |

---

## Tradeoffs

1. **csv module over pandas:** The dataset has 34 rows. pandas would add a heavy dependency for minimal benefit. The csv module provides full control over encoding and edge cases.

2. **Simple file-based cache:** A directory of hashed files is easy to inspect, clear, and debug. No external cache library needed.

3. **Sequential scraping:** Simpler than async/parallel, and the 1 req/sec rate limit means parallelism wouldn't help anyway.

4. **DD/MM/YYYY default:** A single consistent rule is more defensible than guessing per-row. The Pakistan locale convention is documented and traceable.

5. **No automatic USD conversion:** Inventing an exchange rate would introduce silent error. Flagging for human review is more honest.

---

## Future Improvements

1. **Configuration file:** Move rules (date convention, status mappings, skip patterns) to a YAML/JSON config file for easier tuning.

2. **Exchange rate lookup:** Integrate a public exchange rate API to convert USD amounts when a rate is available.

3. **Source system metadata:** If billing system conventions are documented (e.g., "BillingA always uses DD/MM"), use per-source date parsing rules to eliminate ambiguity.

4. **Scraper scheduling:** Add a CLI flag for cache TTL so stale pages are re-fetched after N days.

5. **Structured logging:** Use Python's logging module with JSON output for production log aggregation.

6. **Type checking:** Add `py.typed` marker and run `mypy --strict` in CI.

7. **Integration tests:** Add a test that runs `clean.py` end-to-end on a fixture CSV and asserts output shape.
