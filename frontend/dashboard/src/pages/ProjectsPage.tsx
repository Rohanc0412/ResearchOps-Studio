import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, Search } from "lucide-react";

import { useCreateProjectMutation, useProjectsQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
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
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h1
            className="text-3xl font-bold bg-gradient-to-r from-white to-[#a5b4fc] bg-clip-text text-transparent tracking-[-0.02em]"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Projects
          </h1>
          <p className="mt-1 text-sm font-medium text-slate-500">Create and manage research projects.</p>
        </div>
        <button
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-[#9580c4] px-5 py-3 text-sm font-semibold text-white shadow-[0_4px_12px_rgba(149,128,196,0.25)] transition-all hover:bg-[#a792ce] hover:-translate-y-px hover:shadow-[0_6px_18px_rgba(149,128,196,0.35)] active:translate-y-0 active:bg-[#8670b8]"
        >
          <Plus className="h-4 w-4" />
          New Project
        </button>
      </div>

      {/* Search */}
      <GlassCard>
        <div className="flex items-center gap-3 p-4">
          <Search className="h-[18px] w-[18px] flex-shrink-0 text-slate-500" />
          <input
            placeholder="Search projects…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="flex-1 rounded-lg border border-white/[0.08] bg-slate-950/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/10 transition"
          />
        </div>
      </GlassCard>

      {/* Projects table */}
      {projects.isLoading ? (
        <GlassCard>
          <div className="p-8">
            <Spinner label="Loading projects…" />
          </div>
        </GlassCard>
      ) : projects.isError ? (
        <ErrorBanner message={projects.error instanceof Error ? projects.error.message : "Failed to load projects"} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No projects"
          description="Create your first project to start runs."
          action={<Button onClick={() => setOpen(true)}>New Project</Button>}
        />
      ) : (
        <GlassCard>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/[0.06] bg-slate-950/50">
                <tr>
                  <th className="px-5 py-4 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Name</th>
                  <th className="px-5 py-4 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Created</th>
                  <th className="px-5 py-4 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Last run</th>
                  <th className="px-5 py-4 text-right text-[11px] font-semibold uppercase tracking-wider text-slate-500">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="border-b border-white/[0.04] last:border-0 transition-colors hover:bg-indigo-500/[0.04]">
                    <td className="px-5 py-5">
                      <div className="font-semibold text-slate-100">{p.name}</div>
                      {p.description ? <div className="text-xs text-slate-500">{p.description}</div> : null}
                    </td>
                    <td className="px-5 py-5 text-sm text-slate-400">{formatTs(p.created_at)}</td>
                    <td className="px-5 py-5 text-sm text-slate-400">{p.last_run_status ?? "—"}</td>
                    <td className="px-5 py-5 text-right">
                      <Link
                        to={`/projects/${encodeURIComponent(p.id)}`}
                        className="inline-block rounded-lg px-3 py-1.5 text-sm font-semibold text-[#9580c4] transition-colors hover:bg-[rgba(149,128,196,0.1)] hover:text-[#a792ce]"
                      >
                        Open →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      {/* Create project modal */}
      <Modal open={open} title="Create Project" onClose={() => setOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1.5 text-xs font-semibold text-slate-400">Name</div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Market landscape: LLM evaluation"
              className="w-full rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/10 transition"
            />
          </div>
          <div>
            <div className="mb-1.5 text-xs font-semibold text-slate-400">Description</div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional"
              rows={4}
              className="w-full resize-y rounded-lg border border-slate-800 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500/50 focus:outline-none focus:ring-2 focus:ring-indigo-500/10 transition"
            />
          </div>
          {create.isError ? <ErrorBanner message={create.error instanceof Error ? create.error.message : "Create failed"} /> : null}
          <div className="flex items-center justify-end gap-3 pt-3">
            <button
              onClick={() => setOpen(false)}
              className="rounded-lg border border-white/10 px-5 py-2.5 text-sm font-medium text-slate-300 transition hover:border-white/[0.15] hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              onClick={() => void submitCreate()}
              disabled={!name.trim() || create.isPending}
              className="rounded-lg bg-[#9580c4] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_2px_8px_rgba(149,128,196,0.25)] transition hover:bg-[#a792ce] hover:shadow-[0_4px_12px_rgba(149,128,196,0.35)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {create.isPending ? "Creating…" : "Create"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/** Glassmorphism card with a frosted-glass background and a subtle top-edge gloss. */
function GlassCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`relative overflow-hidden rounded-2xl border border-white/[0.09] bg-[rgba(20,20,26,0.88)] shadow-[0_8px_24px_rgba(0,0,0,0.4)] backdrop-blur-xl ${className ?? ""}`}>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-white/[0.04] to-transparent" />
      <div className="relative">{children}</div>
    </div>
  );
}
