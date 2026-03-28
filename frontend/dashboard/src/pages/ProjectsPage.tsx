import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Folder, Plus, Search } from "lucide-react";

import { useCreateProjectMutation, useProjectsQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Spinner } from "../components/ui/Spinner";
import { formatTs } from "../utils/format";

// All solid hex — no rgba, no opacity modifiers
const BG       = "#0b0b0e";
const SURFACE  = "#101015";
const BORDER   = "#1c1c24";
const ACCENT   = "#9580c4";
const TEXT     = "#e0dde6";
const MUTED    = "#8a8694";

const ROW_STYLE    = { backgroundColor: BG,      boxShadow: `0 0 0 1px ${BORDER}` };
const ROW_HOVER    = { backgroundColor: SURFACE,  boxShadow: `0 0 0 1px ${BORDER}` };

export function ProjectsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projects = useProjectsQuery();
  const create   = useCreateProjectMutation();

  const [q, setQ]               = useState("");
  const [open, setOpen]         = useState(false);
  const [name, setName]         = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setOpen(true);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const rows = useMemo(() => {
    const list  = projects.data ?? [];
    const query = q.trim().toLowerCase();
    return query ? list.filter((p) => p.name.toLowerCase().includes(query)) : list;
  }, [projects.data, q]);

  async function submitCreate() {
    const n = name.trim();
    if (!n) return;
    await create.mutateAsync({ name: n, description: description.trim() || undefined });
    setOpen(false);
    setName("");
    setDescription("");
  }

  return (
    <div className="flex flex-col gap-8">

      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[28px] font-semibold leading-tight" style={{ color: TEXT }}>
            Projects
          </h1>
          <p className="mt-1 text-sm" style={{ color: MUTED }}>
            Create and manage research projects.
          </p>
        </div>
        <Button onClick={() => setOpen(true)} className="shrink-0">
          <Plus className="h-4 w-4" />
          New Project
        </Button>
      </div>

      {/* Search */}
      <div
        className="flex items-center gap-3 rounded-xl px-4 py-3"
        style={{ backgroundColor: BG, boxShadow: `0 0 0 1px ${BORDER}` }}
      >
        <Search className="h-4 w-4 shrink-0" style={{ color: MUTED }} />
        <input
          placeholder="Search projects…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="flex-1 bg-transparent text-sm focus:outline-none"
          style={{ color: TEXT }}
        />
      </div>

      {/* Content */}
      {projects.isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading projects…" />
        </div>
      ) : projects.isError ? (
        <ErrorBanner
          message={projects.error instanceof Error ? projects.error.message : "Failed to load projects"}
        />
      ) : rows.length === 0 && q.trim() ? (
        <EmptyState
          icon={<Folder className="h-5 w-5" />}
          title={`No projects matching "${q.trim()}"`}
          description="Try a different search term or clear the search to see all projects."
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Folder className="h-5 w-5" />}
          title="No projects yet"
          description="Create your first project to start research runs."
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              New Project
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-2">
          {/* Column labels — no background */}
          <div className="grid grid-cols-[2fr_1.5fr_1fr_80px] gap-4 px-4">
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>Name</span>
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>Created</span>
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: MUTED }}>Last run</span>
            <span />
          </div>

          {/* Rows — each is its own element, background = page bg */}
          {rows.map((p) => (
            <Link
              key={p.id}
              to={`/projects/${encodeURIComponent(p.id)}`}
              className="grid grid-cols-[2fr_1.5fr_1fr_80px] items-center gap-4 rounded-xl px-4 py-4"
              style={ROW_STYLE}
              onMouseEnter={(e) => Object.assign((e.currentTarget as HTMLElement).style, ROW_HOVER)}
              onMouseLeave={(e) => Object.assign((e.currentTarget as HTMLElement).style, ROW_STYLE)}
            >
              <div>
                <div className="text-sm font-medium" style={{ color: TEXT }}>{p.name}</div>
                {p.description && (
                  <div className="mt-0.5 text-xs" style={{ color: MUTED }}>{p.description}</div>
                )}
              </div>
              <span className="font-mono text-sm" style={{ color: MUTED }}>{formatTs(p.created_at)}</span>
              <span className="font-mono text-sm" style={{ color: MUTED }}>{p.last_run_status ?? "—"}</span>
              <span className="text-right text-sm font-medium" style={{ color: ACCENT }}>Open →</span>
            </Link>
          ))}
        </div>
      )}

      {/* Create project modal */}
      <Modal open={open} title="New Project" onClose={() => setOpen(false)}>
        <div className="flex flex-col gap-5">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium" htmlFor="proj-name" style={{ color: MUTED }}>
              Name
            </label>
            <Input
              id="proj-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Market landscape: LLM evaluation"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium" htmlFor="proj-desc" style={{ color: MUTED }}>
              Description
              <span className="ml-1" style={{ color: MUTED, opacity: 0.6 }}>(optional)</span>
            </label>
            <textarea
              id="proj-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this project about?"
              rows={3}
              className="w-full resize-y rounded-lg px-3 py-2 text-sm font-sans focus:outline-none"
              style={{
                backgroundColor: BG,
                color: TEXT,
                border: `1px solid ${BORDER}`,
              }}
            />
          </div>

          {create.isError && (
            <ErrorBanner
              message={create.error instanceof Error ? create.error.message : "Create failed"}
            />
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button
              onClick={() => void submitCreate()}
              disabled={!name.trim()}
              loading={create.isPending}
            >
              {create.isPending ? "Creating…" : "Create Project"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
