import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useCreateRunMutation } from "../api/runs";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Input } from "../components/ui/Input";
import { Textarea } from "../components/ui/Textarea";

type OutputType = "report" | "litmap" | "experiment_plan";

export function NewRunPage() {
  const { projectId } = useParams();
  const pid = projectId ?? "";
  const nav = useNavigate();
  const create = useCreateRunMutation(pid);

  const [prompt, setPrompt] = useState("");
  const [outputType, setOutputType] = useState<OutputType>("report");
  const [tokenLimit, setTokenLimit] = useState("");
  const [timeLimit, setTimeLimit] = useState("");
  const [connectorCallsLimit, setConnectorCallsLimit] = useState("");

  const budgetOverride = useMemo(() => {
    const token = numOrUndef(tokenLimit);
    const time = numOrUndef(timeLimit);
    const calls = numOrUndef(connectorCallsLimit);
    if (token === undefined && time === undefined && calls === undefined) return undefined;
    return { token_limit: token, time_limit: time, connector_calls_limit: calls };
  }, [tokenLimit, timeLimit, connectorCallsLimit]);

  async function submit() {
    const run = await create.mutateAsync({
      prompt: prompt.trim(),
      output_type: outputType,
      budget_override: budgetOverride
    });
    nav(`/runs/${encodeURIComponent(run.id)}`, { replace: true });
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="text-lg font-semibold text-slate-100">Create Run</div>
        <div className="text-sm text-slate-500">Start a new run for this project.</div>
      </div>

      <Card>
        <div className="flex flex-col gap-4">
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Prompt</div>
            <Textarea rows={7} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe what you need…" />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="mb-1 text-xs font-medium text-slate-400">Output Type</div>
              <select
                className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
                value={outputType}
                onChange={(e) => setOutputType(e.target.value as OutputType)}
              >
                <option value="report">report</option>
                <option value="litmap">litmap</option>
                <option value="experiment_plan">experiment_plan</option>
              </select>
            </div>
            <div />
          </div>

          <div>
            <div className="text-sm font-semibold text-slate-100">Budget Overrides (optional)</div>
            <div className="mt-2 grid gap-3 md:grid-cols-3">
              <div>
                <div className="mb-1 text-xs font-medium text-slate-400">token_limit</div>
                <Input inputMode="numeric" value={tokenLimit} onChange={(e) => setTokenLimit(e.target.value)} placeholder="e.g. 40000" />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-slate-400">time_limit</div>
                <Input inputMode="numeric" value={timeLimit} onChange={(e) => setTimeLimit(e.target.value)} placeholder="seconds" />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-slate-400">connector_calls_limit</div>
                <Input
                  inputMode="numeric"
                  value={connectorCallsLimit}
                  onChange={(e) => setConnectorCallsLimit(e.target.value)}
                  placeholder="e.g. 200"
                />
              </div>
            </div>
          </div>

          {create.isError ? <ErrorBanner message={create.error instanceof Error ? create.error.message : "Failed to create run"} /> : null}

          <div className="flex justify-end">
            <Button onClick={() => void submit()} disabled={!pid || !prompt.trim() || create.isPending}>
              {create.isPending ? "Starting…" : "Start Run"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function numOrUndef(value: string): number | undefined {
  const v = value.trim();
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

