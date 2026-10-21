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
  # One source failing (a timeout) must not stop the whole refresh: its last good copy stays in out/ and the
  # catalogue shows its older collection date. The release step still refuses broken or shrunken data.
  nice -n 10 python3 -m airmed run all --out out || echo "WARN: some sources failed this week; previous copies kept (see FAIL lines)"
  # keep last week's search index: if this week's build fails, publishing an older index beats deleting the page
  rm -rf search.prev; if [ -d dist/v1/search ]; then cp -a dist/v1/search search.prev; fi
  nice -n 10 python3 -m airmed release --src out --dist dist/v1
  nice -n 10 python3 tools/link_medicines.py --dist dist/v1 || echo "WARN: medicine cross-reference failed; publishing without it"
  nice -n 10 python3 tools/dcat.py --dist dist/v1 || echo "WARN: DCAT metadata failed; publishing without it"
  if curl -sf -m 5 http://127.0.0.1:11434/api/tags >/dev/null; then
    nice -n 10 python3 tools/search_index.py --dist dist/v1 || { echo "WARN: search index failed; publishing last week's index"; rm -rf dist/v1/search; if [ -d search.prev ]; then cp -a search.prev dist/v1/search; fi; }
  else
    echo "WARN: Ollama not reachable; search index skipped"
  fi
  if [ -f "$HOME/.airmid_ftp" ]; then
    python3 tools/publish_ftp.py dist/v1 --remote /airmid/v1 --login-file "$HOME/.airmid_ftp"
  else
    echo "NOT PUBLISHED: ~/.airmid_ftp missing (create it with host, user, password on three lines; chmod 600)"
  fi
  if [ -x "$HOME/airmid/assistant.sh" ]; then  # the private assistant loads the release at start: reload it
    pkill -f "[t]ools/assistant.py" || true
    sleep 2
    # 9>&- : the assistant must NOT inherit the job lock (fd 9), or every later weekly run thinks one is running
    setsid -f "$HOME/airmid/assistant.sh" 9>&- </dev/null >/dev/null 2>&1
    echo "assistant restarted with the new release"
  fi
  echo "== $(date -u +%FT%TZ) done"
} >>"$LOG" 2>&1
find logs -name "*.log" -mtime +90 -delete
