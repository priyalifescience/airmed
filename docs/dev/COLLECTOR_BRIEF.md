# Brief: new Airmid collectors (v1.1), 15 Oct 2026

Repo: `D:\Claude Workfolder\airmed` (public GitHub repo priyalifescience/airmed, Python 3, **stdlib only**, no new dependencies).
Read first: `airmed/collectors/ema_shortages.py`, `airmed/collectors/ctgov_ireland.py`, `airmed/http.py`, `airmed/privacy.py`,
`airmed/cli.py`, `sources/registry.json`, `CHARTER.md`, `tests/test_airmed.py`.

## What you build
For each dataset assigned to you:
1. `airmed/collectors/<key>.py` with `KEY`, `FIELDS`, `fetch_raw() -> bytes`, `parse(raw) -> list[dict]` exactly like the
   existing collectors. Use `..http.fetch` (it enforces https and size caps). Deterministic sort order. Validate counts
   where the source states a total (raise on mismatch). Be polite: small page sizes, a short sleep between pages,
   real User-Agent is already set in http.py.
2. A registry entry as JSON in `sources/pending/<key>.json` (same shape as entries in `sources/registry.json`:
   name, publisher, endpoint, licence, licence_url, attribution, fields_kept (== FIELDS), fields_never, status
   "approved", field_docs for every field, browse_url only if an existing priyalifescience.com page fits, else omit).
   **Do NOT edit `sources/registry.json`, `airmed/collectors/__init__.py`, `cli.py`, `release.py` or any shared file** —
   the integrator merges them. Do not commit, push, or touch the website/FTP.
3. A test in `tests/test_<key>.py` that runs `parse()` on a small saved fixture `tests/fixtures/<key>.<ext>` (trim real
   output to a few records; no personal data in fixtures).
4. Run the collector live once (`python -c "from airmed.collectors import <key> as m; ..."` importing the module
   directly) and report: record count, runtime, raw size, output size estimate.

## Licence rule (binding)
Open the source's actual licence / reuse / terms page and quote the sentence that allows reuse and redistribution
(including on a commercial site and in an open dataset). Put that URL in licence_url. If reuse is unclear, NonCommercial,
ShareAlike-incompatible, or needs registration/API key you don't have: **do not build it**; report why.
Never use: NICE, BfArM, jRCT, PCRS, UMIN, WHO ICTRP, EudraGMDP, Yahoo, UN Comtrade, Lens, any personal names,
contact details, investigator names, emails, phone numbers (CHARTER). Aggregates are preferred over person-level data.

## Size rule
Each dataset's CSV must stay under ~40 MB. If a source is bigger, narrow it sensibly (e.g. date window, fields,
aggregation) and say what you chose and why.

## Report back
Per dataset: key, what it contains, licence quote + URL, records, runtime, sizes, anything you dropped and why, test
result (`python -m pytest -q tests/test_<key>.py` or `python -m unittest`).

## Addendum, 17 Oct 2026 (stage 2)
- Same rules. Registry entries go to `sources/pending/<key>.json` (the integrator merges them into registry.json).
- Tests that check the registry entry must read `sources/pending/<key>.json` if it exists, else
  `sources/registry.json["sources"][key]` (the pending file is deleted after merging).
- Use `airmed.collectors.ctgov_ireland.sponsor_or_blank`-style care: company/organisation names are fine, person names never.
- No API keys are available. If a source needs one, report it instead of building.
- Several Airmid datasets already exist (see registry.json); do not duplicate them.
