import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiFetchJson } from "./client";
import { ProjectSchema } from "../types/dto";

const ProjectsSchema = z.array(ProjectSchema);

export function useProjectsQuery() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: async () => apiFetchJson("/projects", { schema: ProjectsSchema })
  });
}

export function useProjectQuery(projectId: string) {
  return useQuery({
    queryKey: ["projects", projectId],
    queryFn: async () => apiFetchJson(`/projects/${encodeURIComponent(projectId)}`, { schema: ProjectSchema }),
    enabled: Boolean(projectId)
  });
}

export function useCreateProjectMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { name: string; description?: string }) =>
      apiFetchJson("/projects", { method: "POST", body: input, schema: ProjectSchema }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["projects"] });
    }
  });
}

export function useUpdateProjectMutation(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: Partial<{ name: string; description: string }>) =>
      apiFetchJson(`/projects/${encodeURIComponent(projectId)}`, {
        method: "PATCH",
        body: patch,
        schema: ProjectSchema
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["projects"] });
      await qc.invalidateQueries({ queryKey: ["projects", projectId] });
    }
  });
}

