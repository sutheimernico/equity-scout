"""Layer 1 of the catalyst radar: find the moves that are happening RIGHT NOW (v16).

Pure decision logic — the runner owns every network call and every write.

The job: turn a market-wide screener claim into either a signal we stand behind or a
rejection with a reason. Both are recorded, because the rejections are the only data that
can ever answer "were the thresholds right?".

## Why the filter chain is ordered the way it is

Cheapest and most decisive first, so a scan spends no effort on symbols that can never
qualify. The order also encodes what we learned by measuring on 2026-08-19:

1. `unknown_asset` / `not_tradable` — the broker cannot buy it, nothing else matters.
2. `instrument_type` — warrants, rights, units and leveraged ETFs are all flagged tradable
   by the broker, so ONLY the name distinguishes them (TNONW "Tenon Medical Warrant" and
   MRNX "Defiance Daily Target 2X Long MRNA ETF" both sat in the top 10 gainers). A 2x ETF
   on the very stock that jumped is not an independent opportunity, it is the same bet with
   decay attached.
3. `price_floor` — sub-$3 names move in percentages that mean nothing (a 0.029 $ ticker was
   "+276 %" on a half-cent tick).
4. `unverified` / `stale_listing` / `claim_mismatch` — the screener's own percent_change is
   a CLAIM. FIXX was reported at +1378 % while its bars said +7 %, because the endpoint
   divided by a stale close; its last minute bar was from 2024-03-25. Nothing passes here
   without independent bar confirmation.
5. `below_move` — the actual, verified move has to clear the bar.
6. `thin_dollar_volume` / `no_volume_confirmation` — a jump nobody traded is a quote
   artefact. The ratio compares today against yesterday IN THE SAME FEED; absolute IEX
   volume is meaningless (IEX sees 2-3 % of the tape).
7. `spread_unusable` — last, because it is the least reliable measurement we have (below).

## The spread caveat that shapes this module

We can only see IEX quotes; SIP is 403 on this plan. IEX spreads are systematically WIDER
than the real NBBO — MRNA showed 400 bp on IEX on the day it traded 120 million shares,
where the true spread was certainly a fraction of that. So the spread gate is deliberately
loose: it exists to throw out genuine garbage (ZSTK at 2584 bp), NOT to fine-tune entry
cost. The real protection against paying a bad spread is the entry being a LIMIT order
(see st_ignition), never this threshold. Every signal carries its measured spread so the
nightly review can compare it against the fill actually achieved.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MIN_PRICE = 3.0
MIN_MOVE = 0.07               # verified move against previous close
MIN_VOLUME_RATIO = 3.0        # today's volume vs. yesterday's, same feed
MIN_DOLLAR_VOLUME = 500_000.0  # today's IEX dollar volume; ~20-25 M $ on the full tape
MAX_SPREAD_BP = 600.0         # garbage filter only — see module docstring
CLAIM_TOLERANCE = 0.5         # screener claim may deviate this much (relative) from bars
MAX_MINUTE_AGE_HOURS = 24     # a listing whose last print is older is dead, not moving

# Names that are not an independent opportunity even when the broker calls them tradable.
#
# The rule is "ordinary equity only", and it is deliberately blunt. Verified on the live
# scan of 2026-08-19: of 100 screener candidates, 58 were excluded here — warrants, rights,
# and a long tail of derivative products written ON the very stock that moved (MRNX
# "Defiance Daily Target 2X Long MRNA ETF", MRNY "YieldMax MRNA Option Income Strategy
# ETF"). Those carry no information MRNA itself does not already carry, and they add decay,
# a thinner book and a wider spread on top. Chasing a fund's name-by-name issuer list
# (YieldMax, Defiance, Direxion, ProShares, GraniteShares, …) is a losing game, so any
# pooled vehicle is out: an ETF/ETN/fund that jumps 100 % IS a leveraged or option overlay
# on something else by construction.
#
# Excluding them costs no sight: the exclusion is written to the rejection book with the
# instrument name, so a pooled vehicle that moved is still visible in the calibration data.
# Word-boundary matched, because substring matching is wrong here: " trust" hides inside
# "Trustmark Corporation" (an ordinary bank) and " unit" inside "United". Verified by test.
_EXCLUDED_WORDS = (
    "warrant", "warrants", "right", "rights", "unit", "units",
    "etf", "etfs", "etn", "etns", "fund", "funds", "trust", "trusts",
    "2x", "3x", "1x", "inverse", "leveraged",
)
# Substring matched — these are unambiguous product names, not ordinary English words.
_EXCLUDED_PHRASES = (
    "ultrashort", "ultra short", "ultrapro", "proshares", "yieldmax",
    "daily target", "option income", "covered call", "index-linked", "notes due",
)

_EXCLUDED_WORD_RE = re.compile(r"\b(?:" + "|".join(_EXCLUDED_WORDS) + r")\b")

_NY = ZoneInfo("America/New_York")

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"


def _is_excluded_instrument(name: str) -> bool:
    lowered = name.lower()
    if any(phrase in lowered for phrase in _EXCLUDED_PHRASES):
        return True
    return bool(_EXCLUDED_WORD_RE.search(lowered))


def _minute_age_hours(minute_at: str | None, now: datetime) -> float | None:
    """Hours since the symbol's last minute bar; None when unparseable/absent."""
    if not minute_at:
        return None
    try:
        stamp = datetime.fromisoformat(str(minute_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - stamp).total_seconds() / 3600.0


def move_bucket(move: float) -> int:
    """Bucket a move into 10-point steps for the dedup key.

    Why bucketed instead of exact: the scan runs every minute, and an ignition keeps
    ignoring for hours. An exact move would create a new row (and a new alert) every single
    minute; a bucket re-fires only when the move genuinely escalates — +12 % and +19 % share
    a bucket, +12 % and +34 % do not.
    """
    return int(abs(move) * 10)


def score_ignition(
    *, move: float, volume_ratio: float, spread_bp: float, sip_active: bool
) -> float:
    """0..1 conviction. Deliberately simple and monotone — no fitted weights.

    Nothing here is calibrated against outcomes, because no outcomes exist yet. It exists to
    RANK today's candidates against each other so the caps pick the strongest, and it must
    not be read as a probability. Once the lane has closed trades, this is the first thing
    that should be replaced by something measured.
    """
    move_part = min(abs(move) / 0.30, 1.0)          # saturates at +/-30 %
    volume_part = min(volume_ratio / 20.0, 1.0)      # saturates at 20x
    spread_part = max(0.0, 1.0 - spread_bp / MAX_SPREAD_BP)
    breadth_part = 1.0 if sip_active else 0.0
    return round(
        0.40 * move_part + 0.30 * volume_part + 0.20 * spread_part + 0.10 * breadth_part, 4
    )


def pick_ignitions(
    gainers: list[dict],
    losers: list[dict],
    most_actives: dict[str, dict],
    snapshots: dict[str, dict],
    quotes: dict[str, dict],
    assets: dict[str, dict],
    *,
    now: datetime,
    min_move: float = MIN_MOVE,
    min_volume_ratio: float = MIN_VOLUME_RATIO,
    max_spread_bp: float = MAX_SPREAD_BP,
    min_price: float = MIN_PRICE,
    min_dollar_volume: float = MIN_DOLLAR_VOLUME,
) -> tuple[list[dict], list[dict]]:
    """(signals, rejections) — pure, no I/O.

    Losers are scanned too and recorded as `direction='down'`: a crash is a catalyst Nico
    wants to SEE, and the radar's job is sight. Whether anything is traded is the lane's
    decision, not this function's.
    """
    day_key = now.astimezone(_NY).date().isoformat()
    stamp = now.isoformat(timespec="seconds")

    signals: list[dict] = []
    rejections: list[dict] = []
    seen: set[str] = set()

    candidates = (
        [(row, DIRECTION_UP) for row in gainers]
        + [(row, DIRECTION_DOWN) for row in losers]
    )

    for row, direction in candidates:
        ticker = row["symbol"]
        if ticker in seen:
            continue
        seen.add(ticker)

        def _reject(reason: str, detail: str) -> None:
            # seen_at is the NY trading DAY, not the timestamp: a minute-cadence scan would
            # otherwise write the same rejection 390 times a session.
            rejections.append({
                "source": "scan", "ticker": ticker, "reason": reason,
                "seen_at": day_key, "detail": detail,
            })

        asset = assets.get(ticker)
        if asset is None:
            _reject("unknown_asset", "nicht in der Handelsliste des Brokers")
            continue
        if not asset["tradable"]:
            _reject("not_tradable", f"{asset['name'][:60]}: beim Broker nicht handelbar")
            continue
        if _is_excluded_instrument(asset["name"]):
            _reject("instrument_type", f"{asset['name'][:60]}: Warrant/Recht/Hebelprodukt")
            continue

        snap = snapshots.get(ticker)
        if snap is None:
            _reject("unverified", f"Screener meldet {row['percent_change']:+.1f} %, "
                                  "aber keine Bars zur Gegenprüfung")
            continue
        if snap["price"] < min_price:
            _reject("price_floor", f"Kurs {snap['price']:.2f} $ unter {min_price:.0f} $")
            continue

        age = _minute_age_hours(snap.get("minute_at"), now)
        if age is None or age > MAX_MINUTE_AGE_HOURS:
            _reject("stale_listing",
                    f"letzter Kurs vor {age:.0f} h" if age is not None
                    else "kein verwertbarer letzter Kurs")
            continue

        verified_move = snap["price"] / snap["prev_close"] - 1.0
        claimed = row["percent_change"] / 100.0
        # Relative deviation against the LARGER magnitude: an absolute tolerance would pass
        # the FIXX case (+1378 % claimed vs +7 % measured) as "both are big numbers".
        reference = max(abs(claimed), abs(verified_move))
        if reference > 0 and abs(claimed - verified_move) / reference > CLAIM_TOLERANCE:
            _reject("claim_mismatch",
                    f"Screener {claimed:+.1%}, Bars {verified_move:+.1%} — "
                    "Screener rechnet gegen veralteten Schlusskurs")
            continue

        if abs(verified_move) < min_move:
            _reject("below_move", f"Bewegung {verified_move:+.1%} unter Schwelle "
                                  f"{min_move:.0%}")
            continue

        dollar_volume = snap["volume"] * snap["price"]
        if dollar_volume < min_dollar_volume:
            _reject("thin_dollar_volume",
                    f"nur {dollar_volume / 1000:.0f} k$ Umsatz (IEX-Anteil)")
            continue

        prev_volume = snap["prev_volume"]
        if prev_volume <= 0:
            _reject("no_volume_confirmation", "kein Vortagesvolumen zum Vergleich")
            continue
        volume_ratio = snap["volume"] / prev_volume
        if volume_ratio < min_volume_ratio:
            _reject("no_volume_confirmation",
                    f"Volumen nur {volume_ratio:.1f}x Vortag (Schwelle "
                    f"{min_volume_ratio:.0f}x)")
            continue

        quote = quotes.get(ticker)
        if quote is None:
            _reject("no_quote", "kein handelbarer Bid/Ask")
            continue
        if quote["spread_bp"] > max_spread_bp:
            _reject("spread_unusable",
                    f"Spanne {quote['spread_bp']:.0f} bp — nicht handelbar")
            continue

        sip_active = ticker in most_actives
        score = score_ignition(
            move=verified_move, volume_ratio=volume_ratio,
            spread_bp=quote["spread_bp"], sip_active=sip_active,
        )
        arrow = "▲" if direction == DIRECTION_UP else "▼"
        detail = (
            f"{arrow} {verified_move:+.1%} bei {volume_ratio:.0f}x Volumen, "
            f"Spanne {quote['spread_bp']:.0f} bp"
            + (", marktweit unter den aktivsten Titeln" if sip_active else "")
        )
        signals.append({
            "source": "scan",
            "ticker": ticker,
            "kind": f"ignition_{direction}",
            "seen_at": stamp,
            "dedup_key": f"scan:{ticker}:{day_key}:{direction}:{move_bucket(verified_move)}",
            "score": score,
            "ref_price": round(snap["price"], 4),
            "change_pct": round(verified_move, 4),
            "volume_ratio": round(volume_ratio, 2),
            "spread_bp": round(quote["spread_bp"], 1),
            "detail": f"{asset['name'][:48]}: {detail}",
        })

    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals, rejections


def candidate_symbols(gainers: list[dict], losers: list[dict]) -> list[str]:
    """Symbols worth a verification call — the runner's input for snapshots/quotes.

    Kept separate from pick_ignitions so the runner can fetch once for both directions and
    the decision logic stays free of I/O ordering concerns.
    """
    out: list[str] = []
    for row in [*gainers, *losers]:
        symbol = row.get("symbol")
        if symbol and symbol not in out:
            out.append(symbol)
    return out


def alertable(
    signals: list[dict],
    last_alert_by_ticker: dict[str, str],
    *,
    now: datetime,
    min_score: float = 0.45,
    cooldown_hours: float = 6.0,
) -> list[dict]:
    """Which signals earn a push to Nico's phone.

    Two gates, both about not becoming noise: a score floor, and a per-ticker cooldown so a
    stock that ignites and keeps running does not buzz every escalation step. A radar that
    cries wolf gets muted, and a muted radar is the same as no radar.
    """
    out = []
    for signal in signals:
        if signal["score"] < min_score:
            continue
        last = last_alert_by_ticker.get(signal["ticker"])
        if last:
            try:
                last_at = datetime.fromisoformat(last)
            except ValueError:
                last_at = None
            if last_at and now - last_at < timedelta(hours=cooldown_hours):
                continue
        out.append(signal)
    return out
