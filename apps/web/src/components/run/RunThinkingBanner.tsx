import React from "react";
import { cx } from "../../utils/format";

export type RunThinkingStatus = "running" | "failed" | "succeeded" | "canceled";

type RunThinkingBannerProps = {
  primaryText: string;
  secondaryText?: string;
  status: RunThinkingStatus;
  onAnswerNow?: () => void;
  onRetry?: () => void;
};

export function RunThinkingBanner({
  primaryText,
  secondaryText,
  status,
  onAnswerNow,
  onRetry
}: RunThinkingBannerProps) {
  if (status === "succeeded" || status === "canceled") return null;

  const isRunning = status === "running";
  const isFailed = status === "failed";
  const actionLabel = isFailed ? "Retry" : "Answer now";
  const onAction = isFailed ? onRetry : onAnswerNow;

  return (
    <div
      className={cx(
        "flex items-start justify-between gap-4 rounded-xl border px-4 py-3",
        isFailed ? "border-rose-900/60 bg-rose-950/20" : "border-slate-900 bg-slate-950/60"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-100" aria-live="polite">
          {isRunning ? <span className="h-2.5 w-2.5 rounded-full bg-sky-400 animate-pulse" /> : null}
          <span>{primaryText} &rsaquo;</span>
        </div>
        {secondaryText ? (
          <div className="mt-1 text-xs text-slate-400">{secondaryText}</div>
        ) : null}
      </div>
      {onAction ? (
        <button
          type="button"
          className="text-xs font-semibold text-sky-300 hover:text-sky-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
