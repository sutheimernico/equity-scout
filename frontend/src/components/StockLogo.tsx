import { useState } from "react";

import { companyInitials } from "../company";

// Logos come from OUR api (/api/logo/<ticker>), which fetches once and caches locally —
// the phone never talks to the logo provider, so it cannot learn which stocks are being
// looked at, and a cached file still renders when the service worker serves the app
// offline. A 404 is a NORMAL answer (no logo for this listing), hence the monogram
// fallback rather than a broken-image icon.
export function StockLogo({ ticker, name }: { ticker: string; name: string }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span className="stock-logo stock-logo-mono" aria-hidden="true">
        {companyInitials(name)}
      </span>
    );
  }
  return (
    <img
      className="stock-logo"
      src={`/api/logo/${encodeURIComponent(ticker)}`}
      // Decorative: the company name sits next to it in text, so an alt text would just
      // be read twice by a screen reader.
      alt=""
      aria-hidden="true"
      loading="lazy"
      width={28}
      height={28}
      onError={() => setFailed(true)}
    />
  );
}
