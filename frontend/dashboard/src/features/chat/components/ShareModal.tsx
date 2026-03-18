import { useState } from "react";

type ShareModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

export function ShareModal({ isOpen, onClose }: ShareModalProps) {
  const [copied, setCopied] = useState(false);
  const shareLink = "https://researchops.studio/reports/shared-report";

  const handleCopy = () => {
    void navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950" onClick={onClose}>
      <div
        className="w-[420px] max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Share report</h3>
        <p className="mb-4 text-sm text-slate-400">Anyone with this link can view the report</p>
        <div className="flex gap-2 rounded-lg border border-slate-700 bg-slate-900 p-3">
          <input
            type="text"
            value={shareLink}
            readOnly
            className="flex-1 border-none bg-transparent font-mono text-sm text-slate-200 outline-none"
          />
          <button
            onClick={handleCopy}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              copied
                ? "border border-emerald-500 bg-transparent text-emerald-400"
                : "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
            }`}
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
        <button
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Done
        </button>
      </div>
    </div>
  );
}
