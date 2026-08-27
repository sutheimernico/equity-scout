import { describe, expect, it } from "vitest";

import { deviceLabel, pushState, stateMessage, urlBase64ToUint8Array } from "./push";

describe("urlBase64ToUint8Array", () => {
  it("decodes an unpadded base64url VAPID key to raw bytes", () => {
    // "BA" -> 0x04 0x00 ... the first byte of an uncompressed P-256 point.
    const bytes = urlBase64ToUint8Array("BAAA");
    expect(Array.from(bytes)).toEqual([4, 0, 0]);
  });

  it("handles the - and _ substitutions base64url makes", () => {
    // "+/" in standard base64 -> "-_" in base64url. Getting this wrong is the classic
    // silent failure: subscribe() then throws InvalidCharacterError with no explanation.
    expect(Array.from(urlBase64ToUint8Array("-_8="))).toEqual(
      Array.from(urlBase64ToUint8Array("+/8=")),
    );
  });
});

describe("pushState", () => {
  const base = { supported: true, secureContext: true, permission: "default" as NotificationPermission, subscribed: false };

  it("reports unsupported before anything else", () => {
    expect(pushState({ ...base, supported: false, secureContext: false })).toBe("unsupported");
  });

  it("separates 'no HTTPS' from 'not asked' — they need different advice", () => {
    expect(pushState({ ...base, secureContext: false })).toBe("insecure");
    expect(pushState(base)).toBe("prompt");
  });

  it("distinguishes permission from an actual subscription", () => {
    expect(pushState({ ...base, permission: "granted", subscribed: false })).toBe(
      "permitted-not-subscribed",
    );
    expect(pushState({ ...base, permission: "granted", subscribed: true })).toBe("granted");
  });

  it("treats denied as terminal", () => {
    expect(pushState({ ...base, permission: "denied", subscribed: true })).toBe("denied");
  });
});

describe("stateMessage", () => {
  it("gives every state a distinct German sentence", () => {
    const states = ["unsupported", "insecure", "denied", "granted", "permitted-not-subscribed", "prompt"] as const;
    const messages = states.map(stateMessage);
    expect(new Set(messages).size).toBe(states.length);
    expect(messages.every((m) => m.length > 10)).toBe(true);
  });
});

describe("deviceLabel", () => {
  it("names platform and browser so two phones stay apart", () => {
    expect(deviceLabel("Mozilla/5.0 (Linux; Android 14) Chrome/126.0")).toBe("Android · Chrome");
    expect(deviceLabel("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605")).toBe("iOS · Safari");
  });

  it("falls back rather than inventing a name", () => {
    expect(deviceLabel("")).toBe("Gerät · Browser");
  });
});
