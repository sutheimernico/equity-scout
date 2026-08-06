// The headline number of a stock card — shared by the Heute list and the decision inbox
// so the same fact looks the same everywhere (extracted from StockList, 2026-08-06).
// Big on purpose, but it is a third-party opinion: the caption says what it is, the
// footer says whose opinion. null renders an honest "keine Schätzung", never a 0.

export function signedPct(value: number): string {
  const rounded = Math.round(value);
  // U+202F narrow no-break space: German typography puts a space before the % sign, but a
  // full space at 1.35rem tears the number and the unit apart.
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)}\u202F%`;
}

export function PotentialBlock({
  upsidePct,
  analystCount,
}: {
  upsidePct: number | null;
  analystCount: number | null;
}) {
  if (upsidePct === null) {
    return (
      <span className="brief-potential brief-potential-none">
        <span className="brief-potential-cap">Potenzial</span>
        <span className="brief-potential-num">—</span>
        <span className="brief-potential-label">keine Schätzung</span>
      </span>
    );
  }
  return (
    <span className={upsidePct >= 0 ? "brief-potential brief-good" : "brief-potential brief-warn"}>
      {/* The number was unlabelled and read as a riddle: "ich kann nichts mit diesen minus
          sieben Prozent anfangen. Was meint das jetzt?" (Nico 2026-08-06). The caption says
          what it is, the footer says whose opinion it is. */}
      <span className="brief-potential-cap">Potenzial</span>
      <span className="brief-potential-num">{signedPct(upsidePct)}</span>
      <span className="brief-potential-label">laut {analystCount ?? "?"} Analysten</span>
    </span>
  );
}
