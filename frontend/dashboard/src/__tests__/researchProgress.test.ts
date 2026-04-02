import { describe, expect, it } from "vitest";

import { buildResearchProgressCardModel } from "../components/run/researchProgress";
import { RunEventSchema } from "../types/dto";

describe("RunEventSchema", () => {
  it("requires audience and event_type in the run event contract", () => {
    const parsed = RunEventSchema.safeParse({
      ts: "2026-04-02T12:30:00.000Z",
      level: "info",
      stage: "retrieve",
      audience: "progress",
      event_type: "retrieve.plan_created",
      message: "Created query plan",
      payload: { query_count: 3 },
    });

    expect(parsed.success).toBe(true);
  });
});

describe("buildResearchProgressCardModel", () => {
  it("keeps progress events and terminal state events while filtering diagnostic noise", () => {
    const model = buildResearchProgressCardModel({
      activeRun: {
        status: "failed",
        primaryText: "Working",
        error: "Run failed",
      },
      chatTitle: "Contract test",
      messages: [],
      events: [
        {
          ts: "2026-04-02T12:00:00.000Z",
          level: "info",
          stage: "retrieve",
          audience: "progress",
          event_type: "retrieve.query_progress",
          message: "query tick",
          payload: { query_count: 1 },
        },
        {
          ts: "2026-04-02T12:01:00.000Z",
          level: "info",
          stage: "retrieve",
          audience: "diagnostic",
          event_type: "retrieve.internal_debug",
          message: "debug trace",
          payload: {},
        },
        {
          ts: "2026-04-02T12:02:00.000Z",
          level: "info",
          stage: "retrieve",
          audience: "progress",
          event_type: "retrieve.query_progress",
          message: "query tick",
          payload: { query_count: 2 },
        },
        {
          ts: "2026-04-02T12:03:00.000Z",
          level: "warn",
          stage: "evaluate",
          audience: "state",
          event_type: "state",
          message: "Run transitioned: running -> failed",
          payload: { from_status: "running", to_status: "failed" },
        },
        {
          ts: "2026-04-02T12:04:00.000Z",
          level: "info",
          stage: "evaluate",
          audience: "state",
          event_type: "state",
          message: "Run transitioned: created -> queued",
          payload: { from_status: "created", to_status: "queued" },
        },
      ],
    });

    const recentTs = model.recentEvents.map((event) => event.ts);
    expect(recentTs).toContain("2026-04-02T12:03:00.000Z");
    expect(recentTs).toContain("2026-04-02T12:02:00.000Z");
    expect(recentTs).toContain("2026-04-02T12:00:00.000Z");
    expect(recentTs).not.toContain("2026-04-02T12:01:00.000Z");
    expect(recentTs).not.toContain("2026-04-02T12:04:00.000Z");
  });

  it("preserves granular progress rows even when messages repeat", () => {
    const model = buildResearchProgressCardModel({
      activeRun: {
        status: "failed",
        primaryText: "Working",
      },
      chatTitle: "Contract test",
      messages: [],
      events: [
        {
          ts: "2026-04-02T12:00:00.000Z",
          level: "info",
          stage: "retrieve",
          audience: "progress",
          event_type: "retrieve.query_progress",
          message: "query tick",
          payload: { query_count: 1 },
        },
        {
          ts: "2026-04-02T12:02:00.000Z",
          level: "info",
          stage: "retrieve",
          audience: "progress",
          event_type: "retrieve.query_progress",
          message: "query tick",
          payload: { query_count: 2 },
        },
      ],
    });

    const queryTickRows = model.recentEvents.filter(
      (event) => event.ts === "2026-04-02T12:00:00.000Z" || event.ts === "2026-04-02T12:02:00.000Z"
    );

    expect(queryTickRows).toHaveLength(2);
  });
});
