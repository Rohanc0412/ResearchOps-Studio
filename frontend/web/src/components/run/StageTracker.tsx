import { cx } from "../../utils/format";

const STAGES = ["retrieve", "ingest", "outline", "draft", "validate", "factcheck", "export"] as const;

export type Stage = (typeof STAGES)[number];

export function StageTracker({ currentStage }: { currentStage?: Stage | null }) {
  return (
    <div className="grid grid-cols-7 gap-2">
      {STAGES.map((stage) => {
        const isCurrent = currentStage === stage;
        return (
          <div
            key={stage}
            className={cx(
              "rounded-md border border-slate-800 bg-slate-900 px-2 py-2 text-center text-xs text-slate-300",
              isCurrent && "border-sky-500/40 bg-sky-500/10 text-sky-100"
            )}
          >
            {stage}
          </div>
        );
      })}
    </div>
  );
}

