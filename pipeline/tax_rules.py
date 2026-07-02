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


# --- Annual deduction allowances (Thailand, as of 2026) -----------------------
# RMF: deduct up to 30% of assessable income, capped at ฿500,000 — and that cap is
# COMBINED across retirement vehicles (RMF + SSF legacy + PVD + pension insurance),
# which this engine can't see, so treat it as an upper bound, not a guarantee.
# Thai ESG: up to 30% of income, capped at ฿300,000 (separate from the ฿500k pool).
# SSF: expired for new purchases after 2024 — no allowance for 2025+ buys.
WRAPPER_CAPS = {
    "RMF":      {"pct_income": 0.30, "cap": 500_000,
                 "note": "cap shared with SSF/PVD/pension insurance"},
    "Thai ESG": {"pct_income": 0.30, "cap": 300_000, "note": "separate from RMF pool"},
}


def allowance(wrapper, annual_income):
    """Max deductible ฿ this year for a wrapper, or None if unknown wrapper /
    income not configured (callers should then show progress without a cap)."""
    rule = WRAPPER_CAPS.get(wrapper)
    if not rule:
        return None
    if not annual_income:
        return None
    return min(rule["pct_income"] * float(annual_income), rule["cap"])


def rmf_continuity(purchase_years, current_year):
    """RMF requires buying at least every other year (no gap >1 consecutive year).
    Returns (status, message): status in {'ok', 'due', 'at_risk'}.

    - 'ok'      : bought this year already.
    - 'due'     : no purchase this year, but last year is covered — buy by Dec 31
                  to stay comfortably continuous.
    - 'at_risk' : no purchase this year OR last year — buying this year is required
                  to avoid breaching the no-2-consecutive-gap rule.
    """
    yrs = {int(y) for y in purchase_years if y}
    if not yrs:
        return "ok", ""      # no RMF held — rule not applicable
    if current_year in yrs:
        return "ok", f"{current_year} contribution made"
    if current_year - 1 in yrs:
        return "due", f"no {current_year} RMF purchase yet — buy by 31 Dec to maintain continuity"
    return "at_risk", (f"no RMF purchase in {current_year - 1} or {current_year} — "
                       f"a {current_year} purchase is required to avoid breaching the "
                       f"no-2-consecutive-year-gap rule")


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
