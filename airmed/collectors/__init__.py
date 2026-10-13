"""Collectors. Each module exposes KEY, FIELDS, parse(raw: bytes) -> list[dict] and fetch_raw() -> bytes."""

from . import (cso_pharma_exports, ctgov_ireland, ema_medicines, ema_orphans, ema_shortages, fda_approvals,
               fda_shortages, hc_approvals, hpra_medicines, nih_ireland)

ALL = {m.KEY: m for m in (ctgov_ireland, hpra_medicines, ema_shortages, ema_medicines, ema_orphans, fda_shortages,
                          fda_approvals, hc_approvals, cso_pharma_exports, nih_ireland)}
