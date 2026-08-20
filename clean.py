#!/usr/bin/env python3
"""
clean.py – PKHosting.com renewal-data cleaning pipeline.

Usage:
    python clean.py renewals_raw.csv

Outputs:
    clean.csv   – Normalised, deduplicated, validated renewal records.
    issues.csv  – Transparent log of every change, drop, merge, or flag.

Reference date for renewal analysis:  2026-08-03
"""

import csv
import re
import sys
from pathlib import Path
from typing import Any

from parsers import parse_date, parse_money, canonical_domain

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REFERENCE_DATE = "2026-08-03"

CLEAN_COLUMNS = [
    "record_id",
    "customer_id",
    "canonical_domain",
    "service",
    "billing_cycle_months",
    "amount_pkr",
    "registered_on",
    "renews_on",
    "status",
    "contact_email",
]

ISSUES_COLUMNS = ["record_id", "field", "raw_value", "problem", "action_taken"]

# Canonical status values
VALID_STATUSES = {"active", "cancelled", "suspended", "flagged"}


# ---------------------------------------------------------------------------
# Issue collector
# ---------------------------------------------------------------------------

class IssueCollector:
    """Accumulates issue rows for issues.csv."""

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def add(
        self,
        record_id: str,
        field: str,
        raw_value: str,
        problem: str,
        action_taken: str,
    ) -> None:
        self.rows.append(
            {
                "record_id": record_id,
                "field": field,
                "raw_value": raw_value,
                "problem": problem,
                "action_taken": action_taken,
            }
        )


# ---------------------------------------------------------------------------
# Status normalisation
# ---------------------------------------------------------------------------

def normalise_status(raw: str, issues: IssueCollector, record_id: str) -> str:
    """
    Map raw status to one of: active, cancelled, suspended, flagged.

    Rules:
    - Case-insensitive match.
    - 'Cancelled - Refund' and similar → 'cancelled'.
    - Anything unrecognised → 'flagged'.
    """
    stripped = raw.strip()
    lowered = stripped.lower()

    if "cancel" in lowered:
        status = "cancelled"
    elif "suspend" in lowered:
        status = "suspended"
    elif lowered == "active":
        status = "active"
    else:
        status = "flagged"
        issues.add(record_id, "status", stripped, "unrecognised status", f"flagged (original: {stripped})")

    if stripped != status and status != "flagged":
        # Log normalisation (case change, extra text, etc.)
        if stripped.lower() != status:
            issues.add(record_id, "status", stripped, "status normalised", f"set to '{status}'")

    return status


# ---------------------------------------------------------------------------
# Row processing
# ---------------------------------------------------------------------------

def process_row(row: dict[str, str], issues: IssueCollector) -> dict[str, Any] | None:
    """
    Process a single raw row.  Returns a cleaned dict or None if the row
    should be dropped entirely (empty/blank row).
    """
    record_id = row.get("record_id", "").strip()
    if not record_id:
        return None  # blank trailing row

    # --- status ---
    raw_status = row.get("status", "").strip()
    status = normalise_status(raw_status, issues, record_id)

    # --- domain ---
    raw_domain = row.get("domain", "").strip()
    canon, domain_changed, domain_problem = canonical_domain(raw_domain)
    if domain_problem:
        issues.add(record_id, "domain", raw_domain, domain_problem, f"set to '{canon}'" if canon else "set to empty")
    elif domain_changed:
        issues.add(record_id, "domain", raw_domain, "domain normalised", f"set to '{canon}'")

    # --- billing_cycle ---
    raw_cycle = row.get("billing_cycle", "").strip()
    try:
        billing_cycle_months = int(raw_cycle)
    except (ValueError, TypeError):
        billing_cycle_months = 0
        issues.add(record_id, "billing_cycle", raw_cycle, "invalid billing cycle", "set to 0")

    # --- amount ---
    raw_amount = row.get("amount", "").strip()
    money_result = parse_money(raw_amount)
    amount_pkr = money_result["amount"]
    currency = money_result["currency"]

    if money_result["problem"]:
        issues.add(record_id, "amount", raw_amount, money_result["problem"], money_result["action"])
    elif raw_amount and raw_amount != str(amount_pkr):
        # Some normalisation happened (commas removed, symbol stripped, etc.)
        if currency == "PKR":
            issues.add(record_id, "amount", raw_amount, "amount normalised", f"set to {amount_pkr}")

    if currency == "USD":
        issues.add(record_id, "amount", raw_amount, "currency is USD – cannot safely convert to PKR",
                    f"kept numeric value {amount_pkr} as-is; flagged for review")
        status = "flagged"
        issues.add(record_id, "status", raw_status, "USD amount – record flagged", "set to 'flagged'")

    if currency == "AMBIGUOUS":
        issues.add(record_id, "amount", raw_amount, "ambiguous currency (both PKR and USD mentioned)",
                    f"kept numeric value {amount_pkr} as-is; flagged for review")
        status = "flagged"
        issues.add(record_id, "status", raw_status, "ambiguous currency – record flagged", "set to 'flagged'")

    # --- dates ---
    raw_reg = row.get("registered_on", "").strip()
    reg_date, reg_problem = parse_date(raw_reg)
    if reg_problem:
        issues.add(record_id, "registered_on", raw_reg, reg_problem,
                    f"set to '{reg_date}'" if reg_date else "set to empty")
    elif raw_reg and reg_date and raw_reg != reg_date:
        issues.add(record_id, "registered_on", raw_reg, "date normalised to ISO", f"set to '{reg_date}'")

    raw_ren = row.get("renews_on", "").strip()
    ren_date, ren_problem = parse_date(raw_ren)
    if ren_problem:
        issues.add(record_id, "renews_on", raw_ren, ren_problem,
                    f"set to '{ren_date}'" if ren_date else "set to empty")
    elif raw_ren and ren_date and raw_ren != ren_date:
        issues.add(record_id, "renews_on", raw_ren, "date normalised to ISO", f"set to '{ren_date}'")

    # --- contact_email ---
    raw_email = row.get("contact_email", "").strip()
    if not raw_email:
        issues.add(record_id, "contact_email", "", "missing email", "set to empty")

    # --- Cancelled/refund handling ---
    if status == "cancelled":
        issues.add(record_id, "status", raw_status, "cancelled service", "kept in clean.csv with status 'cancelled'")

    # --- Refund indicator (negative or parenthesised amount) ---
    if amount_pkr is not None and amount_pkr < 0:
        issues.add(record_id, "amount", raw_amount, "negative amount interpreted as refund",
                    f"kept as {amount_pkr}")

    return {
        "record_id": record_id,
        "customer_id": row.get("customer_id", "").strip(),
        "canonical_domain": canon or "",
        "service": row.get("service", "").strip(),
        "billing_cycle_months": billing_cycle_months,
        "amount_pkr": amount_pkr if amount_pkr is not None else "",
        "registered_on": reg_date or "",
        "renews_on": ren_date or "",
        "status": status,
        "contact_email": raw_email,
    }


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def deduplicate(records: list[dict], issues: IssueCollector) -> list[dict]:
    """
    Deduplicate records.

    Strategy (documented in NOTES.md):
    1.  Group by (customer_id, canonical_domain, service).
    2.  Exact duplicates: keep one, log the others.
    3.  Conflicting amounts: keep the later record_id (assumed to be a
        correction from a newer billing export), flag both.
    4.  Different statuses: if one is cancelled, keep the cancelled record
        as it represents a more recent business event.
    """
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        key = (rec["customer_id"], rec["canonical_domain"], rec["service"])
        groups[key].append(rec)

    deduped: list[dict] = []
    for key, group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
            continue

        # Multiple records for the same (customer, domain, service)
        # Sort by record_id so behaviour is deterministic
        group.sort(key=lambda r: r["record_id"])

        # Check if exact duplicates (same amount, dates, status)
        def sig(r: dict) -> tuple:
            return (r["amount_pkr"], r["registered_on"], r["renews_on"], r["status"])

        unique_sigs = {sig(r) for r in group}

        if len(unique_sigs) == 1:
            # True exact duplicates – keep the first, drop others
            kept = group[0]
            deduped.append(kept)
            for dropped in group[1:]:
                issues.add(
                    dropped["record_id"], "record", "",
                    f"exact duplicate of {kept['record_id']} (same customer/domain/service/amount/dates/status)",
                    f"dropped – kept {kept['record_id']}",
                )
        else:
            # Conflicting duplicates – examine differences
            amounts = {r["amount_pkr"] for r in group}
            statuses = {r["status"] for r in group}

            if len(amounts) > 1:
                # Conflicting amounts – keep the last (most recent export)
                kept = group[-1]
                deduped.append(kept)
                for other in group[:-1]:
                    issues.add(
                        other["record_id"], "amount",
                        str(other["amount_pkr"]),
                        f"conflicting duplicate amounts: {other['amount_pkr']} vs {kept['amount_pkr']} "
                        f"for same customer/domain/service",
                        f"dropped – kept {kept['record_id']} with amount {kept['amount_pkr']}",
                    )
                issues.add(
                    kept["record_id"], "record", "",
                    f"duplicate group with conflicting amounts – this record kept as most recent",
                    "kept",
                )
            elif len(statuses) > 1:
                # Different statuses – prefer cancelled (more recent event)
                cancelled = [r for r in group if r["status"] == "cancelled"]
                if cancelled:
                    kept = cancelled[0]
                else:
                    kept = group[-1]
                deduped.append(kept)
                for other in group:
                    if other is not kept:
                        issues.add(
                            other["record_id"], "record", "",
                            f"duplicate with different status ({other['status']} vs {kept['status']})",
                            f"dropped – kept {kept['record_id']}",
                        )
            else:
                # Same amount/status but different dates – keep last, log all
                kept = group[-1]
                deduped.append(kept)
                for other in group[:-1]:
                    issues.add(
                        other["record_id"], "record", "",
                        f"duplicate of {kept['record_id']} with different dates",
                        f"dropped – kept {kept['record_id']}",
                    )

    return deduped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python clean.py <input_csv>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    issues = IssueCollector()

    # Read raw data
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_rows = list(reader)

    total_raw = len(raw_rows)

    # Process rows
    processed: list[dict] = []
    blank_rows = 0
    for raw in raw_rows:
        result = process_row(raw, issues)
        if result is None:
            blank_rows += 1
        else:
            processed.append(result)

    # Deduplicate
    cleaned = deduplicate(processed, issues)

    # Count statuses
    status_counts: dict[str, int] = {}
    for rec in cleaned:
        s = rec["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    dropped_ids = {r["record_id"] for r in processed} - {r["record_id"] for r in cleaned}
    flagged = [r for r in cleaned if r["status"] == "flagged"]

    # Write clean.csv
    clean_path = input_path.parent / "clean.csv"
    with open(clean_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CLEAN_COLUMNS)
        writer.writeheader()
        for rec in cleaned:
            writer.writerow(rec)

    # Write issues.csv
    issues_path = input_path.parent / "issues.csv"
    with open(issues_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ISSUES_COLUMNS)
        writer.writeheader()
        for row in issues.rows:
            writer.writerow(row)

    # Stdout summary
    print("=" * 60)
    print("  PKHosting Renewal Cleaning Summary")
    print("=" * 60)
    print(f"  Input file:         {input_path.name}")
    print(f"  Raw rows:           {total_raw}")
    print(f"  Blank rows:         {blank_rows}")
    print(f"  Processed:          {len(processed)}")
    print(f"  After dedup:        {len(cleaned)}")
    print(f"  Dropped (dedup):    {len(dropped_ids)}")
    print(f"  Flagged:            {len(flagged)}")
    print()
    print("  Status breakdown:")
    for status in sorted(status_counts):
        print(f"    {status:15s} {status_counts[status]}")
    print()
    print(f"  Issues logged:      {len(issues.rows)}")
    print(f"  Output:             {clean_path.name}, {issues_path.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
