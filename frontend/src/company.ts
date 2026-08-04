// Company name display helpers. The API delivers legal names ("Yamato Holdings Co., Ltd.",
// "Micron Technology, Inc.") — on a 390 px screen the legal form is the least useful part
// of the string, so it gets trimmed for display while the raw name stays available for the
// title attribute.

// Longest first: "Co., Ltd." must be stripped before "Co." would match half of it.
const LEGAL_SUFFIXES = [
  "co., ltd.",
  "co. ltd.",
  "co., ltd",
  "public limited company",
  "incorporated",
  "corporation",
  "limited",
  "holdings",
  "company",
  "group",
  "s.a.b. de c.v.",
  "n.v.",
  "b.v.",
  "s.a.",
  "s.p.a.",
  "a.g.",
  "ag",
  "sa",
  "se",
  "plc",
  "inc.",
  "inc",
  "corp.",
  "corp",
  "ltd.",
  "ltd",
  "llc",
  "l.p.",
  "lp",
  "nv",
  "oyj",
  "ab",
  "asa",
  "spa",
];

// Yahoo appends share-class descriptions to many US listings ("Air T, Inc. - Common Stock",
// "… - Class A Common Stock"). They describe the instrument, not the company.
const SHARE_CLASS_RE = /\s[-–]\s(?:class\s+\w+\s+)?(?:common|ordinary|registered)\s+(?:stock|shares)$/i;

/** "Yamato Holdings Co., Ltd." -> "Yamato". Never returns an empty string: if stripping
 *  would leave nothing (a company literally called "Group"), the original name wins. */
export function shortCompanyName(name: string): string {
  let out = name.trim().replace(/\s+/g, " ").replace(SHARE_CLASS_RE, "");
  let changed = true;
  // Loop because names stack forms: "… Holdings Co., Ltd." needs three passes.
  while (changed) {
    changed = false;
    const lower = out.toLowerCase();
    for (const suffix of LEGAL_SUFFIXES) {
      if (lower.endsWith(" " + suffix)) {
        out = out.slice(0, out.length - suffix.length - 1).replace(/[,\s]+$/, "");
        changed = true;
        break;
      }
    }
  }
  return out.length > 0 ? out : name.trim();
}

/** Two-letter badge for the logo fallback: initials of the first two words, or the first
 *  two characters of a single-word name. Uppercased, never longer than 2. */
export function companyInitials(name: string): string {
  const words = shortCompanyName(name)
    .split(/[\s.\-/]+/)
    .filter((w) => /[a-z0-9]/i.test(w));
  if (words.length === 0) return name.slice(0, 2).toUpperCase();
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

// The pitch text's first line is built by pitch.py as "📈 <TICKER> — <NAME>", so the
// company name can be recovered from a pitch row even though the pitches table only stores
// the ticker. Returns null when the line does not match — no guessing.
const PITCH_HEAD_RE = /^\s*📈\s*(\S+)\s+—\s+(.+?)\s*$/;

export function companyNameFromPitch(pitch: string, ticker: string): string | null {
  const match = PITCH_HEAD_RE.exec(pitch.split("\n")[0] ?? "");
  if (!match) return null;
  // Guard against a mismatched row: the head must belong to THIS ticker.
  return match[1] === ticker ? match[2] : null;
}
