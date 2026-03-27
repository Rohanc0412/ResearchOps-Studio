import { useState } from "react";
import { ExternalLink } from "lucide-react";

import { downloadArtifact } from "../../../api/artifacts";
import type { Artifact } from "../../../types/dto";

type Props = {
  runId: string;
  artifacts: Artifact[];
};

function extForArtifact(artifact: Artifact): string {
  switch (artifact.type) {
    case "report_md": return ".md";
    case "report_pdf": return ".pdf";
    default: return "." + (artifact.type.split("_").pop() ?? artifact.type);
  }
}

function extractReportTitle(artifacts: Artifact[]): string {
  const md = artifacts.find((a) => a.type === "report_md");
  const markdown = (md?.["metadata"] as Record<string, unknown> | undefined)?.["markdown"];
  if (typeof markdown === "string") {
    const match = /^#\s+(.+)$/m.exec(markdown);
    if (match?.[1]) return match[1].trim();
  }
  return "Research Report";
}

function DocIcon() {
  return (
    <div
      className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border"
      style={{
        background: "rgba(149,128,196,0.15)",
        borderColor: "rgba(149,128,196,0.2)",
      }}
    >
      <svg width="18" height="22" viewBox="0 0 18 22" fill="none">
        <path
          d="M1 3C1 1.9 1.9 1 3 1h8l6 6v12c0 1.1-.9 2-2 2H3c-1.1 0-2-.9-2-2V3z"
          fill="#c4b5e8"
        />
        <path
          d="M1 3C1 1.9 1.9 1 3 1h8l6 6v12c0 1.1-.9 2-2 2H3c-1.1 0-2-.9-2-2V3z"
          fill="url(#ral-depth)"
        />
        <path d="M11 1l6 6h-4a2 2 0 0 1-2-2V1z" fill="#7b5fc4" />
        <path d="M1 3C1 1.9 1.9 1 3 1h8" stroke="rgba(255,255,255,.45)" strokeWidth=".8" fill="none" />
        <rect x="3.5" y="11"   width="9"   height="1.3" rx=".65" fill="rgba(80,50,130,.5)" />
        <rect x="3.5" y="13.7" width="6.5" height="1.3" rx=".65" fill="rgba(80,50,130,.5)" />
        <rect x="3.5" y="16.4" width="8"   height="1.3" rx=".65" fill="rgba(80,50,130,.5)" />
        <defs>
          <linearGradient id="ral-depth" x1="0" y1="0" x2="18" y2="22" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="white" stopOpacity=".12" />
            <stop offset="1" stopColor="black" stopOpacity=".3" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}

export function RunArtifactLinks({ runId, artifacts }: Props) {
  const title = extractReportTitle(artifacts);
  const [downloading, setDownloading] = useState<Record<string, boolean>>({});

  async function handleDownload(artifact: Artifact) {
    if (downloading[artifact.id]) return;
    setDownloading((prev) => ({ ...prev, [artifact.id]: true }));
    try {
      await downloadArtifact(artifact.id);
    } finally {
      setDownloading((prev) => ({ ...prev, [artifact.id]: false }));
    }
  }

  return (
    <div
      className="mt-2 flex items-center gap-3 rounded-[14px] border px-3.5 py-3"
      style={{
        background: "#101015",
        borderColor: "#1c1c24",
        borderLeftColor: "#9580c4",
        borderLeftWidth: "3px",
        boxShadow: "0 4px 20px rgba(0,0,0,.4)",
      }}
    >
      <DocIcon />

      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-obsidian-text">{title}</p>
        <p className="text-[11px] text-obsidian-muted">Run completed</p>
      </div>

      <div className="flex flex-shrink-0 items-center gap-1.5">
        {artifacts.map((artifact) => (
          <button
            key={artifact.id}
            type="button"
            onClick={() => void handleDownload(artifact)}
            disabled={downloading[artifact.id] === true}
            className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium text-[#c4b5e8] transition-colors hover:text-obsidian-text disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              border: "1px solid rgba(149,128,196,.3)",
              background: "rgba(149,128,196,.1)",
            }}
            aria-label={`Download ${extForArtifact(artifact)}`}
          >
            {downloading[artifact.id] ? (
              <span className="h-2.5 w-2.5 animate-spin rounded-full border border-[#2d2540] border-t-[#9580c4]" />
            ) : (
              <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M8 2v8M5 7l3 3 3-3" /><path d="M2 13h12" />
              </svg>
            )}
            {extForArtifact(artifact)}
          </button>
        ))}
        <a
          href={`/runs/${encodeURIComponent(runId)}/artifacts`}
          className="ml-1 flex items-center text-obsidian-muted transition-colors hover:text-obsidian-text"
          aria-label="View all artifacts"
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
}
