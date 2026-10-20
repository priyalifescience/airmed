"""The source registry (sources/registry.json): the only list of sources Airmed may collect from."""

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "sources" / "registry.json"


class SourceNotApproved(Exception):
    pass


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sources"]


def approved_source(key: str, path: Path = REGISTRY_PATH) -> dict:
    """Return the registry entry for `key`, or raise if the source is unknown or not approved."""
    sources = load_registry(path)
    src = sources.get(key)
    if src is None:
        raise SourceNotApproved(f"{key}: not in the source registry")
    if src.get("status") != "approved":
        raise SourceNotApproved(f"{key}: status is {src.get('status')!r} ({src.get('reason', 'no reason given')})")
    for field in ("endpoint", "licence", "licence_url", "attribution", "fields_kept"):
        if not src.get(field):
            raise SourceNotApproved(f"{key}: registry entry is missing {field!r}")
    return src


# "pending": a source with a working collector whose licence is awaiting the publisher's confirmation. It is never
# collected or released (approved_source refuses it), but `run all`, `check` and the release skip it quietly
# instead of failing, so a hold never breaks the weekly refresh. The entry's "reason" says why it is held.
HELD = "pending"


def held_sources(path: Path = REGISTRY_PATH) -> dict:
    """{key: reason} for every source on hold (status 'pending')."""
    return {k: s.get("reason", "") for k, s in load_registry(path).items() if s.get("status") == HELD}


def render(text: str, retrieved: str) -> str:
    """Fill the collection date into registry text ({retrieved_date}), e.g. ClinicalTrials.gov's processing date."""
    return text.replace("{retrieved_date}", (retrieved or "")[:10] or "the collection date in this file's metadata")
