import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Play } from "lucide-react";

import { useProjectQuery } from "../api/projects";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { formatTs } from "../utils/format";

export function ProjectDetailPage() {
  const { projectId } = useParams();
  const id = projectId ?? "";
  const project = useProjectQuery(id);

  if (project.isLoading) {
    return (
      <Card>
        <Spinner label="Loading project…" />
      </Card>
    );
  }

  if (project.isError) {
    return <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />;
  }

  const p = project.data;
  if (!p) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link to="/projects" className="text-slate-400 hover:text-slate-200">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <div className="text-lg font-semibold text-slate-100">{p.name}</div>
            <div className="text-sm text-slate-500">Created {formatTs(p.created_at)}</div>
          </div>
        </div>
        <Link to={`/projects/${encodeURIComponent(p.id)}/new-run`}>
          <Button>
            <Play className="h-4 w-4" />
            New Run
          </Button>
        </Link>
      </div>

      <Card>
        <div className="text-sm font-semibold text-slate-100">Project Info</div>
        <div className="mt-2 text-sm text-slate-400">{p.description ?? "No description."}</div>
      </Card>

      <Card>
        <div className="text-sm font-semibold text-slate-100">Settings</div>
        <div className="mt-2 text-sm text-slate-500">Placeholder: project settings will appear here.</div>
      </Card>
    </div>
  );
}

