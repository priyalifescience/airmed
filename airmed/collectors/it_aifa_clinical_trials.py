"""Italy (AIFA): clinical trials of medicines assessed in Italy (OsSC, the national clinical trials observatory).

AIFA's open data page "Sperimentazioni Cliniche" (https://www.aifa.gov.it/sperimentazioni-cliniche) publishes three
zipped CSVs of trials in OsSC since the second half of 2018:
- sc_approvate.zip: "On-going", approved by both AIFA (competent authority) and the coordinating ethics committee,
  with no end reported;
- sc_concluse.zip: "Concluse", approved and reported as ended in Italy, with the reasons when it ended early;
- sc_non_approvate.zip: "non approvate/ritirate", rejected by AIFA or the ethics committee, or withdrawn by the
  applicant before assessment.
AIFA does not publish phase 1 trials run only in adults (as in the EU Clinical Trials Register). The CSV inside each
zip is named after its extraction date (e.g. 20250103_sc_approvate.csv), kept as `data_date`. Since 31 January 2025
new trials are submitted through the EU CTIS, so these files cover the OsSC era and are expected to change little.

The source has one row per trial and participating centre. We publish one record per trial and file, with the
centres as a list ("CENTRE NAME [Region]") and the distinct regions; the trial-level fields repeat on every source
row and are taken from the first row (therapeutic areas are collected from all rows).

Privacy: the files name no investigators (the glossary describes centres "where the principal investigator
works", but only the centre name is published). The sponsor's contact e-mail (CONTATTO_PROMOTORE) is never kept.
Sponsor and applicant are organisations (all ~1,000 distinct values were checked on 2026-10-21; none is a person);
hospital and organisation names are kept. Values are as published (Italian labels kept, "-" for "not given" turned
into an empty value, dates converted from yyyy/mm/dd to ISO). The source has "?" where the original text had
apostrophes or accented letters; this is how AIFA publishes it.
"""

import csv
import io
import json
import re
import zipfile

from ..http import fetch
from .it_aifa_reimbursed_medicines import clean, decode, it_date

KEY = "it_aifa_clinical_trials"
FIELDS = ["eudract_number", "aifa_file", "title", "study_name", "phase", "condition_technical", "condition",
          "therapeutic_areas", "aifa_decision", "aifa_decision_date", "ethics_decision", "ethics_decision_date",
          "withdrawal_date", "paediatric", "adults", "elderly", "female", "male", "coordinating_centre",
          "coordinating_centre_region", "participating_centres", "participating_regions",
          "participating_centres_count", "sponsor", "applicant", "concluded", "end_date_regular", "end_date_early",
          "early_end_safety", "early_end_efficacy", "early_end_quality", "not_started", "aifa_authorisation_revoked",
          "ethics_opinion_withdrawn", "early_end_other_reasons", "data_date"]
BASE = "https://drive.aifa.gov.it/farmaci/"
FILES = {"sc_approvate": "On-going", "sc_concluse": "Concluse", "sc_non_approvate": "non approvate/ritirate"}
MIN_TRIALS = {"sc_approvate": 500, "sc_concluse": 500, "sc_non_approvate": 50}
# source column -> our field ("date" columns converted to ISO)
TRIAL_COLUMNS = [
    ("TITOLO_STUDIO", "title", ""), ("NOME_STUDIO", "study_name", ""), ("FASE", "phase", ""),
    ("CONDIZIONE_CLINICA_TECNICO", "condition_technical", ""), ("CONDIZIONE_CLINICA", "condition", ""),
    ("VALUTAZIONE_AC", "aifa_decision", ""), ("DATA_VAL_AC", "aifa_decision_date", "date"),
    ("VALUTAZIONE_CEC", "ethics_decision", ""), ("DATA_VAL_CEC", "ethics_decision_date", "date"),
    ("RITIRO_DOMANDA_VALUTAZIONE", "withdrawal_date", "date"), ("ETA_PEDIATRICA", "paediatric", ""),
    ("ADULTI", "adults", ""), ("ANZIANI", "elderly", ""), ("FEMMINE", "female", ""), ("MASCHI", "male", ""),
    ("CENTRO_COORDINATORE", "coordinating_centre", ""),
    ("REGIONE_CENTRO_COORDINATORE", "coordinating_centre_region", ""), ("PROMOTORE", "sponsor", ""),
    ("RICHIEDENTE", "applicant", ""), ("SC_CONCLUSA", "concluded", ""),
    ("DATA_CONCL_IT_REGOLARE", "end_date_regular", "date"), ("DATA_CONCL_IT_ANTICIPATA", "end_date_early", "date"),
    ("SICUREZZA", "early_end_safety", ""), ("EFFICACIA", "early_end_efficacy", ""),
    ("QUALITA_IMP", "early_end_quality", ""), ("SC_NON_INIZIATA", "not_started", ""),
    ("REVOCA_AUTORIZZAZIONE", "aifa_authorisation_revoked", ""), ("REVOCA_PU", "ethics_opinion_withdrawn", ""),
    ("ALTRI_MOTIVI", "early_end_other_reasons", ""),
]
REQUIRED = ["NUMERO_EUDRACT", "TITOLO_STUDIO", "FASE", "AREA_TERAPEUTICA", "CENTRO_PARTECIPANTE",
            "REGIONE_CENTRO_PARTECIPANTE", "PROMOTORE"]


def fetch_raw() -> bytes:
    """{file stem: {"name": csv name inside the zip, "text": csv text}} as JSON."""
    out = {}
    for stem in FILES:
        z = zipfile.ZipFile(io.BytesIO(fetch(BASE + stem + ".zip", timeout=180)))
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise RuntimeError(f"AIFA {stem}.zip: expected one CSV, found {names}")
        out[stem] = {"name": names[0], "text": decode(z.read(names[0]))}
    return json.dumps(out, ensure_ascii=False).encode("utf-8")


def _v(s: str) -> str:
    v = clean(s)
    return "" if v == "-" else v


def parse_file(stem: str, name: str, text: str) -> list:
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    cols = [clean(c) for c in reader.fieldnames or []]
    reader.fieldnames = cols
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise RuntimeError(f"AIFA {stem}: column(s) {missing} missing (got {cols})")
    m = re.match(r"(\d{4})(\d{2})(\d{2})", name.rsplit("/", 1)[-1])
    data_date = f"{m[1]}-{m[2]}-{m[3]}" if m else ""
    trials = {}
    for r in reader:
        eudract = _v(r.get("NUMERO_EUDRACT"))
        if not eudract:
            continue
        t = trials.get(eudract)
        if t is None:
            t = {"eudract_number": eudract, "aifa_file": FILES[stem]}
            for col, field, kind in TRIAL_COLUMNS:
                v = _v(r.get(col))
                t[field] = it_date(v) if kind == "date" else v
            t.update(therapeutic_areas=[], participating_centres=[], participating_regions=[], data_date=data_date)
            trials[eudract] = t
        area = _v(r.get("AREA_TERAPEUTICA"))
        if area and area not in t["therapeutic_areas"]:
            t["therapeutic_areas"].append(area)
        centre, region = _v(r.get("CENTRO_PARTECIPANTE")), _v(r.get("REGIONE_CENTRO_PARTECIPANTE"))
        if centre:
            label = f"{centre} [{region}]" if region else centre
            if label not in t["participating_centres"]:
                t["participating_centres"].append(label)
        if region and region not in t["participating_regions"]:
            t["participating_regions"].append(region)
    out = []
    for t in trials.values():
        t["participating_regions"].sort()
        t["participating_centres_count"] = len(t["participating_centres"])
        out.append({f: t.get(f, "") for f in FIELDS})
    return out


def parse(raw: bytes, min_trials: dict = None) -> list:
    data = json.loads(raw)
    min_trials = MIN_TRIALS if min_trials is None else min_trials
    out = []
    for stem in FILES:
        rows = parse_file(stem, data[stem]["name"], data[stem]["text"])
        if len(rows) < min_trials.get(stem, 0):
            raise RuntimeError(f"AIFA {stem}: only {len(rows)} trials (expected at least {min_trials[stem]})")
        out.extend(rows)
    out.sort(key=lambda r: (r["eudract_number"], r["aifa_file"]))
    return out
