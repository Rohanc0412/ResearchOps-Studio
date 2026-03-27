import type { ChatMessage, RunEvent } from "../../types/dto";

type ProgressStatus = "running" | "failed" | "succeeded" | "canceled";

export type ResearchProgressStepState = "complete" | "current" | "pending";

export type ResearchProgressStep = {
  id: string;
  label: string;
  state: ResearchProgressStepState;
};

export type ResearchProgressEventRow = {
  id: string;
  ts: string;
  message: string;
  detail?: string;
  level: "info" | "warn" | "error";
};

export type ResearchProgressCardModel = {
  title: string;
  steps: ResearchProgressStep[];
  summaryText: string;
  metricText: string;
  progressRatio: number;
  status: ProgressStatus;
  recentEvents: ResearchProgressEventRow[];
};

type BuildResearchProgressCardModelArgs = {
  activeRun: {
    status: ProgressStatus;
    question?: string;
    primaryText: string;
    secondaryText?: string;
    error?: string;
  } | null;
  chatTitle?: string | null;
  messages: ChatMessage[];
  events: RunEvent[];
};

const STAGE_TO_STEP_INDEX: Record<string, number> = {
  retrieve: 0,
  ingest: 1,
  outline: 1,
  evidence_pack: 2,
  draft: 3,
  evaluate: 4,
  validate: 4,
  repair: 4,
  factcheck: 4,
  export: 4
};

const STEP_PHASE_NAMES = ["Collect", "Themes", "Studies", "Compare", "Summary"] as const;

export function buildResearchProgressCardModel({
  activeRun,
  chatTitle,
  messages,
  events
}: BuildResearchProgressCardModelArgs): ResearchProgressCardModel {
  const title = deriveResearchTitle(activeRun?.question, messages, chatTitle);
  const topic = deriveTopicPhrase(title);
  const steps = [
    { id: "collect", label: `Collect recent evidence on ${topic}.` },
    { id: "themes", label: `Extract the main mechanisms and themes behind ${topic}.` },
    { id: "studies", label: `Review studies, benchmarks, and outcomes tied to ${topic}.` },
    { id: "compare", label: `Compare findings, tradeoffs, and limitations across the evidence.` },
    { id: "summary", label: `Summarize practical conclusions and recommendations.` }
  ];

  const latestEvent = events.at(-1);
  const currentStepIndex = deriveCurrentStepIndex(activeRun?.status ?? "running", latestEvent);
  const completedCount = activeRun?.status === "succeeded" ? steps.length : Math.max(0, currentStepIndex);
  const progressRatio = deriveProgressRatio(activeRun?.status ?? "running", currentStepIndex, latestEvent);

  return {
    title,
    steps: steps.map((step, index) => ({
      ...step,
      state:
        activeRun?.status === "succeeded" || index < currentStepIndex
          ? "complete"
          : index === currentStepIndex
            ? activeRun?.status === "canceled" && completedCount === index
              ? "pending"
              : "current"
            : "pending"
    })),
    summaryText: deriveSummaryText(activeRun, latestEvent),
    metricText: deriveMetricText(activeRun?.status ?? "running", latestEvent, events, currentStepIndex),
    progressRatio,
    status: activeRun?.status ?? "running",
    recentEvents: events.slice(-6).reverse().map((event, index) => ({
      id: `${event.ts}-${event.message}-${index}`,
      ts: event.ts,
      message: humanizeEventMessage(event),
      detail: humanizeEventDetail(event),
      level: event.level
    }))
  };
}

function deriveResearchTitle(
  runQuestion: string | undefined,
  messages: ChatMessage[],
  chatTitle?: string | null
) {
  if (runQuestion?.trim()) return clamp(runQuestion.trim(), 72);

  let fallbackTitle: string | null = null;

  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!message || message.role !== "user" || message.type !== "chat") continue;
    const trimmed = message.content_text.trim();
    if (!trimmed) continue;

    if (!isGenericRunTrigger(trimmed)) return clamp(trimmed, 72);
    if (!fallbackTitle) fallbackTitle = clamp(trimmed, 72);
  }

  if (chatTitle?.trim()) return clamp(chatTitle.trim(), 72);
  if (fallbackTitle) return fallbackTitle;
  return "Research report";
}

function deriveTopicPhrase(title: string) {
  const normalized = title.replace(/[.?!]+$/g, "").trim();
  const compact = normalized.length > 58 ? `${normalized.slice(0, 55).trim()}...` : normalized;
  return compact || "the topic";
}

function deriveCurrentStepIndex(status: ProgressStatus, latestEvent?: RunEvent) {
  if (status === "succeeded") return 5;
  if (!latestEvent) return 0;
  const index = STAGE_TO_STEP_INDEX[latestEvent.stage] ?? 0;
  return Math.min(index, 4);
}

function deriveProgressRatio(status: ProgressStatus, currentStepIndex: number, latestEvent?: RunEvent) {
  if (status === "succeeded") return 1;
  if (status === "failed" || status === "canceled") {
    return Math.max(0.08, Math.min(0.96, (currentStepIndex + 0.35) / 5));
  }

  let intraStep = 0.45;
  if (latestEvent) {
    if (latestEvent.message.includes("completed") || latestEvent.message.startsWith("Finished stage:")) {
      intraStep = 0.82;
    } else if (latestEvent.message.includes("started") || latestEvent.message.startsWith("Starting stage:")) {
      intraStep = 0.22;
    }

    const maybeSectionProgress = deriveSectionProgress(latestEvent, latestEvent.stage);
    if (maybeSectionProgress !== null) intraStep = maybeSectionProgress;
  }

  return Math.max(0.08, Math.min(0.96, (currentStepIndex + intraStep) / 5));
}

function deriveSummaryText(
  activeRun: BuildResearchProgressCardModelArgs["activeRun"],
  latestEvent?: RunEvent
) {
  if (activeRun?.status === "succeeded") return "Report completed and ready to review.";
  if (activeRun?.status === "failed") return activeRun.error?.trim() || "Research run failed before completion.";
  if (activeRun?.status === "canceled") return "Research run stopped before finishing.";

  if (latestEvent) return humanizeEventMessage(latestEvent);

  const fallback = [activeRun?.primaryText, activeRun?.secondaryText].filter(Boolean).join(" ");
  return fallback || "Preparing the research plan.";
}

function deriveMetricText(
  status: ProgressStatus,
  latestEvent: RunEvent | undefined,
  events: RunEvent[],
  currentStepIndex: number
): string {
  if (status === "succeeded") return "Done";
  if (status === "failed") return "Needs retry";
  if (status === "canceled") return "Stopped";
  if (!latestEvent) return STEP_PHASE_NAMES[0];

  const payload = latestEvent.payload ?? {};
  const queryCount = pickNumber(payload, ["query_count", "queries", "search_count", "searches"]);
  if (queryCount !== null) return `${queryCount} searches`;

  const sourceCount = pickNumber(payload, ["source_count", "sources", "candidate_count", "paper_count"]);
  if (sourceCount !== null) return `${sourceCount} sources`;

  const snippetCount = pickNumber(payload, ["snippet_count", "evidence_count"]);
  if (snippetCount !== null) return `${snippetCount} snippets`;

  const sectionProgress = deriveSectionMetric(events, latestEvent.stage);
  if (sectionProgress) return sectionProgress;

  const stepIndex = Math.min(currentStepIndex, 4);
  return STEP_PHASE_NAMES[stepIndex] || STEP_PHASE_NAMES[0];
}

function deriveSectionMetric(events: RunEvent[], stage: string) {
  const relevant = stage === "evaluate" || stage === "validate" || stage === "repair" ? "evaluate" : stage;
  const started = new Set<string>();
  const completed = new Set<string>();

  for (const event of events) {
    if (normalizeStage(event.stage) !== relevant) continue;
    const sectionId = readSectionId(event.payload);
    if (!sectionId) continue;
    if (event.message.includes("started")) started.add(sectionId);
    if (event.message.includes("completed") || event.message.includes("finished")) {
      started.add(sectionId);
      completed.add(sectionId);
    }
  }

  if (started.size === 0) return null;
  return `${completed.size}/${started.size} sections`;
}

function deriveSectionProgress(event: RunEvent, stage: string) {
  const payload = event.payload ?? {};
  const completed = pickNumber(payload, ["completed_sections", "completed_count"]);
  const total = pickNumber(payload, ["section_count", "total_sections", "total_count"]);
  if (completed !== null && total && total > 0) return Math.max(0.12, Math.min(0.92, completed / total));

  if (stage === "draft" || stage === "evaluate" || stage === "validate" || stage === "repair") {
    if (event.message.includes("section_started")) return 0.35;
    if (event.message.includes("section_completed")) return 0.72;
  }

  return null;
}

function humanizeEventMessage(event: RunEvent) {
  const message = event.message.trim();
  const sectionLabel = prettifyIdentifier(readSectionId(event.payload));

  if (event.stage === "retrieve") {
    if (message.includes("plan")) return "Planning the search strategy.";
    if (message.includes("query")) return "Collecting search queries and source targets.";
    if (message.includes("rerank")) return "Ranking the strongest sources to cite.";
    if (message.includes("completed")) return "Collected evidence from the latest literature.";
    return "Collecting recent evidence and literature.";
  }

  if (event.stage === "outline") {
    return "Structuring the report into major themes.";
  }

  if (event.stage === "ingest" || event.stage === "evidence_pack") {
    if (sectionLabel) return `Packaging evidence for ${sectionLabel}.`;
    return "Packaging evidence and study notes for drafting.";
  }

  if (event.stage === "draft") {
    if (message.includes("section_started") && sectionLabel) return `Drafting ${sectionLabel}.`;
    if (message.includes("section_completed") && sectionLabel) return `Drafted ${sectionLabel}.`;
    return "Comparing findings and drafting the report.";
  }

  if (event.stage === "evaluate" || event.stage === "validate" || event.stage === "repair" || event.stage === "factcheck") {
    if (message.includes("section_started") && sectionLabel) return `Reviewing ${sectionLabel}.`;
    if (message.includes("section_completed") && sectionLabel) return `Reviewed ${sectionLabel}.`;
    if (event.stage === "repair") return "Repairing sections that need stronger support.";
    return "Checking quality, evidence coverage, and consistency.";
  }

  if (event.stage === "export") {
    return "Exporting the final report artifacts.";
  }

  return sentenceCase(message.replace(/[._]/g, " "));
}

function humanizeEventDetail(event: RunEvent) {
  const payload = event.payload ?? {};
  const sectionLabel = prettifyIdentifier(readSectionId(payload));
  const verdict = typeof payload["verdict"] === "string" ? payload["verdict"] : null;
  const counts = [
    pickMetricValue(payload, "query_count", "queries"),
    pickMetricValue(payload, "search_count", "searches"),
    pickMetricValue(payload, "source_count", "sources"),
    pickMetricValue(payload, "snippet_count", "snippets")
  ].filter(Boolean);

  if (sectionLabel && verdict) return `${sectionLabel} • verdict: ${verdict}`;
  if (sectionLabel && counts.length > 0) return `${sectionLabel} • ${counts[0]}`;
  if (sectionLabel) return sectionLabel;
  if (counts.length > 0) return counts[0]!;
  return undefined;
}

function pickMetricValue(payload: Record<string, unknown>, key: string, label: string) {
  const value = payload[key];
  return typeof value === "number" ? `${value} ${label}` : null;
}

function readSectionId(payload?: Record<string, unknown>) {
  if (!payload) return null;
  const candidate = payload["section_id"] ?? payload["section"] ?? payload["section_name"];
  return typeof candidate === "string" && candidate.trim() ? candidate.trim() : null;
}

function normalizeStage(stage: string) {
  if (stage === "validate" || stage === "repair" || stage === "factcheck") return "evaluate";
  return stage;
}

function pickNumber(payload: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function prettifyIdentifier(value: string | null) {
  if (!value) return null;
  return sentenceCase(value.replace(/[_-]+/g, " "));
}

function sentenceCase(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  return `${trimmed.charAt(0).toUpperCase()}${trimmed.slice(1)}`;
}

function clamp(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 3).trim()}...` : value;
}

function isGenericRunTrigger(value: string) {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return true;

  return [
    "create the detailed research report now",
    "create the research report now",
    "run the research report",
    "run the research report now",
    "run the detailed research report",
    "start the research report",
    "start the research report now",
    "create the report now",
    "generate the report now",
    "continue with the report",
    "run the report now"
  ].includes(normalized.replace(/[.!?]+$/g, ""));
}
