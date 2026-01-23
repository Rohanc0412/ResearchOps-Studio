import { Link, useParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";

import { useSnippetQuery, useSourceQuery } from "../api/evidence";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";

export function EvidencePage() {
  const { snippetId } = useParams();
  const id = snippetId ?? "";
  const snippet = useSnippetQuery(id);
  const source = useSourceQuery(snippet.data?.source_id ?? null);

  if (snippet.isLoading) {
    return (
      <Card>
        <Spinner label="Loading snippet…" />
      </Card>
    );
  }
  if (snippet.isError) {
    return <ErrorBanner message={snippet.error instanceof Error ? snippet.error.message : "Failed to load snippet"} />;
  }
  const s = snippet.data;
  if (!s) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Evidence Snippet</div>
          <div className="text-sm text-slate-500">
            id <span className="text-slate-300">{s.id}</span>
          </div>
        </div>
        <Link to="/projects">
          <Button variant="secondary">Projects</Button>
        </Link>
      </div>

      <Card>
        <div className="mb-2 text-sm font-semibold text-slate-100">Snippet</div>
        <pre className="overflow-auto rounded-md border border-slate-900 bg-black/30 p-3 text-xs text-slate-200">
          {s.text}
        </pre>
        {s.risk_flags?.length ? (
          <div className="mt-3 text-sm text-amber-200">Risk flags: {s.risk_flags.join(", ")}</div>
        ) : null}
      </Card>

      <Card>
        <div className="mb-2 text-sm font-semibold text-slate-100">Source</div>
        {source.isLoading ? (
          <Spinner label="Loading source…" />
        ) : source.isError ? (
          <div className="text-sm text-slate-500">Source lookup failed or is unavailable.</div>
        ) : source.data ? (
          <div className="flex flex-col gap-2 text-sm text-slate-300">
            <div>
              <span className="text-slate-500">Title:</span> {source.data.title ?? "—"}
            </div>
            <div>
              <span className="text-slate-500">Canonical id:</span> {source.data.canonical_id ?? "—"}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-500">URL:</span>{" "}
              {source.data.url ? (
                <a className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200" href={source.data.url} target="_blank" rel="noreferrer">
                  Open <ExternalLink className="h-3 w-3" />
                </a>
              ) : (
                "—"
              )}
            </div>
          </div>
        ) : (
          <div className="text-sm text-slate-500">No source metadata for this snippet.</div>
        )}
      </Card>
    </div>
  );
}

