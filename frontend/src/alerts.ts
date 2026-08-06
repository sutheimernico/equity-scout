// Presentation of the evidence alerts on the phone.
//
// Sampled all 20 stored alerts on 2026-08-06 (plan task 4, step 4). Two shapes exist and
// neither carries jargon:
//   "2 Kongress-Mitglieder haben gekauft"
//   "Stimme: Michael Burry äußert sich negativ — »Michael Burry Warns on Lorem…«"
// The second one appends the source headline, in English, which is the same thing Nico
// rejected on the stock cards ("ich kann nichts mit 'Yamato Holding Stock Faces Profit
// Strain' anfangen"). The headline is the EVIDENCE, the sentence before it is the claim —
// so the glance shows the claim and the headline stays in the evidence view.

/** The claim without its quoted source headline. */
export function alertClaim(reason: string): string {
  const quoted = reason.indexOf(" — »");
  return quoted === -1 ? reason : reason.slice(0, quoted);
}
