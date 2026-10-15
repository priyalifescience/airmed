"""Airmid research assistant: ask questions about the released data in plain English, answered by a LOCAL model.

    python3 tools/assistant.py --dist dist/v1 --host 100.95.148.22 --port 8097 [--model gpt-oss:20b]

How it answers (so every answer can be checked):
  1. Loads every dataset CSV of the release into an in-memory SQLite database (read-only once loaded).
  2. The local model (Ollama) writes ONE SQLite SELECT for the question, given the table schemas.
  3. The query runs under a read-only authorizer, a time limit and a row cap.
  4. The model writes a short answer from the returned rows only. The page shows the answer, the SQL and the rows.
If the model's SQL fails, it gets the error once and may retry. Nothing leaves the machine: no external API calls.
Bind it to a private address (e.g. the Tailscale IP), never to 0.0.0.0 on a public network.
"""

import argparse
import csv
import html
import json
import re
import sqlite3
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

csv.field_size_limit(10_000_000)
ROW_CAP = 200
SQL_SECONDS = 8


def load_db(dist: Path):
    con = sqlite3.connect(":memory:", check_same_thread=False)
    catalog = json.loads((dist / "catalog.json").read_text(encoding="utf-8"))
    schema = []
    for ds in catalog["datasets"]:
        key = ds["key"]
        path = dist / key / f"{key}.csv"
        if not path.exists():
            continue
        with open(path, encoding="utf-8", newline="") as f:
            rd = csv.reader(f)
            cols = next(rd)
            con.execute(f'CREATE TABLE "{key}" ({", ".join(chr(34) + c + chr(34) for c in cols)})')
            con.executemany(f'INSERT INTO "{key}" VALUES ({",".join("?" * len(cols))})', rd)
        n = con.execute(f'SELECT COUNT(*) FROM "{key}"').fetchone()[0]
        sample = con.execute(f'SELECT * FROM "{key}" LIMIT 2').fetchall()
        docs = {fd["name"]: fd.get("description", "") for fd in ds.get("fields", [])}
        schema.append(f'TABLE {key} -- {ds["title"]} ({n} rows; publisher {ds["publisher"]})\n' +
                      "\n".join(f"  {c}: {docs.get(c, '')}" for c in cols) +
                      "\n  example rows: " + json.dumps(sample, ensure_ascii=False)[:600])
    con.commit()

    def authorizer(action, *_):  # after loading: reads only
        return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION) \
            else sqlite3.SQLITE_DENY
    con.set_authorizer(authorizer)
    return con, "\n\n".join(schema)


def ollama(host, model, prompt, max_tokens):
    body = {"model": model, "prompt": prompt, "stream": False, "think": "low",
            "options": {"num_predict": max_tokens, "temperature": 0}}
    req = urllib.request.Request(host + "/api/generate", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r).get("response", "").strip()


SQL_PROMPT = """You write ONE SQLite query to answer a question about public medicines, trials and pharma statistics.
All columns are TEXT (cast numbers with CAST(x AS REAL)); list values are stored as text like "a; b" or JSON.
Use LIKE with % for name matching (case-insensitive). Always add LIMIT 50 or less. Output only the SQL, no prose.
Hints: therapeutic_area columns hold MeSH DISEASE names (e.g. "Bacterial Infections", "Breast Neoplasms"), not drug
classes, so translate a drug class into the diseases it treats and/or match the inn/active_substance/atc columns
(ATC J01 = antibacterials for systemic use, L01 = antineoplastics, A10 = diabetes). Status values vary by source; look
at the example rows. Prefer OR over several matching columns when unsure.

{schema}

Question: {q}
{retry}SQL:"""

ANSWER_PROMPT = """Answer the question in 2 to 5 sentences using ONLY these query results. If the results do not answer it,
say so plainly. Do not add facts that are not in the rows. Mention the dataset (table) the figures come from.

Question: {q}
SQL: {sql}
Rows (first {n}): {rows}

Answer:"""


def clean_sql(text):
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip().rstrip(";")
    if ";" in sql or not re.match(r"(?is)^\s*(select|with)\b", sql):
        raise ValueError("model did not return a single SELECT")
    return sql


def run_sql(con, sql):
    start = time.time()
    con.set_progress_handler(lambda: 1 if time.time() - start > SQL_SECONDS else 0, 10_000)
    try:
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return cols, cur.fetchmany(ROW_CAP)
    finally:
        con.set_progress_handler(None, 0)


def ask(con, schema, q, host, model):
    t0 = time.time()
    retry, last_err = "", None
    for _ in range(2):
        sql = None
        try:
            sql = clean_sql(ollama(host, model, SQL_PROMPT.format(schema=schema, q=q, retry=retry), 400))
            cols, rows = run_sql(con, sql)
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            retry = f"Your previous SQL failed.\nSQL: {sql}\nError: {last_err}\nWrite a corrected query.\n"
    else:
        return {"error": last_err, "sql": sql, "seconds": round(time.time() - t0)}
    shown = [dict(zip(cols, r)) for r in rows[:30]]
    answer = ollama(host, model, ANSWER_PROMPT.format(q=q, sql=sql, n=len(shown),
                                                      rows=json.dumps(shown, ensure_ascii=False)[:6000]), 300)
    return {"answer": answer, "sql": sql, "columns": cols, "rows": [list(r) for r in rows],
            "seconds": round(time.time() - t0)}


PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Airmid research assistant</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:24px auto;padding:0 16px;color:#1d2a24}}
input{{width:75%;padding:10px;font-size:15px}}button{{padding:10px 16px}}pre{{background:#f3f5f4;padding:10px;overflow:auto}}
table{{border-collapse:collapse;font-size:13px}}td,th{{border:1px solid #ccd;padding:4px 6px;text-align:left}}
.note{{color:#667;font-size:13px}}</style>
<h1>Airmid research assistant</h1>
<p class="note">Local model {model} on this machine; answers come only from the Airmid release in {dist}. Always check the SQL and rows. Private: this page is reachable only on the private network.</p>
<form method="post"><input name="q" value="{q}" placeholder="e.g. Which EMA shortages are about antibiotics and still unresolved?" autofocus>
<button>Ask</button></form>{result}"""


def render(model, dist, q="", res=None):
    out = ""
    if res:
        if res.get("error"):
            out += f"<p><b>Could not answer:</b> {html.escape(res['error'])}</p>"
        else:
            out += f"<h2>Answer</h2><p>{html.escape(res['answer'])}</p>"
        if res.get("sql"):
            out += f"<h3>SQL</h3><pre>{html.escape(res['sql'])}</pre>"
        if res.get("rows"):
            out += "<h3>Rows</h3><table><tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in res["columns"]) + "</tr>"
            for r in res["rows"][:100]:
                out += "<tr>" + "".join(f"<td>{html.escape(str(v))[:200]}</td>" for v in r) + "</tr>"
            out += "</table>"
        out += f"<p class='note'>{res.get('seconds')} s</p>"
    return PAGE.format(model=html.escape(model), dist=html.escape(str(dist)), q=html.escape(q), result=out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default="dist/v1")
    ap.add_argument("--host", required=True, help="private address to bind, e.g. the Tailscale IP")
    ap.add_argument("--port", type=int, default=8097)
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--ask", help="answer one question on the command line and exit")
    a = ap.parse_args(argv)
    if a.host in ("0.0.0.0", "::"):
        sys.exit("refusing to bind to all interfaces; pass the private (Tailscale) address")
    dist = Path(a.dist)
    con, schema = load_db(dist)
    print(f"loaded {dist}; schema {len(schema)} chars", flush=True)
    if a.ask:
        print(json.dumps(ask(con, schema, a.ask, a.ollama, a.model), ensure_ascii=False, indent=1)[:4000])
        return

    class H(BaseHTTPRequestHandler):
        def _send(self, body):
            b = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send(render(a.model, dist))

        def do_POST(self):
            n = min(int(self.headers.get("Content-Length", 0)), 4000)
            q = parse_qs(self.rfile.read(n).decode("utf-8", "replace")).get("q", [""])[0].strip()[:500]
            self._send(render(a.model, dist, q, ask(con, schema, q, a.ollama, a.model) if q else None))

        def log_message(self, fmt, *args):
            print(time.strftime("%H:%M:%S"), self.address_string(), fmt % args, flush=True)

    print(f"serving on http://{a.host}:{a.port}", flush=True)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
