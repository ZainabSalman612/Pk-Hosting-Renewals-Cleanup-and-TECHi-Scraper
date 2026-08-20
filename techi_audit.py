#!/usr/bin/env python3
"""
techi_audit.py – Polite TECHi.com metadata scraper.

Discovers article URLs from robots.txt → sitemap, respects robots.txt,
rate-limits to ≤ 1 req/sec, caches all HTTP responses to disk, and
extracts structured metadata from up to 20 published articles.

Usage:
    python techi_audit.py

Outputs:
    techi_articles.csv

Cache directory:
    .techi_cache/   (delete to force re-fetch)
"""

import csv
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://www.techi.com"
ROBOTS_URL = "https://techi.com/robots.txt"
USER_AGENT = "PKHostingAuditBot/1.0 (TechAbout assessment project; contact: techi-audit@pkhosting-demo.example)"
REQUEST_DELAY = 1.0  # seconds between requests
MAX_ARTICLES = 20
CACHE_DIR = Path(".techi_cache")
TIMEOUT = 15  # seconds

OUTPUT_COLUMNS = ["url", "slug", "title", "category", "author_handle", "date_text", "date_iso"]

# Patterns to skip (not article pages)
SKIP_PATTERNS = [
    r"/category/", r"/tag/", r"/author/", r"/@[^/]+/$",
    r"/search/", r"/login", r"/admin", r"/wp-admin",
    r"/page/", r"/cart/", r"/checkout/", r"/my-account/",
    r"/feed/", r"/topic-sitemap/", r"/tools/", r"/learn/",
    r"/markets/stocks/", r"/analysts/", r"/leaders/", r"/products/",
    r"/quote/", r"/register/", r"/dashboard/", r"/assistant/",
    r"/brain/", r"/messages/", r"/forgot-password/", r"/reset-password/",
    r"\.(jpg|jpeg|png|gif|webp|svg|pdf|mp4|mp3|css|js)$",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("techi_audit")


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _cache_key(url: str) -> str:
    """Deterministic filename-safe hash of a URL."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def cache_get(url: str) -> str | None:
    """Return cached response body, or None."""
    path = CACHE_DIR / f"{_cache_key(url)}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def cache_put(url: str, body: str) -> None:
    """Write response body to cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(url)}.txt"
    path.write_text(body, encoding="utf-8")
    # Also store the URL → hash mapping for debugging
    index = CACHE_DIR / "index.json"
    mapping: dict = {}
    if index.exists():
        try:
            mapping = json.loads(index.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    mapping[url] = str(path.name)
    index.write_text(json.dumps(mapping, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# HTTP fetching (with cache and rate limiting)
# ---------------------------------------------------------------------------

_last_request_time = 0.0


def fetch(url: str, session: requests.Session) -> str | None:
    """
    Fetch a URL with caching, rate limiting, and error handling.
    Returns the response body as text, or None on failure.
    """
    global _last_request_time

    # Check cache first
    cached = cache_get(url)
    if cached is not None:
        log.debug("Cache hit: %s", url)
        return cached

    # Rate limit
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)

    try:
        log.info("Fetching: %s", url)
        resp = session.get(url, timeout=TIMEOUT)
        _last_request_time = time.time()

        if resp.status_code == 429:
            log.warning("Rate limited (429) on %s – backing off 5s", url)
            time.sleep(5)
            resp = session.get(url, timeout=TIMEOUT)
            _last_request_time = time.time()

        if resp.status_code >= 400:
            log.warning("HTTP %d for %s", resp.status_code, url)
            return None

        body = resp.text
        cache_put(url, body)
        return body

    except requests.exceptions.Timeout:
        log.warning("Timeout fetching %s", url)
        return None
    except requests.exceptions.ConnectionError as e:
        log.warning("Connection error fetching %s: %s", url, e)
        return None
    except requests.exceptions.RequestException as e:
        log.warning("Request error fetching %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

def load_robots(session: requests.Session) -> RobotFileParser | None:
    """Fetch and parse robots.txt. Returns parser or None."""
    body = fetch(ROBOTS_URL, session)
    if body is None:
        log.error("Could not fetch robots.txt – aborting to avoid scraping disallowed paths")
        return None

    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp


def find_sitemap_url(robots_body: str) -> str | None:
    """Extract Sitemap URL from robots.txt body."""
    for line in robots_body.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    return None


def is_allowed(rp: RobotFileParser, url: str) -> bool:
    """Check if the URL is allowed for our User-Agent."""
    return rp.can_fetch(USER_AGENT, url)


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------

def parse_sitemap_index(body: str) -> list[str]:
    """Parse a sitemap index XML and return child sitemap URLs."""
    urls = []
    try:
        root = ET.fromstring(body)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for sitemap in root.findall("sm:sitemap", ns):
            loc = sitemap.find("sm:loc", ns)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    except ET.ParseError as e:
        log.warning("Failed to parse sitemap index XML: %s", e)
    return urls


def parse_sitemap(body: str) -> list[str]:
    """Parse a sitemap XML and return page URLs."""
    urls = []
    try:
        root = ET.fromstring(body)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        for url_elem in root.findall("sm:url", ns):
            loc = url_elem.find("sm:loc", ns)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    except ET.ParseError as e:
        log.warning("Failed to parse sitemap XML: %s", e)
    return urls


def is_article_url(url: str) -> bool:
    """Heuristic: is this URL likely a published article?"""
    parsed = urlparse(url)
    path = parsed.path

    # Must have a slug-like path (at least one segment)
    segments = [s for s in path.strip("/").split("/") if s]
    if len(segments) == 0:
        return False

    # Skip if it matches non-article patterns
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return False

    # Article URLs on TECHi typically have a single slug segment: /slug-name/
    # Multi-segment paths are often tools, categories, etc.
    if len(segments) == 1:
        return True

    return False


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def extract_slug(url: str) -> str:
    """Derive slug from article URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    segments = path.split("/")
    return segments[-1] if segments else ""


def extract_metadata(url: str, html: str) -> dict[str, str]:
    """
    Extract article metadata from HTML using multiple sources:
    1. JSON-LD structured data (most reliable)
    2. Open Graph meta tags
    3. HTML elements (title, breadcrumbs)
    """
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {
        "url": url,
        "slug": extract_slug(url),
        "title": "",
        "category": "",
        "author_handle": "",
        "date_text": "",
        "date_iso": "",
    }

    # --- JSON-LD ---
    jsonld_data = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "Article":
                jsonld_data = data
                break
        except (json.JSONDecodeError, TypeError):
            continue

    if jsonld_data:
        meta["title"] = _clean_title(jsonld_data.get("headline", ""))

        # Category from articleSection
        section = jsonld_data.get("articleSection", "")
        if section:
            meta["category"] = section

        # Author handle from author URL
        authors = jsonld_data.get("author", [])
        if isinstance(authors, dict):
            authors = [authors]
        if authors:
            author_url = authors[0].get("url", "")
            handle = _extract_handle(author_url)
            if handle:
                meta["author_handle"] = handle

        # Date
        published = jsonld_data.get("datePublished", "")
        if published:
            meta["date_text"] = published
            meta["date_iso"] = _iso_date(published)

    # --- Fallback: Open Graph ---
    if not meta["title"]:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            meta["title"] = _clean_title(og_title["content"])

    if not meta["date_iso"]:
        pub_time = soup.find("meta", property="article:published_time")
        if pub_time and pub_time.get("content"):
            meta["date_text"] = pub_time["content"]
            meta["date_iso"] = _iso_date(pub_time["content"])

    if not meta["author_handle"]:
        author_meta = soup.find("meta", property="article:author")
        if author_meta and author_meta.get("content"):
            handle = _extract_handle(author_meta["content"])
            if handle:
                meta["author_handle"] = handle

    # --- Fallback: <title> tag ---
    if not meta["title"]:
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            meta["title"] = _clean_title(title_tag.string)

    # --- Fallback: breadcrumbs for category ---
    if not meta["category"]:
        breadcrumb_ld = None
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
                    breadcrumb_ld = data
                    break
            except (json.JSONDecodeError, TypeError):
                continue
        if breadcrumb_ld:
            items = breadcrumb_ld.get("itemListElement", [])
            if len(items) >= 2:
                meta["category"] = items[1].get("name", "")

    # --- Relative date handling ---
    if not meta["date_iso"] and meta["date_text"]:
        meta["date_iso"] = _parse_relative_date(meta["date_text"])

    # Look for visible relative date in page markup
    if not meta["date_iso"]:
        time_elem = soup.find("time")
        if time_elem:
            dt_attr = time_elem.get("datetime", "")
            text = time_elem.get_text(strip=True)
            if dt_attr:
                meta["date_text"] = text or dt_attr
                meta["date_iso"] = _iso_date(dt_attr)
            elif text:
                meta["date_text"] = text
                meta["date_iso"] = _parse_relative_date(text)

    return meta


def _clean_title(raw: str) -> str:
    """Remove site suffix from title (e.g., ' | TECHi')."""
    title = raw.strip()
    # Remove common suffixes
    for suffix in [" | TECHi", " - TECHi", " — TECHi"]:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title


def _extract_handle(url: str) -> str:
    """Extract author handle from URL like https://www.techi.com/@zoha/"""
    m = re.search(r"/@([^/]+)", url)
    if m:
        return m.group(1)
    return ""


def _iso_date(raw: str) -> str:
    """Convert a datetime string to YYYY-MM-DD."""
    if not raw:
        return ""

    # ISO 8601 with timezone
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(raw.replace("+00:00", "Z").replace("+0000", "Z"), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Try removing timezone offset manually
    m = re.match(r"(\d{4}-\d{2}-\d{2})T", raw)
    if m:
        return m.group(1)

    # Named month formats
    for fmt in ["%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return ""


def _parse_relative_date(text: str) -> str:
    """Convert 'X days ago', 'Updated 6 hours ago', etc. to ISO date."""
    m = re.search(r"(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago", text, re.IGNORECASE)
    if not m:
        return ""
    n = int(m.group(1))
    unit = m.group(2).lower()
    now = datetime.now()
    if unit == "second":
        dt = now - timedelta(seconds=n)
    elif unit == "minute":
        dt = now - timedelta(minutes=n)
    elif unit == "hour":
        dt = now - timedelta(hours=n)
    elif unit == "day":
        dt = now - timedelta(days=n)
    elif unit == "week":
        dt = now - timedelta(weeks=n)
    elif unit == "month":
        dt = now - timedelta(days=n * 30)
    else:
        return ""
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# URL discovery pipeline
# ---------------------------------------------------------------------------

def discover_article_urls(session: requests.Session, rp: RobotFileParser) -> list[str]:
    """
    Discover article URLs through:
    1. robots.txt → Sitemap reference
    2. Sitemap index → child sitemaps
    3. Child sitemaps → article URLs
    """
    # Get robots.txt body from cache
    robots_body = cache_get(ROBOTS_URL) or fetch(ROBOTS_URL, session) or ""
    sitemap_url = find_sitemap_url(robots_body)

    if not sitemap_url:
        log.warning("No Sitemap found in robots.txt, trying default")
        sitemap_url = f"{BASE_URL}/sitemap_index.xml"

    # Fetch sitemap index
    index_body = fetch(sitemap_url, session)
    if not index_body:
        log.error("Could not fetch sitemap index")
        return []

    child_sitemaps = parse_sitemap_index(index_body)
    log.info("Found %d child sitemaps", len(child_sitemaps))

    # Filter to post sitemaps only (skip category, page, etc.)
    post_sitemaps = [
        s for s in child_sitemaps
        if "post-sitemap" in s or "news-sitemap" in s
    ]

    if not post_sitemaps:
        # Fall back to all sitemaps
        post_sitemaps = child_sitemaps

    log.info("Using %d post sitemaps", len(post_sitemaps))

    all_urls: list[str] = []
    for sm_url in post_sitemaps:
        if len(all_urls) >= MAX_ARTICLES * 3:
            break  # We have enough candidates
        sm_body = fetch(sm_url, session)
        if sm_body:
            urls = parse_sitemap(sm_body)
            all_urls.extend(urls)

    # Filter to likely article URLs
    article_urls = [u for u in all_urls if is_article_url(u)]
    log.info("Found %d candidate article URLs", len(article_urls))

    # Further filter by robots.txt
    allowed_urls = [u for u in article_urls if is_allowed(rp, u)]
    log.info("%d URLs allowed by robots.txt", len(allowed_urls))

    return allowed_urls[:MAX_ARTICLES]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=" * 50)
    log.info("TECHi Article Metadata Scraper")
    log.info("=" * 50)
    log.info("User-Agent: %s", USER_AGENT)
    log.info("Rate limit: %.1f req/sec", 1.0 / REQUEST_DELAY)
    log.info("Cache dir:  %s", CACHE_DIR.resolve())
    log.info("")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    # 1. Load robots.txt
    rp = load_robots(session)
    if rp is None:
        log.error("Aborting: robots.txt unavailable")
        return

    # 2. Discover URLs
    urls = discover_article_urls(session, rp)
    if not urls:
        log.error("No article URLs discovered")
        return

    log.info("Will scrape %d articles", len(urls))
    log.info("")

    # 3. Fetch and extract metadata
    articles: list[dict[str, str]] = []
    for i, url in enumerate(urls, 1):
        log.info("[%d/%d] %s", i, len(urls), url)
        html = fetch(url, session)
        if html is None:
            log.warning("  Skipping – could not fetch")
            continue

        try:
            meta = extract_metadata(url, html)
            articles.append(meta)
            log.info("  title: %s", meta["title"][:80] if meta["title"] else "(none)")
            log.info("  category: %s, author: @%s, date: %s",
                     meta["category"] or "(none)",
                     meta["author_handle"] or "(none)",
                     meta["date_iso"] or "(none)")
        except Exception as e:
            log.warning("  Error extracting metadata: %s", e)
            continue

    # 4. Write CSV
    output_path = Path("techi_articles.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for art in articles:
            writer.writerow(art)

    log.info("")
    log.info("=" * 50)
    log.info("Wrote %d articles to %s", len(articles), output_path)
    log.info("Cache directory: %s", CACHE_DIR.resolve())
    log.info("=" * 50)


if __name__ == "__main__":
    main()
