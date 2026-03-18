import { useState } from "react";
import { Edit3 } from "lucide-react";

import { CitationBadge } from "./CitationBadge";
import type { ReportSection } from "../types";

type ReportSectionViewProps = {
  section: ReportSection;
  onEdit: (sectionId: string, content: string) => void;
  isHighlighted: boolean;
};

export function ReportSectionView({ section, onEdit, isHighlighted }: ReportSectionViewProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState(section.content.map((item) => item.text).join("\n\n"));

  const handleSave = () => {
    onEdit(section.id, editedContent);
    setIsEditing(false);
  };

  return (
    <div className={`mb-7 transition-all duration-300 ${isHighlighted ? "animate-pulse" : ""}`}>
      <div className="mb-4 flex items-center gap-3">
        <div className="h-6 w-1 rounded-sm bg-emerald-500" />
        <h3 className="font-mono text-base font-semibold tracking-wide text-emerald-400">{section.heading}</h3>
        {!isEditing ? (
          <button
            onClick={() => setIsEditing(true)}
            className="ml-auto flex items-center gap-1.5 rounded border border-slate-700 bg-transparent px-2 py-1 text-xs text-slate-500 transition-colors hover:border-slate-500 hover:text-slate-300"
          >
            <Edit3 className="h-3.5 w-3.5" />
            Edit
          </button>
        ) : null}
      </div>

      {isEditing ? (
        <div className="pl-4">
          <textarea
            value={editedContent}
            onChange={(event) => setEditedContent(event.target.value)}
            className="min-h-32 w-full resize-y rounded-lg border border-emerald-500/40 bg-slate-950 p-3 text-sm leading-relaxed text-slate-200 outline-none focus:border-emerald-500/60"
          />
          <div className="mt-3 flex justify-end gap-2">
            <button
              onClick={() => setIsEditing(false)}
              className="rounded-md border border-slate-600 bg-transparent px-4 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-emerald-400"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="pl-4">
          {section.content.map((item, index) => (
            <div key={index} className="mb-3 flex items-start">
              {item.isBullet ? <span className="mr-3 mt-0.5 text-xs text-emerald-500">*</span> : null}
              <p className="flex-1 text-sm leading-relaxed text-slate-300">
                {item.text}
                {item.citations?.map((num) => <CitationBadge key={num} number={num} />)}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
