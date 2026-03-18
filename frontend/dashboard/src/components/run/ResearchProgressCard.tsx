import { ChevronDown, ChevronUp, RotateCcw, Square } from "lucide-react";

import { cx, formatTs } from "../../utils/format";
import type { ResearchProgressCardModel } from "./researchProgress";

type ResearchProgressCardProps = {
  model: ResearchProgressCardModel;
  expanded: boolean;
  onToggleExpanded: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
};

export function ResearchProgressCard({
  model,
  expanded,
  onToggleExpanded,
  onCancel,
  onRetry
}: ResearchProgressCardProps) {
  return (
    <div className="mb-6 rounded-[28px] border border-slate-800 bg-[#121212] p-5 shadow-[0_20px_60px_rgba(0,0,0,0.25)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold tracking-tight text-slate-50">{model.title}</h3>
          <p className="mt-1 text-sm text-slate-400">
            {model.status === "failed"
              ? "Review the last update or retry the run."
              : model.status === "canceled"
                ? "Run stopped before the report finished."
                : "Live research progress"}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggleExpanded}
          className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-[#0f0f0f] px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-500 hover:bg-slate-900"
        >
          Update
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
      </div>

      <div className="mt-6 space-y-4">
        {model.steps.map((step) => (
          <div key={step.id} className="flex items-start gap-4">
            <ProgressStepIcon state={step.state} />
            <div className="pt-0.5">
              <p
                className={cx(
                  "text-[1.05rem] leading-7",
                  step.state === "pending" ? "text-slate-300/85" : "text-slate-50"
                )}
              >
                {step.label}
              </p>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-8 flex items-center justify-between gap-4 text-sm text-slate-400">
        <p className="min-w-0 flex-1 truncate">{model.summaryText}</p>
        <div className="shrink-0 text-right text-lg font-medium text-slate-200">{model.metricText}</div>
      </div>

      <div className="mt-4 flex items-center gap-4">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
          <div
            className={cx(
              "h-full rounded-full transition-[width] duration-300",
              model.status === "failed"
                ? "bg-rose-400"
                : model.status === "canceled"
                  ? "bg-slate-500"
                  : "bg-slate-100"
            )}
            style={{ width: `${Math.max(6, Math.round(model.progressRatio * 100))}%` }}
          />
        </div>

        {model.status === "running" && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            aria-label="Stop research run"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-800 bg-slate-900 text-slate-100 transition hover:border-slate-600 hover:bg-slate-800"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : null}

        {model.status === "failed" && onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-medium text-slate-100 transition hover:border-slate-500 hover:bg-slate-800"
          >
            <RotateCcw className="h-4 w-4" />
            Retry
          </button>
        ) : null}
      </div>

      {expanded ? (
        <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">Recent updates</div>
            <div className="text-xs text-slate-600">{model.recentEvents.length} events</div>
          </div>

          {model.recentEvents.length === 0 ? (
            <div className="rounded-xl border border-slate-900 bg-slate-950 px-3 py-4 text-sm text-slate-500">
              Waiting for live updates from the run stream.
            </div>
          ) : (
            <div className="max-h-56 space-y-2 overflow-y-auto pr-1">
              {model.recentEvents.map((event) => (
                <div
                  key={event.id}
                  className="rounded-xl border border-slate-900 bg-slate-950 px-3 py-3 text-sm text-slate-200"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div
                      className={cx(
                        "text-xs font-medium uppercase tracking-[0.14em]",
                        event.level === "error"
                          ? "text-rose-300"
                          : event.level === "warn"
                            ? "text-amber-300"
                            : "text-slate-500"
                      )}
                    >
                      {event.level}
                    </div>
                    <div className="text-xs text-slate-500">{formatTs(event.ts)}</div>
                  </div>
                  <div className="mt-1 text-sm text-slate-100">{event.message}</div>
                  {event.detail ? <div className="mt-1 text-xs text-slate-500">{event.detail}</div> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function ProgressStepIcon({ state }: { state: ResearchProgressCardModel["steps"][number]["state"] }) {
  if (state === "complete") {
    return (
      <span className="mt-1 inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-100 bg-slate-100 text-slate-950">
        <span className="text-sm font-semibold">✓</span>
      </span>
    );
  }

  if (state === "current") {
    return <span className="mt-1 inline-flex h-7 w-7 rounded-full border-2 border-slate-100" />;
  }

  return (
    <span className="mt-1 inline-flex h-7 w-7 items-center justify-center rounded-full border border-dashed border-slate-600">
      <span className="h-1.5 w-1.5 rounded-full bg-slate-700" />
    </span>
  );
}
