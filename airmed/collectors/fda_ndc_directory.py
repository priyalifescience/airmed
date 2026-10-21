"""US FDA National Drug Code (NDC) Directory via openFDA: one row per listed product, prescription and biological
products plus unfinished drugs (bulk active ingredients and drugs for further processing).

The openFDA search API cannot page past skip=25,000 and the directory holds about 138,000 products, so the collector
reads openFDA's official bulk file for the drug/ndc endpoint (one zipped JSON, about 27 MB), checks that it holds the
number of records its own metadata and the download index state, and keeps the product-level fields. Package rows
(package NDCs, package descriptions) are dropped; `package_count` says how many each product has.

Scope (size rule): the whole directory is ~50 MB as CSV. Over-the-counter products (~57,000: sunscreens, hand
sanitisers, cosmetics-like drugs) and allergenic extracts (~2,300) are left out, which keeps ~79,000 products (~26 MB
CSV). Kept: HUMAN PRESCRIPTION DRUG, BULK INGREDIENT, DRUG FOR FURTHER PROCESSING, VACCINE, PLASMA DERIVATIVE,
CELLULAR THERAPY, LICENSED VACCINE BULK INTERMEDIATE and any product type FDA adds later. Bulk ingredients and drugs
for further processing are where Irish manufacturing sites appear as labelers (Pfizer Ireland, Takeda Ireland ...).

Privacy: labelers are mostly companies, but a few hundred are individuals (physicians, aestheticians and sole traders
listing products under their own name, e.g. "Firstname Surname, M.D., Inc." or "Surname, Firstname"). The labeler name
is kept only when `company_or_blank` reads it as an organisation; otherwise it is blanked, `labeler_withheld` is "yes",
and a brand or generic name that repeats a word of the withheld name is blanked too. Over-blanking a small firm is the
accepted cost of never naming a person.
"""

import io
import json
import re
import zipfile

from ..http import fetch
from ..util import iso_date
from .ctgov_ireland import sponsor_or_blank
from .dete_employment_permits import looks_like_organisation
from .fda_warning_letters import EXTRA_ORG, PERSON
from .medicaid_drug_spending import LABELER_WORDS

KEY = "fda_ndc_directory"
FIELDS = ["product_id", "product_ndc", "product_type", "brand_name", "generic_name", "labeler_name", "labeler_withheld",
          "dosage_form", "route", "marketing_category", "application_number", "active_ingredients", "pharm_class",
          "dea_schedule", "finished", "package_count", "marketing_start_date", "marketing_end_date",
          "listing_expiration_date", "spl_set_id"]
DOWNLOAD_INDEX = "https://api.fda.gov/download.json"
MIN_RECORDS = 50000     # the directory holds ~138,000 products; far fewer means a broken file
EXCLUDED_TYPES = {"HUMAN OTC DRUG", "NON-STANDARDIZED ALLERGENIC", "STANDARDIZED ALLERGENIC"}

# Trade words seen in FDA labeler / recalling-firm names that none of the shared organisation lists carry.
MORE_ORG = re.compile(r"\b(?:dental|first aid|remed(?:y|ies)|safety|foods?|sales|distribut\w*|wholesale|prepack|"
                      r"europe|france|spain|america|indonesia|kgaa|se|sau|slu|s\.?l|a\.?s|s\.?\s?a|d\.?d|limitada|"
                      r"ltda|cie|enterprises|exchanges?|production|parfums|gases|minerals|oils|dollar|stores?|"
                      r"compound\w*|formulations?|unilever|bergen|oxygen|welding|isotop\w*|"
                      r"ireland|brasil|brazil|mexico|india|canada|italia|japan|korea|deutschland)\b", re.I)
# "Surname, Firstname" (optionally with a middle initial): how FDA files write some individual labelers.
INVERTED_NAME = re.compile(r"^[A-Za-z'-]+,\s+[A-Za-z'-]+(?:\s+[A-Za-z]\.?)?$")
PERSON_GROUP_MIN = 50   # a name with "Dr."/"M.D." is kept only for a large company (Dr. Reddy's: ~650 products)
PLAIN_GROUP_MIN = 10    # a multi-word name with no company word is kept when it is behind at least this many rows
STOP = {"the", "and", "of", "for", "inc", "llc", "ltd", "md", "dr", "pa", "pc", "pllc", "co", "corp", "medical",
        "professional", "corporation", "company", "a", "by", "do", "dds", "phd"}


def name_group(name: str) -> str:
    """Spelling-insensitive key for one firm's name variants: its first two words, lower case, letters and digits only."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower().replace("'", "").replace(".", ""))
    return " ".join(words[:2])


def company_or_blank(name: str, rows_in_group: int) -> str:
    """The name when it reads as an organisation, else "" (it may be a natural person)."""
    name = " ".join((name or "").split())
    if not name:
        return ""
    org = bool(sponsor_or_blank(name, "") or LABELER_WORDS.search(name) or EXTRA_ORG.search(name)
               or MORE_ORG.search(name) or looks_like_organisation(name))
    if PERSON.search(name):
        return name if org and rows_in_group >= PERSON_GROUP_MIN else ""
    if org or len(name.split()) == 1:
        return name
    if INVERTED_NAME.match(name):
        return ""
    return name if rows_in_group >= PLAIN_GROUP_MIN else ""


def name_words(name: str) -> set:
    return {w for w in re.findall(r"[a-z]{3,}", (name or "").lower()) if w not in STOP}


def mentions(text: str, words: set) -> bool:
    low = (text or "").lower()
    return any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words)


def _slim(r: dict) -> dict:
    o = r.get("openfda") or {}
    return {
        "product_id": r.get("product_id", ""), "product_ndc": r.get("product_ndc", ""),
        "product_type": r.get("product_type", ""), "brand_name": r.get("brand_name", ""),
        "generic_name": r.get("generic_name", ""), "labeler_name": r.get("labeler_name", ""),
        "dosage_form": r.get("dosage_form", ""), "route": r.get("route") or [],
        "marketing_category": r.get("marketing_category", ""), "application_number": r.get("application_number", ""),
        "active_ingredients": [[a.get("name", ""), a.get("strength", "")] for a in r.get("active_ingredients") or []],
        "pharm_class": r.get("pharm_class") or [], "dea_schedule": r.get("dea_schedule", ""),
        "finished": r.get("finished"), "package_count": len(r.get("packaging") or []),
        "marketing_start_date": r.get("marketing_start_date", ""), "marketing_end_date": r.get("marketing_end_date", ""),
        "listing_expiration_date": r.get("listing_expiration_date", ""), "spl_set_id": o.get("spl_set_id") or [],
    }


def bulk_results(endpoint: str) -> tuple:
    """(results, meta) of openFDA's single-file bulk download for drug/<endpoint>, after the count checks."""
    index = json.loads(fetch(DOWNLOAD_INDEX, timeout=120))["results"]["drug"][endpoint]
    parts = index["partitions"]
    prefix = f"https://download.open.fda.gov/drug/{endpoint}/"
    if len(parts) != 1 or not parts[0]["file"].startswith(prefix):
        raise RuntimeError(f"unexpected openFDA drug/{endpoint} download layout: {[p.get('file') for p in parts]}")
    z = zipfile.ZipFile(io.BytesIO(fetch(parts[0]["file"], timeout=600)))
    names = [n for n in z.namelist() if n.endswith(".json")]
    if len(names) != 1:
        raise RuntimeError(f"expected one JSON file in the drug/{endpoint} zip, found {names}")
    data = json.loads(z.read(names[0]))
    results = data.get("results", [])
    total = data["meta"]["results"]["total"]
    if len(results) != total or total != int(index["total_records"]):
        raise RuntimeError(f"drug/{endpoint} bulk file holds {len(results)} records; its metadata says {total}, "
                           f"the download index says {index['total_records']}")
    return results, data["meta"]


def fetch_raw() -> bytes:
    results, meta = bulk_results("ndc")
    return json.dumps({"total_in_file": len(results), "last_updated": meta.get("last_updated", ""),
                       "results": [_slim(r) for r in results]}).encode("utf-8")


def _flag(v) -> str:
    return "yes" if v is True else "no" if v is False else ""


def parse(raw: bytes, min_records: int = MIN_RECORDS) -> list:
    data = json.loads(raw)
    rows = data.get("results", [])
    if data.get("total_in_file") is not None and data["total_in_file"] != len(rows):
        raise RuntimeError(f"NDC raw file says {data['total_in_file']} products but holds {len(rows)}")
    if len(rows) < min_records:
        raise RuntimeError(f"only {len(rows)} NDC products; refusing a partial directory")
    groups = {}
    for r in rows:
        g = name_group(r.get("labeler_name"))
        groups[g] = groups.get(g, 0) + 1
    out, seen = [], set()
    for r in rows:
        pid = r.get("product_id") or ""
        if not pid or pid in seen or (r.get("product_type") or "").upper() in EXCLUDED_TYPES:
            continue
        seen.add(pid)
        raw_name = " ".join((r.get("labeler_name") or "").split())
        labeler = company_or_blank(raw_name, groups.get(name_group(raw_name), 0))
        hidden = name_words(raw_name) if raw_name and not labeler else set()
        brand, generic = (r.get("brand_name") or "").strip(), (r.get("generic_name") or "").strip()
        out.append({
            "product_id": pid,
            "product_ndc": r.get("product_ndc") or "",
            "product_type": r.get("product_type") or "",
            "brand_name": "" if mentions(brand, hidden) else brand,
            "generic_name": "" if mentions(generic, hidden) else generic,
            "labeler_name": labeler,
            "labeler_withheld": "yes" if raw_name and not labeler else "no",
            "dosage_form": r.get("dosage_form") or "",
            "route": list(r.get("route") or []),
            "marketing_category": r.get("marketing_category") or "",
            "application_number": r.get("application_number") or "",
            "active_ingredients": [" ".join(p for p in a if p) for a in r.get("active_ingredients") or []],
            "pharm_class": list(r.get("pharm_class") or []),
            "dea_schedule": r.get("dea_schedule") or "",
            "finished": _flag(r.get("finished")),
            "package_count": int(r.get("package_count") or 0),
            "marketing_start_date": iso_date(r.get("marketing_start_date") or ""),
            "marketing_end_date": iso_date(r.get("marketing_end_date") or ""),
            "listing_expiration_date": iso_date(r.get("listing_expiration_date") or ""),
            "spl_set_id": "; ".join(r.get("spl_set_id") or []),
        })
    out.sort(key=lambda x: (x["product_ndc"], x["product_id"]))
    return out
