import { useEffect, useMemo, useRef, useState } from "react";

import type { RunEvent } from "../types/dto";
import { RunEventSchema } from "../types/dto";
import { apiFetch } from "../api/client";

type ConnectionState = "idle" | "connecting" | "open" | "closed" | "error";

export function useSSE(path: string | null, enabled: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [state, setState] = useState<ConnectionState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const attemptRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const lastEventIdRef = useRef<number>(0);

  const reset = () => {
    lastEventIdRef.current = 0;
    setEvents([]);
  };

  useEffect(() => {
    if (!enabled || !path) {
      abortRef.current?.abort();
      setState("idle");
      return;
    }

    let cancelled = false;
    const baseDelayMs = 500;
    const maxDelayMs = 15_000;
    const ssePath = path;

    async function connect() {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      setState("connecting");
      setLastError(null);

      try {
        const response = await apiFetch(ssePath, {
          method: "GET",
          headers: {
            accept: "text/event-stream",
            ...(lastEventIdRef.current > 0 ? { "last-event-id": String(lastEventIdRef.current) } : {})
          },
          signal: abort.signal
        });

        if (!response.ok) {
          const text = await response.text().catch(() => "");
          throw new Error(`SSE failed (${response.status}) ${text}`.trim());
        }

        if (!response.body) throw new Error("SSE response has no body");

        attemptRef.current = 0;
        setState("open");

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const raw = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const evt = parseSseEvent(raw);
            if (!evt?.data) continue;
            try {
              const json = JSON.parse(evt.data) as unknown;
              const parsed = RunEventSchema.safeParse(json);
              if (parsed.success) {
                const eventId = evt?.id ?? parsed.data.id;
                if (typeof eventId === "number" && eventId <= lastEventIdRef.current) {
                  continue;
                }
                if (typeof eventId === "number") lastEventIdRef.current = eventId;
                setEvents((prev) => (prev.length > 2000 ? [...prev.slice(-1500), parsed.data] : [...prev, parsed.data]));
              }
            } catch {
              // Ignore invalid JSON
            }
          }
        }

        if (!cancelled) setState("closed");
      } catch (e) {
        if (cancelled) return;
        if (abort.signal.aborted) return;
        setState("error");
        setLastError(e instanceof Error ? e.message : "SSE connection error");
      }

      if (cancelled) return;

      attemptRef.current += 1;
      const delay = Math.min(maxDelayMs, baseDelayMs * 2 ** Math.min(6, attemptRef.current));
      await sleep(delay);
      if (!cancelled) void connect();
    }

    void connect();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [enabled, path]);

  const latestStage = useMemo(() => events.at(-1)?.stage ?? null, [events]);

  return { events, state, lastError, latestStage, reset };
}

function parseSseEvent(chunk: string): { id?: number; event?: string; data?: string } | null {
  const lines = chunk.split("\n").map((l) => l.replace(/\r$/, ""));
  let id: number | undefined;
  let event: string | undefined;
  const dataLines: string[] = [];
  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("id:")) {
      const v = Number(line.slice("id:".length).trim());
      if (!Number.isNaN(v)) id = v;
    }
    if (line.startsWith("event:")) event = line.slice("event:".length).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trimStart());
  }
  if (!event && dataLines.length === 0) return null;
  return { id, event, data: dataLines.join("\n") };
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
