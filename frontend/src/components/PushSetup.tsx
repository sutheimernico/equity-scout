import { useCallback, useEffect, useState } from "react";

import {
  fetchPushConfig,
  registerPush,
  sendTestPush,
  unregisterPush,
  type PushConfig,
} from "../api";
import { deviceLabel, pushState, stateMessage, urlBase64ToUint8Array, type PushState } from "../push";

// Notification settings: turn this phone into a device that gets alerts from the app
// itself. The card is deliberately blunt about state — the failure mode of a notification
// system is silence, and silence looks exactly like "nothing happened today".
export function PushSetup() {
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [state, setState] = useState<PushState>("prompt");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const supported =
      typeof navigator !== "undefined" &&
      "serviceWorker" in navigator &&
      typeof window !== "undefined" &&
      "PushManager" in window;
    let subscribed = false;
    if (supported) {
      try {
        const registration = await navigator.serviceWorker.getRegistration();
        subscribed = Boolean(await registration?.pushManager.getSubscription());
      } catch {
        subscribed = false;
      }
    }
    setState(
      pushState({
        supported,
        secureContext: typeof window !== "undefined" ? window.isSecureContext : false,
        permission: typeof Notification !== "undefined" ? Notification.permission : "default",
        subscribed,
      }),
    );
    try {
      setConfig(await fetchPushConfig());
    } catch {
      setConfig(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const enable = useCallback(async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setError("Ohne Erlaubnis kann dir die App nichts schicken.");
        await refresh();
        return;
      }
      // The service worker only registers in a production build; without it there is no
      // push endpoint to hand the server, so say so instead of failing cryptically.
      const registration = await navigator.serviceWorker.ready;
      const key = (await fetchPushConfig()).public_key;
      const subscription = await registration.pushManager.subscribe({
        // Chrome refuses a subscription that could stay silent, so this is not optional.
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key) as BufferSource,
      });
      await registerPush(subscription.toJSON(), deviceLabel(navigator.userAgent));
      setNote("Aktiviert. Gleich kommt eine Testnachricht.");
      await sendTestPush();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Aktivierung fehlgeschlagen.");
    } finally {
      setBusy(false);
      await refresh();
    }
  }, [refresh]);

  const disable = useCallback(async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) {
        await unregisterPush(subscription.endpoint);
        await subscription.unsubscribe();
      }
      setNote("Dieses Gerät bekommt keine Benachrichtigungen mehr.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Abmelden fehlgeschlagen.");
    } finally {
      setBusy(false);
      await refresh();
    }
  }, [refresh]);

  const test = useCallback(async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const result = await sendTestPush();
      const report = result.report as Record<string, { sent?: number; error?: string }>;
      const lines = Object.entries(report).map(([channel, outcome]) =>
        outcome?.error ? `${channel}: Fehler` : `${channel}: ok`,
      );
      setNote(`Test verschickt — ${lines.join(", ")}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test fehlgeschlagen.");
    } finally {
      setBusy(false);
      await refresh();
    }
  }, [refresh]);

  const active = state === "granted";
  const canEnable = state === "prompt" || state === "permitted-not-subscribed";

  return (
    <section className="strat-block reveal">
      <h3 className="block-title">Auf diesem Gerät</h3>
      <p className={active ? "push-state ok" : "push-state"}>{stateMessage(state)}</p>
      <div className="tabbar wrap">
        {canEnable && (
          <button className="tab primary" onClick={enable} disabled={busy}>
            Benachrichtigungen einschalten
          </button>
        )}
        {active && (
          <>
            <button className="tab" onClick={test} disabled={busy}>
              Testnachricht schicken
            </button>
            <button className="tab" onClick={disable} disabled={busy}>
              Ausschalten
            </button>
          </>
        )}
        {!active && !canEnable && (
          <button className="tab" onClick={test} disabled={busy}>
            Andere Kanäle testen
          </button>
        )}
      </div>
      {note && <p className="push-note">{note}</p>}
      {error && <p className="push-error">{error}</p>}

      <h3 className="block-title">Kanäle</h3>
      <dl className="brief-detail">
        <dt>App-Nachricht</dt>
        <dd>
          {config?.channels.webpush
            ? `${config.devices.length} Gerät${config.devices.length === 1 ? "" : "e"} eingetragen`
            : "kein Gerät eingetragen"}
        </dd>
        <dt>ntfy (Reserve)</dt>
        <dd>{config?.channels.ntfy ? "eingerichtet" : "nicht eingerichtet"}</dd>
        <dt>Telegram</dt>
        <dd>{config?.channels.telegram ? "eingerichtet" : "nicht eingerichtet"}</dd>
      </dl>

      {config && config.devices.length > 0 && (
        <>
          <h3 className="block-title">Eingetragene Geräte</h3>
          <ul className="push-devices">
            {config.devices.map((device) => (
              <li key={device.endpoint_hint}>
                <b>{device.label ?? "Gerät"}</b>{" "}
                <span className="muted">seit {device.created_at.slice(0, 10)}</span>
                <br />
                <span className="muted">
                  {device.last_ok_at
                    ? `zuletzt zugestellt: ${device.last_ok_at.slice(0, 16).replace("T", " ")}`
                    : "noch nichts zugestellt"}
                  {device.failures > 0 ? ` · ${device.failures} Fehlversuche` : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {!config?.public_base_url && (
        <p className="muted">
          Hinweis: Ohne feste Adresse (PUBLIC_BASE_URL) öffnet ein Tippen auf die
          Benachrichtigung nur die Startseite statt der passenden Aktie.
        </p>
      )}
    </section>
  );
}
