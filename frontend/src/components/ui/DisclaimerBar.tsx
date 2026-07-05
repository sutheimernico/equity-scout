// Per-surface disclaimer strip: every copilot response carries a German `disclaimer`;
// each surface renders it as a subtle hairline-topped footer (reuses the `.surface-disclaimer` CSS).
export function DisclaimerBar({ text }: { text: string }) {
  return <p className="surface-disclaimer">{text}</p>;
}
