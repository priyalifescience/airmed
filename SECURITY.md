# Security policy

## What this repository must never contain

- Passwords, API keys, tokens, private keys or service-account files
- Hosting, FTP or database details of any website
- Personal data: names, emails or phone numbers of investigators, staff, officials or anyone else
- Data from sources marked `blocked` in `sources/registry.json`
- Collected data outside a reviewed release (`out/` and `data/raw/` are ignored by git)

This repository is built from scratch as a clean project. It is **not** a copy of the Priya Life Science
website code, which is a separate, private system.

## How that is enforced

| Layer | What it does |
|---|---|
| `.gitignore` | Ignores secret-looking files and collected data |
| `tools/leak_scan.py` | Blocks credential patterns and forbidden files; run before every commit and in CI |
| Gitleaks in CI | Scans the **full git history** on every push and pull request |
| Source registry | A collector refuses to run unless its source is `approved`, with licence and attribution recorded |
| Field allow-list | Collectors request only the fields listed in the registry; personal-data field names are refused |
| Privacy guard | Any value containing an email address or phone number is blanked and counted |
| No keys needed | Every source is a public, keyless API; the code reads no secrets and CI uses none |
| Least-privilege CI | Workflows run with read-only permissions |

## Reporting a problem

If you find a secret, personal data or a licensing problem in this repository, email
**info@priyalifescience.com** with the subject "Airmed security". Please do not open a public issue for it.
We aim to reply within 3 working days, remove the material, and rotate any exposed credential.
