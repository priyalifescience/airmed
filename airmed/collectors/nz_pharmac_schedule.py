"""PHARMAC (Te Pātaka Whaioranga) Pharmaceutical Schedule, New Zealand: the latest monthly XML edition.

One record per funded pack (Pharmacode), in sections B Community Pharmaceuticals, C Extemporaneously Compounded
Preparations and Galenicals, D Special Foods and I National Immunisation Schedule, with its chemical,
formulation, brand, subsidy and supplier price (NZ dollars, excluding GST, as published), and the rules and
Special Authority forms that apply to it from the pack's own entries up to its therapeutic group.

The therapeutic group codes are PHARMAC's own hierarchy; they look like ATC letters but are not WHO ATC codes.
The Special Authority criteria text and applicant lists are not kept, only the form numbers.
"""

import re
import xml.etree.ElementTree as ET

from ..http import fetch

KEY = "nz_pharmac_schedule"
FIELDS = ["edition", "published", "section", "therapeutic_group_code", "therapeutic_group_1", "therapeutic_group_2",
          "therapeutic_group_3", "chemical", "formulation", "brand", "pack_id", "nzmt_ctpp_id", "quantity", "multiple",
          "subsidy", "price", "alternate_subsidy", "surcharge", "original_pack", "cost_brand_source", "sole_supply",
          "principal_supply", "to_be_delisted", "section_29", "special_authority_forms", "rules", "restricted"]
ARCHIVE = "https://schedule.pharmac.govt.nz/pub/schedule/archive/"
NS = "{http://schedule.pharmac.govt.nz/2006/07/Schedule#}"
NZMT = "{nzmt.org.nz}"
RESTRICTING = {"Special", "SpecEnd", "SpecOnly", "PCT"}
LEVELS = ("Section", "ATC1", "ATC2", "ATC3", "Chemical", "Formulation", "Brand")


def fetch_raw() -> bytes:
    index = fetch(ARCHIVE, timeout=120).decode("utf-8", "replace")
    editions = sorted(set(re.findall(r"Schedule_(\d{4}-\d{2})\.xml", index)))
    if not editions:
        raise RuntimeError("no Schedule_YYYY-MM.xml file listed in the PHARMAC archive")
    return fetch(f"{ARCHIVE}Schedule_{editions[-1]}.xml", timeout=300)


def _text(e, tag: str) -> str:
    c = e.find(NS + tag)
    return (c.text or "").strip() if c is not None and c.text else ""


def _num(s: str):
    if s == "":
        return ""
    f = float(s)
    return int(f) if f.is_integer() and "." not in s else f


def _yes(v) -> str:
    return "yes" if v in ("true", "1") else ("no" if v in (None, "false", "0") else v)


def parse(raw: bytes) -> list:
    root = ET.fromstring(raw)
    if root.tag != NS + "Schedule":
        raise RuntimeError(f"not a PHARMAC Schedule document: {root.tag}")
    front = root.find(NS + "Front")
    edition, published = _text(front, "Edition"), _text(front, "Published")
    out, seen = [], set()

    def walk(e, ctx):
        tag = e.tag.replace(NS, "")
        if tag == "Pack":
            pid = e.get("ID")
            if pid in seen:
                raise RuntimeError(f"duplicate PHARMAC pack {pid}")
            seen.add(pid)
            brand = ctx.get("Brand")
            battr = brand.attrib if brand is not None else {}
            forms = sorted(set(ctx["forms"]))
            rules = sorted(set(ctx["rules"]))
            out.append({"edition": edition, "published": published, "section": ctx["section"],
                        "therapeutic_group_code": ctx.get("code", ""), "therapeutic_group_1": ctx.get("ATC1", ""),
                        "therapeutic_group_2": ctx.get("ATC2", ""), "therapeutic_group_3": ctx.get("ATC3", ""),
                        "chemical": ctx.get("Chemical", ""), "formulation": ctx.get("Formulation", ""),
                        "brand": _text(brand, "Name") if brand is not None else "", "pack_id": pid, "nzmt_ctpp_id": e.get(NZMT + "ctpp_id", ""),
                        "quantity": _num(_text(e, "Quantity")), "multiple": _num(_text(e, "Multiple")),
                        "subsidy": _num(_text(e, "Subsidy")), "price": _num(_text(e, "Price")),
                        "alternate_subsidy": _num(_text(e, "Alternate")), "surcharge": _num(_text(e, "Surcharge")),
                        "original_pack": _yes(e.get("OP")), "cost_brand_source": _yes(e.get("CBS")),
                        "sole_supply": battr.get("SoleSupply", ""), "principal_supply": battr.get("PSS", ""),
                        "to_be_delisted": battr.get("ToBeDelisted", ""), "section_29": _yes(battr.get("S29")),
                        "special_authority_forms": forms, "rules": rules,
                        "restricted": "yes" if forms or any(r.split(":")[0] in RESTRICTING for r in rules) else "no"})
            return
        if tag not in LEVELS:
            return
        ctx = dict(ctx, rules=list(ctx["rules"]), forms=list(ctx["forms"]))
        if tag == "Section":
            ctx["section"] = f"{e.get('ID')} {_text(e, 'Name')}"
        elif tag == "Brand":
            ctx["Brand"] = e
        else:
            ctx[tag] = _text(e, "Name")
            if tag.startswith("ATC"):
                ctx["code"] = e.get("ID", "")
        for r in e.findall(NS + "Rule"):
            ctx["rules"].append(r.get("Type") + (f":{r.get('Attribute')}" if r.get("Attribute") else ""))
        for q in e.findall(NS + "Request"):
            if q.get("Form"):
                ctx["forms"].append(q.get("Form"))
        for c in e:
            walk(c, ctx)

    for s in root.findall(NS + "Section"):
        walk(s, {"rules": [], "forms": []})
    if len(root.findall(NS + "Section")) >= 4 and len(out) < 2000:
        raise RuntimeError(f"only {len(out)} PHARMAC packs; refusing a partial dataset")
    out.sort(key=lambda x: (x["section"], x["therapeutic_group_code"], x["chemical"], x["formulation"], x["brand"],
                            x["pack_id"]))
    return out
