import { ArrowLeft } from "lucide-react";

type ChatViewHeaderProps = {
  chatTitle: string;
  projectName: string;
  onBack: () => void;
};

export function ChatViewHeader({ chatTitle, projectName, onBack }: ChatViewHeaderProps) {
  return (
    <div className="border-b border-slate-800 px-6 py-5">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to project"
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
        </button>
        <div>
          <h1 className="font-mono text-xl font-semibold text-slate-100">{chatTitle}</h1>
          <p className="mt-1 text-sm text-slate-500">{projectName}</p>
        </div>
      </div>
    </div>
  );
}
