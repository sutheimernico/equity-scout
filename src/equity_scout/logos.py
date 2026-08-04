"""Company logos for the phone cockpit: fetched once per ticker, cached locally forever.

Why local caching at all (owner decision, not an optimization): the phone must never leak
which tickers Nico looks at to a third-party logo provider on every dashboard load, and the
cached PNG has to keep working when the service worker serves the app offline. So the
*server* is the only thing that ever talks to the logo provider, and only once per ticker.

yfinance's `.info` no longer has `logo_url` (Yahoo removed it) but still has `website`
(e.g. "https://www.microsoft.com"). We turn that into a bare domain and ask Google's public
favicon endpoint for an icon - not a logo API, but favicons double as small square logos
well enough for a dashboard badge, see `fetch_logo_bytes` for the caveat about its
placeholder image.

Same fail-safe idiom as fundamentals.py: a thin, lazily-imported yfinance seam so this
module is fully testable offline, and every layer degrades to None instead of raising -
a missing logo is an honest gap the frontend renders as a monogram badge, never an error.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

LOGO_DIR = "data/logos"  # created on demand by ensure_logo; never assumed to pre-exist

# Same ticker charset used by api.py's own validators (e.g. the /api/entry/{ticker} and
# /api/stack/{ticker} guards). Real tickers use dots and hyphens (PETR4.SA, TEL2-B.ST,
# 9022.T), so we can't just reject those - but this allow-list also means '/' and '\\'
# are rejected simply for not being in it, which is exactly what keeps a ticker from ever
# being able to address a path outside LOGO_DIR.
_TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")


def _validate_ticker(ticker: str) -> str:
    """Allow-list the ticker before it touches any path. Raises ValueError (not None) for
    anything outside the charset: a malformed/hostile ticker here is a caller bug or an
    attack, and we want that loud, not silently swallowed into a different file."""
    t = ticker.strip().upper()
    if not _TICKER_RE.fullmatch(t):
        raise ValueError(f"invalid ticker for logo path: {ticker!r}")
    return t


def _ticker_file_path(ticker: str, suffix: str) -> Path:
    t = _validate_ticker(ticker)
    base = Path(LOGO_DIR).resolve()
    path = (Path(LOGO_DIR) / f"{t}{suffix}")
    # Belt-and-suspenders: the allow-list above already blocks '/' and separators, so this
    # can't normally trigger. It's here so a future edit to _TICKER_RE (e.g. widening the
    # charset) can't quietly turn into a path-traversal bug - resolve() + is_relative_to()
    # is checked against the actual filesystem path, not just the ticker string.
    if not path.resolve().is_relative_to(base):
        raise ValueError(f"ticker escapes LOGO_DIR: {ticker!r}")
    return path


def logo_path(ticker: str) -> Path:
    """Path to the cached logo PNG for `ticker` (may or may not exist yet)."""
    return _ticker_file_path(ticker, ".png")


def miss_path(ticker: str) -> Path:
    """Path to the sidecar marker recording 'no logo available' for `ticker`, so a ticker
    without a logo isn't re-fetched on every request within the TTL (see ensure_logo)."""
    return _ticker_file_path(ticker, ".miss")


def _default_fetch_info(ticker: str) -> dict:
    """Lazy yfinance import, mirrors fundamentals.py's seam so this module stays
    offline-testable and doesn't force a yfinance import at module load time."""
    import yfinance as yf

    info = yf.Ticker(ticker).info
    return info if isinstance(info, dict) else {}


def company_domain(ticker: str, *, fetch_info=None) -> str | None:
    """The bare domain (no scheme, no www., no path) behind `ticker`'s yfinance
    `website` field, or None if it's absent or the lookup fails. Never raises - a
    smaller/non-US ticker frequently has no website on file, which is an honest gap."""
    fetch = fetch_info or _default_fetch_info
    try:
        info = fetch(ticker)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    website = info.get("website")
    if not isinstance(website, str) or not website:
        return None
    # yfinance is inconsistent about whether `website` carries a scheme; urlparse only
    # populates `.netloc` when one is present, so normalize to "//host/..." first.
    candidate = website if "//" in website else f"//{website}"
    host = urlparse(candidate).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Google serves this EXACT 726-byte, 16x16 "globe" PNG for any domain it has no favicon
# for at all - verified empirically (2026-08-04) against several unrelated nonexistent
# domains: byte-identical (same SHA-256) every time regardless of the requested `sz`. A
# plain "reject if small" byte threshold CANNOT catch this: the placeholder (726 bytes) is
# larger than some genuine, well-compressed 128px logos (Microsoft's real favicon is 426
# bytes), so hash-matching the known placeholder is the only reliable signal we found for
# "no real logo exists" - see the honest-absence requirement in the module docstring.
_KNOWN_PLACEHOLDER_SHA256 = "59bfe9bc385ad69f50793ce4a53397316d7a875a7148a63c16df9b674c6cda64"

# Sanity floor only, distinct from the placeholder hash above: rejects an obviously
# truncated/garbage download (e.g. a proxy error body that happens to start with bytes
# that survived the PNG-magic check). Set comfortably below the smallest real logo we
# observed in practice (a low-res company icon at 349 bytes).
_MIN_PLAUSIBLE_BYTES = 100


def _default_fetch(url: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as resp:  # nosec - fixed https host, not user input
        return resp.read()


def fetch_logo_bytes(domain: str, *, fetch=None) -> bytes | None:
    """Fetch a favicon-as-logo for `domain` from Google's public favicon endpoint.
    None on any failure: network error, non-PNG body, implausibly small body, or
    Google's own "no favicon" placeholder - a caller-visible miss, never an exception."""
    fetch = fetch or _default_fetch
    url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
    try:
        data = fetch(url)
    except Exception:
        return None
    if not data or len(data) < _MIN_PLAUSIBLE_BYTES:
        return None
    if not data.startswith(_PNG_MAGIC):
        return None
    if hashlib.sha256(data).hexdigest() == _KNOWN_PLACEHOLDER_SHA256:
        return None
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via temp file + rename so a reader can never observe a half-written PNG -
    os.replace is atomic as long as the temp file lives on the same filesystem, which
    creating it inside `path.parent` guarantees."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# 30 days: long enough that a ticker with a genuinely absent website (small-cap, delisted,
# a data gap in yfinance) isn't re-hit on every dashboard load or autopilot cycle; short
# enough that a company that later gets a website/favicon (rebrand, new listing) is retried
# well within a year rather than being stuck "no logo" forever.
MISS_TTL_SECONDS = 30 * 24 * 3600


def ensure_logo(
    ticker: str,
    *,
    fetch_info=None,
    fetch=None,
    ttl_seconds: int = MISS_TTL_SECONDS,
) -> Path | None:
    """Orchestrator: cached hit -> return its path; recent recorded miss -> None without
    any network call; otherwise resolve the domain, fetch, cache the result (hit or miss),
    and return it. Every failure path (bad ticker, no domain, fetch failure, disk error)
    degrades to None - this function must never raise."""
    try:
        path = logo_path(ticker)
    except ValueError:
        return None  # malformed/hostile ticker: never touch the filesystem for it

    if path.exists():
        return path

    miss = miss_path(ticker)
    if miss.exists():
        try:
            age = time.time() - miss.stat().st_mtime
        except OSError:
            age = 0.0
        if age < ttl_seconds:
            return None  # known recent miss - honor the TTL, no network call

    domain = company_domain(ticker, fetch_info=fetch_info)
    data = fetch_logo_bytes(domain, fetch=fetch) if domain else None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if data:
            _atomic_write(path, data)
            # A later hit invalidates any stale miss marker from an earlier attempt.
            miss.unlink(missing_ok=True)
            return path
        miss.touch(exist_ok=True)
        return None
    except OSError:
        return None  # disk error - degrade to None, never raise
