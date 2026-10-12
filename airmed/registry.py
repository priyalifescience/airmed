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
