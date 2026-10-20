# Mirrors: Kaggle and Hugging Face

Copies of each release on Kaggle and Hugging Face make Airmid Éireann easy to find for students and data
scientists. Each mirror links back to the live, weekly-updated release, which stays the source of truth.

The account owner creates the dataset on each platform (we never create accounts or upload on someone's behalf
without them). Upload the CSV files and `datapackage.json` files from the release zip
(`tools/data_archive.py` builds it) and use the text below.

## Kaggle (`dataset-metadata.json`)

```json
{
  "title": "Airmid Eireann: Ireland's Open Pharma Data",
  "id": "priyalifescience/airmid-eireann-open-pharma-data",
  "subtitle": "Trials, medicines, shortages, approvals, safety, trade and research for Ireland and Europe",
  "description": "Open datasets collected from official publishers (HPRA, EMA, CSO, ClinicalTrials.gov, Eurostat, OECD, CORDIS, OpenAlex, U.S. FDA, Health Canada, MHRA, NIH), each with its source licence. Live weekly copy: https://priyalifescience.com/opendata/airmid/v1/ . Project: https://priyalifescience.com/airmed . Code: https://github.com/priyalifescience/airmed . Cite: DOI 10.5281/zenodo.23336432. Multiple licences, per file: each dataset keeps its source's licence (see each datapackage.json and catalog.json); not all are CC BY 4.0 (e.g. NIH RePORTER is ODbL 1.0; ClinicalTrials.gov, OECD and NTPF data have their own terms, listed in README.md). No personal names or contact details. Not medical advice.",
  "licenses": [{"name": "other"}],
  "keywords": ["health", "medicine", "pharmaceuticals", "clinical trials", "europe", "ireland"]
}
```

## Hugging Face dataset card (`README.md` at the top of the dataset repo)

```markdown
---
license: other
language: [en]
pretty_name: "Airmid Éireann: Ireland's Open Pharma Data"
tags: [medicine, pharmaceuticals, clinical-trials, open-data, ireland, europe]
size_categories: [100K<n<1M]
---

# Airmid Éireann: Ireland's Open Pharma Data

Open datasets on medicines, clinical trials, approvals, shortages, safety, trade, spending and research for Ireland
and Europe, collected from official publishers and released with each source's licence.

- Live, weekly-updated release: https://priyalifescience.com/opendata/airmid/v1/
- Project page: https://priyalifescience.com/airmed
- Code: https://github.com/priyalifescience/airmed
- Cite: DOI 10.5281/zenodo.23336432 (all versions)

**Licences.** Multiple licences: each dataset keeps the licence of its source (listed in `catalog.json` and each
`datapackage.json`); they are not all CC BY 4.0 (NIH RePORTER is ODbL 1.0, share-alike; ClinicalTrials.gov, OECD and
NTPF data have their own terms, and conditions are listed in `README.md`). The medicine cross-reference is CC BY 4.0.
Credit the original publisher and
"Airmid Éireann, Priya Life Science".

**Privacy.** No personal names or contact details. **Not medical advice.** FAERS counts are reports, not proof that a
medicine caused an event.
```
