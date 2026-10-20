# Data licences

**Code** in this repository is licensed under the European Union Public Licence v1.2 (`LICENSE`).

**Data** produced by the collectors keeps the licence of its source: there are **multiple licences, one per
dataset**, and they are not all CC BY 4.0. Each dataset's `datapackage.json` names the publisher, the licence, a link
to the licence, the attribution to use and any licence notes (conditions or disclaimers the publisher requires to be
passed on, e.g. the ClinicalTrials.gov, NTPF, Eurostat and Oireachtas terms). The full, current list is
`sources/registry.json` and each release's `catalog.json`; the table below shows the first datasets only.

| Dataset | Publisher | Licence | Attribution |
|---|---|---|---|
| `ctgov_ireland` | U.S. National Library of Medicine | [ClinicalTrials.gov Terms and Conditions](https://clinicaltrials.gov/about-site/terms-conditions) (international copyright outside the US) | Source: ClinicalTrials.gov, a U.S. Government database of the U.S. National Library of Medicine, with the processing date and the modifications (see `datapackage.json`). |
| `ema_shortages` | European Medicines Agency | Re-use, commercial or not, with acknowledgement in each copy, [EMA legal notice](https://www.ema.europa.eu/en/about-us/about-website/legal-notice) | Source: European Medicines Agency (EMA). |
| `hpra_medicines` | Health Products Regulatory Authority | [CC BY 4.0](https://data.gov.ie/dataset/medicines-authorised-or-transfer-pending-products) | Source: Health Products Regulatory Authority (HPRA), CC BY 4.0. |
| `ema_medicines` | European Medicines Agency | Re-use, commercial or not, with acknowledgement in each copy, [EMA legal notice](https://www.ema.europa.eu/en/about-us/about-website/legal-notice) | Source: European Medicines Agency (EMA). |
| `ema_orphans` | European Medicines Agency | Re-use, commercial or not, with acknowledgement in each copy, [EMA legal notice](https://www.ema.europa.eu/en/about-us/about-website/legal-notice) | Source: European Medicines Agency (EMA). |
| `fda_shortages` | U.S. FDA (openFDA) | Public domain, [openFDA terms](https://open.fda.gov/terms/) | Source: U.S. Food and Drug Administration, openFDA. Not endorsed by the FDA. |
| `fda_approvals` | U.S. FDA (Drugs@FDA) | Public domain, [openFDA terms](https://open.fda.gov/terms/) | Source: U.S. Food and Drug Administration, Drugs@FDA via openFDA. Not endorsed by the FDA. |
| `hc_approvals` | Health Canada | [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) | Contains information licensed under the Open Government Licence – Canada. |
| `cso_pharma_exports` | Central Statistics Office, Ireland | [CC BY 4.0](https://www.cso.ie/en/aboutus/whoweare/copyrightpolicy/) | Source: Central Statistics Office, Ireland (table TSM10), CC BY 4.0. |
| `nih_ireland` | U.S. National Institutes of Health | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1.0/) (share-alike), as declared by NIH on catalog.data.gov | Source: NIH RePORTER, U.S. National Institutes of Health. Licensed under ODbL 1.0. Extracted and filtered to Irish organisations by Airmid Éireann; this derived database is also made available under ODbL 1.0. |

Data compiled by Priya Life Science itself (for example, checked site locations) will be released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), credited to "Airmid Éireann, Priya Life Science".

Sources marked `blocked` in `sources/registry.json` are never collected or published here, and the
registry says why. Sources marked `pending` have a collector but are held (not collected, not released) until the
publisher confirms the licence; the registry entry's `reason` says why.

Nothing here is medical advice.
