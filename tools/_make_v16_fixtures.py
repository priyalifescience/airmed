"""Cut the test fixtures for the Swiss and Czech collectors from full downloads (6 November 2026).
  python tools/_make_v16_fixtures.py <bag_page1.json> <dlp.zip> <mr.zip>
"""

import csv
import io
import json
import sys
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
bag, dlp, mr = sys.argv[1:4]

items = json.loads(Path(bag).read_text(encoding="utf-8"))["items"][:3]
(FIXTURES / "ch_specialities_list.json").write_text(json.dumps({"total": 3, "items": items}, ensure_ascii=False, indent=0), encoding="utf-8")


def rows(z, name):
    return list(csv.reader(io.StringIO(z.read(name).decode("cp1250")), delimiter=";"))


def csv_bytes(table):
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n", quoting=csv.QUOTE_MINIMAL).writerows(table)
    return buf.getvalue().encode("cp1250")


with zipfile.ZipFile(dlp) as z:
    main = rows(z, "dlp_lecivepripravky.csv")
    head, body = main[0], main[1:]
    col = {c: i for i, c in enumerate(head)}
    keep = [r for r in body if r[col["KOD_SUKL"]] == "0000362"] + [r for r in body if r[col["ZEMDRZ"]] == "IRL"][:2] + [r for r in body if r[col["REG_PROC"]] == "EUR"][:2]
    ll = {c.strip() for r in keep for c in r[col["LL"]].split(",")}
    forms, routes, regs = {r[col["FORMA"]] for r in keep}, {r[col["CESTA"]] for r in keep}, {r[col["REG"]] for r in keep}
    orgs = {(r[col["DRZ"]], r[col["ZEMDRZ"]]) for r in keep}
    out = zipfile.ZipFile(FIXTURES / "cz_sukl_medicines.zip", "w", zipfile.ZIP_DEFLATED)
    out.writestr("dlp_lecivepripravky.csv", csv_bytes([head] + keep))
    for name, test in [("dlp_organizace.csv", lambda r: (r[0], r[1]) in orgs), ("dlp_formy.csv", lambda r: r[0] in forms),
                       ("dlp_cesty.csv", lambda r: r[0] in routes), ("dlp_stavyreg.csv", lambda r: r[0] in regs),
                       ("dlp_latky.csv", lambda r: r[0] in ll)]:
        table = rows(z, name)
        out.writestr(name, csv_bytes([table[0]] + [r for r in table[1:] if test(r)]))
    out.close()

with zipfile.ZipFile(mr) as z:
    table = rows(z, "mr_hlaseni.csv")
    keep = [r for r in table[1:] if r[1] in ("0000009", "0000025", "0000072")]
    with zipfile.ZipFile(FIXTURES / "cz_sukl_supply_notices.zip", "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("mr_hlaseni.csv", csv_bytes([table[0]] + keep))
print("fixtures written")
