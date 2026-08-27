"""ntfy.sh push channel — the zero-setup fallback for phone notifications.

Web Push (push.py) is the primary channel because the notification then belongs to our
own app. It needs an HTTPS origin and an installed PWA. ntfy needs neither: install the
free ntfy app, subscribe to a topic, and any HTTP POST to that topic pops up on the
phone. That makes it the channel that works on the very first day and the safety net
when the PWA install is gone (new phone, cleared data, reinstalled app).

Transport is stdlib urllib — same rule as telegram_client.py, no new dependency for a
plain POST. The topic acts as the secret: anyone who knows it can post to it, so it is
configured via env (`NTFY_TOPIC`) and must be an unguessable string.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_SERVER = "https://ntfy.sh"
# ntfy priorities: 1 min .. 5 max. 4 (high) bypasses some Do-Not-Disturb setups; reserve it
# for things worth waking up for, keep the daily digest at default.
PRIORITY_DEFAULT = 3
PRIORITY_HIGH = 4


class NtfyError(RuntimeError):
    """Delivery to the ntfy server failed."""


def load_config(env: dict | None = None) -> dict | None:
    """`NTFY_TOPIC` (required) + `NTFY_SERVER` (optional). None = channel not configured,
    which is a normal state, never an error."""
    source = os.environ if env is None else env
    topic = (source.get("NTFY_TOPIC") or "").strip()
    if not topic:
        return None
    return {
        "topic": topic,
        "server": (source.get("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/"),
    }


def send(
    *,
    topic: str,
    title: str,
    body: str,
    server: str = DEFAULT_SERVER,
    url: str | None = None,
    priority: int = PRIORITY_DEFAULT,
    tags: list[str] | None = None,
    opener: object | None = None,
) -> None:
    """POST one notification. `url` becomes a tap-through link back into the cockpit."""
    payload: dict = {
        "topic": topic,
        "title": title,
        "message": body,
        "priority": priority,
    }
    if tags:
        payload["tags"] = tags
    if url:
        # "view" action = a button; click= makes the whole notification tappable. Both,
        # because on Android the notification body itself is the bigger target.
        payload["click"] = url
        payload["actions"] = [{"action": "view", "label": "Im Cockpit öffnen", "url": url}]
    request = urllib.request.Request(
        server,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    open_url = opener if opener is not None else urllib.request.urlopen
    try:
        with open_url(request, timeout=15) as response:  # type: ignore[operator]
            status = getattr(response, "status", 200)
            if status >= 300:
                raise NtfyError(f"ntfy antwortete mit HTTP {status}")
    except urllib.error.HTTPError as err:
        raise NtfyError(f"ntfy HTTP {err.code}: {err.reason}") from err
    except urllib.error.URLError as err:
        raise NtfyError(f"ntfy nicht erreichbar: {err.reason}") from err
