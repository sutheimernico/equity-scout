// Time-context badge every paper depot carries (plan v6 P6): is this a BACKTEST
// (recomputed history), a FORWARD paper track (accumulating since a date) or a live
// paper account? Kills the old "Live (Forward)" ambiguity — nothing here is real-money.
export function TimeContextBadge({
  kind,
  since,
}: {
  kind: "backtest" | "forward" | "paper";
  since?: string | null;
}) {
  const label =
    kind === "backtest"
      ? "Backtest — zurückgerechnet"
      : kind === "forward"
        ? `Forward-Paper${since ? ` seit ${since}` : " — läuft vorwärts"}`
        : `Paper-Depot${since ? ` seit ${since}` : ""}`;
  return (
    <span className="chip time-badge" title="Zeitkontext dieses Depots — kein Echtgeld">
      {label}
    </span>
  );
}
