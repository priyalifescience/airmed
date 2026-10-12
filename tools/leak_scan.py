"""Block secrets and private files from the repository. Runs in CI on every push and pull request,
and locally before every commit (see CONTRIBUTING.md). Exit code 1 = something must be removed.

Checks every tracked file (or the paths given) for:
  - credential patterns (private keys, GitHub / Google / Slack / AWS tokens, FTP and database passwords)
  - files that must never be committed (.env, key files, collected data outside a reviewed release)
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

PATTERNS = {
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "GitHub token": r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "Google service account": r"\"type\"\s*:\s*\"service_account\"",
    "AWS key": r"\bAKIA[0-9A-Z]{16}\b",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
    "OpenAI/Anthropic-style key": r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b",
    "password assignment": r"(?i)\b(pass(word|wd)?|pwd|secret|api_?key|token)\b\s*[:=]\s*['\"][^'\"\s]{6,}['\"]",
    "hosting account id": r"\bu\d{9}\b",
}
FORBIDDEN_NAMES = [r"(^|/)\.env(\.|$)", r"\.(pem|p12|pfx|key)$", r"(^|/)\.ftp_pass$", r"(^|/)\.gsc_key\.json$",
                   r"(^|/)id_(rsa|ed25519)", r"(^|/)out/", r"(^|/)data/raw/"]


def tracked_files() -> list:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        return [ROOT / p for p in out.decode("utf-8").split("\0") if p]
    except Exception:
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


def scan(paths) -> list:
    problems = []
    for p in paths:
        p = Path(p).resolve()
        rel = p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)
        for rx in FORBIDDEN_NAMES:
            if re.search(rx, rel):
                problems.append(f"{rel}: this file must never be committed")
        if p == SELF or not p.is_file() or p.stat().st_size > 5_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, rx in PATTERNS.items():
            for m in re.finditer(rx, text):
                line = text.count("\n", 0, m.start()) + 1
                problems.append(f"{rel}:{line}: possible {label}")
    return problems


if __name__ == "__main__":
    problems = scan(sys.argv[1:] or tracked_files())
    for pr in problems:
        print("BLOCKED", pr)
    print(f"secret scan: {len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
