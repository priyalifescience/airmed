#!/usr/bin/env bash
# Airmid Éireann weekly refresh: collect -> build release (refuses broken/shrunk/unsafe data) -> add the medicine
# cross-reference and the search index -> publish over FTP.
# Runs from cron. Never publishes if collection or release fails. The cross-reference and search index are extras:
# if either fails, the release is still published without the failed extra (logged).
# The FTP login lives in ~/.airmid_ftp (chmod 600), never in code. Embeddings come from a local Ollama model.
set -euo pipefail
cd "$HOME/airmid"
exec 9>"$HOME/airmid/.lock"; flock -n 9 || { echo "already running"; exit 0; }
LOG="logs/$(date -u +%Y-%m-%d).log"
{
  echo "== $(date -u +%FT%TZ) start"
  nice -n 10 python3 -m airmed run all --out out
  nice -n 10 python3 -m airmed release --src out --dist dist/v1
  nice -n 10 python3 tools/link_medicines.py --dist dist/v1 || echo "WARN: medicine cross-reference failed; publishing without it"
  if curl -sf -m 5 http://127.0.0.1:11434/api/tags >/dev/null; then
    nice -n 10 python3 tools/search_index.py --dist dist/v1 || { echo "WARN: search index failed; publishing without it"; rm -rf dist/v1/search; }
  else
    echo "WARN: Ollama not reachable; search index skipped"
  fi
  if [ -f "$HOME/.airmid_ftp" ]; then
    python3 tools/publish_ftp.py dist/v1 --remote /airmid/v1 --login-file "$HOME/.airmid_ftp"
  else
    echo "NOT PUBLISHED: ~/.airmid_ftp missing (create it with host, user, password on three lines; chmod 600)"
  fi
  echo "== $(date -u +%FT%TZ) done"
} >>"$LOG" 2>&1
find logs -name "*.log" -mtime +90 -delete
