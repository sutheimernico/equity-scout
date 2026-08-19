"""Point-in-time catalyst features for the entry model (v17, spec §4 "ML — die Datengrundlage").

The 207 trained entry versions saw eleven columns, all of them price and momentum, and not one
cleared the promotion bar. The W0 study (2026-08-11) says why that is not a tuning problem:
return is not recoverable from chart shape at our data volume. So the lever is a NEW information
source, and this module supplies the one the short-term traders already act on — the catalyst.

Two producers feed one block:

* **the local news archive** (`data/news/news-YYYY.csv.gz`, second-resolution Benzinga wire) run
  through the SAME classifier the live radar uses (`catalyst_news.classify_catalyst`). This is the
  historical spine: ten years deep, so a training row from 2018 gets the same kind of reading a
  live row gets today.
* **`catalysts.db`** (`catalyst_signals`), which adds what the archive cannot carry — the scan
  layer's VERIFIED move, volume ratio and measured spread, plus the calendar layer's dated
  upcoming catalysts. That table started on 2026-08-19, so its historical contribution is
  effectively nil; it exists here so the live scoring path reads the same block, not because it
  adds training coverage. Read `coverage()` before reading any AUC — the P3 evidence round looked
  like a +0.003 improvement until coverage turned out to be 2.5 %.

Built as a deliberate copy of `evidence_features.EvidenceIndex` / `volume_features.VolumeIndex`:
same constructor seam, same `features(ticker, as_of)` signature, same additive contract, so a
reader who knows one knows all three and `build_backfill_dataset` needs no new concepts.

## Point-in-time rule (the expensive one)

A catalyst counts only when it became PUBLICLY KNOWABLE strictly before `as_of`. Three
consequences, each of them load-bearing:

1. The timestamp used is the wire's `created_at` / the signal's `seen_at` — when we could have
   read it — never an event date. A merger announced on Monday about a deal signed Friday is a
   Monday catalyst.
2. UTC timestamps are converted to `MARKET_TZ` before the date comparison. 2020-05-01T01:00Z is
   2020-04-30 21:00 in New York, i.e. the PREVIOUS trading date; taking the UTC date would move
   roughly one in six overnight items forward by a day, always in the leaking direction.
3. Windows are half-open `(as_of - window, as_of)` — an item stamped ON `as_of` is excluded, as in
   `evidence_features`. Same-day wire items are readable in principle, but only with intraday
   alignment we do not carry here; the conservative side costs at most one day of recency and
   cannot manufacture an edge.

The reaction move (`cat_last_move`) is the one value that legitimately uses `as_of`'s own close:
it is the stock's close-to-close return on the session that first traded on the news, and
`entry_features.build_feature_row` already reads closes up to and including `as_of`. It is still
guarded explicitly (`move_on <= as_of`) rather than argued about, so a caller passing an
unusual `as_of` cannot slip a future session in.

## Why every kind counts, weak ones included

`analyst_action` is 11 399 of the 19 383 classified archive articles — more than half. The live
radar filters those out below `MIN_STRENGTH` because they are not worth an alert on Nico's phone;
that is an ALERTING decision, not a feature one. Analyst intensity is real attention data, and
`cat_last_strength` / `cat_max_strength_30d` carry the quality distinction the model can split on.
Dropping half the sample to reuse an alerting threshold would be a silent, unmeasured choice.

One story per class per day per ticker: the same deal is re-reported by several outlets, and
counting each re-publication would inflate `cat_count_30d` by the republication factor —
`news_history.dedupe_news` guards the same trap one layer down.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from equity_scout import db as db_module
from equity_scout.catalyst_news import MAX_SYMBOLS_PER_ARTICLE, classify_catalyst
from equity_scout.catalyst_storage import DEFAULT_CATALYST_DB_PATH, SOURCE_CALENDAR
from equity_scout.data.news_history import DATA_BASE_PATH, load_news
from equity_scout.market_hours import MARKET_TZ

# Ordered, single-sourced layout — the reason `FEATURE_COLUMNS` is a tuple and not a comment:
# the dataset builder and the fitted model must never disagree about the column order.
CATALYST_FEATURE_COLUMNS: tuple[str, ...] = (
    "cat_days_since",
    "cat_last_strength",
    "cat_last_move",
    "cat_count_30d",
    "cat_count_365d",
    "cat_max_strength_30d",
    "cat_volume_ratio",
    "cat_spread_bp",
    "cat_days_to_due",
)
# The column that answers "did this row see a catalyst at all" — the coverage question to read
# BEFORE any effect size, single-sourced so a window change cannot rot a magic string.
CATALYST_ACTIVE_COLUMN = "cat_count_30d"

# ~21 trading days: the window in which a catalyst is still the reason a stock is moving. Shorter
# than the evidence block's 91d on purpose — an insider CLUSTER is a slow accumulation signal, a
# headline is an event.
SHORT_WINDOW_DAYS = 30
# One calendar year — catalyst intensity, and the cap for "days since".
LONG_WINDOW_DAYS = 365
# The calendar layer's own horizon (`catalyst_calendar.DEFAULT_HORIZON_DAYS` is 90) — and the cap
# for "days until the next dated catalyst", so "nothing scheduled" and "scheduled far out" are
# the same reading rather than an arbitrary sentinel the model has to learn around.
DUE_HORIZON_DAYS = 90

_MARKET_ZONE = ZoneInfo(MARKET_TZ)
_CLOSE_TIME = time(16, 0)  # NYSE regular close; a wire item after it trades on the NEXT session

# A ticker with no catalyst history gets neutral values rather than being dropped: "nothing
# happened" is a FACT that was knowable at decision time, not a missing measurement. The two
# non-zero defaults are the window caps, so absence reads as "not within the window" instead of
# as an impossible zero-day recency.
NEUTRAL: dict[str, float] = {
    "cat_days_since": float(LONG_WINDOW_DAYS),
    "cat_last_strength": 0.0,
    "cat_last_move": 0.0,
    "cat_count_30d": 0.0,
    "cat_count_365d": 0.0,
    "cat_max_strength_30d": 0.0,
    "cat_volume_ratio": 0.0,
    "cat_spread_bp": 0.0,
    "cat_days_to_due": float(DUE_HORIZON_DAYS),
}


def _as_date(value: object) -> date:
    """Same strictness as `evidence_features._as_date` / `volume_features._as_date`: a null or
    tz-aware `as_of` would silently shift every window by up to a day, so it raises instead of
    picking a zone on the caller's behalf."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value  # a plain date has no time-of-day, hence no zone to mis-convert
    stamp = pd.Timestamp(value)  # type: ignore[arg-type]
    if stamp is pd.NaT:
        raise ValueError("as_of must not be None/NaT")
    if stamp.tzinfo is not None:
        raise ValueError(
            f"as_of must be tz-naive (exchange-local date); got tz-aware {value!r} — "
            "convert to the exchange-local date explicitly before calling"
        )
    return stamp.date()


def _market_stamp(value: object) -> tuple[date, bool]:
    """A wire timestamp as `(exchange-local date, after_close)` — see the module docstring's
    point-in-time rule 2 for why the conversion is mandatory rather than cosmetic.

    A naive timestamp is read as UTC: every producer writing into this path stores UTC
    (`news_history` parses with `utc=True`, the radar writes `...Z`/`+00:00`), so UTC is the
    documented format and not a guess. Raises on an unparsable value — a guessed catalyst date
    is worse than a missing catalyst.
    """
    stamp = pd.Timestamp(value)  # type: ignore[arg-type]
    if stamp is pd.NaT:
        raise ValueError(f"unparsable catalyst timestamp {value!r}")
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(timezone.utc)
    local = stamp.tz_convert(_MARKET_ZONE)
    return local.date(), local.time() >= _CLOSE_TIME


@dataclass(frozen=True)
class CatalystEvent:
    """One catalyst as the feature block needs it.

    `on` is the KNOWABILITY date (exchange-local), never an event date. `move`/`move_on` are the
    verified reaction on the first session that could trade on it — 0.0/None while unmeasured,
    which is the honest state for an archive row until a price frame is attached.

    Same mutability caveat as `EvidenceIndex`: frozen freezes the field binding, not what the
    fields point at.
    """

    on: date
    after_close: bool
    kind: str
    strength: float
    move: float = 0.0
    move_on: date | None = None
    volume_ratio: float = 0.0
    spread_bp: float = 0.0


def _dedupe(entries: list[CatalystEvent]) -> list[CatalystEvent]:
    """One event per (date, kind), sorted by date — see the module docstring on republication.

    Tie-break is `(-strength, -|move|)`, so a scan row carrying a verified move beats a bare
    headline of the same class on the same day instead of the order the loaders happened to run in.
    """
    best: dict[tuple[date, str], CatalystEvent] = {}
    for event in sorted(entries, key=lambda e: (-e.strength, -abs(e.move))):
        best.setdefault((event.on, event.kind), event)
    return sorted(best.values(), key=lambda e: e.on)


def catalyst_events_from_news(news: pd.DataFrame) -> dict[str, list[CatalystEvent]]:
    """Classified catalysts per ticker from a loaded news frame — pure, no I/O, no network.

    Applies the live radar's roundup filter (`MAX_SYMBOLS_PER_ARTICLE`): an item tagged with more
    symbols than that is market commentary ("10 stocks to watch"), and letting it through would
    stamp a catalyst on every name it mentions. Measured on the archive, that filter drops 46 940
    of 262 953 rows.
    """
    events: dict[str, list[CatalystEvent]] = {}
    if news.empty:
        return events
    for stamp, symbols_raw, headline in zip(
        news["created_at"], news["symbols"], news["headline"], strict=True
    ):
        symbols = [s.strip().upper() for s in str(symbols_raw).split(",") if s.strip()]
        if not symbols or len(symbols) > MAX_SYMBOLS_PER_ARTICLE:
            continue
        classified = classify_catalyst(str(headline))
        if classified is None:
            continue  # the overwhelming majority: ordinary commentary
        kind, strength, _phrase = classified
        on, after_close = _market_stamp(stamp)
        for symbol in symbols:
            events.setdefault(symbol, []).append(
                CatalystEvent(on=on, after_close=after_close, kind=kind, strength=float(strength))
            )
    return {ticker: _dedupe(entries) for ticker, entries in events.items()}


def _float(value: object, default: float = 0.0) -> float:
    """A stored REAL as a usable float — NULL and non-finite both mean "not measured"."""
    if value is None:
        return default
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def catalyst_events_from_db(
    db_path: str | Path = DEFAULT_CATALYST_DB_PATH,
) -> tuple[dict[str, list[CatalystEvent]], dict[str, list[tuple[date, date]]]]:
    """`(events, due_dates)` from `catalyst_signals` — the live radar's own record.

    `due_dates` maps ticker -> [(known_on, due_on)], carrying BOTH dates because a scheduled
    catalyst is only usable once the calendar entry itself existed: `known_on` is when the radar
    saw the date, `due_on` is the date itself. Without the first, a 2026 calendar row would put a
    2019 training row on notice about a readout nobody had announced.

    A MISSING FILE warns and returns empty: the news archive is the historical spine and stays
    usable without the live DB, and `db.connect` would otherwise create an empty file as a side
    effect of a read. An EXISTING file without the table raises — that is a wrong path, and an
    empty result from it is too easy to mistake for the honest "no catalysts" case.

    `change_pct` is stored as a FRACTION despite its name (`catalyst_scan` formats it with `%`),
    so it is directly comparable to the archive-derived close-to-close move.
    """
    path = Path(db_path)
    if not path.exists():
        print(f"WARNUNG: {path} fehlt — Katalysator-Block nutzt nur das News-Archiv.")
        return {}, {}
    with db_module.connect(str(path)) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'catalyst_signals'"
        ).fetchone()
        if table_exists is None:
            raise ValueError(f"catalyst_signals table not found in {str(path)!r} — wrong db_path?")
        rows = conn.execute(
            "SELECT source, ticker, kind, seen_at, score, change_pct, volume_ratio, spread_bp, "
            "due_date FROM catalyst_signals"
        ).fetchall()

    events: dict[str, list[CatalystEvent]] = {}
    due: dict[str, list[tuple[date, date]]] = {}
    skipped = 0
    for source, ticker, kind, seen_at, score, change_pct, volume_ratio, spread_bp, due_date in rows:
        try:
            on, after_close = _market_stamp(seen_at)
        except ValueError:
            skipped += 1
            continue  # a signal we cannot date is not a feature; counted, never guessed
        symbol = str(ticker).strip().upper()
        if due_date:
            try:
                due.setdefault(symbol, []).append((on, date.fromisoformat(str(due_date)[:10])))
            except ValueError:
                skipped += 1
        if source == SOURCE_CALENDAR:
            # A calendar row is a diary entry, not something that happened — it must supply lead
            # time only. Counting it as a past catalyst would put every waiting ticker on the
            # same footing as one that actually moved.
            continue
        move = _float(change_pct)
        events.setdefault(symbol, []).append(
            CatalystEvent(
                on=on,
                after_close=after_close,
                kind=str(kind),
                strength=_float(score),
                move=move,
                move_on=on if move else None,
                volume_ratio=_float(volume_ratio),
                spread_bp=_float(spread_bp),
            )
        )
    if skipped:
        print(f"{skipped} von {len(rows)} Katalysator-Zeilen übersprungen (Datum unlesbar).")
    for entries in due.values():
        entries.sort()
    return {ticker: _dedupe(entries) for ticker, entries in events.items()}, due


def attach_reaction_moves(
    events: dict[str, list[CatalystEvent]], closes: pd.DataFrame
) -> dict[str, list[CatalystEvent]]:
    """Annotate each event with the stock's close-to-close return on the session that first
    traded on it — pure, no I/O. Events already carrying a measured move keep it.

    The session is the first one at or after `on`, advanced by one when the wire came in after the
    16:00 close. An event before the frame's first session (no previous close) or after its last
    stays unannotated: a reaction we cannot measure is 0.0, never an estimate.
    """
    out: dict[str, list[CatalystEvent]] = {}
    for ticker, entries in events.items():
        series = closes[ticker].dropna().sort_index() if ticker in closes.columns else None
        if series is None or len(series) < 2:
            out[ticker] = list(entries)
            continue
        sessions = [stamp.date() for stamp in pd.DatetimeIndex(series.index)]
        values = [float(v) for v in series]
        annotated: list[CatalystEvent] = []
        for event in entries:
            if event.move_on is not None:
                annotated.append(event)
                continue
            pos = bisect_left(sessions, event.on)
            if event.after_close and pos < len(sessions) and sessions[pos] == event.on:
                pos += 1
            if pos == 0 or pos >= len(sessions):
                annotated.append(event)
                continue
            previous = values[pos - 1]
            if previous <= 0:
                annotated.append(event)
                continue
            annotated.append(
                replace(event, move=values[pos] / previous - 1.0, move_on=sessions[pos])
            )
        out[ticker] = annotated
    return out


@dataclass(frozen=True)
class CatalystIndex:
    """Per-ticker sorted catalyst events plus the dated-catalyst diary — the whole state the
    feature block needs. Built once per training run and queried ~100k times, so it is an
    in-memory dict rather than a per-row query; lists are short enough (25 events per ticker on
    the archive average) that `features` scans linearly instead of carrying a bisect index
    nobody can read.
    """

    events: dict[str, list[CatalystEvent]]
    due_dates: dict[str, list[tuple[date, date]]]

    def features(self, ticker: str, as_of: object) -> dict[str, float]:
        """The catalyst block for one (ticker, as_of), keys == `CATALYST_FEATURE_COLUMNS`.

        Never None — see NEUTRAL for why a ticker without catalysts is kept rather than dropped.
        Windows are half-open `(as_of - window, as_of)`; see the module docstring's rule 3.
        """
        as_of_date = _as_date(as_of)
        symbol = ticker.upper()
        short_start = as_of_date - timedelta(days=SHORT_WINDOW_DAYS)
        long_start = as_of_date - timedelta(days=LONG_WINDOW_DAYS)

        count_30d = 0
        count_365d = 0
        max_strength_30d = 0.0
        last: CatalystEvent | None = None
        for event in self.events.get(symbol, ()):  # sorted by `on`, so the last hit is the newest
            if event.on >= as_of_date:
                continue  # not knowable on this decision day
            if event.on <= long_start:
                continue
            count_365d += 1
            last = event
            if event.on > short_start:
                count_30d += 1
                max_strength_30d = max(max_strength_30d, event.strength)

        row = dict(NEUTRAL)
        row["cat_count_30d"] = float(count_30d)
        row["cat_count_365d"] = float(count_365d)
        row["cat_max_strength_30d"] = max_strength_30d
        if last is not None:
            row["cat_days_since"] = float((as_of_date - last.on).days)
            row["cat_last_strength"] = last.strength
            # Explicit guard rather than a calendar argument: the reaction session is normally at
            # or before `as_of` (see module docstring), but an unusual `as_of` must not be able to
            # pull a future session's return into a feature.
            if last.move_on is not None and last.move_on <= as_of_date:
                row["cat_last_move"] = last.move
            row["cat_volume_ratio"] = last.volume_ratio
            row["cat_spread_bp"] = last.spread_bp

        horizon_end = as_of_date + timedelta(days=DUE_HORIZON_DAYS)
        nearest: date | None = None
        for known_on, due_on in self.due_dates.get(symbol, ()):
            if known_on >= as_of_date:
                continue  # the diary entry itself was not knowable yet
            if due_on < as_of_date or due_on > horizon_end:
                continue
            if nearest is None or due_on < nearest:
                nearest = due_on
        if nearest is not None:
            row["cat_days_to_due"] = float((nearest - as_of_date).days)

        return {column: row[column] for column in CATALYST_FEATURE_COLUMNS}

    def coverage(self, tickers: list[str]) -> float:
        """Share of `tickers` with at least one catalyst on record.

        The number to read BEFORE any AUC comparison: the P3 evidence run looked like a +0.003
        improvement until coverage turned out to be 2.5 %, at which point the comparison meant
        nothing. Same trap, same guard.
        """
        if not tickers:
            return 0.0
        return sum(1 for t in tickers if self.events.get(t.upper())) / len(tickers)


def archive_years(root: Path | str = DATA_BASE_PATH) -> list[int]:
    """Years the local news archive actually holds, ascending.

    Discovered instead of hardcoded: a pinned range would silently stop including new years the
    moment the archive is extended, and "the file is there but nobody reads it" is the kind of
    quiet coverage loss this whole module exists to avoid.
    """
    years: list[int] = []
    for path in Path(root).glob("news-*.csv.gz"):
        stem = path.name.removeprefix("news-").removesuffix(".csv.gz")
        if stem.isdigit():
            years.append(int(stem))
    return sorted(years)


def load_catalyst_index(
    *,
    news_root: Path | str = DATA_BASE_PATH,
    news_years: list[int] | None = None,
    catalyst_db_path: str | Path = DEFAULT_CATALYST_DB_PATH,
    closes: pd.DataFrame | None = None,
) -> CatalystIndex:
    """Build the index from the local archive plus the live radar DB. Reads files only, never the
    network.

    `closes` (the training panel's close frame) enables `cat_last_move`; without it that column
    stays 0.0 everywhere, which is a real difference in the feature block and not a detail — pass
    it whenever a price panel is at hand.
    """
    years = archive_years(news_root) if news_years is None else news_years
    news = load_news(years, root=news_root)
    merged = catalyst_events_from_news(news)
    db_events, due_dates = catalyst_events_from_db(catalyst_db_path)
    for ticker, entries in db_events.items():
        merged[ticker] = _dedupe(merged.get(ticker, []) + entries)
    if closes is not None:
        merged = attach_reaction_moves(merged, closes)
    return CatalystIndex(events=merged, due_dates=due_dates)
