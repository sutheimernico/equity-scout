import { type ReactNode } from "react";

// Progressive disclosure: the summary line is always visible, the depth folds away.
// Replaces the wall-of-text explainers and the old MethodologyNote.
export function Disclosure({
  summary,
  defaultOpen = false,
  children,
}: {
  summary: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details className="disclosure" open={defaultOpen}>
      <summary>
        <span className="disclosure-chev" aria-hidden="true">
          ›
        </span>
        <span className="disclosure-summary">{summary}</span>
      </summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}
