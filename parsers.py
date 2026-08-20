"""
parsers.py – Reusable parsing functions for dates, money, and domains.

Each parser returns structured results suitable for clean.py issue reporting
and for unit testing.

AMBIGUOUS-DATE RULE (documented here and in NOTES.md):
    For slash-separated dates (DD/MM/YYYY vs MM/DD/YYYY):
    1. If the first number > 12 → it must be the day   → DD/MM/YYYY
    2. If the second number > 12 → it must be the day  → MM/DD/YYYY
    3. If both ≤ 12 → genuinely ambiguous.
       We default to DD/MM/YYYY (Pakistan locale) and flag the ambiguity.
"""

import re
from datetime import datetime, date, timedelta
from urllib.parse import urlparse


# ============================================================================
# DATE PARSING
# ============================================================================

def parse_date(raw: str) -> tuple[str | None, str | None]:
    """
    Parse a date string into ISO format (YYYY-MM-DD).

    Returns:
        (iso_date_str | None, problem_description | None)

    If both values are None the input was empty/blank.
    If iso_date is returned with a problem, the date was repaired/interpreted.
    """
    if not raw or not raw.strip():
        return None, "blank/missing date"

    text = raw.strip()

    # Handle non-date placeholders
    if text.upper() in ("N/A", "TBD", "NA", "-", "NONE", "NULL", ""):
        return None, f"placeholder value '{text}' – not a date"

    # ------------------------------------------------------------------
    # ISO 8601:  2025-01-15  or  2025-01-15 00:00:00
    # ------------------------------------------------------------------
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+\d{2}:\d{2}:\d{2})?$", text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _validate_ymd(y, mo, d, text)

    # ------------------------------------------------------------------
    # Slash-separated:  DD/MM/YYYY  or  MM/DD/YYYY
    # ------------------------------------------------------------------
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _resolve_slash_date(a, b, y, text)

    # ------------------------------------------------------------------
    # Dot-separated:  DD.MM.YYYY (common European/PK format)
    # ------------------------------------------------------------------
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _validate_ymd(y, mo, d, text, note="dot-separated date parsed as DD.MM.YYYY")

    # ------------------------------------------------------------------
    # Dash-Month-Year:  11-Apr-2025
    # ------------------------------------------------------------------
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{4})$", text)
    if m:
        d = int(m.group(1))
        month_str = m.group(2)
        y = int(m.group(3))
        mo = _month_name_to_num(month_str)
        if mo is None:
            return None, f"unrecognised month name '{month_str}'"
        return _validate_ymd(y, mo, d, text, note="dash-month-year format")

    # ------------------------------------------------------------------
    # "May 2, 2025" or "January 10, 2026"
    # ------------------------------------------------------------------
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})$", text)
    if m:
        month_str = m.group(1)
        d = int(m.group(2))
        y = int(m.group(3))
        mo = _month_name_to_num(month_str)
        if mo is None:
            return None, f"unrecognised month name '{month_str}'"
        return _validate_ymd(y, mo, d, text, note="'Month D, YYYY' format")

    # ------------------------------------------------------------------
    # "25th August 2026"  or  "1st January 2025"
    # ------------------------------------------------------------------
    m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]+)\s+(\d{4})$", text)
    if m:
        d = int(m.group(1))
        month_str = m.group(2)
        y = int(m.group(3))
        mo = _month_name_to_num(month_str)
        if mo is None:
            return None, f"unrecognised month name '{month_str}'"
        return _validate_ymd(y, mo, d, text, note="ordinal-day format")

    # ------------------------------------------------------------------
    # Relative dates: "6 days ago", "Updated 2 days ago", etc.
    # ------------------------------------------------------------------
    m = re.match(r"(?:updated|published)?\s*(\d+)\s+(day|hour|minute|week|month)s?\s+ago",
                 text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        return _relative_to_iso(n, unit, text)

    # ------------------------------------------------------------------
    # Fallback – unrecognised
    # ------------------------------------------------------------------
    return None, f"unrecognised date format '{text}'"


def _month_name_to_num(name: str) -> int | None:
    """Convert month name/abbreviation to number (1–12)."""
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    return months.get(name.lower())


def _validate_ymd(
    y: int, m: int, d: int, raw: str, note: str | None = None
) -> tuple[str | None, str | None]:
    """Validate year/month/day and return ISO string."""
    try:
        dt = date(y, m, d)
        problem = note  # informational note if format was unusual
        return dt.isoformat(), problem
    except ValueError:
        return None, f"impossible date (y={y}, m={m}, d={d}) from '{raw}'"


def _resolve_slash_date(
    a: int, b: int, y: int, raw: str
) -> tuple[str | None, str | None]:
    """
    Resolve DD/MM/YYYY vs MM/DD/YYYY ambiguity.

    Rules:
      1.  a > 12 → a is day, b is month  (DD/MM/YYYY)
      2.  b > 12 → b is day, a is month  (MM/DD/YYYY)
      3.  Both ≤ 12 → ambiguous; default DD/MM/YYYY (Pakistan locale), flag it.
    """
    a_could_be_month = 1 <= a <= 12
    b_could_be_month = 1 <= b <= 12

    if not a_could_be_month and not b_could_be_month:
        return None, f"impossible date – neither {a} nor {b} is a valid month in '{raw}'"

    if not a_could_be_month:
        # a must be day → DD/MM/YYYY
        d, m = a, b
        result, prob = _validate_ymd(y, m, d, raw)
        if prob and prob.startswith("impossible"):
            return result, prob
        return result, prob

    if not b_could_be_month:
        # b must be day → MM/DD/YYYY
        m, d = a, b
        result, prob = _validate_ymd(y, m, d, raw)
        note = "interpreted as MM/DD/YYYY (second value > 12)"
        return result, note if result else prob

    # Both ≤ 12: genuinely ambiguous – default to DD/MM/YYYY
    d, m = a, b
    result, prob = _validate_ymd(y, m, d, raw)
    if result:
        return result, f"ambiguous date '{raw}' – defaulted to DD/MM/YYYY (Pakistan locale)"
    # If DD/MM fails (shouldn't since both ≤ 12), try MM/DD
    m2, d2 = a, b
    result2, prob2 = _validate_ymd(y, m2, d2, raw)
    return result2, f"ambiguous date '{raw}' – DD/MM/YYYY invalid, used MM/DD/YYYY"


def _relative_to_iso(
    n: int, unit: str, raw: str
) -> tuple[str | None, str | None]:
    """Convert a relative time expression to an ISO date."""
    now = datetime.now()
    if unit == "day":
        dt = now - timedelta(days=n)
    elif unit == "hour":
        dt = now - timedelta(hours=n)
    elif unit == "minute":
        dt = now - timedelta(minutes=n)
    elif unit == "week":
        dt = now - timedelta(weeks=n)
    elif unit == "month":
        # Approximate – subtract n*30 days
        dt = now - timedelta(days=n * 30)
    else:
        return None, f"unrecognised relative unit '{unit}'"
    return dt.date().isoformat(), f"relative date '{raw}' resolved to {dt.date().isoformat()}"


# ============================================================================
# MONEY PARSING
# ============================================================================

def parse_money(raw: str) -> dict[str, object]:
    """
    Parse a messy monetary value.

    Returns:
        {
            "amount": float | None,
            "currency": "PKR" | "USD" | "AMBIGUOUS" | "NONE" | None,
            "problem": str | None,
            "action": str | None,
        }

    Rules:
    - PKR / Rs / Rs. → currency = "PKR"
    - $ → currency = "USD"
    - Both PKR and USD present → "AMBIGUOUS"
    - Parentheses (1,500.00) → negative (refund)
    - "Free" / "Waived" → amount = 0, currency = "PKR"
    - "/-" suffix is a Pakistani convention, stripped
    - Em-dash or garbled text → flagged
    - European-style "12.500,00" → interpreted as 12500.00
    """
    if not raw or not raw.strip():
        return {"amount": None, "currency": None, "problem": "blank/missing amount", "action": "set to empty"}

    text = raw.strip()

    # --- Special text values ---
    if text.lower() in ("free", "waived"):
        return {"amount": 0.0, "currency": "PKR", "problem": f"amount is '{text}'", "action": "set to 0.00"}

    # --- Detect parentheses (refund/negative) ---
    is_negative = False
    if text.startswith("(") and text.endswith(")"):
        is_negative = True
        text = text[1:-1].strip()

    # --- Detect currencies ---
    has_pkr = bool(re.search(r"PKR|Rs\.?", text, re.IGNORECASE))
    has_usd = bool(re.search(r"\$|USD", text, re.IGNORECASE))

    if has_pkr and has_usd:
        currency = "AMBIGUOUS"
    elif has_pkr:
        currency = "PKR"
    elif has_usd:
        currency = "USD"
    else:
        currency = "PKR"  # default for PKHosting context

    # --- Strip currency symbols and text ---
    cleaned = text
    cleaned = re.sub(r"PKR|Rs\.?|/-", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\$|USD", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # --- Handle em-dash or other garbled chars ---
    # The em-dash '—' (U+2014) is not a minus sign
    if "—" in cleaned or "–" in cleaned:
        return {
            "amount": None,
            "currency": currency,
            "problem": f"garbled amount containing dash character in '{raw}'",
            "action": "set to empty; flagged",
        }

    # --- Detect European-style decimal: "12.500,00" (dots as thousands, comma as decimal) ---
    m_euro = re.match(r"^([\d.]+),(\d{2})$", cleaned)
    if m_euro:
        int_part = m_euro.group(1).replace(".", "")
        dec_part = m_euro.group(2)
        try:
            amount = float(f"{int_part}.{dec_part}")
            if is_negative:
                amount = -amount
            return {
                "amount": amount,
                "currency": currency,
                "problem": f"European-style number format '{raw}'",
                "action": f"interpreted as {amount}",
            }
        except ValueError:
            pass

    # --- Standard: remove commas, parse as float ---
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.strip()

    if not cleaned:
        return {"amount": None, "currency": currency, "problem": f"no numeric value found in '{raw}'",
                "action": "set to empty"}

    try:
        amount = float(cleaned)
    except ValueError:
        return {"amount": None, "currency": currency, "problem": f"unparseable amount '{raw}'",
                "action": "set to empty; flagged"}

    if is_negative:
        amount = -amount

    problem = None
    action = None

    return {"amount": amount, "currency": currency, "problem": problem, "action": action}


# ============================================================================
# DOMAIN NORMALISATION
# ============================================================================

def canonical_domain(raw: str) -> tuple[str, bool, str | None]:
    """
    Normalise a domain to its canonical form.

    Returns:
        (canonical_domain, was_changed, problem_description | None)

    Canonicalisation rules (documented in NOTES.md):
    1.  Strip whitespace.
    2.  Strip protocol (http://, https://).
    3.  Strip trailing slashes and paths.
    4.  Lowercase.
    5.  Strip 'www.' prefix.
        Rationale: In web-hosting contexts, www.example.com and example.com
        almost always refer to the same service.  Meaningful subdomains like
        blog.example.com are preserved.
    6.  Flag empty/invalid domains.
    """
    if not raw or not raw.strip():
        return "", False, "blank/missing domain"

    original = raw.strip()
    domain = original

    # Remove protocol
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)

    # Remove trailing slash and any path
    domain = domain.split("/")[0]

    # Strip whitespace again (in case of " example.com ")
    domain = domain.strip()

    # Lowercase
    domain = domain.lower()

    # Remove www. prefix
    if domain.startswith("www."):
        domain = domain[4:]

    # Basic validation
    if not domain:
        return "", False, f"empty domain after normalisation from '{original}'"
    if "." not in domain:
        return domain, True, f"domain '{domain}' has no TLD – possibly invalid"

    changed = domain != original
    problem = None

    return domain, changed, problem
