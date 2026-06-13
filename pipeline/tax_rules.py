"""tax_rules.py — Thai tax-wrapper lock-up logic.

Currently: the RMF "Sellable Year" (the year units can be redeemed tax-free).

RMF rule (Thailand, as of 2026): redemption is tax-free only when BOTH conditions
hold —
  (1) at least 5 years have passed since the investor's FIRST-EVER RMF purchase,
      counted day-to-day; the 5-year clock does NOT restart for later purchases, and
  (2) the investor is at least 55 years old.
So the sellable year is the LATER of (first-RMF-year + 5) and (birth-year + 55).
This is the mainstream Revenue Department / AMC interpretation (e.g. SCB, Krungsri
AM, Bangkok Bank). A new RMF bought by an investor who already meets the 5-year
holding and is (or will be) 55 inherits the same age-55 sellable year — it does not
need its own 5-year hold.

Other Thai wrappers use different rules (SSF = purchase + 10y, per-purchase, no age
test; Thai ESG = purchase + 5-8y; legacy LTF ≈ 7 calendar years) — extend here when
those need deriving rather than hand-entry.
"""
from __future__ import annotations


def rmf_sellable_year(birth_year, first_rmf_year):
    """Year an RMF lot becomes redeemable tax-free, or None if inputs are missing.

    = max(first_rmf_year + 5, birth_year + 55)  — see module docstring.
    """
    cands = []
    try:
        if first_rmf_year:
            cands.append(int(first_rmf_year) + 5)
    except (TypeError, ValueError):
        pass
    try:
        if birth_year:
            cands.append(int(birth_year) + 55)
    except (TypeError, ValueError):
        pass
    return max(cands) if cands else None
