import { Check, ChevronDown, ChevronUp, RotateCcw } from "lucide-react";

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
  const isRunning = model.status === "running";
  const isFailed  = model.status === "failed";

  return (
    <div className="mb-6 rounded-[24px] border border-white/[0.07] bg-[#0c0c0c] p-[22px] shadow-[0_24px_64px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.04)]">

      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-semibold leading-snug tracking-tight text-[#f8fafc]">
            {model.title}
          </h3>
          <div className="mt-1 flex items-center gap-1.5">
            {isRunning && (
              <span className="h-[5px] w-[5px] shrink-0 animate-dot-blink rounded-full bg-white/40" />
            )}
            <p
              className={cx(
                "text-[9px] uppercase tracking-[0.18em]",
                isFailed ? "text-[rgba(255,100,100,0.5)]" : "text-white/[0.28]"
              )}
            >
              {isFailed
                ? "Run failed — review or retry"
                : model.status === "canceled"
                  ? "Run stopped before the report finished"
                  : "Live research progress"}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleExpanded}
          className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-white/[0.09] bg-white/[0.04] px-3.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-white/55 transition hover:border-white/20 hover:text-white/70"
        >
          Updates
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>
      </div>

      {/* ── Steps ────────────────────────────────────────────────── */}
      <div className="mb-5 flex flex-col pl-2.5">
        {model.steps.map((step, index) => {
          const isLast = index === model.steps.length - 1;
          return (
            <div key={step.id} className="flex items-start gap-3">
              {/* track: badge + connector */}
              <div className="flex w-7 shrink-0 flex-col items-center">
                <ProgressStepBadge
                  index={index + 1}
                  state={step.state}
                  isFailed={isFailed && step.state === "current"}
                />
                {!isLast && (
                  <div
                    className={cx(
                      "my-[3px] w-px",
                      step.state === "complete" ? "bg-white/25" : "bg-white/[0.07]"
                    )}
                    style={{ height: "16px" }}
                  />
                )}
              </div>

              {/* label */}
              <div className="min-w-0 flex-1 pt-[5px]">
                <p
                  className={cx(
                    "text-[11px] leading-relaxed",
                    isFailed && step.state === "current"
                      ? "text-[rgba(255,100,100,0.6)]"
                      : step.state === "current"
                        ? "font-medium text-[#f8fafc]"
                        : step.state === "complete"
                          ? "text-white/45"
                          : "text-white/[0.16]"
                  )}
                >
                  {step.state === "current" && isRunning ? (
                    <WaveText text={step.label} duration={2.8} />
                  ) : (
                    step.label
                  )}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Footer: summary + metric ──────────────────────────────── */}
      <div className="mb-2.5 flex items-center justify-between gap-4">
        <p className="min-w-0 flex-1 truncate text-[10px]">
          {isRunning ? (
            <WaveText text={model.summaryText} duration={3.2} className="text-white/[0.62]" />
          ) : (
            <span className={isFailed ? "text-[rgba(255,100,100,0.45)]" : "text-white/[0.28]"}>
              {model.summaryText}
            </span>
          )}
        </p>
        <div
          className={cx(
            "shrink-0 text-right text-[11px] font-semibold",
            isFailed
              ? "text-[rgba(255,100,100,0.8)]"
              : model.status === "canceled"
                ? "text-white/35"
                : "text-white/65"
          )}
        >
          {model.metricText}
        </div>
      </div>

      {/* ── Progress bar ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <div className="h-[2px] flex-1 overflow-hidden rounded-full bg-white/[0.07]">
          <div
            className={cx(
              "h-full rounded-full",
              isRunning
                ? "animate-shimmer bg-[linear-gradient(90deg,rgba(255,255,255,0.4)_0%,rgba(255,255,255,0.85)_40%,#fff_50%,rgba(255,255,255,0.85)_60%,rgba(255,255,255,0.4)_100%)] bg-[length:200%_100%]"
                : isFailed
                  ? "bg-[rgba(255,80,80,0.6)]"
                  : model.status === "canceled"
                    ? "bg-white/20"
                    : "bg-white/75"
            )}
            style={{ width: `${Math.max(6, Math.round(model.progressRatio * 100))}%` }}
          />
        </div>

        {isRunning && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            aria-label="Stop research run"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-white/60 transition hover:border-white/20 hover:bg-white/[0.08]"
          >
            <svg width="9" height="9" viewBox="0 0 9 9" fill="currentColor">
              <rect width="9" height="9" rx="1" />
            </svg>
          </button>
        )}

        {isFailed && onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border border-white/[0.12] bg-white/[0.04] px-3 text-[9px] font-semibold uppercase tracking-[0.12em] text-white/60 transition hover:border-white/25 hover:text-white/80"
          >
            <RotateCcw className="h-3 w-3" />
            Retry
          </button>
        )}
      </div>

      {/* ── Expanded events log (unchanged) ──────────────────────── */}
      {expanded && (
        <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-950/70 p-3 md:p-4">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
              Recent updates
            </div>
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
                  className="rounded-xl border border-slate-900 bg-slate-950 px-3 py-3"
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
                  {event.detail ? (
                    <div className="mt-1 text-xs text-slate-500">{event.detail}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── ProgressStepBadge ────────────────────────────────────────────────────────

type StepState = ResearchProgressCardModel["steps"][number]["state"];

function ProgressStepBadge({
  index,
  state,
  isFailed
}: {
  index: number;
  state: StepState;
  isFailed: boolean;
}) {
  if (state === "complete") {
    return (
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/[0.88]">
        <Check className="h-3 w-3 stroke-[2.5] text-[#0a0a0a]" />
      </span>
    );
  }

  if (isFailed) {
    return (
      <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[rgba(255,80,80,0.3)] bg-[rgba(255,80,80,0.15)] text-[11px] font-bold text-[rgba(255,100,100,0.7)]">
        ✕
      </span>
    );
  }

  if (state === "current") {
    return (
      <span className="animate-halo-pulse inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-bold text-[#0a0a0a]">
        {index}
      </span>
    );
  }

  // pending
  return (
    <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/[0.12] text-[11px] font-semibold text-white/20">
      {index}
    </span>
  );
}

// ─── WaveText ─────────────────────────────────────────────────────────────────

function WaveText({
  text,
  duration,
  className
}: {
  text: string;
  duration: number;
  className?: string;
}) {
  return (
    <span className={className}>
      {text.split("").map((ch, i, arr) => {
        if (ch === " ") return " ";
        const delay = -(duration * (1 - i / arr.length));
        return (
          <span
            key={i}
            className="animate-letter-breathe inline-block"
            style={{
              animationDuration: `${duration}s`,
              animationDelay: `${delay.toFixed(2)}s`
            }}
          >
            {ch}
          </span>
        );
      })}
    </span>
  );
}
