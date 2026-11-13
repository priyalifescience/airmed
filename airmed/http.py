"""Polite HTTP for public APIs: identifying User-Agent, timeouts, a pause between requests, limited retries.

No API keys, tokens or cookies are ever sent. Only https URLs are allowed.
"""

import http.client
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


def fetch(url: str, timeout: int = 60, retries: int = 3, data: bytes = None, headers: dict = None,
          backoff: float = 5.0) -> bytes:
    """GET (or POST when `data` is given) and return the body.

    Retries 429, 5xx and dropped connections. The pause before attempt n+1 is backoff * 2**(n-1) seconds, capped at
    5 minutes (the default 5 s gives 5 s then 10 s, as before 1.7). v1.7: a connection the server closes without a
    reply ("Remote end closed connection", IncompleteRead, reset, timeout) is retried too; before, only URLError was,
    and one dropped connection failed the whole source (scot_phs_prescribing, 21 Oct to 9 Nov 2026)."""
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
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(min(backoff * 2 ** (attempt - 1), 300))
    raise RuntimeError("unreachable")


def fetch_json_retry(url: str, timeout: int = 120, attempts: int = 4, pause: float = 20.0):
    """GET JSON; when the reply is cut short (it does not parse), wait and fetch it again (v1.7).

    OpenAlex sometimes ends a large reply at about 2 MB without an error, which left "Unterminated string" failures
    (openalex_ireland_pharma 26 Oct and 2 Nov, openalex_europe_pharma 9 Nov 2026)."""
    for attempt in range(1, attempts + 1):
        body = fetch(url, timeout=timeout)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            if attempt == attempts:
                raise
            time.sleep(pause * attempt)
    raise RuntimeError("unreachable")


def fetch_json(url: str, timeout: int = 60, body: dict = None):
    """GET JSON, or POST `body` as JSON and return the decoded reply."""
    if body is None:
        return json.loads(fetch(url, timeout=timeout))
    return json.loads(fetch(url, timeout=timeout, data=json.dumps(body).encode("utf-8"),
                            headers={"Content-Type": "application/json"}))
