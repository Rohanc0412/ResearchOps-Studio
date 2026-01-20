import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { RunSchema } from "../types/dto";

const OkSchema = z.object({ ok: z.literal(true) }).passthrough();

export function useRunQuery(runId: string) {
  return useQuery({
    queryKey: ["runs", runId],
    queryFn: async () => apiFetchJson(`/runs/${encodeURIComponent(runId)}`, { schema: RunSchema }),
    enabled: Boolean(runId),
    refetchInterval: 5_000
  });
}

export function useCreateRunMutation(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      prompt: string;
      output_type?: "report" | "litmap" | "experiment_plan";
      budget_override?: {
        token_limit?: number;
        time_limit?: number;
        connector_calls_limit?: number;
      };
      llm_provider?: "local" | "hosted";
      llm_model?: string;
    }) =>
      apiFetchJson(`/projects/${encodeURIComponent(projectId)}/runs`, {
        method: "POST",
        body: { ...input, output_type: input.output_type ?? "report" },
        schema: RunSchema
      }),
    onSuccess: async (run) => {
      await qc.setQueryData(["runs", run.id], run);
    }
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
    mutationFn: async () =>
      apiFetchJson(`/runs/${encodeURIComponent(runId)}/retry`, { method: "POST", schema: OkSchema }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["runs", runId] });
    }
  });
}

