"""Collectors. Each module exposes KEY, FIELDS, parse(raw: bytes) -> list[dict] and fetch_raw() -> bytes."""

from . import (cordis_health, cso_pharma_exports, ctgov_europe, ctgov_ireland, ema_medicines, ema_orphans, ema_shortages, eurostat_pharma_industry, eurostat_pharma_trade, faers_counts, fda_approvals, fda_device_recalls, fda_shortages, hc_approvals, hpra_medicines, mhra_safety_alerts, nih_ireland, oecd_pharma_spending, openalex_ireland_pharma)

ALL = {m.KEY: m for m in (ctgov_ireland, hpra_medicines, ema_shortages, ema_medicines, ema_orphans, fda_shortages, fda_approvals, hc_approvals, cso_pharma_exports, nih_ireland, cordis_health, ctgov_europe, eurostat_pharma_industry, eurostat_pharma_trade, faers_counts, fda_device_recalls, mhra_safety_alerts, oecd_pharma_spending, openalex_ireland_pharma)}
