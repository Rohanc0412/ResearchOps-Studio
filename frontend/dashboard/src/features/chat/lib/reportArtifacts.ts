import type { Artifact, ChatMessage } from "../../../types/dto";

export function buildFinalResponse(artifacts: Artifact[]): string {
  for (const artifact of artifacts) {
    const md = artifact.metadata?.["markdown"];
    if (typeof md === "string" && md.trim()) return md.trim();

    const msg = artifact.metadata?.["message"];
    if (typeof msg === "string" && msg.trim()) return msg.trim();
  }

  return "Run completed. Output is available in artifacts.";
}

export function extractLatestRunId(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!message || message.type !== "run_started") continue;
    const runId = message.content_json?.["run_id"];
    if (typeof runId === "string" && runId.trim()) return runId;
  }
  return null;
}
