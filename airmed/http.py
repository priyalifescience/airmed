"""Polite HTTP for public APIs: identifying User-Agent, timeouts, a pause between requests, limited retries.

No API keys, tokens or cookies are ever sent. Only https URLs are allowed.
"""

import json
import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"Airmed/{__version__} (+https://priyalifescience.com/airmed; info@priyalifescience.com)"
PAUSE_SECONDS = 1.0
MAX_BYTES = 400 * 1024 * 1024   # no public source we use is near this; a larger reply means something is wrong
_last_request = 0.0


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to other https URLs (never downgrade to plain http)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.HTTPError(newurl, code, "refusing redirect away from https", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnlyRedirects)


def fetch(url: str, timeout: int = 60, retries: int = 3, data: bytes = None, headers: dict = None) -> bytes:
    """GET (or POST when `data` is given) and return the body."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs are allowed")
    global _last_request
    for attempt in range(1, retries + 1):
        wait = PAUSE_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "*/*", **(headers or {})})
        try:
            with _opener.open(req, timeout=timeout) as resp:
                body = resp.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError(f"{url}: reply larger than {MAX_BYTES} bytes, refused")
                return body
        except urllib.error.HTTPError as e:
            # 4xx other than 429 will not get better by retrying
            if e.code != 429 and e.code < 500 or attempt == retries:
                raise
        except urllib.error.URLError:
            if attempt == retries:
                raise
        time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def fetch_json(url: str, timeout: int = 60, body: dict = None):
    """GET JSON, or POST `body` as JSON and return the decoded reply."""
    if body is None:
        return json.loads(fetch(url, timeout=timeout))
    return json.loads(fetch(url, timeout=timeout, data=json.dumps(body).encode("utf-8"),
                            headers={"Content-Type": "application/json"}))
