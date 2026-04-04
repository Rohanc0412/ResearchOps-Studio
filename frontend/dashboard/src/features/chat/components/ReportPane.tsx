import { type RefObject } from "react";
import { Download, Share2, Sparkles, Trash2 } from "lucide-react";

import { ResearchProgressCard } from "../../../components/run/ResearchProgressCard";
import type { ResearchProgressCardModel } from "../../../components/run/researchProgress";
import type { ActiveRun, Report } from "../types";
import { ReportSectionView } from "./ReportSectionView";

type ReportPaneProps = {
  report: Report;
  activeRun: ActiveRun | null;
  progressCard: ResearchProgressCardModel | null;
  progressDetailsOpen: boolean;
  reportStatusLabel: string;
  reportStatusClasses: string;
  highlightedSection: string | null;
  contentRef: RefObject<HTMLDivElement>;
  onToggleExpanded: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
  onExport: () => void;
  onClear: () => void;
  onShare: () => void;
  onSectionEdit: (sectionId: string, newContent: string) => void;
};

const REPORT_ACTION_BUTTON_CLASSES =
  "inline-flex h-11 shrink-0 items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600";

export function ReportPane({
  report,
  activeRun,
  progressCard,
  progressDetailsOpen,
  reportStatusLabel,
  reportStatusClasses,
  highlightedSection,
  contentRef,
  onToggleExpanded,
  onCancel,
  onRetry,
  onExport,
  onClear,
  onShare,
  onSectionEdit,
}: ReportPaneProps) {
  return (
    <div className="flex w-[55%] min-h-0 flex-col bg-slate-950">
      <div className="flex items-center justify-between border-b border-slate-800 px-8 py-5">
        <h2 className="font-mono text-lg font-semibold tracking-tight text-slate-100 md:text-xl">{report.title}</h2>
        {(activeRun !== null || report.sections.length > 0) && (
          <div className="flex items-center gap-3">
            <div
              className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[0.7rem] font-medium uppercase tracking-[0.16em] ${reportStatusClasses}`}
            >
              <div
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  activeRun?.status === "failed"
                    ? "bg-rose-400"
                    : activeRun?.status === "canceled"
                      ? "bg-slate-400"
                      : "animate-pulse bg-emerald-500"
                }`}
              />
              {reportStatusLabel}
            </div>
          </div>
        )}
      </div>

      {report.sections.length > 0 && (
        <div className="flex flex-wrap gap-3 border-b border-slate-800 px-8 py-4">
          <button onClick={onExport} className={REPORT_ACTION_BUTTON_CLASSES}>
            <Download className="h-4 w-4" />
            Export
          </button>
          <button onClick={onClear} className={REPORT_ACTION_BUTTON_CLASSES}>
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
          <button onClick={onShare} className={REPORT_ACTION_BUTTON_CLASSES}>
            <Share2 className="h-4 w-4" />
            Share
          </button>
          <div className="ml-auto">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-500">
              <Sparkles className="h-5 w-5" />
            </div>
          </div>
        </div>
      )}

      <div ref={contentRef} className="flex-1 overflow-y-auto p-8">
        {progressCard ? (
          <ResearchProgressCard
            model={progressCard}
            expanded={progressDetailsOpen}
            onToggleExpanded={onToggleExpanded}
            onCancel={onCancel}
            onRetry={onRetry}
            runId={activeRun?.runId}
          />
        ) : null}

        {report.sections.length === 0 ? (
          <div className="py-20 text-center text-slate-500">
            <div className="mb-4 text-5xl opacity-50">Report</div>
            <p className="text-sm">No report yet</p>
            <p className="mt-2 text-xs text-slate-600">Enable <span className="font-medium text-slate-400">Run research report</span> in the composer and send your question to generate a full report</p>
          </div>
        ) : (
          report.sections.map((section) => (
            <ReportSectionView
              key={section.id}
              section={section}
              onEdit={onSectionEdit}
              isHighlighted={highlightedSection === section.id}
            />
          ))
        )}
      </div>
    </div>
  );
}
