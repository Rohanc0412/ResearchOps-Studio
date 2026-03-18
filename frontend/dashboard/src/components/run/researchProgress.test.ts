import { describe, expect, it } from "vitest";

import { buildResearchProgressCardModel } from "./researchProgress";
import type { ChatMessage } from "../../types/dto";

function makeMessage(partial: Partial<ChatMessage>): ChatMessage {
  return {
    id: partial.id ?? "msg-1",
    role: partial.role ?? "user",
    type: partial.type ?? "chat",
    content_text: partial.content_text ?? "",
    content_json: partial.content_json ?? null,
    created_at: partial.created_at ?? new Date().toISOString()
  };
}

describe("buildResearchProgressCardModel", () => {
  it("prefers the original research prompt over a generic run trigger", () => {
    const model = buildResearchProgressCardModel({
      activeRun: {
        status: "running",
        primaryText: "Starting run..."
      },
      chatTitle: "Effects of DHT on hair fall",
      messages: [
        makeMessage({ id: "m1", content_text: "Effects of DHT on hair fall" }),
        makeMessage({ id: "m2", content_text: "Create the detailed research report now." })
      ],
      events: []
    });

    expect(model.title).toBe("Effects of DHT on hair fall");
    expect(model.steps[0]?.label).toContain("Effects of DHT on hair fall");
  });
});
