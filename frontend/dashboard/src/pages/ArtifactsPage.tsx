import { useMemo, useState } from "react";
import { useNavigate, useSearchParams, useParams, Link } from "react-router-dom";
import { BarChart2, ChevronLeft, Download, ExternalLink, Eye, FileText, FlaskConical } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { downloadArtifact, useRunArtifactsQuery, useRunSnippetsQuery } from "../api/artifacts";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { formatTs } from "../utils/format";
import type { Artifact } from "../types/dto";
import { EvaluationTab } from "../components/run/EvaluationTab";

export function ArtifactsPage() {
  const { runId } = useParams();
  const id = runId ?? "";
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const focus = sp.get("focus");

  const artifacts = useRunArtifactsQuery(id);
  const snippets = useRunSnippetsQuery(id);
  const [tab, setTab] = useState<"artifacts" | "evidence" | "evaluation">("artifacts");
  const [preview, setPreview] = useState<{ id: string; markdown: string } | null>(null);

  const focusArtifact = useMemo(() => {
    if (!focus) return null;
    return artifacts.data?.find((a) => a.id === focus) ?? null;
  }, [artifacts.data, focus]);

  async function onDownload(a: Artifact) {
    await downloadArtifact(a.id);
  }

  function onOpen(a: Artifact) {
    const md = a.metadata?.["markdown"];
    if (typeof md === "string" && md.trim()) setPreview({ id: a.id, markdown: md });
    else setPreview(null);
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Back + header */}
      <div className="flex flex-col gap-4">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(-1)}
          className="w-fit"
        >
          <ChevronLeft className="h-4 w-4" />
          Back
        </Button>

        <div>
          <h1 className="font-display text-[28px] font-semibold leading-tight text-obsidian-text">
            Artifacts
          </h1>
          <p className="mt-1 font-mono text-sm text-obsidian-muted">
            Run <span className="text-obsidian-text">{id}</span>
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-obsidian-border">
        {(["artifacts", "evidence", "evaluation"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={[
              "flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors",
              tab === t
                ? "border-b-2 border-obsidian-accent text-obsidian-text"
                : "text-obsidian-muted hover:text-obsidian-text",
            ].join(" ")}
          >
            {t === "artifacts" ? (
              <FileText className="h-3.5 w-3.5" />
            ) : t === "evidence" ? (
              <FlaskConical className="h-3.5 w-3.5" />
            ) : (
              <BarChart2 className="h-3.5 w-3.5" />
            )}
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "evaluation" ? (
        <EvaluationTab runId={id} />
      ) : tab === "evidence" ? (
        snippets.isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner label="Loading evidence…" />
          </div>
        ) : snippets.isError ? (
          <ErrorBanner
            message={snippets.error instanceof Error ? snippets.error.message : "Failed to load evidence"}
          />
        ) : (snippets.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon={<FlaskConical className="h-5 w-5" />}
            title="No evidence snippets"
            description="Evidence snippets are collected during the Retrieve stage."
          />
        ) : (
          <div className="flex flex-col gap-2">
            {(snippets.data ?? []).map((s) => (
              <Link
                key={s.id}
                to={`/evidence/snippets/${encodeURIComponent(s.id)}`}
                className="flex items-start gap-3 rounded-xl border border-obsidian-border bg-obsidian-surface-elevated px-4 py-3 transition-colors hover:border-obsidian-accent"
              >
                <FlaskConical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-obsidian-accent" />
                <div className="min-w-0 flex-1">
                  {s.source_title && (
                    <div className="mb-1 flex items-center gap-2">
                      <span className="truncate font-mono text-[11px] font-medium text-obsidian-accent">
                        {s.source_title}
                      </span>
                      {s.source_url && <ExternalLink className="h-3 w-3 shrink-0 text-obsidian-muted" />}
                    </div>
                  )}
                  <p className="font-mono text-xs leading-relaxed text-obsidian-muted line-clamp-2">{s.text}</p>
                </div>
              </Link>
            ))}
          </div>
        )
      ) : artifacts.isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading artifacts…" />
        </div>
      ) : artifacts.isError ? (
        <ErrorBanner
          message={artifacts.error instanceof Error ? artifacts.error.message : "Failed to load artifacts"}
        />
      ) : (artifacts.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="No artifacts yet"
          description="Artifacts will appear here once a run completes."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
          {/* Artifact list — 40% */}
          <div className="flex flex-col gap-2">
            {(artifacts.data ?? []).map((a) => (
              <div
                key={a.id}
                className={[
                  "flex items-center gap-3 rounded-xl border px-4 py-3",
                  "bg-obsidian-surface-elevated transition-colors",
                  a.id === focusArtifact?.id || a.id === preview?.id
                    ? "border-obsidian-accent"
                    : "border-obsidian-border",
                ].join(" ")}
              >
                {/* Icon + info */}
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#1e1b2e]">
                  <FileText className="h-3.5 w-3.5 text-obsidian-accent" />
                </div>

                <div className="min-w-0 flex-1">
                  <span className="inline-block rounded-md border border-[#2d2545] bg-[#1e1b2e] px-2 py-0.5 font-mono text-[11px] font-medium text-obsidian-accent">
                    {a.type}
                  </span>
                  <div data-testid="artifact-timestamp" className="mt-0.5 font-mono text-xs text-obsidian-muted">
                    {formatTs(a.created_at)}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex shrink-0 items-center gap-1.5">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void onDownload(a)}
                    title="Download"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </Button>
                  {a.type.includes("report") && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onOpen(a)}
                      title="Preview"
                    >
                      <Eye className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Preview panel — 60% */}
          <div className="overflow-hidden rounded-xl border border-obsidian-border bg-obsidian-surface-elevated">
            <div className="border-b border-obsidian-border px-4 py-3">
              <span className="text-[11px] font-semibold uppercase tracking-widest text-obsidian-muted">
                Preview
              </span>
            </div>
            <div className="p-4">
              {preview ? (
                <div className="prose prose-invert prose-sm max-h-[560px] max-w-none overflow-auto rounded-lg border border-obsidian-border bg-obsidian-bg p-4 text-obsidian-text">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{preview.markdown}</ReactMarkdown>
                </div>
              ) : (
                <p className="py-8 text-center text-sm text-obsidian-muted">
                  Select an artifact with embedded markdown to preview,
                  or use the download button to save the file.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

