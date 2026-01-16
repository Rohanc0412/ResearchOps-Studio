import { z } from "zod";

export type IsoTimestamp = string;

export type Me = {
  user_id: string;
  tenant_id: string;
  roles: string[];
  email?: string;
};

export const MeSchema: z.ZodType<Me, z.ZodTypeDef, unknown> = z
  .object({
    user_id: z.string().min(1),
    tenant_id: z.string().min(1),
    roles: z.union([z.array(z.string()), z.string()]).optional(),
    role: z.string().optional(),
    email: z.string().email().optional()
  })
  .passthrough()
  .transform((value): Me => {
    const roles = Array.isArray(value.roles)
      ? value.roles
      : typeof value.roles === "string"
        ? value.roles
            .split(",")
            .map((r) => r.trim())
            .filter(Boolean)
        : value.role
          ? [value.role]
          : [];
    return { user_id: value.user_id, tenant_id: value.tenant_id, roles, email: value.email };
  });

export type Project = {
  id: string;
  name: string;
  description?: string | null;
  created_at?: string;
  updated_at?: string;
  last_run_status?: string;
  [k: string]: unknown;
};

const ProjectWireSchema = z
  .object({
    id: z.string().min(1).optional(),
    project_id: z.string().min(1).optional(),
    name: z.string().min(1),
    description: z.string().nullable().optional(),
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
    last_run_status: z.string().optional()
  })
  .passthrough();

export const ProjectSchema: z.ZodType<Project, z.ZodTypeDef, unknown> = ProjectWireSchema.transform((p): Project => {
  const id = p.id ?? p.project_id;
  if (!id) throw new Error("Project is missing id");
  return { ...p, id };
});

export const RunStatusSchema = z.enum(["created", "queued", "running", "failed", "succeeded", "canceled"]);
export type RunStatus = z.infer<typeof RunStatusSchema>;

export type Artifact = {
  id: string;
  type: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
  [k: string]: unknown;
};

const ArtifactWireSchema = z
  .object({
    id: z.string().min(1).optional(),
    artifact_id: z.string().min(1).optional(),
    type: z.string().min(1).optional(),
    artifact_type: z.string().min(1).optional(),
    created_at: z.string().optional(),
    metadata: z.record(z.unknown()).optional()
  })
  .passthrough();

export const ArtifactSchema: z.ZodType<Artifact, z.ZodTypeDef, unknown> = ArtifactWireSchema.transform((a): Artifact => {
  const id = a.id ?? a.artifact_id;
  const type = a.type ?? a.artifact_type;
  if (!id) throw new Error("Artifact is missing id");
  if (!type) throw new Error("Artifact is missing type");
  return { ...a, id, type };
});

export type Run = {
  id: string;
  status: RunStatus;
  project_id?: string;
  tenant_id?: string;
  created_at?: string;
  updated_at?: string;
  error_message?: string | null;
  budgets?: Record<string, unknown>;
  artifacts?: Artifact[];
  [k: string]: unknown;
};

const RunWireSchema = z
  .object({
    id: z.string().min(1).optional(),
    run_id: z.string().min(1).optional(),
    project_id: z.string().optional(),
    tenant_id: z.string().optional(),
    status: RunStatusSchema,
    created_at: z.string().optional(),
    updated_at: z.string().optional(),
    error_message: z.string().nullable().optional(),
    budgets: z.record(z.unknown()).optional(),
    artifacts: z.array(ArtifactSchema).optional()
  })
  .passthrough();

export const RunSchema: z.ZodType<Run, z.ZodTypeDef, unknown> = RunWireSchema.transform((r): Run => {
  const id = r.id ?? r.run_id;
  if (!id) throw new Error("Run is missing id");
  return { ...r, id };
});

export const RunEventSchema = z
  .object({
    ts: z.string().min(1),
    level: z.enum(["info", "warn", "error"]),
    stage: z.enum(["retrieve", "ingest", "outline", "draft", "validate", "factcheck", "export"]),
    message: z.string(),
    payload: z.record(z.unknown()).optional()
  })
  .passthrough();

export type RunEvent = z.infer<typeof RunEventSchema>;

export type Snippet = {
  id: string;
  source_id?: string | null;
  text: string;
  title?: string;
  url?: string;
  risk_flags?: string[];
  [k: string]: unknown;
};

const SnippetWireSchema = z
  .object({
    id: z.string().min(1).optional(),
    snippet_id: z.string().min(1).optional(),
    source_id: z.string().nullable().optional(),
    text: z.string().min(1),
    title: z.string().optional(),
    url: z.string().optional(),
    risk_flags: z.array(z.string()).optional()
  })
  .passthrough();

export const SnippetSchema: z.ZodType<Snippet, z.ZodTypeDef, unknown> = SnippetWireSchema.transform((s): Snippet => {
  const id = s.id ?? s.snippet_id;
  if (!id) throw new Error("Snippet is missing id");
  return { ...s, id };
});

export type Source = {
  id: string;
  title?: string;
  url?: string;
  canonical_id?: string;
  [k: string]: unknown;
};

const SourceWireSchema = z
  .object({
    id: z.string().min(1).optional(),
    source_id: z.string().min(1).optional(),
    title: z.string().optional(),
    url: z.string().optional(),
    canonical_id: z.string().optional()
  })
  .passthrough();

export const SourceSchema: z.ZodType<Source, z.ZodTypeDef, unknown> = SourceWireSchema.transform((s): Source => {
  const id = s.id ?? s.source_id;
  if (!id) throw new Error("Source is missing id");
  return { ...s, id };
});

export function parseDto<T>(schema: z.ZodType<T>, data: unknown): T {
  return schema.parse(data);
}
