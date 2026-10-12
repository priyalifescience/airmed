# Airmid Éireann: project charter

**Airmid Éireann: Ireland's Open Pharma Data Project**, by Priya Life Science.
Data catalogue: **Tobar Airmid** ("Airmid's Well"). Tagline: *Ireland's well of open medicine data.*

## Why the name

Airmid is a healer of the Tuatha Dé Danann in early Irish mythology. In *Cath Maige Tuired*, healing herbs
grow from her brother Miach's grave, and she gathers them onto her cloak and sorts them by their powers.
This project gathers Ireland's scattered public medicine data and puts it in order.
*Éireann* means "of Ireland"; *tobar* means "well".

## Mission

Gather Ireland's public pharma data, check it, say exactly where every number comes from, and make it free
for anyone to use: students, researchers, journalists, patients and companies.

## Scope

**In:** collectors for public, keyless sources on medicines, clinical trials, approvals, shortages,
patents and exclusivity, manufacturing sites, research funding and industry statistics for Ireland and Europe;
the resulting datasets, each with its source, licence and date.

**Out:** the Priya Life Science website and its private systems; personal data; any source whose terms
do not allow redistribution (see `sources/registry.json`); medical advice.

## Principles

1. **Nothing invented.** If a value is not in the source, it is not in the dataset. Gaps stay gaps.
2. **Every number has a source:** publisher, licence and retrieval date travel with every dataset.
3. **Privacy first:** no personal names or contact details, ever.
4. **Licences respected:** a source is collected only after its licence is checked and recorded.
5. **Mistakes fixed in public**, on the project's changelog and the Priya Life Science corrections log.
6. **Secure by default:** no secrets anywhere in the project; automated scanning on every change.

## Licences

Code: EUPL-1.2. Data: each source's own licence; data compiled by Priya Life Science: CC BY 4.0.

## Governance

Maintainer: Priya Life Science (founder: Sreepriya). Changes arrive as pull requests; a maintainer reviews
each one. Adding or approving a source needs a pull request that cites the licence page.
The repository stays private until the maintainers approve making it public.

## Roadmap (targets)

| When | Milestone |
|---|---|
| October 2026 | Charter, source registry, first three collectors, secret scanning |
| December 2026 | First public release of datasets (CSV, JSON, datapackage) with a Zenodo DOI |
| Early 2027 | Repository public; versioned JSON files as a simple API |
| 2027 | More sources and countries; a rate-limited live API; outside contributors |
