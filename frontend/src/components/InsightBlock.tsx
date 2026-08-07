import type { NewsItem, StockInsight } from "../api";

// The two AI texts of a stock card — business sentence + summarised news, shared by the
// Heute list and the screener (extracted from StockList 2026-08-07 so the two render the
// same insight identically). Labelled as machine-written, because they are — and dated,
// because a summary of last week's headlines read as today's news would be misleading.
// `news` (the wire items behind Pick.news) renders as a separate linked source list — the
// German one-liners come from a different feed and an LLM pass, so headline→link pairing
// would be guesswork; sources are shown as what they are instead.
export function InsightBlock({
  insight,
  news,
}: {
  insight: StockInsight | null | undefined;
  news?: NewsItem[] | null;
}) {
  if (!insight) {
    return (
      <p className="brief-muted brief-insight">
        Noch keine KI-Zusammenfassung erzeugt (läuft im 18:00-Lauf).
      </p>
    );
  }
  const when = new Date(insight.generated_at).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
  });
  // German one-liners when the generator produced them; the English wire titles are the
  // fallback for rows from before that existed (Nico 2026-08-06: "ich kann nichts mit
  // 'Yamato Holding Stock Faces Profit Strain Behind A Premium PE' anfangen").
  const headlines =
    insight.headlines_de.length > 0 ? insight.headlines_de : insight.headlines;
  return (
    <div className="brief-insight">
      {insight.business && <p className="brief-insight-business">{insight.business}</p>}
      {insight.news_summary ? (
        <p className="brief-insight-news">📰 {insight.news_summary}</p>
      ) : (
        <p className="brief-muted">Keine aktuellen Schlagzeilen gefunden.</p>
      )}
      {headlines.length > 0 && (
        <>
          <p className="brief-headlines-head">Schlagzeilen</p>
          <ul className="brief-headlines">
            {headlines.map((title) => (
              <li key={title}>{title}</li>
            ))}
          </ul>
        </>
      )}
      {news && news.length > 0 && (
        <>
          <p className="brief-headlines-head">Original-Quellen</p>
          <ul className="brief-headlines">
            {news.map((n) => (
              <li key={n.link}>
                <a href={n.link} target="_blank" rel="noopener noreferrer">
                  {n.title}
                </a>{" "}
                <span className="brief-muted">({n.publisher})</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="brief-muted brief-insight-foot">
        KI-Zusammenfassung ({insight.model ?? "lokal"}) vom {when} — keine Empfehlung.
      </p>
    </div>
  );
}
