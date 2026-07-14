# Pitch Redesign: Chart Photo + Compact Sectioned Caption

**Date:** 2026-07-15 (same session, Nico mid-turn wish)
**Status:** SHIPPED same session (commit `571ba91`) — retro spec for the record.

## Nico's ask (condensed)

The pitch messages were unübersichtlich. New: every pitch carries a picture of the price
history (ideally 1 year), and the text must be much shorter but complete, clearly
sectioned — score + why, KGV, price/1y move, who bought/said what.

## What shipped

- `charts.py`: `fetch_year_closes` (yfinance seam) + `render_year_chart` (pure, matplotlib
  Agg → PNG bytes) + `year_return`.
- `pitch.build_pitch_caption`: one fact per line — header, Score + top factors, KGV/Kurs/1J,
  Einstiegszone, Analysten-Ø-Ziel (labelled fremde Meinung), 👥 evidence (≤2 lines via
  `evidence_summary_lines`), ⚠️ risk, disclaimer footer. Hard cap 980 chars (Telegram photo
  captions cap at 1024 UTF-16 units).
- `telegram_client.send_photo` (stdlib multipart, pure `build_multipart` unit-tested) +
  `edit_caption` + `edit_pitch_outcome` (decision-outcome edit falls back from
  editMessageText to a short caption edit for photo messages; "not modified" = success).
- `run_notify._telegram_sender`: photo pitch first, ANY failure falls back to the classic
  long text message. The dashboard inbox always keeps the long `build_pitch` text.
- `notify_watchlist` send seam extended to `(pitch_id, text, entry, fundamentals)`.
- Digest "Heute aufgefallen" lines truncate press-headline reasons at 90 chars.

**Live proof:** demo photo pitch (9022.T, 378-char caption, 53 kB chart) delivered to the
Daily-Equity-Scout chat via the real code path. Gate: 628 tests + ruff green.

## Out of scope / notes

- Charts only for pitches (2–5/day), not for digest lines or evidence alerts (volume).
- 1y fetch is live per pitched ticker (few per day — no cache needed).
- Buttons work on photo messages (reply_markup on sendPhoto); decision outcome edits fall
  back to caption edits automatically.
