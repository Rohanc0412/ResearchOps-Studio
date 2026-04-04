// frontend/dashboard/src/api/evaluation.ts
import { useCallback, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson, apiBaseUrl } from "./client";
import { accessToken, handleUnauthorized } from "./auth";

// ── Schemas ───────────────────────────────────────────────────────────────────

export const EvaluationClaimSchema = z.object({
  claim_index: z.number(),
  claim_text: z.string(),
  verdict: z.string(),
  citations: z.array(z.string()),
  notes: z.string().optional(),
});
export type EvaluationClaim = z.infer<typeof EvaluationClaimSchema>;

export const EvaluationSectionSchema = z.object({
  section_id: z.string(),
  title: z.string(),
  quality_score: z.number().nullable(),
  claims: z.array(EvaluationClaimSchema),
});
export type EvaluationSection = z.infer<typeof EvaluationSectionSchema>;

export const EvaluationPassSchema = z.object({
  id: z.string(),
  scope: z.string(),
  pass_index: z.number(),
  status: z.string(),
  evaluated_at: z.string().nullable().optional(),
  quality_pct: z.number().nullable().optional(),
  hallucination_rate: z.number().nullable().optional(),
  sections: z.array(EvaluationSectionSchema),
});
export type EvaluationPass = z.infer<typeof EvaluationPassSchema>;

export const EvaluationResultSchema = z.object({
  status: z.enum(["none", "running", "complete"]),
  evaluated_at: z.string().nullable().optional(),
  quality_pct: z.number().nullable().optional(),
  hallucination_rate: z.number().nullable().optional(),
  sections: z.array(EvaluationSectionSchema).optional(),
  history: z.array(EvaluationPassSchema).optional(),
});
export type EvaluationResult = z.infer<typeof EvaluationResultSchema>;

export const EvaluationProgressSchema = z.object({
  step: z.number(),
  stepLabel: z.string(),
  partialQualityPct: z.number().nullable().optional(),
  partialHallucinationRate: z.number().nullable().optional(),
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
  const isRunningRef = useRef(false);

  const mutate = useCallback(async () => {
    if (isRunningRef.current) return;
    setIsRunning(true);
    isRunningRef.current = true;
    setProgress({ step: 1, stepLabel: "Starting...", sections: [] });
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
        if (response.status === 401) handleUnauthorized();
        if (response.status === 409) {
          await qc.invalidateQueries({ queryKey: ["runs", runId, "evaluation"] });
          setError("Evaluation is already running.");
          return;
        }
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
              partialQualityPct: prev?.partialQualityPct,
              partialHallucinationRate: prev?.partialHallucinationRate,
            }));
          }

          if (type === "evaluation.section") {
            const sec = EvaluationSectionSchema.safeParse({
              section_id: event["section_id"],
              title: event["section_title"],
              quality_score: event["quality_score"] ?? null,
              claims: event["verdicts"] ?? [],
            });
            if (sec.success) {
              setProgress((prev) => ({
                ...(prev ?? { step: 1, stepLabel: "Scoring sections..." }),
                sections: [...(prev?.sections ?? []), sec.data],
              }));
            }
          }

          if (type === "evaluation.complete") {
            await qc.refetchQueries({ queryKey: ["runs", runId, "evaluation"] });
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
      isRunningRef.current = false;
      setProgress(null);
    }
  }, [runId, qc]);

  return { mutate, isRunning, progress, error };
}
