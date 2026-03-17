import { useQuery } from "@tanstack/react-query";

import { apiFetchJson } from "./client";
import { SnippetSchema, SourceSchema } from "../types/dto";

export function useSnippetQuery(snippetId: string) {
  return useQuery({
    queryKey: ["snippets", snippetId],
    queryFn: async () => apiFetchJson(`/snippets/${encodeURIComponent(snippetId)}`, { schema: SnippetSchema }),
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

