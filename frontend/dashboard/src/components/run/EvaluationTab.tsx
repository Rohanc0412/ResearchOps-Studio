// frontend/dashboard/src/components/run/EvaluationTab.tsx
import { useState } from "react";
import { RotateCcw, PlayCircle, CheckCircle2 } from "lucide-react";

import {
  useEvaluationQuery,
  useRunEvaluateMutation,
  type EvaluationPass,
  type EvaluationSection,
  type EvaluationIssue,
} from "../../api/evaluation";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ErrorBanner } from "../ui/ErrorBanner";
import { Spinner } from "../ui/Spinner";
import { cx } from "../../utils/format";

// ── Issue type display config ─────────────────────────────────────────────────

const ISSUE_COLORS: Record<string, { badge: string; dot: string }> = {
  unsupported:      { badge: "bg-amber-500/10 text-amber-400",   dot: "bg-amber-400" },
  contradicted:     { badge: "bg-red-500/10 text-red-400",       dot: "bg-red-400" },
  missing_citation: { badge: "bg-obsidian-accent/10 text-obsidian-accent", dot: "bg-obsidian-accent" },
  overstated:       { badge: "bg-violet-500/10 text-violet-400", dot: "bg-violet-400" },
  invalid_citation: { badge: "bg-red-500/10 text-red-400",       dot: "bg-red-400" },
  not_in_pack:      { badge: "bg-amber-500/10 text-amber-400",   dot: "bg-amber-400" },
};

function issueColors(problem: string) {
  return ISSUE_COLORS[problem] ?? { badge: "bg-obsidian-border text-obsidian-muted", dot: "bg-obsidian-muted" };
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

function IssueItem({ issue }: { issue: EvaluationIssue }) {
  const colors = issueColors(issue.problem);
  return (
    <div className="flex flex-col gap-1.5">
      <span className={cx("inline-block w-fit rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wide", colors.badge)}>
        {issue.problem.replace(/_/g, " ")}
      </span>
      {issue.notes && (
        <p className="border-l-2 border-obsidian-border pl-2 font-mono text-[11px] italic leading-relaxed text-obsidian-muted">
          {issue.notes}
        </p>
      )}
    </div>
  );
}

function SectionRow({ section }: { section: EvaluationSection }) {
  const [open, setOpen] = useState(false);
  const isFail = section.verdict === "fail";

  const headerContent = (
    <>
      <span className={cx("text-[13px]", isFail ? "font-semibold text-obsidian-text" : "text-obsidian-muted")}>
        {section.title}
      </span>
      <div className="flex items-center gap-2.5">
        <span
          className={cx(
            "rounded px-2 py-0.5 font-mono text-[10px] font-bold",
            isFail ? "bg-red-500/10 text-red-400" : "bg-green-500/10 text-green-400"
          )}
        >
          {section.verdict}
        </span>
        {isFail && (
          <span className="text-[10px] text-obsidian-border">{open ? "▲" : "▼"}</span>
        )}
      </div>
    </>
  );

  return (
    <div className={cx("overflow-hidden rounded-[10px] border", isFail ? "border-red-500/20" : "border-obsidian-border")}>
      {isFail ? (
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

      {isFail && open && section.issues.length > 0 && (
        <div className="flex flex-col gap-3 border-t border-obsidian-border bg-obsidian-bg px-4 py-3">
          {section.issues.map((issue, i) => (
            <IssueItem key={i} issue={issue} />
          ))}
        </div>
      )}
    </div>
  );
}

function IssueBreakdownBar({ issuesByType }: { issuesByType: Record<string, number> }) {
  const total = Object.values(issuesByType).reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  const entries = Object.entries(issuesByType).sort((a, b) => b[1] - a[1]);

  return (
    <div className="rounded-xl border border-obsidian-border bg-obsidian-surface-elevated p-4">
      <p className="mb-3 font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
        Issue Breakdown
      </p>
      <div className="mb-3 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
        {entries.map(([problem, count]) => {
          const colors = issueColors(problem);
          return (
            <div
              key={problem}
              className={cx("h-full", colors.dot)}
              style={{ flex: count }}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-3">
        {entries.map(([problem, count]) => {
          const colors = issueColors(problem);
          return (
            <span key={problem} className="flex items-center gap-1.5 font-mono text-[10px] text-obsidian-muted">
              <span className={cx("h-1.5 w-1.5 rounded-full", colors.dot)} />
              {count} {problem.replace(/_/g, " ")}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function formatPassScope(scope: string) {
  return scope === "manual" ? "Manual" : "Pipeline";
}

function EvaluationHistoryCard({ evaluationPass }: { evaluationPass: EvaluationPass }) {
  const [open, setOpen] = useState(false);
  const hasFailures = (evaluationPass.sections ?? []).some((section) => section.verdict === "fail");
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
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-obsidian-muted">
              {formatPassScope(evaluationPass.scope)} pass {evaluationPass.pass_index}
            </span>
            <span
              className={cx(
                "rounded px-2 py-0.5 font-mono text-[10px] font-bold",
                hasFailures ? "bg-amber-500/10 text-amber-400" : "bg-green-500/10 text-green-400"
              )}
            >
              {(evaluationPass.sections_passed ?? 0)}/{evaluationPass.sections_total ?? 0} passed
            </span>
          </div>
          <span className="font-mono text-[10px] text-obsidian-border">{evaluatedLabel}</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <div className="text-[12px] font-medium text-obsidian-text">
              {evaluationPass.grounding_pct != null ? `${evaluationPass.grounding_pct}% grounding` : "No grounding score"}
            </div>
            {evaluationPass.faithfulness_pct != null && (
              <div className="font-mono text-[10px] text-obsidian-muted">
                {evaluationPass.faithfulness_pct}% faithfulness
              </div>
            )}
          </div>
          <span className="text-[10px] text-obsidian-border">{open ? "Collapse" : "Expand"}</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-obsidian-border px-4 py-4">
          {evaluationPass.issues_by_type && Object.keys(evaluationPass.issues_by_type).length > 0 && (
            <div className="mb-4">
              <IssueBreakdownBar issuesByType={evaluationPass.issues_by_type} />
            </div>
          )}

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
          step: result?.faithfulness_pct != null ? 3 : result?.grounding_pct != null ? 2 : 1,
          stepLabel:
            result?.faithfulness_pct != null
              ? "Finalizing evaluation results..."
              : result?.grounding_pct != null
                ? "Computing answer faithfulness..."
                : "Scoring section grounding...",
          partialGrounding: result?.grounding_pct,
          partialFaithfulness: result?.faithfulness_pct,
          partialSectionsPassed: result?.sections_passed,
          partialSectionsTotal: result?.sections_total,
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
          description="Score this report for grounding, faithfulness, and section coverage."
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
            <span className="font-mono text-[11px] text-obsidian-muted">Step {activeProgress.step} of 3</span>
          </div>
          <div className="mb-2 h-1 overflow-hidden rounded-full bg-obsidian-border">
            <div
              className="h-full rounded-full bg-obsidian-accent transition-all duration-500"
              style={{ width: `${Math.round((activeProgress.step / 3) * 100)}%` }}
            />
          </div>
          <p className="font-mono text-[11px] text-obsidian-accent">
            <span className="animate-pulse">*</span> {activeProgress.stepLabel}
          </p>
        </div>

        <div className="grid grid-cols-3 gap-2.5">
          <MetricCard
            value={activeProgress.partialGrounding != null ? `${activeProgress.partialGrounding}%` : "-"}
            label="Grounding Score"
            sublabel="latest available"
            colorClass={activeProgress.partialGrounding != null ? "text-green-400" : "text-obsidian-muted"}
            borderClass="border-t-2 border-t-green-500/30"
          />
          <MetricCard
            value={activeProgress.partialFaithfulness != null ? `${activeProgress.partialFaithfulness}%` : "-"}
            label="Answer Faithfulness"
            sublabel="available after step 2"
            colorClass={activeProgress.partialFaithfulness != null ? "text-amber-400" : "text-obsidian-muted"}
            borderClass="border-t-2 border-t-amber-500/30"
          />
          <MetricCard
            value={
              activeProgress.partialSectionsPassed != null && activeProgress.partialSectionsTotal != null
                ? `${activeProgress.partialSectionsPassed}/${activeProgress.partialSectionsTotal}`
                : "-"
            }
            label="Sections Passed"
            sublabel=">= 70% grounding threshold"
            colorClass={
              activeProgress.partialSectionsPassed != null && activeProgress.partialSectionsTotal != null
                ? "text-obsidian-text"
                : "text-obsidian-muted"
            }
            borderClass="border-t-2 border-t-obsidian-accent/20"
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

        <div className="grid grid-cols-3 gap-2.5">
          <MetricCard
            value={result.grounding_pct != null ? `${result.grounding_pct}%` : "—"}
            label="Grounding Score"
            sublabel="facts backed by evidence"
            colorClass={scoreColor(result.grounding_pct)}
            borderClass="border-t-2 border-t-green-500/50"
          />
          <MetricCard
            value={result.faithfulness_pct != null ? `${result.faithfulness_pct}%` : "—"}
            label="Answer Faithfulness"
            sublabel="claims traceable to sources"
            colorClass={scoreColor(result.faithfulness_pct)}
            borderClass="border-t-2 border-t-amber-500/50"
          />
          <MetricCard
            value={`${result.sections_passed ?? 0}/${result.sections_total ?? 0}`}
            label="Sections Passed"
            sublabel="≥ 70% grounding threshold"
            colorClass="text-obsidian-text"
            borderClass="border-t-2 border-t-obsidian-accent/50"
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

        {result.issues_by_type && Object.keys(result.issues_by_type).length > 0 && (
          <IssueBreakdownBar issuesByType={result.issues_by_type} />
        )}

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
