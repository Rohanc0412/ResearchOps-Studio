import { useMemo, useState } from "react";
import { Link, useSearchParams, useParams } from "react-router-dom";
import { Download, FileText } from "lucide-react";

import { downloadArtifact, useRunArtifactsQuery } from "../api/artifacts";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { formatTs } from "../utils/format";
import type { Artifact } from "../types/dto";

export function ArtifactsPage() {
  const { runId } = useParams();
  const id = runId ?? "";
  const [sp] = useSearchParams();
  const focus = sp.get("focus");

  const artifacts = useRunArtifactsQuery(id);
  const [preview, setPreview] = useState<{ id: string; markdown: string } | null>(null);

  const focusArtifact = useMemo(() => {
    if (!focus) return null;
    return artifacts.data?.find((a) => a.id === focus) ?? null;
  }, [artifacts.data, focus]);

  async function onDownload(a: Artifact) {
    await downloadArtifact(a.id);
  }

  function onOpen(a: Artifact) {
    const md = a.metadata?.["markdown"];
    if (typeof md === "string" && md.trim()) setPreview({ id: a.id, markdown: md });
    else setPreview(null);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">Artifacts</div>
          <div className="text-sm text-slate-500">
            Run <span className="text-slate-300">{id}</span>
          </div>
        </div>
        <Link to={`/runs/${encodeURIComponent(id)}`}>
          <Button variant="secondary">Back to Run</Button>
        </Link>
      </div>

      {artifacts.isLoading ? (
        <Card>
          <Spinner label="Loading artifacts???" />
        </Card>
      ) : artifacts.isError ? (
        <ErrorBanner message={artifacts.error instanceof Error ? artifacts.error.message : "Failed to load artifacts"} />
      ) : (artifacts.data?.length ?? 0) === 0 ? (
        <Card>
          <div className="text-sm text-slate-500">No artifacts yet.</div>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-3">
            {artifacts.data!.map((a) => (
              <Card key={a.id} className={a.id === focusArtifact?.id ? "border-sky-500/40" : undefined}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-slate-400" />
                      <div className="text-sm font-medium text-slate-100">{a.type}</div>
                    </div>
                    <div className="mt-1 text-xs text-slate-500">{formatTs(a.created_at)}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="secondary" onClick={() => void onDownload(a)}>
                      <Download className="h-4 w-4" />
                      Download
                    </Button>
                    {a.type.includes("report") ? (
                      <Button variant="secondary" onClick={() => onOpen(a)}>
                        Open
                      </Button>
                    ) : null}
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <Card>
            <div className="mb-2 text-sm font-semibold text-slate-100">Preview</div>
            {preview ? (
              <pre className="max-h-[520px] overflow-auto rounded-md border border-slate-900 bg-slate-950 p-3 text-xs text-slate-200">
                {preview.markdown}
              </pre>
            ) : (
              <div className="text-sm text-slate-500">
                Select an artifact with embedded markdown metadata to preview. Otherwise use Download.
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}


