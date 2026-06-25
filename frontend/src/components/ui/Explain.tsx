import { type ReactNode } from "react";

// One info-box primitive, replacing the two near-identical `.explain` / `.block-hint` patterns.
// `info` = boxed surface (intro lines); `hint` = quiet caption under a block title.
export function Explain({ tone = "info", children }: { tone?: "info" | "hint"; children: ReactNode }) {
  return <p className={tone === "hint" ? "block-hint" : "explain"}>{children}</p>;
}
