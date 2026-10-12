# Contributing

Thank you for helping. A few rules keep Airmed Éireann open, legal and safe.

## Before every commit

```
python tools/secret_scan.py
python -m unittest discover -s tests -t .
python -m airmed check
```

All three must pass. CI runs them again, plus Gitleaks over the full history.

## Adding a source

1. Find the source's licence page and confirm that redistribution is allowed.
2. Add an entry to `sources/registry.json` with `status: "approved"`, the endpoint, licence, licence URL,
   attribution and the exact `fields_kept`. Link the licence page in the pull request.
3. Write a collector in `airmed/collectors/` that requests **only** those fields from a public, keyless API.
4. Add offline tests with a small, hand-written sample (no network in tests).

Never add: API keys or logins, scraping behind logins or CAPTCHAs, personal names or contact details,
or any source marked `blocked`.

## Code style

Python standard library only, unless a dependency is clearly worth auditing. Clear names over clever code.

## Use of AI

Parts of this code were drafted with an AI assistant (Claude, by Anthropic) and reviewed by the maintainers.
Contributors are welcome to use AI tools too, but say so in the pull request, and you remain responsible for
checking every line.
