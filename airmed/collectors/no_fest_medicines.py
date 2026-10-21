"""Norway: FEST (Forskrivnings- og ekspedisjonsstøtte), the national medicines file for e-prescribing, one row per
medicine package (varenummer) with ATC, active substances, current pharmacy prices, reimbursement and generic
substitution group.

Source: Direktoratet for medisinske produkter (DMP, formerly the Norwegian Medicines Agency), FEST "Rekvirent"
download, version 2.5.1 (M30 message): https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/
fest/festfiler/fest251.zip (~15 MB zip, one ~120 MB XML), updated about twice a month. Licence NLOD 2.0 (data.norge.no
catalogue; DMP: "Systemleverandører kan fritt benytte informasjonen i FEST ... i henhold til Norsk lisens for offentlige
data (NLOD)").

What is used from the XML (catalogues KatLegemiddelpakning, KatLegemiddelMerkevare, KatVirkestoff, KatRefusjon,
KatByttegruppe): one row per OppfLegemiddelpakning (~10,800 active packages), with the brand product it points to
(LegemiddelMerkevare: brand name, company, reference product, routes, substances), substance names (Virkestoff:
English name where given, else Norwegian), reimbursement groups (Refusjonsgruppe: group number such as "R05CB13_1" and
legal basis such as "§5-14 §2") and the substitution group (Byttegruppe code and name).
Not used: interactions (KatInteraksjon), dosing texts, warnings (KatVarselSlv), conditions (KatVilkar), dose packs
(KatLegemiddeldose), trade goods (KatHandelsvare), the "Institusjon" file with in-house hospital products, and the
veterinary file.

Prices: each package lists dated prices by type (AUP = pharmacy retail price, AIP = pharmacy purchase price,
Refusjonspris = reimbursement price, Trinnpris = stepped price). The price valid on the FEST extract date
(HentetDato) is kept for each type; a price that only starts later is not used. Prices are NOK as published.
For the few packages with several Pakningsinfo blocks (kits), the first block gives brand, size and DDD.
Labels are Norwegian as published (DN attributes). The company is an organisation; FEST holds no personal data in
the fields kept.
"""

import io
import xml.etree.ElementTree as ET
import zipfile

from ..http import fetch

KEY = "no_fest_medicines"
FIELDS = ["fest_date", "varenr", "ean", "atc_code", "atc_name", "name_form_strength", "brand_name", "company",
          "reference_product", "product_type", "prescription_group", "dosage_form", "routes", "active_substances",
          "pack_size", "pack_unit", "pack_type", "ddd", "ddd_unit", "marketing_date", "temporarily_unavailable_from",
          "black_triangle", "aup_nok", "aip_nok", "reimbursement_price_nok", "step_price_nok", "aup_valid_from",
          "reimbursed", "reimbursement_groups", "reimbursement_basis", "substitution_group",
          "substitution_group_name"]
URL = ("https://www.dmp.no/globalassets/documents/om-oss/distribusjon-av-legemiddeldata/fest/festfiler/fest251.zip")
M30 = "{http://www.kith.no/xmlstds/eresept/m30/2014-12-01}"
F = "{http://www.kith.no/xmlstds/eresept/forskrivning/2014-12-01}"
PRICE_TYPES = {"AUP": "aup_nok", "AIP": "aip_nok", "Refusjonspris": "reimbursement_price_nok",
               "Trinnpris": "step_price_nok"}
MIN_PACKAGES = 7000    # ~10,800 packages; far fewer means a broken download


def fetch_raw() -> bytes:
    return fetch(URL, timeout=300)


def _t(el, path: str) -> str:
    x = el.find(path)
    return (x.text or "").strip() if x is not None and x.text else ""


def _a(el, path: str, name: str) -> str:
    x = el.find(path)
    return (x.get(name) or "").strip() if x is not None else ""


def _f(path: str) -> str:
    return "/".join(F + p for p in path.split("/"))


def _num(v: str):
    if not v:
        return ""
    x = float(v)
    return int(x) if x == int(x) else x


def _price_now(prices: list, day: str) -> dict:
    """{type: (from, price)} for the price of each type valid on `day` (ISO dates compare as strings)."""
    best = {}
    for typ, price, start, end in prices:
        if start and start <= day and (not end or end > day):
            if typ not in best or start > best[typ][0]:
                best[typ] = (start, price)
    return best


def parse(raw: bytes, min_packages: int = MIN_PACKAGES) -> list:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if len(names) != 1:
            raise RuntimeError(f"FEST zip should hold one XML file, holds {names}")
        subst, subst_str, brands, reimb, subgroups, packs, fest_date = {}, {}, {}, {}, {}, [], ""
        with z.open(names[0]) as f:
            for _, el in ET.iterparse(f):   # the stdlib parser does not fetch external entities
                tag = el.tag
                if tag == M30 + "HentetDato":
                    fest_date = (el.text or "").strip()[:10]
                elif tag == M30 + "OppfVirkestoff":
                    v = el.find(F + "Virkestoff")
                    if v is not None:
                        subst[_t(v, F + "Id")] = _t(v, F + "NavnEngelsk") or _t(v, F + "Navn")
                    s = el.find(F + "VirkestoffMedStyrke")
                    if s is not None:
                        subst_str[_t(s, F + "Id")] = _t(s, F + "RefVirkestoff")
                    el.clear()
                elif tag == M30 + "OppfLegemiddelMerkevare":
                    b = el.find(F + "LegemiddelMerkevare")
                    if b is not None:
                        brands[_t(b, F + "Id")] = {
                            "brand_name": _t(b, F + "Varenavn"),
                            "company": _t(b, _f("ProduktInfo/Produsent")),
                            "reference_product": _t(b, _f("ProduktInfo/Referanseprodukt")),
                            "routes": [x.get("DN", "").strip() for x in
                                       b.findall(_f("AdministreringLegemiddel/Administrasjonsvei")) if x.get("DN")],
                            "refs": [x.text.strip() for x in b.findall(_f("SortertVirkestoffMedStyrke/RefVirkestoffMedStyrke"))
                                     if x.text],
                            "refs_plain": [x.text.strip() for x in b.findall(_f("SortertVirkestoffUtenStyrke/RefVirkestoff"))
                                           if x.text],
                        }
                    el.clear()
                elif tag == M30 + "OppfRefusjon":
                    for h in el.findall(M30 + "Refusjonshjemmel"):
                        basis = _a(h, M30 + "Refusjonshjemmel", "DN")
                        for g in h.findall(M30 + "Refusjonsgruppe"):
                            reimb[_t(g, M30 + "Id")] = (_a(g, M30 + "GruppeNr", "V"), basis)
                    el.clear()
                elif tag == M30 + "OppfByttegruppe":
                    g = el.find(M30 + "Byttegruppe")   # this catalogue is in the M30 namespace
                    if g is not None:
                        subgroups[_t(g, M30 + "Id")] = (_a(g, M30 + "Kode", "V"), _a(g, M30 + "Kode", "DN"))
                    el.clear()
                elif tag == M30 + "OppfLegemiddelpakning":
                    if _a(el, M30 + "Status", "V") == "A":
                        p = el.find(F + "Legemiddelpakning")
                        if p is not None:
                            packs.append(p)
                    else:
                        el.clear()
    if len(fest_date) != 10:
        raise RuntimeError("FEST file has no extract date (HentetDato)")
    out, seen = [], set()
    for p in packs:
        varenr = _t(p, F + "Varenr")
        if not varenr or varenr in seen:
            raise RuntimeError(f"FEST package number missing or repeated: {varenr!r}")
        seen.add(varenr)
        info = p.find(F + "Pakningsinfo")
        brand = brands.get(_t(info, F + "RefLegemiddelMerkevare"), {}) if info is not None else {}
        names_ = []
        for ref in brand.get("refs", []):
            n = subst.get(subst_str.get(ref, ""), "")
            if n and n not in names_:
                names_.append(n)
        for ref in brand.get("refs_plain", []):
            n = subst.get(ref, "")
            if n and n not in names_:
                names_.append(n)
        prices = [(_a(x, F + "Type", "DN"), _a(x, F + "Pris", "V") or _t(x, F + "Pris"), _t(x, F + "GyldigFraDato"),
                   _t(x, F + "GyldigTilDato")) for x in p.findall(F + "PrisVare")]
        now = _price_now(prices, fest_date)
        groups, basis = [], []
        for r in p.findall(F + "Refusjon"):
            nr, b = reimb.get(_t(r, F + "RefRefusjonsgruppe"), ("", ""))
            if nr and nr not in groups:
                groups.append(nr)
            if b and b not in basis:
                basis.append(b)
        sg = p.find(_f("PakningByttegruppe/RefByttegruppe"))
        sg_code, sg_name = subgroups.get((sg.text or "").strip(), ("", "")) if sg is not None else ("", "")
        row = {
            "fest_date": fest_date,
            "varenr": varenr,
            "ean": [x.text.strip() for x in p.findall(F + "Ean") if x.text and x.text.strip()],
            "atc_code": _a(p, F + "Atc", "V"),
            "atc_name": _a(p, F + "Atc", "DN"),
            "name_form_strength": _t(p, F + "NavnFormStyrke"),
            "brand_name": brand.get("brand_name", ""),
            "company": brand.get("company", ""),
            "reference_product": brand.get("reference_product", ""),
            "product_type": _a(p, F + "Preparattype", "DN"),
            "prescription_group": _a(p, F + "Reseptgruppe", "V"),
            "dosage_form": _a(p, F + "LegemiddelformKort", "DN"),
            "routes": brand.get("routes", []),
            "active_substances": names_,
            "pack_size": _t(info, F + "Pakningsstr") if info is not None else "",
            "pack_unit": _a(info, F + "EnhetPakning", "V") if info is not None else "",
            "pack_type": _a(info, F + "Pakningstype", "DN") if info is not None else "",
            "ddd": _num(_a(info, F + "DDD", "V")) if info is not None else "",
            "ddd_unit": _a(info, F + "DDD", "U") if info is not None else "",
            "marketing_date": _t(p, _f("Markedsforingsinfo/Markedsforingsdato")),
            "temporarily_unavailable_from": _t(p, _f("Markedsforingsinfo/MidlUtgattDato")),
            "black_triangle": "yes" if _a(p, F + "SvartTrekant", "V") == "1" else "no",
            "aup_valid_from": now.get("AUP", ("", ""))[0],
            "reimbursed": "yes" if groups else "no",
            "reimbursement_groups": groups,
            "reimbursement_basis": basis,
            "substitution_group": sg_code,
            "substitution_group_name": sg_name,
        }
        for typ, field in PRICE_TYPES.items():
            row[field] = _num(now[typ][1]) if typ in now else ""
        out.append({k: row[k] for k in FIELDS})
    if len(out) < min_packages:
        raise RuntimeError(f"FEST holds only {len(out)} packages; refusing a partial dataset")
    out.sort(key=lambda r: r["varenr"])
    return out
