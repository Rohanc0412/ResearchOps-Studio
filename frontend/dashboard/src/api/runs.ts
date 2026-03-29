import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { RunSchema } from "../types/dto";

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "canceled"]);

const OkSchema = z.object({ ok: z.literal(true) }).passthrough();

export function useRunQuery(runId: string) {
  return useQuery({
    queryKey: ["runs", runId],
    queryFn: async () => apiFetchJson(`/runs/${encodeURIComponent(runId)}`, { schema: RunSchema }),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      query.state.data && TERMINAL_STATUSES.has(query.state.data.status) ? false : 5_000
  });
}

export function useCancelRunMutation(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      apiFetchJson(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", schema: OkSchema }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["runs", runId] });
    }
  });
}

export function useRetryRunMutation(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (llmModel?: string) =>
      apiFetchJson(`/runs/${encodeURIComponent(runId)}/retry`, {
        method: "POST",
        schema: OkSchema,
        body: llmModel ? { llm_model: llmModel } : undefined,
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["runs", runId] });
    }
  });
}

