import { afterEach, describe, expect, it, vi } from "vitest";

import { askChatStream } from "./api";

function streamOf(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("askChatStream", () => {
  it("calls onChunk per arriving piece and finishes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf(["Micron ", "hat ein KGV"])));
    const seen: string[] = [];

    await askChatStream("Wie hoch ist das KGV?", (text) => seen.push(text));

    expect(seen.join("")).toBe("Micron hat ein KGV");
    expect(seen.length).toBeGreaterThan(1); // wirklich gestreamt, nicht am Stück
  });

  it("keeps umlauts intact when they straddle a chunk boundary", async () => {
    // "ä" ist zwei Bytes — ohne {stream: true} im Decoder wird daraus ein Fragezeichen.
    const bytes = new TextEncoder().encode("Rückgang");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 2)); // schneidet mitten durch "ü"
        controller.enqueue(bytes.slice(2));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 200 })));
    let text = "";

    await askChatStream("Frage?", (chunk) => {
      text += chunk;
    });

    expect(text).toBe("Rückgang");
  });

  it("throws when the endpoint fails so the panel can show an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));

    await expect(askChatStream("Frage?", () => {})).rejects.toThrow();
  });
});
