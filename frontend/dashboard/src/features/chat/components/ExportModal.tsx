type ExportModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onExport: (format: string) => void;
};

const exportOptions = [
  { id: "pdf", label: "PDF document", description: "Best for sharing and printing" },
  { id: "docx", label: "Word document", description: "Editable in Microsoft Word" },
  { id: "md", label: "Markdown", description: "Plain text with formatting" },
  { id: "html", label: "HTML", description: "Web-ready format" }
];

export function ExportModal({ isOpen, onClose, onExport }: ExportModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950" onClick={onClose}>
      <div
        className="w-96 max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Export report</h3>
        <div className="flex flex-col gap-3">
          {exportOptions.map((option) => (
            <button
              key={option.id}
              onClick={() => onExport(option.id)}
              className="rounded-xl border border-slate-700 bg-slate-900 p-4 text-left transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10"
            >
              <div className="text-sm font-medium text-slate-100">{option.label}</div>
              <div className="mt-0.5 text-xs text-slate-500">{option.description}</div>
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
