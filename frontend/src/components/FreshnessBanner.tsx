import { describeFreshness, useFreshness } from "../useFreshness";

/** Sticky top-of-page label for "you're looking at the last known state, from when". */
export function FreshnessBanner() {
  const freshness = useFreshness();
  const label = describeFreshness(freshness);
  if (label === null) return null;
  return (
    <div className="freshness-banner" role="status">
      ⚠️ {label}
    </div>
  );
}
