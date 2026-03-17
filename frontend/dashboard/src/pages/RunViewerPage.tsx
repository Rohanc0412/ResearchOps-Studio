import { Link, useParams } from "react-router-dom";
import { RefreshCw, Square, RotateCcw, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState, type ComponentProps } from "react";

import { useRunArtifactsQuery } from "../api/artifacts";
import { useCancelRunMutation, useRetryRunMutation, useRunQuery } from "../api/runs";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { BudgetPanel } from "../components/run/BudgetPanel";
import { EventsFeed } from "../components/run/EventsFeed";
import { StageTracker, type Stage } from "../components/run/StageTracker";
import { useAuth } from "../auth/useAuth";
import { useSSE } from "../hooks/useSSE";
import { formatTs } from "../utils/format";
import type { RunEvent } from "../types/dto";

export function RunViewerPage() {
  const { runId } = useParams();
  const id = runId ?? "";
  const auth = useAuth();

  const run = useRunQuery(id);
  const artifacts = useRunArtifactsQuery(id);
  const cancel = useCancelRunMutation(id);
  const retry = useRetryRunMutation(id);

  const [autoScroll, setAutoScroll] = useState(true);
  const [streamEnabled, setStreamEnabled] = useState<boolean>(auth.isAuthenticated);
  const sse = useSSE(id ? `/runs/${encodeURIComponent(id)}/events` : null, streamEnabled);

  type BadgeTone = NonNullable<ComponentProps<typeof Badge>["tone"]>;
  const statusTone: BadgeTone = useMemo(() => {
    const s = run.data?.status;
    if (s === "succeeded") return "success";
    if (s === "failed") return "danger";
    if (s === "running" || s === "queued" || s === "created") return "info";
    return "neutral";
  }, [run.data?.status]);

  const stage = sse.latestStage as Stage | null;
  const terminalFromEvents = useMemo(() => {
    const terminal = new Set(["succeeded", "failed", "canceled"]);
    return sse.events.some((evt) => {
      const payload = (evt as { payload?: Record<string, unknown> }).payload;
      const status = payload?.status;
      if (typeof status === "string" && terminal.has(status)) return true;
      const toStatus = payload?.to_status;
      if (typeof toStatus === "string" && terminal.has(toStatus)) return true;
      return false;
    });
  }, [sse.events]);
  const shouldStream = auth.isAuthenticated && run.data?.status !== "succeeded" && !terminalFromEvents;
  const retrievalSummary = useMemo(() => extractRetrievalSummary(sse.events), [sse.events]);

  useEffect(() => {
    setStreamEnabled(shouldStream);
  }, [shouldStream]);

  useEffect(() => {
    if (terminalFromEvents && run.data?.status !== "succeeded") {
      void run.refetch();
    }
  }, [terminalFromEvents, run]);

  useEffect(() => {
    if (terminalFromEvents || run.data?.status === "succeeded") {
      void artifacts.refetch();
    }
  }, [terminalFromEvents, run.data?.status, artifacts]);

  if (run.isLoading) {
    return (
      <Card>
        <Spinner label="Loading run…" />
      </Card>
    );
  }

  if (run.isError) {
    return <ErrorBanner message={run.error instanceof Error ? run.error.message : "Failed to load run"} />;
  }

  const r = run.data;
  if (!r) return null;

  return (
    <div className="flex flex-col gap-4">
      {r.status !== "succeeded" && !terminalFromEvents && sse.state !== "open" ? (
        <ErrorBanner
          title="Live stream disconnected"
          message={
            sse.lastError
              ? `Will retry automatically. Last error: ${sse.lastError}`
              : "Attempting to connect. Events will appear when available."
          }
        />
      ) : null}

      <Card>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-sm text-slate-500">Run</div>
            <div className="text-lg font-semibold text-slate-100">{r.id}</div>
            <div className="mt-1 text-sm text-slate-500">Created {formatTs(r.created_at)}</div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={statusTone}>{r.status}</Badge>
            <Button variant="secondary" onClick={() => void run.refetch()} title="Refresh">
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button variant="danger" onClick={() => void cancel.mutateAsync()} disabled={cancel.isPending}>
              <Square className="h-4 w-4" />
              Cancel
            </Button>
            <Button variant="secondary" onClick={() => void retry.mutateAsync()} disabled={retry.isPending}>
              <RotateCcw className="h-4 w-4" />
              Retry
            </Button>
          </div>
        </div>
        {r.error_message ? <div className="mt-3 text-sm text-rose-200">Error: {r.error_message}</div> : null}
      </Card>

      <Card>
        <div className="mb-3 text-sm font-semibold text-slate-100">Progress</div>
        <StageTracker currentStage={stage} />
      </Card>

      {retrievalSummary ? (
        <Card>
          <div className="mb-3 text-sm font-semibold text-slate-100">Retrieval</div>
          <div className="grid gap-2 text-sm text-slate-300">
            <div>
              Retrieved{" "}
              <span className="text-slate-100">
                {retrievalSummary.totalCandidates ?? retrievalSummary.totalSourcesRetrieved ?? "?"}
              </span>{" "}
              candidates, kept{" "}
              <span className="text-slate-100">{retrievalSummary.finalSourceCount ?? "?"}</span>
            </div>
            {retrievalSummary.keywordCandidates !== null || retrievalSummary.vectorCandidates !== null ? (
              <div>
                Keyword:{" "}
                <span className="text-slate-100">{retrievalSummary.keywordCandidates ?? "?"}</span> · Vector:{" "}
                <span className="text-slate-100">{retrievalSummary.vectorCandidates ?? "?"}</span>
              </div>
            ) : null}
            {retrievalSummary.duplicatesRemoved !== null ? (
              <div>
                Duplicates removed:{" "}
                <span className="text-slate-100">{retrievalSummary.duplicatesRemoved}</span>
              </div>
            ) : null}
            {retrievalSummary.connectorsUsed.length ? (
              <div className="text-xs text-slate-400">
                Connectors: {retrievalSummary.connectorsUsed.join(", ")}
              </div>
            ) : null}
          </div>
          {retrievalSummary.topSources.length ? (
            <div className="mt-3 border-t border-slate-900 pt-3">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Top sources</div>
              <div className="mt-2 grid gap-2 text-sm text-slate-200">
                {retrievalSummary.topSources.map((source) => (
                  <div key={`${source.canonical_id ?? source.title}`} className="rounded-md border border-slate-900 bg-slate-950 px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm text-slate-100">{source.title ?? "Untitled source"}</div>
                      <div className="text-xs text-slate-500">{source.connector ?? "unknown"}</div>
                    </div>
                    <div className="text-xs text-slate-400">
                      {source.year ? `${source.year} · ` : ""}{source.canonical_id ?? source.url ?? ""}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <EventsFeed events={sse.events} autoScroll={autoScroll} onToggleAutoScroll={() => setAutoScroll((v) => !v)} />
        </div>
        <BudgetPanel budgets={typeof r.budgets === "object" ? (r.budgets as Record<string, unknown>) : null} />
      </div>

      <Card>
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold text-slate-100">Artifacts</div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => void artifacts.refetch()}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
            <Link to={`/runs/${encodeURIComponent(r.id)}/artifacts`}>
              <Button variant="secondary">
                <ExternalLink className="h-4 w-4" />
                Open
              </Button>
            </Link>
          </div>
        </div>
        {artifacts.isLoading ? (
          <Spinner label="Loading artifacts…" />
        ) : artifacts.isError ? (
          <ErrorBanner message={artifacts.error instanceof Error ? artifacts.error.message : "Failed to load artifacts"} />
        ) : (artifacts.data?.length ?? 0) === 0 ? (
          <div className="text-sm text-slate-500">No artifacts yet.</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {artifacts.data!.map((a) => (
              <Card key={a.id} className="p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-slate-100">{a.type}</div>
                    <div className="text-xs text-slate-500">{formatTs(a.created_at)}</div>
                  </div>
                  <Link to={`/runs/${encodeURIComponent(r.id)}/artifacts?focus=${encodeURIComponent(a.id)}`} className="text-sm font-medium text-sky-300 hover:text-sky-200">
                    View
                  </Link>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

type RetrievalSummary = {
  totalCandidates: number | null;
  totalSourcesRetrieved: number | null;
  keywordCandidates: number | null;
  vectorCandidates: number | null;
  duplicatesRemoved: number | null;
  finalSourceCount: number | null;
  connectorsUsed: string[];
  topSources: {
    title: string | null;
    connector: string | null;
    year: number | null;
    url: string | null;
    canonical_id: string | null;
  }[];
};

function extractRetrievalSummary(events: RunEvent[]): RetrievalSummary | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const payload = events[i].payload;
    if (!payload || typeof payload !== "object") continue;

    const totalCandidates = asNumber(payload.total_candidates);
    const totalSourcesRetrieved = asNumber(payload.total_sources_retrieved);
    const keywordCandidates = asNumber(payload.keyword_candidates);
    const vectorCandidates = asNumber(payload.vector_candidates);
    const duplicatesRemoved = asNumber(payload.duplicates_removed);
    const finalSourceCount = asNumber(payload.final_source_count);
    const connectorsUsed = asStringArray(payload.connectors_used);
    const topSources = asTopSources(payload.top_sources);

    if (
      totalCandidates !== null ||
      totalSourcesRetrieved !== null ||
      finalSourceCount !== null ||
      topSources.length
    ) {
      return {
        totalCandidates,
        totalSourcesRetrieved,
        keywordCandidates,
        vectorCandidates,
        duplicatesRemoved,
        finalSourceCount,
        connectorsUsed,
        topSources,
      };
    }
  }

  return null;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((entry) => typeof entry === "string");
}

function asTopSources(value: unknown): RetrievalSummary["topSources"] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => {
      if (!entry || typeof entry !== "object") return null;
      const source = entry as Record<string, unknown>;
      return {
        title: typeof source.title === "string" ? source.title : null,
        connector: typeof source.connector === "string" ? source.connector : null,
        year: asNumber(source.year),
        url: typeof source.url === "string" ? source.url : null,
        canonical_id: typeof source.canonical_id === "string" ? source.canonical_id : null,
      };
    })
    .filter((entry): entry is NonNullable<typeof entry> => Boolean(entry));
}
