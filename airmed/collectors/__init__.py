"""Collectors. Each module exposes KEY, FIELDS, parse(raw: bytes) -> list[dict] and fetch_raw() -> bytes."""

from . import ctgov_ireland, ema_shortages, hpra_medicines

ALL = {m.KEY: m for m in (ctgov_ireland, ema_shortages, hpra_medicines)}
