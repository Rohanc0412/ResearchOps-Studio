// frontend/dashboard/src/api/evaluation.ts
import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson, apiBaseUrl } from "./client";
import { accessToken } from "./auth";

// ── Schemas ───────────────────────────────────────────────────────────────────

export const EvaluationIssueSchema = z.object({
  sentence_index: z.number(),
  problem: z.string(),
  notes: z.string(),
  citations: z.array(z.string()),
});
export type EvaluationIssue = z.infer<typeof EvaluationIssueSchema>;

export const EvaluationSectionSchema = z.object({
  section_id: z.string(),
  title: z.string(),
  grounding_score: z.number().nullable(),
  verdict: z.enum(["pass", "fail"]),
  issues: z.array(EvaluationIssueSchema),
});
export type EvaluationSection = z.infer<typeof EvaluationSectionSchema>;

export const EvaluationResultSchema = z.object({
  status: z.enum(["none", "running", "complete"]),
  evaluated_at: z.string().nullable().optional(),
  grounding_pct: z.number().nullable().optional(),
  faithfulness_pct: z.number().nullable().optional(),
  sections_passed: z.number().optional(),
  sections_total: z.number().optional(),
  issues_by_type: z.record(z.number()).optional(),
  sections: z.array(EvaluationSectionSchema).optional(),
});
export type EvaluationResult = z.infer<typeof EvaluationResultSchema>;

export const EvaluationProgressSchema = z.object({
  step: z.number(),
  stepLabel: z.string(),
  partialGrounding: z.number().nullable().optional(),
  partialFaithfulness: z.number().nullable().optional(),
  sections: z.array(EvaluationSectionSchema),
});
export type EvaluationProgress = z.infer<typeof EvaluationProgressSchema>;

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useEvaluationQuery(runId: string) {
  return useQuery({
    queryKey: ["runs", runId, "evaluation"],
    queryFn: async () =>
      apiFetchJson(`/runs/${encodeURIComponent(runId)}/evaluation`, {
        schema: EvaluationResultSchema,
      }),
    enabled: Boolean(runId),
  });
}

export function useRunEvaluateMutation(runId: string) {
  const qc = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState<EvaluationProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const mutate = useCallback(async () => {
    if (isRunning) return;
    setIsRunning(true);
    setProgress({ step: 1, stepLabel: "Starting…", sections: [] });
    setError(null);

    abortRef.current = new AbortController();

    try {
      const token = accessToken();
      const url = `${apiBaseUrl()}/runs/${encodeURIComponent(runId)}/evaluate`;
      const response = await fetch(url, {
        method: "POST",
        signal: abortRef.current.signal,
        headers: {
          accept: "text/event-stream",
          ...(token ? { authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
      });

      if (!response.ok || !response.body) {
        setError(`Request failed (${response.status})`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let event: Record<string, unknown>;
          try {
            event = JSON.parse(line.slice(6)) as Record<string, unknown>;
          } catch {
            continue;
          }

          const type = event["type"] as string;

          if (type === "evaluation.step") {
            setProgress((prev) => ({
              step: event["step"] as number,
              stepLabel: event["label"] as string,
              sections: prev?.sections ?? [],
              partialGrounding: prev?.partialGrounding,
              partialFaithfulness: prev?.partialFaithfulness,
            }));
          }

          if (type === "evaluation.section") {
            const sec = EvaluationSectionSchema.safeParse(event);
            if (sec.success) {
              setProgress((prev) => ({
                ...(prev ?? { step: 1, stepLabel: "Scoring sections…" }),
                sections: [...(prev?.sections ?? []), sec.data],
              }));
            }
          }

          if (type === "evaluation.grounding_done") {
            setProgress((prev) => ({
              ...(prev ?? { step: 1, stepLabel: "Grounding complete" }),
              sections: prev?.sections ?? [],
              partialGrounding: event["overall_grounding_pct"] as number,
            }));
          }

          if (type === "evaluation.faithfulness_done") {
            setProgress((prev) => ({
              ...(prev ?? { step: 2, stepLabel: "Faithfulness complete" }),
              sections: prev?.sections ?? [],
              partialFaithfulness: (event["faithfulness_pct"] as number | null) ?? undefined,
            }));
          }

          if (type === "evaluation.complete") {
            await qc.invalidateQueries({ queryKey: ["runs", runId, "evaluation"] });
          }

          if (type === "error") {
            setError((event["code"] as string | undefined) ?? "unknown_error");
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "unknown_error");
    } finally {
      setIsRunning(false);
      setProgress(null);
    }
  }, [runId, isRunning, qc]);

  return { mutate, isRunning, progress, error };
}
