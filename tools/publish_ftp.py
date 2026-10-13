"""Publish a built release folder to the website over FTPS (FTP with TLS: login and files are encrypted, and the
server certificate is verified).

    python tools/publish_ftp.py dist/v1 --remote /public_html/opendata/airmid/v1 --login-file ~/.airmid_ftp

The login file (never committed; chmod 600) has three lines: host, user, password.

Safe swap: everything is uploaded to <remote>.new and every file size is read back; only then is the live folder
renamed to <remote>.old, <remote>.new renamed into place, and <remote>.old deleted. Visitors only see a gap of a
moment between the two renames, never a half-uploaded release.
"""

import argparse
import ftplib
import os
import ssl
import posixpath
import sys
from pathlib import Path


def read_login(path: str):
    p = Path(os.path.expanduser(path))
    if os.name != "nt" and p.stat().st_mode & 0o077:
        sys.exit(f"{p}: permissions too open, run: chmod 600 {p}")
    host, user, password = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()[:3]]
    return host, user, password


def exists(ftp, path):
    try:
        ftp.cwd(path)
        ftp.cwd("/")
        return True
    except ftplib.error_perm:
        return False


def mkdirs(ftp, path):
    cur = ""
    for part in path.strip("/").split("/"):
        cur += "/" + part
        if not exists(ftp, cur):
            ftp.mkd(cur)


def rmtree(ftp, path):
    for name, facts in ftp.mlsd(path):
        if name in (".", ".."):
            continue
        full = posixpath.join(path, name)
        if facts.get("type") == "dir":
            rmtree(ftp, full)
        else:
            ftp.delete(full)
    ftp.rmd(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dist")
    ap.add_argument("--remote", default="/public_html/opendata/airmid/v1")
    ap.add_argument("--login-file", default="~/.airmid_ftp")
    a = ap.parse_args()
    dist = Path(a.dist)
    if not (dist / "catalog.json").exists():
        sys.exit("no catalog.json: build the release first (python -m airmed release)")
    files = [p for p in dist.rglob("*") if p.is_file()]
    host, user, password = read_login(a.login_file)
    new, old = a.remote + ".new", a.remote + ".old"
    ctx = ssl.create_default_context()          # verifies the certificate and the host name
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    with ftplib.FTP_TLS(host, timeout=120, context=ctx) as ftp:
        ftp.auth()                                # encrypt before the password is sent
        ftp.login(user, password)
        ftp.prot_p()                              # encrypt the file transfers too
        mkdirs(ftp, posixpath.dirname(a.remote))
        for leftover in (new, old):
            if exists(ftp, leftover):
                rmtree(ftp, leftover)
        for f in files:
            rel = f.relative_to(dist).as_posix()
            target = posixpath.join(new, rel)
            mkdirs(ftp, posixpath.dirname(target))
            with open(f, "rb") as fh:
                ftp.storbinary(f"STOR {target}", fh)
        ftp.voidcmd("TYPE I")
        bad = [f for f in files if ftp.size(posixpath.join(new, f.relative_to(dist).as_posix())) != f.stat().st_size]
        if bad:
            sys.exit(f"size mismatch after upload, live release untouched: {[str(b) for b in bad][:5]}")
        live = exists(ftp, a.remote)
        if live:
            ftp.rename(a.remote, old)
        ftp.rename(new, a.remote)
        if live:
            rmtree(ftp, old)
    print(f"published {len(files)} files to {a.remote}")


if __name__ == "__main__":
    main()
