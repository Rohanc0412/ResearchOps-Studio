// frontend/dashboard/src/components/run/EvaluationTab.tsx
import { useState } from "react";
import { RotateCcw, PlayCircle, CheckCircle2 } from "lucide-react";

import {
  useEvaluationQuery,
  useRunEvaluateMutation,
  type EvaluationPass,
  type EvaluationSection,
  type EvaluationClaim,
} from "../../api/evaluation";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ErrorBanner } from "../ui/ErrorBanner";
import { Spinner } from "../ui/Spinner";
import { cx } from "../../utils/format";

// ── Verdict display config ────────────────────────────────────────────────────

const VERDICT_COLORS: Record<string, { badge: string; dot: string }> = {
  supported:        { badge: "bg-green-500/10 text-green-400",   dot: "bg-green-400" },
  unsupported:      { badge: "bg-amber-500/10 text-amber-400",   dot: "bg-amber-400" },
  contradicted:     { badge: "bg-red-500/10 text-red-400",       dot: "bg-red-400" },
  missing_citation: { badge: "bg-obsidian-accent/10 text-obsidian-accent", dot: "bg-obsidian-accent" },
  overstated:       { badge: "bg-violet-500/10 text-violet-400", dot: "bg-violet-400" },
  invalid_citation: { badge: "bg-red-500/10 text-red-400",       dot: "bg-red-400" },
};

function verdictColors(verdict: string) {
  return VERDICT_COLORS[verdict] ?? { badge: "bg-obsidian-border text-obsidian-muted", dot: "bg-obsidian-muted" };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricCard({
  value,
  label,
  sublabel,
  colorClass,
  borderClass,
}: {
  value: string;
  label: string;
  sublabel: string;
  colorClass: string;
  borderClass: string;
}) {
  return (
    <div className={cx("rounded-xl border border-obsidian-border bg-obsidian-surface-elevated p-4 text-center", borderClass)}>
      <div className={cx("text-2xl font-bold leading-none", colorClass)}>{value}</div>
      <div className="mt-1.5 text-[11px] font-medium text-obsidian-muted">{label}</div>
      <div className="mt-0.5 font-mono text-[10px] text-obsidian-border">{sublabel}</div>
    </div>
  );
}

function ClaimItem({ claim }: { claim: EvaluationClaim }) {
  const colors = verdictColors(claim.verdict);
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className={cx("inline-block w-fit rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wide", colors.badge)}>
          {claim.verdict.replace(/_/g, " ")}
        </span>
        <span className="font-mono text-[11px] text-obsidian-muted">{claim.claim_text}</span>
      </div>
      {claim.notes && (
        <p className="border-l-2 border-obsidian-border pl-2 font-mono text-[11px] italic leading-relaxed text-obsidian-muted">
          {claim.notes}
        </p>
      )}
    </div>
  );
}

function SectionRow({ section }: { section: EvaluationSection }) {
  const [open, setOpen] = useState(false);
  const score = section.quality_score;
  const isLow = score != null && score < 70;
  const hasClaims = section.claims.length > 0;

  const scoreLabel =
    score != null
      ? `${score}%`
      : section.claims.length === 0
        ? "no claims"
        : "—";
  const scoreColorClass = score == null ? "text-obsidian-muted" : score >= 70 ? "text-green-400" : "text-amber-400";

  const headerContent = (
    <>
      <span className={cx("text-[13px]", isLow ? "font-semibold text-obsidian-text" : "text-obsidian-muted")}>
        {section.title}
      </span>
      <div className="flex items-center gap-2.5">
        <span className={cx("rounded px-2 py-0.5 font-mono text-[10px] font-bold", scoreColorClass)}>
          {scoreLabel}
        </span>
        {hasClaims && (
          <span className="text-[10px] text-obsidian-border">{open ? "▲" : "▼"}</span>
        )}
      </div>
    </>
  );

  return (
    <div className={cx("overflow-hidden rounded-[10px] border", isLow ? "border-amber-500/20" : "border-obsidian-border")}>
      {hasClaims ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between bg-obsidian-surface-elevated px-4 py-2.5 cursor-pointer"
        >
          {headerContent}
        </button>
      ) : (
        <div className="flex w-full items-center justify-between bg-obsidian-surface-elevated px-4 py-2.5">
          {headerContent}
        </div>
      )}

      {hasClaims && open && (
        <div className="flex flex-col gap-3 border-t border-obsidian-border bg-obsidian-bg px-4 py-3">
          {section.claims.map((claim, i) => (
            <ClaimItem key={i} claim={claim} />
          ))}
        </div>
      )}
    </div>
  );
}


function formatPassScope(scope: string) {
  return scope === "manual" ? "Manual" : "Pipeline";
}

function EvaluationHistoryCard({ evaluationPass }: { evaluationPass: EvaluationPass }) {
  const [open, setOpen] = useState(false);
  const qualityPct = evaluationPass.quality_pct;
  const hallucinationRate = evaluationPass.hallucination_rate;
  const evaluatedLabel = evaluationPass.evaluated_at
    ? new Date(evaluationPass.evaluated_at).toLocaleString()
    : "Unknown";

  return (
    <div className="rounded-xl border border-obsidian-border bg-obsidian-surface-elevated">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
            {formatPassScope(evaluationPass.scope)} pass {evaluationPass.pass_index}
          </span>
          <span className="font-mono text-[10px] text-obsidian-border">{evaluatedLabel}</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <div className={cx("text-[12px] font-medium", qualityPct != null ? (qualityPct >= 70 ? "text-green-400" : "text-amber-400") : "text-obsidian-muted")}>
              {qualityPct != null ? `${qualityPct}% quality` : "No score"}
            </div>
            {hallucinationRate != null && (
              <div className="font-mono text-[10px] text-obsidian-muted">
                {hallucinationRate}% hallucination
              </div>
            )}
          </div>
          <span className="text-[10px] text-obsidian-border">{open ? "Collapse" : "Expand"}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-obsidian-border px-4 py-4">
          <div className="flex flex-col gap-1">
            {evaluationPass.sections.map((section) => (
              <SectionRow key={`${evaluationPass.id}-${section.section_id}`} section={section} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function EvaluationTab({ runId }: { runId: string }) {
  const evalQuery = useEvaluationQuery(runId);
  const { mutate, isRunning, progress, error: mutationError } = useRunEvaluateMutation(runId);

  if (evalQuery.isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading evaluation…" />
      </div>
    );
  }

  if (evalQuery.isError) {
    return (
      <ErrorBanner
        message={evalQuery.error instanceof Error ? evalQuery.error.message : "Failed to load evaluation"}
      />
    );
  }

  const result = evalQuery.data;
  const storedStatus = result?.status ?? "none";
  const latestHistory = result?.history?.[0];
  const serverProgress =
    storedStatus === "running"
      ? {
          step: 1,
          stepLabel: "Verifying claims against evidence…",
          partialQualityPct: result?.quality_pct,
          partialHallucinationRate: result?.hallucination_rate,
          sections: result?.sections ?? latestHistory?.sections ?? [],
        }
      : null;
  const activeProgress = progress ?? serverProgress;

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!isRunning && storedStatus === "none") {
    return (
      <div className="flex flex-col gap-4">
        {mutationError && <ErrorBanner message={mutationError} />}
        <EmptyState
          icon={<CheckCircle2 className="h-5 w-5" />}
          title="No evaluation yet"
          description="Score this report for claim quality and hallucination rate."
          action={
            <Button variant="primary" onClick={() => void mutate()}>
              <PlayCircle className="h-4 w-4" />
              Run Evaluation
            </Button>
          }
        />
      </div>
    );
  }

  // ── Running state ──────────────────────────────────────────────────────────
  if ((isRunning || storedStatus === "running") && activeProgress) {
    return (
      <div className="flex flex-col gap-4">
        {mutationError && <ErrorBanner message={mutationError} />}
        <div className="rounded-xl border border-obsidian-border bg-obsidian-surface-elevated p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[13px] font-semibold text-obsidian-text">Evaluating report...</span>
            <span className="font-mono text-[11px] text-obsidian-muted">Step {activeProgress.step} of 2</span>
          </div>
          <div className="mb-2 h-1 overflow-hidden rounded-full bg-obsidian-border">
            <div
              className="h-full rounded-full bg-obsidian-accent transition-all duration-500"
              style={{ width: `${Math.round((activeProgress.step / 2) * 100)}%` }}
            />
          </div>
          <p className="font-mono text-[11px] text-obsidian-accent">
            <span className="animate-pulse">*</span> {activeProgress.stepLabel}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <MetricCard
            value={activeProgress.partialQualityPct != null ? `${activeProgress.partialQualityPct}%` : "-"}
            label="Quality Score"
            sublabel="available after scoring"
            colorClass={activeProgress.partialQualityPct != null ? "text-green-400" : "text-obsidian-muted"}
            borderClass="border-t-2 border-t-green-500/30"
          />
          <MetricCard
            value={activeProgress.partialHallucinationRate != null ? `${activeProgress.partialHallucinationRate}%` : "-"}
            label="Hallucination Rate"
            sublabel="available after scoring"
            colorClass={activeProgress.partialHallucinationRate != null ? "text-amber-400" : "text-obsidian-muted"}
            borderClass="border-t-2 border-t-amber-500/30"
          />
        </div>

        {(activeProgress.sections?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
              Latest Section Results
            </p>
            <div className="flex flex-col gap-1">
              {activeProgress.sections.map((section) => (
                <SectionRow key={section.section_id} section={section} />
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Complete state ─────────────────────────────────────────────────────────
  if (result && result.status === "complete") {
    const scoreColor = (pct: number | null | undefined) =>
      pct == null ? "text-obsidian-muted" : pct >= 70 ? "text-green-400" : "text-amber-400";
    const history = result.history ?? [];

    return (
      <div className="flex flex-col gap-4">
        {mutationError && <ErrorBanner message={mutationError} />}

        <div className="grid grid-cols-2 gap-2.5">
          <MetricCard
            value={result.quality_pct != null ? `${result.quality_pct}%` : "—"}
            label="Quality Score"
            sublabel="weighted claim quality"
            colorClass={scoreColor(result.quality_pct)}
            borderClass="border-t-2 border-t-green-500/50"
          />
          <MetricCard
            value={result.hallucination_rate != null ? `${result.hallucination_rate}%` : "—"}
            label="Hallucination Rate"
            sublabel="contradicted + unsupported"
            colorClass={result.hallucination_rate == null ? "text-obsidian-muted" : result.hallucination_rate <= 10 ? "text-green-400" : "text-amber-400"}
            borderClass="border-t-2 border-t-amber-500/50"
          />
        </div>

        <div className="flex items-center justify-between">
          {result.evaluated_at && (
            <span className="font-mono text-[10px] text-obsidian-border">
              Evaluated {new Date(result.evaluated_at).toLocaleString()}
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={() => void mutate()} disabled={isRunning} data-testid="rerun-evaluation-btn">
            <RotateCcw className="h-3.5 w-3.5" />
            Re-evaluate
          </Button>
        </div>

        {(result.sections?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
              Section Details
            </p>
            <div className="flex flex-col gap-1">
              {(result.sections ?? []).map((section) => (
                <SectionRow key={section.section_id} section={section} />
              ))}
            </div>
          </div>
        )}

        {history.length > 0 && (
          <div className="flex flex-col gap-4">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
              Evaluation History
            </p>
            <div className="flex flex-col gap-3">
              {history.map((evaluationPass) => (
                <EvaluationHistoryCard key={evaluationPass.id} evaluationPass={evaluationPass} />
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}
