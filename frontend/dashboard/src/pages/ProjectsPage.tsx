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

export function ProjectsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projects = useProjectsQuery();
  const create = useCreateProjectMutation();

  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (searchParams.get("new") === "1") {
      setOpen(true);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const rows = useMemo(() => {
    const list = projects.data ?? [];
    const query = q.trim().toLowerCase();
    if (!query) return list;
    return list.filter((p) => p.name.toLowerCase().includes(query));
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
          <h1 className="font-display text-[28px] font-semibold leading-tight text-obsidian-text">
            Projects
          </h1>
          <p className="mt-1 text-sm text-obsidian-muted">
            Create and manage research projects.
          </p>
        </div>
        <Button onClick={() => setOpen(true)} className="shrink-0">
          <Plus className="h-4 w-4" />
          New Project
        </Button>
      </div>

      {/* Search */}
      <div className="flex items-center gap-3 rounded-xl border border-obsidian-border-subtle bg-obsidian-surface-elevated px-4 py-3">
        <Search className="h-4 w-4 shrink-0 text-obsidian-muted" />
        <input
          placeholder="Search projects…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="flex-1 bg-transparent text-sm text-obsidian-text placeholder:text-obsidian-muted focus:outline-none"
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
        <div className="overflow-hidden rounded-xl border border-obsidian-border">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-obsidian-border bg-obsidian-surface">
                <th className="px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-obsidian-muted">
                  Name
                </th>
                <th className="px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-obsidian-muted">
                  Created
                </th>
                <th className="px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-obsidian-muted">
                  Last run
                </th>
                <th className="px-5 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-obsidian-muted">
                  &nbsp;
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-obsidian-border-subtle">
              {rows.map((p) => (
                <tr
                  key={p.id}
                  className="bg-obsidian-surface-elevated transition-colors hover:bg-obsidian-accent-dim"
                >
                  <td className="px-5 py-4">
                    <div className="font-medium text-obsidian-text">{p.name}</div>
                    {p.description && (
                      <div className="mt-0.5 text-xs text-obsidian-muted">{p.description}</div>
                    )}
                  </td>
                  <td className="px-5 py-4 font-mono text-sm text-obsidian-muted">
                    {formatTs(p.created_at)}
                  </td>
                  <td className="px-5 py-4 font-mono text-sm text-obsidian-muted">
                    {p.last_run_status ?? "—"}
                  </td>
                  <td className="px-5 py-4 text-right">
                    <Link
                      to={`/projects/${encodeURIComponent(p.id)}`}
                      className="text-sm font-medium text-obsidian-accent hover:brightness-125"
                    >
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create project modal */}
      <Modal open={open} title="New Project" onClose={() => setOpen(false)}>
        <div className="flex flex-col gap-5">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-obsidian-muted" htmlFor="proj-name">
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
            <label className="block text-xs font-medium text-obsidian-muted" htmlFor="proj-desc">
              Description
              <span className="ml-1 text-obsidian-muted/60">(optional)</span>
            </label>
            <textarea
              id="proj-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this project about?"
              rows={3}
              className="w-full resize-y rounded-lg border border-obsidian-border bg-obsidian-bg px-3 py-2 text-sm font-sans text-obsidian-text placeholder:text-obsidian-muted focus:border-obsidian-accent focus:outline-none focus:ring-2 focus:ring-obsidian-accent/20"
            />
          </div>

          {create.isError && (
            <ErrorBanner
              message={create.error instanceof Error ? create.error.message : "Create failed"}
            />
          )}

          <div className="flex items-center justify-end gap-3 pt-1">
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
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
