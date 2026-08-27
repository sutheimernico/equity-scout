"""Web Push (RFC 8030 + VAPID) — the channel that pops up on the phone as OUR app.

Why a second channel next to Telegram: a Telegram message is a message in a chat app.
Nico asked for the notification to come *from the app* (2026-08-27), which on Android
means a Web Push subscription owned by the installed PWA/TWA. The push travels
browser-vendor -> phone, so it arrives even while the phone's screen is off and even
though this backend is a laptop behind a Tailnet — the only requirement is that the
laptop can make an OUTBOUND request at send time.

Keys: a VAPID keypair identifies this server to the push service. It is generated once
and cached in `.state/vapid.json` (gitignored, like every other runtime state file) so
a restart does not invalidate every subscription. `VAPID_PRIVATE_KEY_PEM` overrides it
for anyone who wants to manage the key elsewhere.

Send seam: `send` is injected (default `pywebpush.webpush`) so tests never touch the
network — same rule as the Telegram client.
"""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from equity_scout.constants import DEFAULT_DB_PATH
from equity_scout.push_storage import (
    delete_subscription,
    list_subscriptions,
    record_failure,
    record_success,
)

DEFAULT_KEY_PATH = ".state/vapid.json"
# The push service wants a contact for the server operator. It is never shown to anyone;
# a mailto: URI is what the spec asks for and Chrome/Mozilla both accept this form.
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:equity-scout@localhost")
# TTL: how long the push service holds an undelivered message. A market opportunity is
# stale within the trading day, so a message that could not be delivered for 6 hours is
# better dropped than shown at midnight as if it were news.
DEFAULT_TTL_SECONDS = 6 * 3600


class PushError(RuntimeError):
    """A push send failed. Carries the push service's own status code when there is one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class VapidKeys:
    private_pem: str
    public_key: str  # base64url, unpadded — what the browser passes as applicationServerKey


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_keys() -> VapidKeys:
    """Fresh P-256 keypair. Public half is the uncompressed point (65 bytes), which is the
    only encoding `PushManager.subscribe` accepts."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    point = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return VapidKeys(private_pem=pem, public_key=_b64url(point))


def load_or_create_keys(path: str = DEFAULT_KEY_PATH) -> VapidKeys:
    """Env override > cached file > freshly generated (and cached).

    Rotating the key silently invalidates every existing subscription, so the cache file
    is the point of this function: it must survive restarts and redeploys.
    """
    env_pem = os.environ.get("VAPID_PRIVATE_KEY_PEM")
    env_pub = os.environ.get("VAPID_PUBLIC_KEY")
    if env_pem and env_pub:
        return VapidKeys(private_pem=env_pem, public_key=env_pub)

    file = Path(path)
    if file.exists():
        try:
            payload = json.loads(file.read_text())
            return VapidKeys(
                private_pem=payload["private_pem"], public_key=payload["public_key"]
            )
        except (json.JSONDecodeError, KeyError):
            # A corrupt cache is not worth crashing over, but it IS worth being loud about:
            # regenerating means every phone must re-subscribe.
            print(f"Warnung: {path} unlesbar — neuer VAPID-Schlüssel, Handys müssen neu abonnieren")

    keys = generate_keys()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"private_pem": keys.private_pem, "public_key": keys.public_key}))
    file.chmod(0o600)
    return keys


def build_payload(
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
    urgency: str = "normal",
) -> str:
    """The JSON the service worker receives. Kept flat and small: push services cap the
    encrypted payload around 4 KB, and the worker only needs enough to render one line."""
    payload = {"title": title, "body": body, "url": url, "urgency": urgency}
    if tag:
        # A tag makes a repeat notification REPLACE the previous one instead of stacking.
        # Same ticker twice in a day should be one line on the lock screen, not two.
        payload["tag"] = tag
    return json.dumps(payload, ensure_ascii=False)


def _subscription_info(row: dict) -> dict:
    return {
        "endpoint": row["endpoint"],
        "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
    }


def _default_send(subscription_info: dict, payload: str, keys: VapidKeys, ttl: int) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=keys.private_pem,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=ttl,
            timeout=15,
        )
    except WebPushException as err:  # pragma: no cover - network path
        status = getattr(getattr(err, "response", None), "status_code", None)
        raise PushError(str(err), status=status) from err


# 404 = the endpoint never existed, 410 = the browser revoked it (app uninstalled, data
# cleared). Both are permanent: retrying forever would keep a dead row alive and make the
# health line lie about how many phones are actually reachable.
GONE_STATUSES = frozenset({404, 410})


def broadcast(
    payload: str,
    *,
    db_path: str = DEFAULT_DB_PATH,
    send: Callable[[dict, str, VapidKeys, int], None] | None = None,
    keys: VapidKeys | None = None,
    ttl: int = DEFAULT_TTL_SECONDS,
    now: str | None = None,
) -> dict:
    """Send one payload to every registered device. Returns a per-device summary.

    Never raises: one dead phone must not stop the other from being told about a trading
    opportunity, and the caller (a cron job) has nowhere useful to put an exception.
    """
    sender = send or _default_send
    vapid = keys or load_or_create_keys()
    stamp = now or datetime.now(timezone.utc).isoformat()
    rows = list_subscriptions(db_path)
    sent, failed, removed = 0, 0, 0
    errors: list[str] = []
    for row in rows:
        try:
            sender(_subscription_info(row), payload, vapid, ttl)
        except PushError as err:
            if err.status in GONE_STATUSES:
                delete_subscription(db_path, row["endpoint"])
                removed += 1
            else:
                record_failure(db_path, row["endpoint"], error=str(err))
                failed += 1
                errors.append(f"{row['endpoint'][:40]}…: {err}")
            continue
        except Exception as err:  # noqa: BLE001 - transport can raise anything
            record_failure(db_path, row["endpoint"], error=str(err))
            failed += 1
            errors.append(f"{row['endpoint'][:40]}…: {err}")
            continue
        record_success(db_path, row["endpoint"], at=stamp)
        sent += 1
    return {
        "devices": len(rows),
        "sent": sent,
        "failed": failed,
        "removed": removed,
        "errors": errors,
    }


def notify(
    *,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
    urgency: str = "normal",
    db_path: str = DEFAULT_DB_PATH,
    send: Callable[[dict, str, VapidKeys, int], None] | None = None,
) -> dict:
    """Convenience wrapper: build the payload and broadcast it."""
    return broadcast(
        build_payload(title=title, body=body, url=url, tag=tag, urgency=urgency),
        db_path=db_path,
        send=send,
    )
