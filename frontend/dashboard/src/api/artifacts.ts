import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

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
  const match = /filename\*?=(?:UTF-8''|\"?)([^\";]+)/i.exec(disposition);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1].replace(/\"/g, ""));
  } catch {
    return match[1].replace(/\"/g, "");
  }
}

