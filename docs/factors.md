# Factor definitions

equity-scout scores each instrument on five factor families, then blends them per risk bucket.
Scoring is **cross-sectional and rank-based**: within the gated universe, each raw metric becomes a
percentile in `[0, 1]`. A family's score is the mean of its available metric percentiles; if a family
has no usable data for an instrument, its score is `0.0`.

## Families

| Family    | Metrics (yfinance)                     | Direction          | Ranked       |
|-----------|----------------------------------------|--------------------|--------------|
| value     | `trailingPE`, `priceToBook`            | lower is better    | within sector |
| quality   | `returnOnEquity`, `profitMargins`      | higher is better   | within sector |
| growth    | `revenueGrowth`, `earningsGrowth`      | higher is better   | within sector |
| momentum  | 6-month total return (from prices)     | higher is better   | global       |
| low_vol   | stdev of daily returns (from prices)   | lower is better    | global       |

## Design decisions (and why)

- **Rank-based, not z-score → no winsorizing.** Percentile ranks are ordinal: an outlier's
  magnitude doesn't move its rank, so the score is naturally robust to extreme values. Winsorizing
  would change nothing here, so it isn't applied.
- **Invalid values dropped, not ranked.** A non-positive `trailingPE` or `priceToBook` is treated as
  missing, not as "cheap". A negative P/E means losses; ranking it as the cheapest stock would be
  exactly wrong. Such a metric is excluded before ranking.
- **value / quality / growth are ranked within sector.** A tech P/E is not comparable to a utility's;
  margins and growth rates are structurally sector-dependent. Ranking within sector removes that
  bias. Momentum and low-vol are price-derived and ranked globally.
- **Small sectors degrade gracefully.** A metric present for a single instrument in its sector scores
  `0.5` (neutral). With a small universe many sector groups are tiny, so sector-relative scores are
  coarse; breadth improves with the combined universe (see `PLAN.md` Phase 2).
- **Sector source is layered.** Constituent tables provide sectors where they have them; for the
  bulk US directory (no sector column) the persistent `instrument_meta` store overlays sectors
  discovered on earlier live fetches (`universe.apply_meta_overlay`), and a live yfinance `.info`
  fetch backfills + persists the rest. Only names never fetched live rank in the "Unknown" group,
  and that group shrinks with every nightly prefetch rotation.

## Risk buckets

A bucket's composite score is the weighted sum of the five family percentiles.

| Family    | defensive | balanced | aggressive |
|-----------|-----------|----------|------------|
| value     | 0.30      | 0.20     | 0.10       |
| quality   | 0.35      | 0.20     | 0.10       |
| momentum  | 0.05      | 0.20     | 0.40       |
| growth    | 0.05      | 0.20     | 0.35       |
| low_vol   | 0.25      | 0.20     | 0.05       |

Defensive leans on quality + value + calm prices; aggressive leans on momentum + growth.

## Honest limitations

- These weights are **reasoned defaults, not backtested**. equity-scout does not claim they beat the
  market — it is a research/screening assistant, not a strategy with a measured edge.
- Free fundamentals (yfinance) are unofficial and patchy outside the US; the data-completeness gate
  drops thin coverage, which also shrinks small sectors further.
- Point-in-time only: scores reflect *today's* data, not a historical, survivorship-free panel.
