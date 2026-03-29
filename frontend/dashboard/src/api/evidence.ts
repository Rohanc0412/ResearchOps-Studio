import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { SnippetSchema, SourceSchema } from "../types/dto";

const SnippetDetailResponseSchema = z
  .object({
    snippet: z.record(z.unknown()),
    source: z.record(z.unknown()).optional()
  })
  .passthrough();

export function useSnippetQuery(snippetId: string) {
  return useQuery({
    queryKey: ["snippets", snippetId],
    queryFn: async () => {
      const raw = await apiFetchJson(`/snippets/${encodeURIComponent(snippetId)}`, {
        schema: SnippetDetailResponseSchema
      });
      const snippetObj = raw.snippet as Record<string, unknown>;
      const riskFlags = snippetObj["risk_flags"];
      const riskFlagsArray = Array.isArray(riskFlags)
        ? riskFlags
        : riskFlags && typeof riskFlags === "object"
          ? Object.entries(riskFlags as Record<string, string>)
              .filter(([, v]) => v !== "False" && v !== false)
              .map(([k]) => k)
          : undefined;
      const flat = {
        ...snippetObj,
        source_id: (raw.source as Record<string, unknown>)?.["id"] ?? snippetObj["source_id"],
        risk_flags: riskFlagsArray
      };
      return SnippetSchema.parse(flat);
    },
    enabled: Boolean(snippetId)
  });
}

export function useSourceQuery(sourceId?: string | null) {
  return useQuery({
    queryKey: ["sources", sourceId],
    queryFn: async () => apiFetchJson(`/sources/${encodeURIComponent(sourceId!)}`, { schema: SourceSchema }),
    enabled: Boolean(sourceId)
  });
}

