"""Ignition lane (lane `ignition`, 2026-08-19): ride a verified catalyst move — a MEASUREMENT
lane, not a proven edge.

Pure decision logic; the runner owns all I/O and the order plumbing.

## What this lane can and cannot do

It cannot catch the jump. Moderna's Phase-3 readout was published before the open, so the
stock GAPPED +100 % — nobody who was not already positioned bought at yesterday's price. The
honest question a lane can ask is the next one: after a verified, volume-confirmed catalyst
move, does the stock CONTINUE far enough to pay for the spread? Post-event drift is a real
documented effect in the literature; whether it survives retail costs on our data is exactly
what has never been measured here.

So this lane exists to produce that measurement with real broker fills. Stop criterion: after
60 closed trades `significance.assess_trades` decides. A verdict of "negativ" ends the lane,
the way the ORB rule ended the session lane on 2026-08-17.

## The four rules that keep it from being a chase

1. **Chase protection.** An entry is refused once the move has run past `MAX_ENTRY_MOVE`.
   Buying a stock that is already +130 % on the day is not participation, it is providing
   exit liquidity to whoever bought at +20 %. This is the rule most likely to make the lane
   skip the spectacular cases — deliberately.
2. **Limit entry, never market.** The limit sits at bid + `LIMIT_SPREAD_FRACTION` of the
   spread, so we pay a quarter of the spread rather than all of it. A no-fill is a fine
   outcome; the position we do not take costs nothing.
3. **Hard caps.** One position per ticker, `MAX_POSITIONS` open, `MAX_ENTRIES_PER_DAY` new
   entries per day. Without the daily cap a single wild session could put the whole book
   into ignition names within an hour.
4. **Volume must still confirm at entry time.** The signal was verified when the scan wrote
   it, but the runner acts a minute or more later. A move whose volume has since dried up is
   no longer the same move.

## Exits

Trailing stop from the high-water mark, a hard stop from entry, and a time stop. No profit
target: capping the upside of a continuation trade removes the only outcome that could pay
for the losers. The trail is what takes profit.

Leverage stays at 1x (`ENTRY_FRACTION` of book value per position) even though the paper
account permits 4x. Multiplying an unmeasured expectancy is not a strategy — the parameter
is one line away once a verdict exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from equity_scout.shortterm_book import LaneBook

LANE = "ignition"

ENTRY_FRACTION = 0.10       # of book value per position; 1x leverage by decision
MAX_POSITIONS = 4
MAX_ENTRIES_PER_DAY = 3
MIN_SIGNAL_SCORE = 0.55     # only the strongest scan signals are worth a fill
MAX_ENTRY_MOVE = 0.35       # chase protection: refuse above this day move
MIN_ENTRY_MOVE = 0.07       # below this it is not an ignition
MIN_VOLUME_RATIO_AT_ENTRY = 3.0
MAX_SPREAD_BP_AT_ENTRY = 250.0  # tighter than the scan's sight threshold — we must trade it
LIMIT_SPREAD_FRACTION = 0.25    # limit = bid + this share of the spread

STOP_LOSS = 0.08            # hard stop from the effective entry price
TRAIL_PCT = 0.10            # trailing stop from the high-water mark
MAX_HOLD_DAYS = 5           # a catalyst that has not paid in a week is not paying

STOP_CRITERION_TRADES = 60  # significance.assess_trades decides after this many closes

_NY = ZoneInfo("America/New_York")


def limit_price(bid: float, ask: float, *, fraction: float = LIMIT_SPREAD_FRACTION) -> float:
    """Entry limit inside the spread: bid + `fraction` of the spread.

    At fraction=0.25 we offer a quarter of the spread instead of crossing it. On MRNA's
    400 bp spread that is 100 bp of cost instead of 400 — and if the offer is not hit, we
    simply do not own the stock.
    """
    if bid <= 0 or ask <= bid:
        return 0.0
    return round(bid + (ask - bid) * fraction, 2)


def target_prices(entry_price: float) -> tuple[float, float]:
    """(stop_price, target_price) for the broker bracket.

    The bracket needs a take-profit leg to be accepted, but this lane's real exit is the
    trailing stop evaluated by pick_exits. The leg is therefore placed far away — it is a
    backstop against a runaway print while we are not looking, not the intended exit.
    """
    return (
        round(entry_price * (1.0 - STOP_LOSS), 2),
        round(entry_price * (1.0 + TRAIL_PCT * 4.0), 2),
    )


def pick_entries(
    signals: list[dict],
    quotes: dict[str, dict],
    book: LaneBook,
    *,
    now: datetime,
    entries_today: int,
    traded_today: set[str],
    max_positions: int = MAX_POSITIONS,
    max_entries_per_day: int = MAX_ENTRIES_PER_DAY,
    min_score: float = MIN_SIGNAL_SCORE,
) -> tuple[list[dict], list[dict]]:
    """(picks, rejections) — pure, no I/O.

    `signals` are scan signals from the catalyst book, strongest first. Only upward
    ignitions are traded: this lane is long-only, and a crash is recorded by the radar for
    sight, not bought.
    """
    day_key = now.astimezone(_NY).date().isoformat()
    picks: list[dict] = []
    rejections: list[dict] = []
    free_slots = max(0, max_positions - len(book.positions))
    remaining_today = max(0, max_entries_per_day - entries_today)

    for signal in signals:
        ticker = signal["ticker"]

        def _reject(reason: str, detail: str) -> None:
            rejections.append({
                "source": "ignition", "ticker": ticker, "reason": reason,
                "seen_at": day_key, "detail": detail,
            })

        if signal.get("kind") != "ignition_up":
            continue  # downward moves are sight-only for a long-only lane
        if ticker in book.positions:
            _reject("already_held", "Position läuft bereits")
            continue
        if ticker in traded_today:
            continue  # one attempt per ticker per day; the day marker tells that story
        if signal.get("score", 0.0) < min_score:
            _reject("score_too_low",
                    f"Signalgüte {signal.get('score', 0):.2f} unter {min_score:.2f}")
            continue

        move = signal.get("change_pct") or 0.0
        if move > MAX_ENTRY_MOVE:
            _reject("chase_protection",
                    f"Bewegung {move:+.0%} schon zu weit gelaufen "
                    f"(Grenze {MAX_ENTRY_MOVE:.0%})")
            continue
        if move < MIN_ENTRY_MOVE:
            _reject("move_too_small", f"Bewegung {move:+.1%} zu klein")
            continue
        if (signal.get("volume_ratio") or 0.0) < MIN_VOLUME_RATIO_AT_ENTRY:
            _reject("volume_faded",
                    f"Volumen nur {signal.get('volume_ratio', 0):.1f}x — Bewegung "
                    "trägt nicht mehr")
            continue

        quote = quotes.get(ticker)
        if quote is None:
            _reject("no_quote", "kein aktueller Bid/Ask zur Orderzeit")
            continue
        if quote["spread_bp"] > MAX_SPREAD_BP_AT_ENTRY:
            _reject("spread_too_wide",
                    f"Spanne {quote['spread_bp']:.0f} bp über Handelsgrenze "
                    f"{MAX_SPREAD_BP_AT_ENTRY:.0f} bp")
            continue

        if len(picks) >= free_slots:
            _reject("cap_full", f"alle {max_positions} Plätze belegt")
            continue
        if len(picks) >= remaining_today:
            _reject("daily_cap", f"Tagesgrenze {max_entries_per_day} Einstiege erreicht")
            continue

        offer = limit_price(quote["bid"], quote["ask"])
        if offer <= 0:
            _reject("no_quote", "Bid/Ask nicht verwertbar")
            continue
        stop_price, target_price = target_prices(offer)
        picks.append({
            "ticker": ticker,
            "signal_id": signal.get("id"),
            "signal_price": signal.get("ref_price"),
            "limit_price": offer,
            "stop_price": stop_price,
            "target_price": target_price,
            "move": move,
            "reason": (
                f"Katalysator-Sprung {move:+.1%} bei "
                f"{signal.get('volume_ratio', 0):.0f}x Volumen — Limit {offer:.2f} $"
            ),
        })

    return picks, rejections


def pick_exits(
    book: LaneBook,
    prices: dict[str, float],
    high_water: dict[str, float],
    *,
    now: datetime,
) -> list[dict]:
    """Positions to close, with the German reason that goes into the trade log.

    A position without a current price is HELD untouched — the same stance as every other
    lane in this repo: you cannot honestly value a sale you have no price for.
    """
    exits: list[dict] = []
    for ticker, position in book.positions.items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        peak = max(high_water.get(ticker, position.entry_price), price)
        return_pct = price / position.entry_price - 1.0
        held_days = (now - datetime.fromisoformat(position.opened_at)).days

        if return_pct <= -STOP_LOSS:
            reason = f"Stop bei {return_pct:+.1%} gerissen"
        elif price <= peak * (1.0 - TRAIL_PCT) and peak > position.entry_price:
            reason = (
                f"Trailing-Stop: {TRAIL_PCT:.0%} unter Hoch {peak:.2f} $ "
                f"(Ergebnis {return_pct:+.1%})"
            )
        elif held_days >= MAX_HOLD_DAYS:
            reason = f"Zeitstop nach {held_days} Tagen ({return_pct:+.1%})"
        else:
            continue
        exits.append({"ticker": ticker, "price": price, "reason": reason,
                      "return_pct": return_pct})
    return exits


def update_high_water(
    high_water: dict[str, float], prices: dict[str, float], held: set[str]
) -> dict[str, float]:
    """Carry the per-position high-water mark forward; drop marks for closed positions.

    The trail is only honest if the peak survives process restarts, so the runner persists
    this — an in-memory peak would reset the trail every minute and never trigger.
    """
    out = {t: v for t, v in high_water.items() if t in held}
    for ticker in held:
        price = prices.get(ticker)
        if price and price > 0:
            out[ticker] = max(out.get(ticker, 0.0), price)
    return out


def stop_criterion_reached(closed_trades: int) -> bool:
    return closed_trades >= STOP_CRITERION_TRADES


def position_rule_text() -> str:
    """What the phone card shows for an open ignition position."""
    return (
        f"Stop bei −{STOP_LOSS:.0%} vom Einstieg, Trailing-Stop {TRAIL_PCT:.0%} unter dem "
        f"Höchstkurs, spätestens Verkauf nach {MAX_HOLD_DAYS} Handelstagen. "
        "Kein fester Zielkurs — der Trailing-Stop nimmt den Gewinn mit."
    )


def market_closing_soon(now: datetime, *, minutes: int = 10) -> bool:
    """True inside the last `minutes` before the US close.

    Used to stop opening NEW positions late in the session: an entry at 15:58 has no room to
    work before the trail would need a full session to mean anything.
    """
    local = now.astimezone(_NY)
    close = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return timedelta(0) <= close - local <= timedelta(minutes=minutes)
