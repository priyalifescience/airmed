"""Polite HTTP for public APIs: identifying User-Agent, timeouts, a pause between requests, limited retries.

No API keys, tokens or cookies are ever sent. Only https URLs are allowed.
"""

import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"Airmed/{__version__} (+https://priyalifescience.com/airmed; info@priyalifescience.com)"
PAUSE_SECONDS = 1.0
_last_request = 0.0


def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("only https URLs are allowed")
    global _last_request
    for attempt in range(1, retries + 1):
        wait = PAUSE_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            # 4xx other than 429 will not get better by retrying
            if e.code != 429 and e.code < 500 or attempt == retries:
                raise
        except urllib.error.URLError:
            if attempt == retries:
                raise
        time.sleep(5 * attempt)
    raise RuntimeError("unreachable")
