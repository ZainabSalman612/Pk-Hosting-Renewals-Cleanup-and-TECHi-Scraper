"""
tests/test_parsers.py – Offline pytest tests for date, money, and domain parsers.

All tests are pure unit tests with no network I/O.
"""

# pyrefly: ignore [missing-import]
import pytest
from parsers import parse_date, parse_money, canonical_domain


# ============================================================================
# DATE PARSING TESTS
# ============================================================================

class TestParseDate:
    """Tests for the date parser."""

    # --- ISO format ---
    def test_iso_date(self):
        iso, problem = parse_date("2025-01-15")
        assert iso == "2025-01-15"
        assert problem is None

    def test_iso_with_time(self):
        iso, problem = parse_date("2025-05-02 00:00:00")
        assert iso == "2025-05-02"

    def test_iso_with_afternoon_time(self):
        iso, problem = parse_date("2026-08-17 14:30:00")
        assert iso == "2026-08-17"

    # --- Unambiguous slash dates ---
    def test_slash_dd_mm_yyyy_unambiguous(self):
        """25/12/2025: first > 12 → must be day → DD/MM/YYYY → Dec 25."""
        iso, problem = parse_date("25/12/2025")
        assert iso == "2025-12-25"

    def test_slash_mm_dd_yyyy_unambiguous(self):
        """12/25/2025: second > 12 → must be day → MM/DD/YYYY → Dec 25."""
        iso, problem = parse_date("12/25/2025")
        assert iso == "2025-12-25"
        assert problem is not None and "MM/DD/YYYY" in problem

    # --- Ambiguous slash dates ---
    def test_slash_ambiguous_defaults_dd_mm(self):
        """05/08/2025: both ≤ 12 → ambiguous → default DD/MM/YYYY."""
        iso, problem = parse_date("05/08/2025")
        assert iso == "2025-08-05"
        assert problem is not None and "ambiguous" in problem.lower()

    def test_slash_ambiguous_both_valid(self):
        """01/06/2025: both ≤ 12 → ambiguous."""
        iso, problem = parse_date("01/06/2025")
        assert iso == "2025-06-01"
        assert "ambiguous" in problem.lower()

    # --- Impossible dates ---
    def test_impossible_feb_31(self):
        """31/02/2026 → Feb 31 doesn't exist."""
        iso, problem = parse_date("31/02/2026")
        assert iso is None
        assert problem is not None and "impossible" in problem.lower()

    def test_impossible_feb_29_nonleap(self):
        """2025-02-29 → 2025 is not a leap year."""
        iso, problem = parse_date("2025-02-29")
        assert iso is None
        assert "impossible" in problem.lower()

    def test_impossible_iso_month_13(self):
        """2025-13-40 → month 13 is invalid."""
        iso, problem = parse_date("2025-13-40")
        assert iso is None
        assert "impossible" in problem.lower()

    # --- Blank / missing ---
    def test_blank(self):
        iso, problem = parse_date("")
        assert iso is None
        assert "blank" in problem.lower()

    def test_none_like(self):
        iso, problem = parse_date("   ")
        assert iso is None

    # --- Placeholders ---
    def test_na(self):
        iso, problem = parse_date("N/A")
        assert iso is None
        assert "placeholder" in problem.lower()

    def test_tbd(self):
        iso, problem = parse_date("TBD")
        assert iso is None
        assert "placeholder" in problem.lower()

    # --- Named month formats ---
    def test_dash_month_year(self):
        iso, problem = parse_date("11-Apr-2025")
        assert iso == "2025-04-11"

    def test_month_day_year(self):
        iso, problem = parse_date("May 2, 2025")
        assert iso == "2025-05-02"

    def test_ordinal_day(self):
        iso, problem = parse_date("25th August 2026")
        assert iso == "2026-08-25"

    def test_ordinal_1st(self):
        iso, problem = parse_date("1st January 2025")
        assert iso == "2025-01-01"

    # --- Dot-separated ---
    def test_dot_separated(self):
        iso, problem = parse_date("11.04.2025")
        assert iso == "2025-04-11"

    # --- Malformed ---
    def test_garbage(self):
        iso, problem = parse_date("not-a-date")
        assert iso is None
        assert problem is not None

    def test_partial(self):
        iso, problem = parse_date("2025-01")
        assert iso is None

    # --- Relative dates ---
    def test_relative_days_ago(self):
        iso, problem = parse_date("6 days ago")
        assert iso is not None
        assert "relative" in problem.lower()

    def test_relative_updated(self):
        iso, problem = parse_date("Updated 2 days ago")
        assert iso is not None

    def test_relative_published(self):
        iso, problem = parse_date("Published 3 days ago")
        assert iso is not None

    def test_relative_hours(self):
        iso, problem = parse_date("5 hours ago")
        assert iso is not None

    def test_relative_week(self):
        iso, problem = parse_date("1 week ago")
        assert iso is not None


# ============================================================================
# MONEY PARSING TESTS
# ============================================================================

class TestParseMoney:
    """Tests for the money parser."""

    # --- PKR with symbols ---
    def test_pkr_with_symbol(self):
        r = parse_money("PKR 4,500.00")
        assert r["amount"] == 4500.00
        assert r["currency"] == "PKR"

    def test_rs_dot_with_commas(self):
        r = parse_money("Rs. 3,200")
        assert r["amount"] == 3200.0
        assert r["currency"] == "PKR"

    def test_rs_no_space(self):
        r = parse_money("Rs.2,500/-")
        assert r["amount"] == 2500.0
        assert r["currency"] == "PKR"

    def test_pkr_no_space(self):
        r = parse_money("PKR12000")
        assert r["amount"] == 12000.0
        assert r["currency"] == "PKR"

    # --- Bare numbers ---
    def test_bare_number(self):
        r = parse_money("10000")
        assert r["amount"] == 10000.0
        assert r["currency"] == "PKR"  # defaults to PKR

    # --- USD ---
    def test_usd(self):
        r = parse_money("$45.00")
        assert r["amount"] == 45.00
        assert r["currency"] == "USD"

    # --- Parentheses (refund) ---
    def test_parentheses_refund(self):
        r = parse_money("(1,500.00)")
        assert r["amount"] == -1500.00

    # --- Blank ---
    def test_blank(self):
        r = parse_money("")
        assert r["amount"] is None
        assert "blank" in r["problem"].lower()

    def test_whitespace_only(self):
        r = parse_money("   ")
        assert r["amount"] is None

    # --- Free / Waived ---
    def test_free(self):
        r = parse_money("Free")
        assert r["amount"] == 0.0

    def test_waived(self):
        r = parse_money("Waived")
        assert r["amount"] == 0.0

    # --- Ambiguous currency ---
    def test_ambiguous_pkr_usd(self):
        r = parse_money("PKR 4,600.00 USD")
        assert r["currency"] == "AMBIGUOUS"

    # --- European format ---
    def test_european_format(self):
        r = parse_money("12.500,00 PKR")
        assert r["amount"] == 12500.00
        assert r["currency"] == "PKR"

    # --- Em-dash garbled ---
    def test_garbled_emdash(self):
        r = parse_money("PKR —500")
        assert r["amount"] is None
        assert r["problem"] is not None

    # --- Decimals ---
    def test_decimal(self):
        r = parse_money("PKR 4,500.50")
        assert r["amount"] == 4500.50

    # --- Malformed ---
    def test_nonsense(self):
        r = parse_money("abc xyz")
        assert r["amount"] is None


# ============================================================================
# DOMAIN NORMALISATION TESTS
# ============================================================================

class TestCanonicalDomain:
    """Tests for the domain normaliser."""

    def test_simple(self):
        canon, changed, prob = canonical_domain("example.com")
        assert canon == "example.com"

    def test_uppercase(self):
        canon, changed, prob = canonical_domain("EXAMPLE.COM")
        assert canon == "example.com"
        assert changed is True

    def test_www_prefix(self):
        canon, changed, prob = canonical_domain("www.example.com")
        assert canon == "example.com"
        assert changed is True

    def test_http_protocol(self):
        canon, changed, prob = canonical_domain("http://example.com")
        assert canon == "example.com"

    def test_https_protocol(self):
        canon, changed, prob = canonical_domain("https://example.com")
        assert canon == "example.com"

    def test_trailing_slash(self):
        canon, changed, prob = canonical_domain("example.com/")
        assert canon == "example.com"

    def test_path(self):
        canon, changed, prob = canonical_domain("example.com/some/path")
        assert canon == "example.com"

    def test_https_www_trailing(self):
        canon, changed, prob = canonical_domain("HTTPS://WWW.Zenithweb.PK/")
        assert canon == "zenithweb.pk"
        assert changed is True

    def test_http_www_trailing(self):
        canon, changed, prob = canonical_domain("http://www.crimsoncloud.pk/")
        assert canon == "crimsoncloud.pk"

    def test_whitespace(self):
        canon, changed, prob = canonical_domain(" ivorycoast-hosting.pk ")
        assert canon == "ivorycoast-hosting.pk"

    def test_meaningful_subdomain(self):
        """blog.example.com should NOT be stripped to example.com."""
        canon, changed, prob = canonical_domain("blog.example.com")
        assert canon == "blog.example.com"

    def test_blank(self):
        canon, changed, prob = canonical_domain("")
        assert canon == ""
        assert prob is not None

    def test_whitespace_only(self):
        canon, changed, prob = canonical_domain("   ")
        assert canon == ""

    def test_trailing_slash_domain(self):
        """quartzvps.pk/ should normalise to quartzvps.pk."""
        canon, changed, prob = canonical_domain("quartzvps.pk/")
        assert canon == "quartzvps.pk"

    def test_starlite_uppercase(self):
        canon, changed, prob = canonical_domain("STARLITE-HOSTING.PK")
        assert canon == "starlite-hosting.pk"


# ============================================================================
# EDGE CASES FROM renewals_raw.csv
# ============================================================================

class TestCSVEdgeCases:
    """Tests derived from actual anomalies found in the raw data."""

    def test_date_08_09_2026_ambiguous(self):
        """08/09/2026: both ≤ 12, ambiguous – should be flagged."""
        iso, prob = parse_date("08/09/2026")
        assert iso is not None
        assert "ambiguous" in prob.lower()

    def test_date_09_08_2026_ambiguous(self):
        """09/08/2026: both ≤ 12, ambiguous."""
        iso, prob = parse_date("09/08/2026")
        assert iso is not None
        assert "ambiguous" in prob.lower()

    def test_date_07_20_2025_unambiguous(self):
        """07/20/2025: second > 12 → MM/DD/YYYY."""
        iso, prob = parse_date("07/20/2025")
        assert iso == "2025-07-20"

    def test_date_12_10_2025_ambiguous(self):
        """12/10/2025: both ≤ 12 → ambiguous → DD/MM → Oct 12."""
        iso, prob = parse_date("12/10/2025")
        assert iso == "2025-10-12"
        assert "ambiguous" in prob.lower()

    def test_money_rs_with_slash_dash(self):
        """Rs.2,500/- → PKR 2500."""
        r = parse_money("Rs.2,500/-")
        assert r["amount"] == 2500.0
        assert r["currency"] == "PKR"

    def test_pkr_6000(self):
        r = parse_money("PKR 6,000")
        assert r["amount"] == 6000.0
