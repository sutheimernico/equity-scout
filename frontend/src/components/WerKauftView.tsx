import { PeoplePanel } from "./PeoplePanel";
import { VoicesPanel } from "./VoicesPanel";

// "Mehr → Wer kauft?" (mockup v2): Personen + Stimmen were two nav entries over the
// same /api/evidence source. Buys also appear directly on each stock profile — this
// page is for browsing. Both panels keep their full depth (person track records,
// congress-by-stock, voice tonality) and their own headers; they are stacked, not
// trimmed.
export function WerKauftView() {
  return (
    <>
      <PeoplePanel />
      <VoicesPanel />
    </>
  );
}
