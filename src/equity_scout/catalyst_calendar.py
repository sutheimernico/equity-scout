"""Layer 3 of the catalyst radar (v16, plan task D): dated catalysts we can know IN ADVANCE.

Layers 1 and 2 react — they see a move or a headline that already exists. This layer is the
only one that can put a ticker on the radar BEFORE anything happens, and it can only do that
for catalysts that carry a public date. Two such calendars exist for free:

* **ClinicalTrials.gov v2** (keyless, no registration): phase-2/3 studies of industry
  sponsors whose PRIMARY COMPLETION date falls inside the horizon. Primary completion is
  when the primary endpoint is measured — the readout that moved MRNA 127 % on 2026-08-19
  is exactly this kind of date. Verified live on 2026-08-19: 542 such studies in the next
  90 days from 339 distinct lead sponsors.
* **`earnings_dates`** in equity_scout.db, filled by scripts/run_earnings.py. Read-only
  here; widening that source is a different strand.

The hard part is not the fetch, it is **sponsor name -> ticker**. A trial names a legal
entity ("ModernaTX, Inc.", "Merck Sharp & Dohme LLC"); the universe names an issuer
("Moderna", "Merck & Co."). Matching is deliberately conservative — a wrong ticker would put
a catalyst on the WRONG company, which is worse than a gap, so ambiguity produces no signal:

    stage 1  token-set equality of normalized names, unique hit only
    stage 2  a single-token sponsor name that extends a unique universe name by at most two
             letters (the corporate-entity tag: "ModernaTX" -> "Moderna")

Measured against 1 077 distinct industry lead sponsors of the next 365 days (2026-08-19):
216 exact + 1 stage-2 = 217 mapped (20 %), 4 refused as ambiguous, 856 unmapped. The
unmapped majority is honest coverage, not a matcher bug — most trial sponsors are private
companies, foreign subsidiaries or delisted names that are not in a 7 500-name universe.
Two looser rules were built, measured and REJECTED because they bought reach with wrong
tickers: matching on the first token alone (~15 of 30 extra hits wrong, e.g. "Lumen
Bioscience" -> LUMN Lumen Technologies, "Turning Point Therapeutics" -> TPB Turning Point
Brands) and stripping industry words like "Therapeutics" before matching (~5 of 15 wrong,
e.g. "Thryv Therapeutics" -> THRY Thryv Holdings). One known false positive survives in
stage 1: "Polaris Group" (a Taiwanese biotech) matches PII, Polaris Inc.

Pure logic here, all I/O in scripts/run_catalyst_calendar.py — except the fetch itself,
which follows kraken_data's shape: an injectable `get_json` and an honest None (never an
invented study) when the transport fails.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta

from equity_scout.catalyst_storage import SOURCE_CALENDAR
from equity_scout.evidence.edgar import _SUFFIX_TOKENS

CT_API_URL = "https://clinicaltrials.gov/api/v2/studies"
CT_STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"

DEFAULT_HORIZON_DAYS = 90

KIND_TRIAL = "trial_readout"
KIND_EARNINGS = "earnings"

REASON_AMBIGUOUS = "ambiguous_sponsor"

# Both statuses mean the study is still running, so its primary completion is still ahead of
# it. COMPLETED/TERMINATED studies carry a date that has already passed, WITHDRAWN ones a
# date that will never arrive.
_STATUS_FILTER = "RECRUITING|ACTIVE_NOT_RECRUITING"
_FIELDS = (
    "NCTId|BriefTitle|OverallStatus|Phase|LeadSponsorName|PrimaryCompletionDate|EnrollmentCount"
)
_PAGE_SIZE = 1000
_MAX_PAGES = 10  # 10k studies; a guard against a pagination loop, not an expected limit
_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Trial:
    nct_id: str
    title: str
    sponsor: str
    phases: tuple[str, ...]
    status: str
    due_date: str  # ISO date, normalized (see `resolve_due_date`)
    month_only: bool  # the source gave YYYY-MM, so the real day is anywhere in that month
    enrollment: int | None


# --- sponsor -> ticker ---------------------------------------------------------------------

# International legal forms EDGAR's 13F vocabulary does not carry: it sees US filers, while
# trial sponsors are global ("Novo Nordisk A/S", "Immunovant Sciences GmbH", "Hemab ApS").
# "AND"/"OF" are joiners, not legal forms, but they are what separates "Eli Lilly and
# Company" from the universe's "Lilly (Eli)".
_EXTRA_SUFFIX_TOKENS = frozenset({
    "LLC", "LP", "LLP", "GMBH", "AB", "AS", "APS", "OY", "OYJ", "KGAA", "SPA", "BV",
    "PTE", "BHD", "ASA", "KG", "SAS", "SRL", "SARL", "AND", "OF",
})
_SUFFIXES = frozenset(_SUFFIX_TOKENS) | _EXTRA_SUFFIX_TOKENS

# Exchange listing tails in universe_combined.csv names — "GSK plc American Depositary Shares
# (Each representing two Ordinary Shares)". Everything from the marker on is boilerplate that
# no sponsor name carries. Both NASDAQ's "Depository" and the correct "Depositary" occur.
_LISTING_TAIL_MARKERS = (
    "COMMON STOCK", "COMMON SHARES", "ORDINARY SHARES", "ORDINARY SHARE",
    "AMERICAN DEPOSITARY", "AMERICAN DEPOSITORY", "DEPOSITARY SHARES", "DEPOSITARY SHARE",
    "DEPOSITORY SHARES", "DEPOSITORY SHARE", "DEPOSITARY RECEIPTS", "DEPOSITORY RECEIPTS",
)

_PARENTHETICAL = re.compile(r"\([^)]*\)")

# Stage 2 only trusts a name long enough to be a brand rather than an abbreviation, and only
# a tag short enough to be a legal-entity marker ("TX", "RX") rather than a different word.
_MIN_STEM_LENGTH = 6
_MAX_ENTITY_TAG_LENGTH = 2


def _name_tokens(name: str) -> list[str]:
    """Uppercase alphanumeric tokens of an issuer/sponsor name, minus listing tail and suffixes.

    Local by design, like voices' `_normalize_universe_name`: `edgar._normalize` also
    normalizes 13F issuer names, where changing the vocabulary would silently reshuffle
    ambiguity sets in a live strand.
    """
    head = name.split(" - ", 1)[0].upper()  # NASDAQ-style "<name> - <listing tail>"
    flat = " ".join("".join(c if c.isalnum() else " " for c in head).split())
    for marker in _LISTING_TAIL_MARKERS:
        cut = flat.find(marker)
        if cut >= 0:
            flat = flat[:cut]
            break
    return [t for t in flat.split() if t not in _SUFFIXES]


def company_keys(name: str) -> set[frozenset[str]]:
    """Token-SET keys for a company name — one with parenthetical content, one without.

    Sets, not ordered strings, because the two sides disagree on word order: the universe's
    "Lilly (Eli)" only meets the sponsor's "Eli Lilly and Company" as {ELI, LILLY}. Both
    parenthetical variants are kept because a parenthesis is sometimes part of the name
    ("Lilly (Eli)") and sometimes boilerplate ("Zenas BioPharma (USA), LLC"); a variant that
    is garbage simply never matches anything, since every lookup demands a unique hit.
    """
    keys = set()
    for variant in (_PARENTHETICAL.sub(" ", name), name):
        tokens = _name_tokens(variant)
        if tokens:
            keys.add(frozenset(tokens))
    return keys


@dataclass(frozen=True)
class SponsorIndex:
    by_key: dict[frozenset[str], set[str]]
    by_stem: dict[str, set[str]]  # single-token names, for the stage-2 entity-tag rule


def build_sponsor_index(instruments: list[tuple[str, str]]) -> SponsorIndex:
    """(ticker, company_name) pairs -> lookup index. Same input shape as `edgar.build_name_matcher`.

    Unlike that matcher this one keeps EVERY ticker per key instead of the first one, because
    a colliding key here has to become a refusal, not a coin flip.
    """
    by_key: dict[frozenset[str], set[str]] = {}
    by_stem: dict[str, set[str]] = {}
    for ticker, name in instruments:
        for key in company_keys(name):
            by_key.setdefault(key, set()).add(ticker)
            if len(key) == 1:
                stem = next(iter(key))
                if len(stem) >= _MIN_STEM_LENGTH:
                    by_stem.setdefault(stem, set()).add(ticker)
    return SponsorIndex(by_key=by_key, by_stem=by_stem)


def match_sponsor(index: SponsorIndex, sponsor: str) -> tuple[str | None, list[str]]:
    """Sponsor name -> (ticker, candidates). ticker is None unless exactly ONE candidate exists.

    The candidate list is the caller's evidence: empty means "not in our universe" (a gap),
    two or more means "we cannot tell which listing" (a refusal worth logging).
    """
    candidates: set[str] = set()
    for key in company_keys(sponsor):
        candidates |= index.by_key.get(key, set())
    if len(candidates) == 1:
        return candidates.pop(), []
    if candidates:
        return None, sorted(candidates)

    tokens = _name_tokens(_PARENTHETICAL.sub(" ", sponsor))
    if len(tokens) != 1:
        return None, []
    word = tokens[0]
    stem_hits = {
        ticker
        for stem, tickers in index.by_stem.items()
        if word.startswith(stem) and 0 < len(word) - len(stem) <= _MAX_ENTITY_TAG_LENGTH
        for ticker in tickers
    }
    return (stem_hits.pop(), []) if len(stem_hits) == 1 else (None, sorted(stem_hits))


# --- dates --------------------------------------------------------------------------------


def resolve_due_date(raw: str) -> str | None:
    """"2026-10-05" -> unchanged; "2026-11" -> "2026-11-01"; anything else -> None.

    First of the month, not last, because that is how ClinicalTrials.gov's own date-range
    filter reads a month-only value — verified 2026-08-19: querying [2026-08-19, 2026-11-17]
    returned 71 studies dated "2026-11" and none dated "2026-08". Resolving it the other way
    would silently drop 13 % of the payload the server just said was in range.
    """
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw or ""):
        return raw
    if re.fullmatch(r"\d{4}-\d{2}", raw or ""):
        return f"{raw}-01"
    return None


def _phase_label(phases: tuple[str, ...]) -> str:
    numbers = [p.removeprefix("PHASE") for p in phases if p.startswith("PHASE")]
    return "Phase " + "/".join(numbers) if numbers else "Studie ohne Phasenangabe"


def _trial_score(phases: tuple[str, ...]) -> float:
    """Ordinal priority, NOT a probability — layer 3 has no outcome data to calibrate against.

    A phase-3 primary completion is the readout most likely to move a price and a phase-1/2
    combination the least, because an early-phase endpoint is smaller and rarely registrational.
    """
    score = 0.6 if "PHASE3" in phases else 0.45
    return round(score - 0.15, 2) if "PHASE1" in phases else score


# The known-date premium of an earnings report is low: it is scheduled, quarterly and priced
# in. It stays on the radar because a warning is still a warning, ranked below every readout.
EARNINGS_SCORE = 0.25


# --- API ----------------------------------------------------------------------------------


def build_query_url(*, today: str, days: int, page_token: str | None = None) -> str:
    """Essie-expression query for the horizon. Sponsor class INDUSTRY only — an academic
    sponsor has no ticker, so an academic study can never become a signal."""
    end = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    params = {
        "format": "json",
        "filter.overallStatus": _STATUS_FILTER,
        "filter.advanced": (
            "AREA[Phase](PHASE2 OR PHASE3)"
            " AND AREA[LeadSponsorClass]INDUSTRY"
            f" AND AREA[PrimaryCompletionDate]RANGE[{today},{end}]"
        ),
        "fields": _FIELDS,
        "pageSize": str(_PAGE_SIZE),
    }
    if page_token:
        params["pageToken"] = page_token
    return f"{CT_API_URL}?{urllib.parse.urlencode(params)}"


def _get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - network failure degrades to "no calendar this run"
        return None


def parse_studies(payload: dict) -> list[Trial]:
    """Studies from one page. A study without a usable date or sponsor is dropped, not guessed."""
    trials = []
    for study in payload.get("studies") or []:
        protocol = study.get("protocolSection") or {}
        status = protocol.get("statusModule") or {}
        raw_date = (status.get("primaryCompletionDateStruct") or {}).get("date") or ""
        due = resolve_due_date(raw_date)
        sponsor = ((protocol.get("sponsorCollaboratorsModule") or {}).get("leadSponsor")
                   or {}).get("name") or ""
        ident = protocol.get("identificationModule") or {}
        design = protocol.get("designModule") or {}
        if not due or not sponsor or not ident.get("nctId"):
            continue
        trials.append(Trial(
            nct_id=ident["nctId"],
            title=ident.get("briefTitle") or "",
            sponsor=sponsor,
            phases=tuple(design.get("phases") or ()),
            status=status.get("overallStatus") or "",
            due_date=due,
            month_only=len(raw_date) == 7,
            enrollment=(design.get("enrollmentInfo") or {}).get("count"),
        ))
    return trials


def fetch_trials(*, today: str, days: int, get_json=_get_json) -> list[Trial] | None:
    """All pages of the horizon, or None when the very first request fails.

    None means "we did not look" and must never be reported as "no upcoming readouts". A
    LATER page failing returns what was collected so far — partial is honest here, because
    every study carries its own dedup key and the next run picks the rest up.
    """
    trials: list[Trial] = []
    token: str | None = None
    for page in range(_MAX_PAGES):
        payload = get_json(build_query_url(today=today, days=days, page_token=token))
        if payload is None:
            return None if page == 0 else trials
        trials.extend(parse_studies(payload))
        token = payload.get("nextPageToken")
        if not token:
            break
    return trials


# --- signals ------------------------------------------------------------------------------


def _in_window(due_date: str, *, today: str, days: int) -> bool:
    end = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    return today <= due_date <= end


def trial_signals(
    trials: list[Trial], index: SponsorIndex, *, today: str, days: int, seen_at: str
) -> tuple[list[dict], list[dict], int]:
    """-> (signals, rejections, unmapped_count).

    The window is re-checked locally instead of trusted from the query: the same function
    then serves a cached payload, a `--days` change and the test fixtures identically.

    Only AMBIGUOUS sponsors become rejection rows. Unmapped ones are counted, not stored —
    ~850 of them per run would bury the calibration data that the rejection table exists for,
    and "this private company has no ticker" is not a threshold anyone will ever re-tune.
    """
    signals: list[dict] = []
    rejections: list[dict] = []
    seen_ambiguous: set[str] = set()
    unmapped: set[str] = set()
    for trial in trials:
        if not _in_window(trial.due_date, today=today, days=days):
            continue
        ticker, candidates = match_sponsor(index, trial.sponsor)
        if ticker is None:
            if candidates and trial.sponsor not in seen_ambiguous:
                seen_ambiguous.add(trial.sponsor)
                rejections.append({
                    "source": SOURCE_CALENDAR,
                    # The rejection is about an unresolved SPONSOR, not about a ticker — the
                    # sponsor name goes in the ticker column so the table's uniqueness key
                    # dedups per sponsor per run.
                    "ticker": trial.sponsor,
                    "reason": REASON_AMBIGUOUS,
                    "seen_at": seen_at,
                    "detail": (
                        f"Sponsor '{trial.sponsor}' passt auf mehrere Notierungen "
                        f"({', '.join(candidates)}) — kein Signal, um nicht die falsche "
                        f"Aktie zu markieren (z. B. {trial.nct_id})"
                    ),
                })
            elif not candidates:
                unmapped.add(trial.sponsor)
            continue
        precision = (
            " · Termin nur monatsgenau, der Tag steht noch nicht fest" if trial.month_only else ""
        )
        size = f", {trial.enrollment} Teilnehmer" if trial.enrollment else ""
        signals.append({
            "source": SOURCE_CALENDAR,
            "ticker": ticker,
            "kind": KIND_TRIAL,
            "seen_at": seen_at,
            # The date is part of the key on purpose: a study whose readout gets rescheduled
            # is a NEW warning, while a re-run on the same date writes nothing.
            "dedup_key": f"{SOURCE_CALENDAR}:{KIND_TRIAL}:{trial.nct_id}:{trial.due_date}",
            "score": _trial_score(trial.phases),
            "detail": (
                f"{_phase_label(trial.phases)}: Primärer Studienabschluss am {trial.due_date} "
                f"erwartet — Sponsor {trial.sponsor}{size}{precision}"
            ),
            "headline": trial.title,
            "url": CT_STUDY_URL.format(nct_id=trial.nct_id),
            "due_date": trial.due_date,
        })
    return signals, rejections, len(unmapped)


def earnings_signals(rows: list[dict], *, seen_at: str) -> list[dict]:
    """`earnings_storage.earnings_within` rows -> signals. Read-only view of another strand's table."""
    return [
        {
            "source": SOURCE_CALENDAR,
            "ticker": row["ticker"],
            "kind": KIND_EARNINGS,
            "seen_at": seen_at,
            "dedup_key": f"{SOURCE_CALENDAR}:{KIND_EARNINGS}:{row['ticker']}:{row['earnings_date']}",
            "score": EARNINGS_SCORE,
            "detail": (
                f"Quartalszahlen erwartet am {row['earnings_date']} — bekannter Termin aus dem "
                f"Earnings-Kalender (yfinance, deckt nur einen Teil des Universums ab)"
            ),
            "due_date": row["earnings_date"],
        }
        for row in rows
    ]
