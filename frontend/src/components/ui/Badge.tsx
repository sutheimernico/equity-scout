import { type ReactNode } from "react";

// Small pill tag. Consolidates the inline `.region-tag` / `.news-badge` / `.bench-tag` look.
export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "region" | "news" | "bench" | "neutral";
  children: ReactNode;
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}
