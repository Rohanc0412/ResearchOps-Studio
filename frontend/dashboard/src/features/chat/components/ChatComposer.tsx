import type { KeyboardEvent } from "react";

type ModelOption = {
  value: string;
  label: string;
};

type ChatComposerProps = {
  draft: string;
  isTyping: boolean;
  runPipelineArmed: boolean;
  selectedModel: string;
  customModel: string;
  modelOptions: ModelOption[];
  customModelValue: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onQuickAction: (action: string) => void;
  onTogglePipeline: () => void;
  onSelectedModelChange: (value: string) => void;
  onCustomModelChange: (value: string) => void;
};

const QUICK_ACTIONS = ["Add conclusion", "Add recommendations", "Summarize findings", "Add references"];

export function ChatComposer({
  draft,
  isTyping,
  runPipelineArmed,
  selectedModel,
  customModel,
  modelOptions,
  customModelValue,
  onDraftChange,
  onSend,
  onQuickAction,
  onTogglePipeline,
  onSelectedModelChange,
  onCustomModelChange,
}: ChatComposerProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  };

  return (
    <>
      <div className="flex flex-wrap gap-2 px-6 pb-3">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action}
            onClick={() => onQuickAction(action)}
            className="rounded-full border border-slate-700 bg-slate-900 px-3.5 py-2 text-xs text-slate-400 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10 hover:text-emerald-400"
          >
            {action}
          </button>
        ))}
      </div>

      <div className="border-t border-slate-800 px-6 py-4">
        <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-400">
          <span>LLM model</span>
          <div className="flex flex-1 flex-wrap items-center gap-2">
            <select
              value={selectedModel}
              onChange={(event) => onSelectedModelChange(event.target.value)}
              className="min-w-[220px] rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
            >
              {modelOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {selectedModel === customModelValue ? (
              <input
                value={customModel}
                onChange={(event) => onCustomModelChange(event.target.value)}
                placeholder="Enter model id"
                className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
              />
            ) : null}
          </div>
          <button
            type="button"
            data-testid="pipeline-toggle"
            aria-pressed={runPipelineArmed}
            onClick={onTogglePipeline}
            className={`rounded-full border px-3.5 py-2 text-xs transition-colors ${
              runPipelineArmed
                ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-200"
                : "border-slate-700 bg-slate-900 text-slate-400 hover:border-emerald-500/30 hover:text-emerald-300"
            }`}
          >
            Run research report
          </button>
        </div>

        <div className="flex items-end gap-3">
          <textarea
            value={draft}
            onChange={(event) => onDraftChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              runPipelineArmed
                ? "Describe your research topic - report will run on send..."
                : "Ask a question or request a report..."
            }
            rows={1}
            className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900 px-4 py-3.5 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-500/50"
          />
          <button
            onClick={onSend}
            disabled={!draft.trim() || isTyping}
            className={`flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
              draft.trim() && !isTyping
                ? "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                : "cursor-not-allowed bg-emerald-500/30 text-slate-500"
            }`}
          >
            <span className="sr-only">Send message</span>
            <svg viewBox="0 0 24 24" className="h-5 w-5 fill-current" aria-hidden="true">
              <path d="M3.4 20.4 22 12 3.4 3.6l.1 6.5L15 12 3.5 13.9l-.1 6.5Z" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );
}
