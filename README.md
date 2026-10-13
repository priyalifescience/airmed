![Airmid Éireann: Ireland's Open Pharma Data Project](docs/airmid-banner.jpg)

# Airmid Éireann

**Ireland's Open Pharma Data Project**, by [Priya Life Science](https://priyalifescience.com/airmed).

*Ireland's well of open medicine data.* Airmid Éireann collects Ireland's public records on medicines,
clinical trials, approvals and shortages from official sources, checks them, and publishes them as open
datasets, each with its source, licence and date.

> **Status: in development.** First public data release planned for December 2026.

## What it collects

| Source key | Dataset | Publisher | Licence |
|---|---|---|---|
| `ctgov_ireland` | Clinical trials with a site in Ireland | ClinicalTrials.gov (U.S. NLM) | Public data |
| `hpra_medicines` | Human medicines authorised in Ireland | HPRA | CC BY 4.0 |
| `ema_shortages` | Medicine shortages in the EU | European Medicines Agency | Re-use with credit |
| `ema_medicines` | Human medicines evaluated by the EMA | European Medicines Agency | Re-use with credit |
| `ema_orphans` | EU orphan designations | European Medicines Agency | Re-use with credit |
| `fda_shortages` | US drug shortages | U.S. FDA (openFDA) | Public domain |
| `fda_approvals` | US original approvals since 2021 | U.S. FDA (Drugs@FDA) | Public domain |
| `hc_approvals` | Health Canada new drug approvals since 2016 | Health Canada | Open Government Licence – Canada |
| `cso_pharma_exports` | Irish pharma exports by country, monthly | Central Statistics Office | CC BY 4.0 |
| `nih_ireland` | NIH awards to organisations in Ireland | U.S. NIH | Public domain |

Full details, field descriptions, and the sources we will **not** collect and why: [`sources/registry.json`](sources/registry.json)
and [`LICENSE-DATA.md`](LICENSE-DATA.md).

## Quick start

Python 3.10+ and nothing else (standard library only).

```
python -m airmed list            # every source and its status
python -m airmed run all         # collect all approved sources into ./out
python -m airmed run hpra_medicines --out mydata
python -m airmed release --src out --dist dist/v1   # build a publishable release
```

A release adds `catalog.json` (every dataset, its licence, record count, fields and file links), a data dictionary
and a changelog. It is refused if a source is missing, a dataset shrank by more than 20%, or a contact-like value
slipped through.

Each dataset is written as CSV and JSON plus a `datapackage.json` (Frictionless Data) recording the
publisher, licence, retrieval time and file checksums.

## Safety by design

- Public, keyless APIs only. The code needs no passwords or keys and reads none.
- A collector runs only if its source is `approved` in the registry, and requests only the listed fields.
- A privacy guard refuses personal-data fields and blanks any email address or phone number.
- Secret scanning (our own scanner plus Gitleaks over the full history) runs on every push.

See [`SECURITY.md`](SECURITY.md) and [`CHARTER.md`](CHARTER.md).

## Licences

Code: [EUPL-1.2](LICENSE). Data: each source's own licence ([`LICENSE-DATA.md`](LICENSE-DATA.md)).
Nothing here is medical advice.

## The name

Airmid is a healer in early Irish mythology who gathered the healing herbs and sorted them by their powers.
*Éireann* means "of Ireland"; the data catalogue is *Tobar Airmid*, "Airmid's Well".
