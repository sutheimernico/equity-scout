"""Company logo cache: offline-only, no real yfinance or network calls in these tests -
every seam (fetch_info, fetch) is stubbed. See logos.py for the caching/TTL reasoning."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from equity_scout import logos
from equity_scout.api import create_app
from equity_scout.storage import init_db

_PLAUSIBLE_PNG = logos._PNG_MAGIC + b"\x00" * 200  # well above _MIN_PLAUSIBLE_BYTES, not the placeholder


def _raising_fetch(*_args, **_kwargs):
    raise AssertionError("network seam must not be called")


# --- company_domain ---------------------------------------------------------------


def test_company_domain_strips_scheme_and_www():
    domain = logos.company_domain("MSFT", fetch_info=lambda t: {"website": "https://www.microsoft.com"})
    assert domain == "microsoft.com"


def test_company_domain_strips_path():
    domain = logos.company_domain("MSFT", fetch_info=lambda t: {"website": "https://www.microsoft.com/en-us/about"})
    assert domain == "microsoft.com"


def test_company_domain_none_when_website_missing():
    assert logos.company_domain("ZZZZ", fetch_info=lambda t: {"longName": "No Website Inc."}) is None


def test_company_domain_none_on_fetch_failure():
    assert logos.company_domain("ZZZZ", fetch_info=_raising_fetch) is None


# --- fetch_logo_bytes --------------------------------------------------------------


def test_fetch_logo_bytes_rejects_empty_response():
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: b"") is None


def test_fetch_logo_bytes_rejects_too_small_response():
    tiny = logos._PNG_MAGIC + b"\x00" * 4  # under _MIN_PLAUSIBLE_BYTES despite valid magic
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: tiny) is None


def test_fetch_logo_bytes_rejects_non_png_response():
    html_error_body = b"<HTML><BODY>301 Moved</BODY></HTML>" * 10
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: html_error_body) is None


def test_fetch_logo_bytes_rejects_known_placeholder(monkeypatch):
    # We don't ship Google's real 726-byte "no favicon at all" globe PNG in the test tree,
    # so this test proves the hash-match mechanism itself: point the known-placeholder
    # constant at our fake payload's own hash and confirm it gets rejected even though it
    # is a valid, big-enough PNG (i.e. the hash check, not size/magic, is what catches it).
    import hashlib

    fake_placeholder = logos._PNG_MAGIC + b"\x01" * 300
    monkeypatch.setattr(
        logos, "_KNOWN_PLACEHOLDER_SHA256", hashlib.sha256(fake_placeholder).hexdigest()
    )
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: fake_placeholder) is None
    # A different payload of the same shape (not the placeholder) is still accepted.
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: _PLAUSIBLE_PNG) is not None


def test_fetch_logo_bytes_accepts_plausible_png():
    assert logos.fetch_logo_bytes("example.com", fetch=lambda url: _PLAUSIBLE_PNG) == _PLAUSIBLE_PNG


def test_fetch_logo_bytes_none_on_fetch_exception():
    assert logos.fetch_logo_bytes("example.com", fetch=_raising_fetch) is None


# --- path safety (security regression) ---------------------------------------------


def test_logo_path_rejects_dot_dot_slash(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    with pytest.raises(ValueError):
        logos.logo_path("../../etc/passwd")


def test_logo_path_rejects_bare_slash(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    with pytest.raises(ValueError):
        logos.logo_path("AAPL/../../evil")


def test_ensure_logo_never_writes_outside_logo_dir_for_hostile_ticker(tmp_path, monkeypatch):
    logo_dir = tmp_path / "logos"
    monkeypatch.setattr(logos, "LOGO_DIR", str(logo_dir))
    result = logos.ensure_logo(
        "../../evil",
        fetch_info=lambda t: {"website": "https://evil.example.com"},
        fetch=lambda url: _PLAUSIBLE_PNG,
    )
    assert result is None
    # nothing escaped: no file landed anywhere outside (or even inside) the intended dir
    assert not (tmp_path / "evil.png").exists()
    assert not (tmp_path.parent / "evil.png").exists()


# --- ensure_logo: caching + miss TTL -------------------------------------------------


def test_ensure_logo_writes_file_on_hit_and_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    path = logos.ensure_logo(
        "MSFT",
        fetch_info=lambda t: {"website": "https://www.microsoft.com"},
        fetch=lambda url: _PLAUSIBLE_PNG,
    )
    assert path is not None
    assert path.exists()
    assert path.read_bytes() == _PLAUSIBLE_PNG


def test_ensure_logo_second_call_uses_cache_no_refetch(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    first = logos.ensure_logo(
        "MSFT",
        fetch_info=lambda t: {"website": "https://www.microsoft.com"},
        fetch=lambda url: _PLAUSIBLE_PNG,
    )
    assert first is not None

    # Second call: both seams raise if called at all - a cache hit must never touch them.
    second = logos.ensure_logo("MSFT", fetch_info=_raising_fetch, fetch=_raising_fetch)
    assert second == first
    assert second.read_bytes() == _PLAUSIBLE_PNG


def test_ensure_logo_records_miss_and_records_no_refetch_within_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    first = logos.ensure_logo(
        "ZZZZ",
        fetch_info=lambda t: {"longName": "No Website Inc."},  # no website -> honest miss
        fetch=_raising_fetch,
    )
    assert first is None
    assert logos.miss_path("ZZZZ").exists()

    # Second call within the TTL: no network seam call at all (both raise if invoked).
    second = logos.ensure_logo("ZZZZ", fetch_info=_raising_fetch, fetch=_raising_fetch)
    assert second is None


def test_ensure_logo_refetches_after_ttl_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    first = logos.ensure_logo(
        "ZZZZ", fetch_info=lambda t: {}, fetch=_raising_fetch, ttl_seconds=0,
    )
    assert first is None
    # ttl_seconds=0 means even the freshly-written marker already counts as expired.
    second = logos.ensure_logo(
        "ZZZZ",
        fetch_info=lambda t: {"website": "https://www.microsoft.com"},
        fetch=lambda url: _PLAUSIBLE_PNG,
        ttl_seconds=0,
    )
    assert second is not None
    assert second.read_bytes() == _PLAUSIBLE_PNG


# --- endpoint ------------------------------------------------------------------------


def test_logo_endpoint_returns_png_for_cached_logo(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    db = tmp_path / "api.db"
    init_db(db)

    # Pre-seed the cache directly so the endpoint hits the "cached file exists" path and
    # never needs a network seam.
    path = logos.logo_path("AAPL")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PLAUSIBLE_PNG)

    client = TestClient(create_app(str(db)))
    resp = client.get("/api/logo/AAPL")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == _PLAUSIBLE_PNG
    assert "max-age" in resp.headers.get("cache-control", "")


def test_logo_endpoint_returns_404_for_ticker_without_logo(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    # api.py calls ensure_logo(ticker) with no seams supplied, which would otherwise fall
    # through to the real yfinance seam - stub it so this test makes no network call and
    # resolves to "no domain" quickly, exactly like a ticker yfinance has no website for.
    monkeypatch.setattr(logos, "_default_fetch_info", lambda t: {})

    db = tmp_path / "api.db"
    init_db(db)
    client = TestClient(create_app(str(db)))
    resp = client.get("/api/logo/ZZZZ")
    assert resp.status_code == 404


def test_logo_endpoint_rejects_malformed_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(logos, "LOGO_DIR", str(tmp_path / "logos"))
    db = tmp_path / "api.db"
    init_db(db)
    client = TestClient(create_app(str(db)))
    resp = client.get("/api/logo/..%2Fetc")
    assert resp.status_code in (400, 404, 422)
