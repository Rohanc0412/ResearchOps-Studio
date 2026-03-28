import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

const RunSnippetSchema = z.object({
  id: z.string(),
  text: z.string(),
  source_id: z.string().nullable(),
  source_title: z.string().nullable(),
  source_url: z.string().nullable(),
});
export type RunSnippet = z.infer<typeof RunSnippetSchema>;
const RunSnippetsSchema = z.array(RunSnippetSchema);

import { apiFetch, apiFetchJson } from "./client";
import { ArtifactSchema } from "../types/dto";

const ArtifactsSchema = z.array(ArtifactSchema);

export function useRunArtifactsQuery(runId: string) {
  return useQuery({
    queryKey: ["runs", runId, "artifacts"],
    queryFn: async () => apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, { schema: ArtifactsSchema }),
    enabled: Boolean(runId)
  });
}

export function useRunSnippetsQuery(runId: string) {
  return useQuery({
    queryKey: ["runs", runId, "snippets"],
    queryFn: async () => apiFetchJson(`/runs/${encodeURIComponent(runId)}/snippets`, { schema: RunSnippetsSchema }),
    enabled: Boolean(runId),
  });
}

export async function downloadArtifact(artifactId: string): Promise<void> {
  const response = await apiFetch(`/artifacts/${encodeURIComponent(artifactId)}/download`, { method: "GET" });
  if (!response.ok) throw new Error(`Download failed (${response.status})`);

  const blob = await response.blob();
  const filename = filenameFromDisposition(response.headers.get("content-disposition")) ?? `artifact-${artifactId}`;

  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8''|"?)([^";]+)/i.exec(disposition);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1].replace(/"/g, ""));
  } catch {
    return match[1].replace(/"/g, "");
  }
}

