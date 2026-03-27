import { Link, useParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";

import { useSnippetQuery, useSourceQuery } from "../api/evidence";
import { Button } from "../components/ui/Button";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";

export function EvidencePage() {
  const { snippetId } = useParams();
  const id = snippetId ?? "";
  const snippet = useSnippetQuery(id);
  const source = useSourceQuery(snippet.data?.source_id ?? null);

  if (snippet.isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading snippet…" />
      </div>
    );
  }
  if (snippet.isError) {
    return (
      <ErrorBanner
        message={snippet.error instanceof Error ? snippet.error.message : "Failed to load snippet"}
      />
    );
  }
  const s = snippet.data;
  if (!s) return null;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-[28px] font-semibold leading-tight text-obsidian-text">
            Evidence Snippet
          </h1>
          <p className="mt-1 font-mono text-sm text-obsidian-muted">
            id <span className="text-obsidian-text">{s.id}</span>
          </p>
        </div>
        <Link to="/projects">
          <Button variant="secondary" size="sm" className="shrink-0">
            Projects
          </Button>
        </Link>
      </div>

      {/* Snippet content */}
      <div className="flex flex-col gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
          Content
        </div>
        <pre className="overflow-auto rounded-xl border border-obsidian-border bg-obsidian-bg p-5 font-mono text-sm leading-relaxed text-obsidian-text">
          {s.text}
        </pre>
        {s.risk_flags?.length ? (
          <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-2.5">
            <span className="text-[11px] font-semibold uppercase tracking-widest text-amber-400/70">
              Risk flags
            </span>
            <span className="text-sm text-amber-300">{s.risk_flags.join(", ")}</span>
          </div>
        ) : null}
      </div>

      {/* Source metadata */}
      <div className="flex flex-col gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
          Source
        </div>

        <div className="overflow-hidden rounded-xl border border-obsidian-border bg-obsidian-surface-elevated">
          {source.isLoading ? (
            <div className="flex justify-center p-8">
              <Spinner label="Loading source…" />
            </div>
          ) : source.isError ? (
            <p className="px-5 py-4 text-sm text-obsidian-muted">
              Source lookup failed or is unavailable.
            </p>
          ) : source.data ? (
            <dl className="divide-y divide-obsidian-border-subtle">
              <div className="flex items-baseline gap-4 px-5 py-3.5">
                <dt className="w-32 shrink-0 font-mono text-xs text-obsidian-muted">title</dt>
                <dd className="text-sm text-obsidian-text">{source.data.title ?? "—"}</dd>
              </div>
              <div className="flex items-baseline gap-4 px-5 py-3.5">
                <dt className="w-32 shrink-0 font-mono text-xs text-obsidian-muted">canonical_id</dt>
                <dd className="font-mono text-sm text-obsidian-text">
                  {source.data.canonical_id ?? "—"}
                </dd>
              </div>
              <div className="flex items-center gap-4 px-5 py-3.5">
                <dt className="w-32 shrink-0 font-mono text-xs text-obsidian-muted">url</dt>
                <dd className="text-sm">
                  {source.data.url ? (
                    <a
                      className="inline-flex items-center gap-1.5 text-obsidian-accent hover:brightness-125"
                      href={source.data.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open source
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    <span className="text-obsidian-muted">—</span>
                  )}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="px-5 py-4 text-sm text-obsidian-muted">
              No source metadata for this snippet.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
