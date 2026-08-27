// Push-subscription plumbing, kept out of the component so the fiddly parts are testable.
//
// The browser's PushManager wants the VAPID public key as raw bytes, but it travels as
// base64url text — a mismatch here fails at subscribe() time with an opaque
// InvalidCharacterError, which is exactly the kind of thing worth a unit test.

/** base64url (unpadded, as the server sends it) -> the Uint8Array `applicationServerKey` wants. */
export function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(normalized);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

export type PushState =
  | "unsupported" // no service worker / no Push API (iOS Safari before install, old browsers)
  | "insecure" // not an HTTPS origin: the API exists but subscribe() always fails
  | "denied" // the owner said no; only the browser's own settings can undo this
  | "granted" // permission held AND a subscription exists on this device
  | "permitted-not-subscribed" // permission held, but no subscription (fresh install, cleared data)
  | "prompt"; // never asked

/** Decide what the settings card should offer, from facts the component can pass in. */
export function pushState(input: {
  supported: boolean;
  secureContext: boolean;
  permission: NotificationPermission;
  subscribed: boolean;
}): PushState {
  if (!input.supported) return "unsupported";
  // Localhost counts as secure, which is why this is a flag from the browser and not a
  // protocol check: the cockpit is developed on http://127.0.0.1 and served over HTTPS.
  if (!input.secureContext) return "insecure";
  if (input.permission === "denied") return "denied";
  if (input.permission === "granted") return input.subscribed ? "granted" : "permitted-not-subscribed";
  return "prompt";
}

/** German one-liner explaining the state — the card's whole job is to be unambiguous. */
export function stateMessage(state: PushState): string {
  switch (state) {
    case "unsupported":
      return "Dieser Browser kann keine Push-Nachrichten. Auf dem iPhone: erst „Zum Home-Bildschirm“ hinzufügen.";
    case "insecure":
      return "Push braucht eine HTTPS-Adresse. Öffne das Cockpit über die Tailscale-Adresse (https://…ts.net).";
    case "denied":
      return "Du hast Benachrichtigungen für diese Seite blockiert. Das lässt sich nur in den Browser-Einstellungen wieder erlauben.";
    case "granted":
      return "Aktiv — dieses Gerät bekommt Benachrichtigungen.";
    case "permitted-not-subscribed":
      return "Erlaubt, aber dieses Gerät ist noch nicht eingetragen.";
    case "prompt":
      return "Noch nicht aktiviert.";
  }
}

/** Short device label so several phones/browsers stay distinguishable in the list. */
export function deviceLabel(userAgent: string): string {
  const ua = userAgent || "";
  const platform = /Android/i.test(ua)
    ? "Android"
    : /iPhone|iPad/i.test(ua)
      ? "iOS"
      : /Windows/i.test(ua)
        ? "Windows"
        : /Mac OS X/i.test(ua)
          ? "Mac"
          : /Linux/i.test(ua)
            ? "Linux"
            : "Gerät";
  const browser = /EdgA?\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : "Browser";
  return `${platform} · ${browser}`;
}
