"""One alert, every configured channel — Telegram, Web Push, ntfy.

Before this module every sender wired Telegram by hand, so adding a phone channel meant
editing every call site. `deliver()` is the single fan-out: callers describe WHAT
happened, this decides WHERE it goes. Each channel is independent — a dead Telegram token
must never cost the phone push, and vice versa — so every send is caught and reported
rather than raised.

The three channels are deliberately not equivalent:
- **Telegram** carries the long form (HTML, decision buttons, charts). Unchanged.
- **Web Push** is the lock-screen line from our own app: title + one sentence + deep link.
- **ntfy** is the fallback that needs no HTTPS origin and no app install.

Deep links are absolute when `PUBLIC_BASE_URL` is set (the phone taps a notification while
the cockpit is not open, so a relative path has nothing to resolve against).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from equity_scout import ntfy, push
from equity_scout.constants import DEFAULT_DB_PATH


@dataclass(frozen=True)
class Alert:
    """What happened, in the two lengths the channels need."""

    title: str
    body: str  # one or two sentences — the lock-screen line
    url: str = "/"  # relative deep link into the cockpit
    tag: str | None = None  # repeat alerts with the same tag replace each other
    high_priority: bool = False
    telegram_html: str | None = None  # long form; None = do not send to Telegram
    emoji_tags: list[str] = field(default_factory=list)  # ntfy icon tags


def public_url(path: str) -> str:
    """Absolute cockpit URL when we know our public origin, else the raw path.

    A notification is tapped from the lock screen, where there is no page to resolve a
    relative URL against — so an unset PUBLIC_BASE_URL degrades to "opens the app at its
    start page", never to a broken link.
    """
    base = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if not base:
        return path
    return f"{base}{path if path.startswith('/') else '/' + path}"


def deliver(
    alert: Alert,
    *,
    db_path: str = DEFAULT_DB_PATH,
    env: dict | None = None,
    send_telegram=None,
    send_push=None,
    send_ntfy=None,
) -> dict:
    """Fan the alert out. Returns `{channel: status}` — never raises."""
    source = os.environ if env is None else env
    report: dict = {}

    # --- Telegram (long form) -------------------------------------------------------
    if alert.telegram_html is not None:
        report["telegram"] = _telegram(alert, source, send_telegram)

    # --- Web Push (our own app) -----------------------------------------------------
    push_send = send_push or push.notify
    try:
        result = push_send(
            title=alert.title,
            body=alert.body,
            url=public_url(alert.url),
            tag=alert.tag,
            urgency="high" if alert.high_priority else "normal",
            db_path=db_path,
        )
        report["webpush"] = result
    except Exception as err:  # noqa: BLE001 - a broken channel must not stop the others
        report["webpush"] = {"error": str(err)}

    # --- ntfy (fallback) ------------------------------------------------------------
    config = ntfy.load_config(source)
    if config is None:
        report["ntfy"] = {"skipped": "kein NTFY_TOPIC gesetzt"}
    else:
        ntfy_send = send_ntfy or ntfy.send
        try:
            ntfy_send(
                topic=config["topic"],
                server=config["server"],
                title=alert.title,
                body=alert.body,
                url=public_url(alert.url),
                priority=ntfy.PRIORITY_HIGH if alert.high_priority else ntfy.PRIORITY_DEFAULT,
                tags=alert.emoji_tags or None,
            )
            report["ntfy"] = {"sent": 1}
        except Exception as err:  # noqa: BLE001
            report["ntfy"] = {"error": str(err)}
    return report


def _telegram(alert: Alert, source: dict, send_telegram) -> dict:
    from equity_scout.telegram_client import (
        TelegramError,
        load_telegram_config,
        send_message,
    )

    config = load_telegram_config(dict(source))
    if config is None:
        return {"skipped": "kein Telegram-Token"}
    sender = send_telegram or send_message
    try:
        message_id = sender(
            config["token"],
            config.get("daily_chat_id", config["chat_id"]),
            alert.telegram_html,
        )
        return {"sent": 1, "message_id": message_id}
    except TelegramError as err:
        return {"error": str(err)}
    except Exception as err:  # noqa: BLE001
        return {"error": str(err)}
