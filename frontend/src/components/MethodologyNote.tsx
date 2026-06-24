// Collapsible in-app explanation of how scores are produced — keeps the screen honest and legible.
export function MethodologyNote() {
  return (
    <details className="note">
      <summary>How are these scores computed?</summary>
      <p>
        Each stock is scored on five factor families — Value, Quality, Momentum, Growth and Low
        Volatility — from free fundamentals and price history. For every metric, stocks are ranked
        cross-sectionally into a percentile (0–100); Value, Quality and Growth are ranked within
        sector, so a tech P/E is never compared to a utility's. Each risk bucket weights the
        families differently — open a card to see <em>percentile × weight = contribution</em>, and
        the composite is their sum. Rank-based scoring is robust to outliers; a non-positive P/E is
        dropped, not treated as "cheap". This is a research screen, not investment advice — the
        weights are reasoned defaults, not backtested.
      </p>
    </details>
  );
}
