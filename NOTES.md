# NOTES.md — Renewal Cleaning Analysis

**Reference date:** 2026-08-03 (treated as "today" per assessment instructions)

---

## 1. Ambiguous-Date Rule

Slash-separated dates (e.g., `05/08/2025`) are ambiguous between DD/MM/YYYY and MM/DD/YYYY.

**Resolution:**
1. If the first number > 12 → it **must** be the day → **DD/MM/YYYY** (e.g., `25/12/2025` → Dec 25)
2. If the second number > 12 → it **must** be the day → **MM/DD/YYYY** (e.g., `07/20/2025` → Jul 20)
3. If both ≤ 12 → **genuinely ambiguous** → default to **DD/MM/YYYY** (Pakistan locale convention) and flag in issues.csv

**Rationale:** PKHosting is a Pakistani company. The DD/MM/YYYY format is the standard date convention in Pakistan. Both BillingA and BillingC produce slash-separated dates, but there is no metadata distinguishing their date conventions. Defaulting to the local convention is the most defensible choice.

**Records affected by ambiguity:** R001, R003, R004, R005, R006, R007, R009, R015, R016, R017, R021

---

## 2. Deduplication Rule

**Definition of duplicate:** Records sharing the same `(customer_id, canonical_domain, service)` tuple.

**Records identified:** R011 and R011b are duplicates:
- Same customer (C1011), same domain (amberhost.pk), same service (Hosting)
- Same amount (PKR 5,200) and same dates (2025-04-11 → 2026-08-25)
- The only difference is date formatting (one uses `11-Apr-2025`, the other `11.04.2025`) and source_system

**Resolution:** Keep R011 (first occurrence), drop R011b. Both are recorded in issues.csv.

**Rationale:** When records are identical after normalisation, keeping the first avoids arbitrary selection. Since both resolve to the same clean data, the choice is cosmetic.

---

## 3. Currency / USD Rule

**PKR records:** Amounts prefixed with `PKR`, `Rs.`, `Rs`, or bare numbers are treated as Pakistani Rupees. This is the assumed default currency for a Pakistani hosting company.

**USD record (R019):** `$45.00` — USD cannot be safely converted to PKR without a known exchange rate. Inventing a rate would be unsound.
- **Action:** Kept the numeric value (45.0) as-is. Status set to **flagged**. Excluded from the PKR renewal total.

**Ambiguous currency (R020f):** `PKR 4,600.00 USD` — contains both PKR and USD indicators. Impossible to determine the intended currency.
- **Action:** Kept the numeric value (4600.0). Status set to **flagged**. Excluded from the PKR renewal total.

---

## 4. Cancelled / Suspended Treatment

**Cancelled (R018):** Status raw value is `Cancelled - Refund`. Normalised to `cancelled`.
- This record is **kept in clean.csv** with status `cancelled` so there is a complete audit trail.
- **Excluded from the renewal total** — a cancelled service will not generate revenue.

**Suspended:** No records with "suspended" status exist in the raw data.

---

## 5. Refund Treatment

**R018:** Amount `(1,500.00)` — parentheses indicate a negative/refund amount per accounting convention.
- Parsed as **-1500.0 PKR**.
- Combined with status `Cancelled - Refund`, this confirms the record is a refund for a cancelled service.
- **Excluded from renewal total.**

---

## 6. Invalid-Date Treatment

| Record | Field         | Raw Value     | Problem                        | Action                |
|--------|---------------|---------------|-------------------------------|-----------------------|
| R012   | renews_on     | 31/02/2026    | Feb 31 does not exist          | Set to empty          |
| R013   | registered_on | 2025-02-29    | 2025 is not a leap year        | Set to empty          |
| R013b  | registered_on | 2025-13-40    | Month 13, day 40               | Set to empty          |
| R015b  | registered_on | N/A           | Placeholder                    | Set to empty          |
| R015c  | renews_on     | TBD           | Placeholder                    | Set to empty          |
| R014   | registered_on | (blank)       | Missing                        | Set to empty          |
| R015   | renews_on     | (blank)       | Missing                        | Set to empty          |

Records with missing `renews_on` cannot be included in the renewal window calculation since we don't know when they renew.

---

## 7. Domain Canonicalisation Rule

**Steps applied (in order):**
1. Strip whitespace
2. Remove protocol (`http://`, `https://`)
3. Remove trailing slash and any path
4. Lowercase
5. Remove `www.` prefix

**Rationale for stripping `www.`:** In web hosting, `www.example.com` and `example.com` almost always refer to the same service. Meaningful subdomains (e.g., `blog.example.com`) are preserved — only the `www.` prefix is removed.

**Examples:**
- `HTTPS://WWW.Zenithweb.PK/` → `zenithweb.pk`
- `http://www.crimsoncloud.pk/` → `crimsoncloud.pk`
- ` ivorycoast-hosting.pk ` → `ivorycoast-hosting.pk` (whitespace stripped)
- `quartzvps.pk/` → `quartzvps.pk`

---

## 8. Additional Anomalies Discovered

| Anomaly | Records | Details |
|---------|---------|---------|
| **ISO datetime with time** | R011c, R011d | `2025-05-02 00:00:00` and `2026-08-17 14:30:00` — time portion stripped |
| **Dot-separated dates** | R011b | `11.04.2025` — European/PK format, parsed as DD.MM.YYYY |
| **Ordinal dates** | R011d | `25th August 2026` — ordinal suffix parsed |
| **Named month dates** | R011, R011d | `11-Apr-2025`, `May 2, 2025` |
| **Pakistani Rs. with /-** | R016 | `Rs.2,500/-` — `/-` is a Pakistani formatting convention, stripped |
| **European decimal format** | R020b | `12.500,00 PKR` — dots as thousands separators, comma as decimal |
| **Garbled amount** | R020c | `PKR —500` — em-dash (U+2014) is not a minus sign; unparseable |
| **Free/Waived** | R020d, R020e | Text amounts `Free` and `Waived` → set to 0.00 |
| **No-space PKR** | R020 | `PKR12000` — no space between currency and number |
| **Mixed case status** | R003 | `active` (lowercase) vs `Active` — normalised |
| **Missing amount** | R017 | Amount field is blank |
| **Trailing blank row** | — | CSV has a blank line at the end; correctly ignored by parser |

---

## 9. Renewal Total Calculation (2026-08-03 through 2026-09-02)

### Included Renewals

| Record | Domain              | Renews On   | Amount (PKR) | Status |
|--------|---------------------|-------------|-------------|--------|
| R001   | pkhosting-demo1.pk  | 2026-08-05  | 4,500       | active |
| R002   | blueoceanvps.com    | 2026-08-15  | 3,200       | active |
| R007   | nimbustech.pk       | 2026-08-09  | 2,200       | active |
| R008   | redfoxhosting.pk    | 2026-08-20  | 4,800       | active |
| R009   | greentree.pk        | 2026-08-28  | 3,500       | active |
| R010   | paklink.pk          | 2026-08-11  | 1,800       | active |
| R011   | amberhost.pk        | 2026-08-25  | 5,200       | active |
| R011c  | thornfield.pk       | 2026-08-17  | 3,600       | active |
| R011d  | heronbay.pk         | 2026-08-25  | 4,150       | active |
| R013   | cobaltdomains.pk    | 2026-08-29  | 1,600       | active |
| R013b  | marrowhost.pk       | 2026-08-31  | 4,050       | active |
| R014   | trueline.pk         | 2026-08-18  | 3,000       | active |
| R015b  | dunestay.pk         | 2026-08-16  | 4,250       | active |
| R016   | brightpixel.pk      | 2026-09-01  | 2,500       | active |
| R020   | pinnaclecloud.pk    | 2026-08-14  | 12,000      | active |
| R020b  | ledgerhost.pk       | 2026-08-25  | 12,500      | active |
| R020d  | thistledown.pk      | 2026-08-19  | 0           | active (Free) |
| R020e  | copperkettle.pk     | 2026-08-20  | 0           | active (Waived) |
| R021   | zenithweb.pk        | 2026-08-19  | 4,900       | active |
| R022   | ivorycoast-hosting.pk | 2026-08-24 | 4,300      | active |
| R023   | quartzvps.pk        | 2026-08-27  | 3,100       | active |

**Sum: PKR 85,150.00**

### Excluded Renewals (with reasons)

| Record | Domain              | Renews On   | Amount      | Reason |
|--------|---------------------|-------------|-------------|--------|
| R003   | starlite-hosting.pk | 2026-03-10  | 6,000       | Renews **before** window (Mar 10) |
| R004   | crimsoncloud.pk     | 2025-12-25  | 2,800       | Renews **before** window (Dec 2025) |
| R005   | silverline.pk       | 2025-12-25  | 1,500       | Renews **before** window (Dec 2025) |
| R006   | oceanicweb.com      | 2026-09-08  | 5,000       | Renews **after** window (Sep 8) |
| R012   | falconweb.pk        | (empty)     | 4,000       | Missing renewal date (impossible date 31/02) |
| R015   | skywardhost.com     | (empty)     | 4,700       | Missing renewal date |
| R015c  | cinderpoint.pk      | (empty)     | 3,150       | Missing renewal date (was "TBD") |
| R017   | oaktree.pk          | 2026-10-12  | (empty)     | Renews **after** window; also missing amount |
| R018   | meridianhost.pk     | 2026-08-10  | -1,500      | **Cancelled** service with refund — excluded |
| R019   | westgate.pk         | 2026-08-22  | 45 (USD)    | **Flagged** — USD amount, cannot include in PKR total |
| R020c  | molehillvps.pk      | 2026-08-26  | (empty)     | Missing amount (garbled: `PKR —500`) |
| R020f  | hollowbrook.pk      | 2026-08-21  | 4,600       | **Flagged** — ambiguous currency (PKR+USD in same field) |

### Arithmetic

```
  4,500 + 3,200 + 2,200 + 4,800 + 3,500 + 1,800 + 5,200
+ 3,600 + 4,150 + 1,600 + 4,050 + 3,000 + 4,250 + 2,500
+ 12,000 + 12,500 + 0 + 0 + 4,900 + 4,300 + 3,100
= PKR 85,150.00
```

### Discussion

The total **PKR 85,150.00** represents the **most defensible sum** of confirmed PKR-denominated, active-status renewals due within the 30-day window.

**Key judgement calls affecting the total:**
1. **R018 excluded** (-1,500): It's cancelled with a refund. Including a refund would reduce the total to 83,650, but a cancelled service should not appear in a "renewals due" calculation.
2. **R019 excluded** (45 USD): No exchange rate is available. Including it at face value would mix currencies.
3. **R020f excluded** (4,600): Currency is ambiguous. If it's truly PKR, the total would be 89,750.
4. **R020c excluded**: Amount is unparseable due to garbled input.
5. **Free/Waived records included** (R020d, R020e): They renew within the window and have active status. Their contribution is PKR 0.

---

## 10. Status Model

| Status     | Meaning                                                  | Count |
|------------|----------------------------------------------------------|-------|
| `active`   | Service is active and expected to renew                  | 30    |
| `cancelled`| Service has been cancelled (may include refund)          | 1     |
| `flagged`  | Record requires human review (currency issues, etc.)     | 2     |

No `suspended` status was found in the raw data. The status model is intentionally minimal — additional statuses (e.g., `past_due`, `expired`) could be added if the source systems provide them.
