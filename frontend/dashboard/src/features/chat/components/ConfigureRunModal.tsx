import { useState } from "react";
import { Modal } from "../../../components/ui/Modal";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE } from "../constants";

export type StageModels = {
  retrieve: string | null;
  outline: string | null;
  draft: string | null;
  evaluate: string | null;
  repair: string | null;
};

const STAGES: { key: keyof StageModels; label: string }[] = [
  { key: "retrieve", label: "Retriever" },
  { key: "outline", label: "Outliner" },
  { key: "draft", label: "Writer" },
  { key: "evaluate", label: "Evaluator" },
  { key: "repair", label: "Repair Agent" },
];

const AUTO_VALUE = "__auto__";

const STAGE_OPTIONS = [
  { value: AUTO_VALUE, label: "Auto (balanced)" },
  ...MODEL_OPTIONS.filter((o) => o.value !== CUSTOM_MODEL_VALUE),
  { value: CUSTOM_MODEL_VALUE, label: "Custom…" },
];

const defaultSelected = (): Record<keyof StageModels, string> => ({
  retrieve: AUTO_VALUE,
  outline: AUTO_VALUE,
  draft: AUTO_VALUE,
  evaluate: AUTO_VALUE,
  repair: AUTO_VALUE,
});

const defaultCustom = (): Record<keyof StageModels, string> => ({
  retrieve: "",
  outline: "",
  draft: "",
  evaluate: "",
  repair: "",
});

interface Props {
  open: boolean;
  onCancel: () => void;
  onStart: (stageModels: StageModels) => void;
}

export function ConfigureRunModal({ open, onCancel, onStart }: Props) {
  const [selected, setSelected] = useState<Record<keyof StageModels, string>>(defaultSelected);
  const [custom, setCustom] = useState<Record<keyof StageModels, string>>(defaultCustom);

  function handleStart() {
    const stageModels: StageModels = {
      retrieve: null,
      outline: null,
      draft: null,
      evaluate: null,
      repair: null,
    };
    for (const { key } of STAGES) {
      const val = selected[key];
      if (val === AUTO_VALUE) {
        stageModels[key] = null;
      } else if (val === CUSTOM_MODEL_VALUE) {
        stageModels[key] = custom[key].trim() || null;
      } else {
        stageModels[key] = val;
      }
    }
    onStart(stageModels);
  }

  return (
    <Modal open={open} onClose={onCancel} title="Configure Research Run">
      <div className="space-y-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-400">
              <th className="pb-2 pr-4 font-medium">Stage</th>
              <th className="pb-2 font-medium">Model</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {STAGES.map(({ key, label }) => (
              <tr key={key}>
                <td className="py-2 pr-4 text-slate-300">{label}</td>
                <td className="py-2">
                  <div className="flex flex-col gap-1">
                    <select
                      value={selected[key]}
                      onChange={(e) =>
                        setSelected((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                    >
                      {STAGE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    {selected[key] === CUSTOM_MODEL_VALUE && (
                      <input
                        value={custom[key]}
                        onChange={(e) =>
                          setCustom((prev) => ({ ...prev, [key]: e.target.value }))
                        }
                        placeholder="Enter model id"
                        className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                      />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-slate-700 px-4 py-2 text-xs text-slate-400 hover:border-slate-500 hover:text-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleStart}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-xs text-white hover:bg-emerald-500 transition-colors"
          >
            Start Run
          </button>
        </div>
      </div>
    </Modal>
  );
}
