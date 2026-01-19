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
