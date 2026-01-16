import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Search } from "lucide-react";

import { useCreateProjectMutation, useProjectsQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Spinner } from "../components/ui/Spinner";
import { formatTs } from "../utils/format";

export function ProjectsPage() {
  const projects = useProjectsQuery();
  const create = useCreateProjectMutation();

  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

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
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-lg font-semibold text-slate-100">Projects</div>
          <div className="text-sm text-slate-500">Create and manage research projects.</div>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" />
          New Project
        </Button>
      </div>

      <Card className="p-4">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-slate-500" />
          <Input placeholder="Search projects…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </Card>

      {projects.isLoading ? (
        <Card>
          <Spinner label="Loading projects…" />
        </Card>
      ) : projects.isError ? (
        <ErrorBanner message={projects.error instanceof Error ? projects.error.message : "Failed to load projects"} />
      ) : rows.length === 0 ? (
        <EmptyState title="No projects" description="Create your first project to start runs." action={<Button onClick={() => setOpen(true)}>New Project</Button>} />
      ) : (
        <Card className="p-0">
          <div className="overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-900 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3">Last run</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="border-b border-slate-900 last:border-0">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-100">{p.name}</div>
                      {p.description ? <div className="text-xs text-slate-500">{p.description}</div> : null}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{formatTs(p.created_at)}</td>
                    <td className="px-4 py-3 text-slate-400">{p.last_run_status ?? "—"}</td>
                    <td className="px-4 py-3 text-right">
                      <Link to={`/projects/${encodeURIComponent(p.id)}`} className="text-sm font-medium text-sky-300 hover:text-sky-200">
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Modal open={open} title="Create Project" onClose={() => setOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Name</div>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Market landscape: LLM evaluation" />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Description</div>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
              rows={4}
              placeholder="Optional"
            />
          </div>
          {create.isError ? <ErrorBanner message={create.error instanceof Error ? create.error.message : "Create failed"} /> : null}
          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void submitCreate()} disabled={!name.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
