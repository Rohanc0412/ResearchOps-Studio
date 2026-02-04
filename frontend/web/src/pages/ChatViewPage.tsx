// TECH: React hooks used for component lifecycle, memoization, refs (DOM access), and local UI state.
// PLAIN: Tools React gives us to remember values, react to changes, and update what the user sees.
import { useEffect, useMemo, useRef, useState } from "react";

// TECH: React Router helpers for navigation and reading URL parameters/state.
// PLAIN: Lets the page know which chat/project to show and lets us move to other pages.
import { Link, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";

// TECH: Icon components (SVG) from lucide-react for consistent UI icons.
// PLAIN: Small pictures (icons) used on buttons like back, download, send, etc.
import { ArrowLeft, Download, Edit3, Send, Share2, Sparkles, Trash2 } from "lucide-react";

// TECH: jsPDF library generates PDFs in the browser (client-side export).
// PLAIN: Used to create a PDF file you can download.
import jsPDF from "jspdf";

// TECH: docx library generates Word documents (.docx) in the browser.
// PLAIN: Used to create an editable Word file you can download.
import { Document, Paragraph, TextRun, HeadingLevel, Packer } from "docx";

// TECH: file-saver triggers a browser download for a Blob without server involvement.
// PLAIN: Helps download the file you created directly to your computer.
import { saveAs } from "file-saver";

// TECH: Markdown renderer and GitHub-flavored markdown support.
// PLAIN: Lets chat messages show bold text, lists, and code properly.
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// TECH: Custom API hooks to fetch conversations/messages and send messages.
// PLAIN: Ready-made helpers that talk to the app???s backend for chat data.
import {
  flattenInfiniteMessages,
  useChatConversationsQuery,
  useChatMessagesInfiniteQuery,
  useSendChatMessageMutationInfinite
} from "../api/chat";

// TECH: Custom API hook to fetch the project details by ID.
// PLAIN: Loads the project name and information for this chat.
import { useProjectQuery } from "../api/projects";

// TECH: Custom API mutations to cancel and retry long-running report generation runs.
// PLAIN: Buttons to stop or retry the background ???report generation??? job.
import { useCancelRunMutation, useRetryRunMutation } from "../api/runs";

// TECH: Shared API helper for JSON requests with schema validation.
// PLAIN: A safe way to fetch data from the server and make sure it looks correct.
import { apiFetchJson } from "../api/client";

// TECH: Reusable UI components for errors and loading spinners.
// PLAIN: Shows helpful messages when something fails and a loader while waiting.
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Spinner } from "../components/ui/Spinner";
import { Button } from "../components/ui/Button";
import type { TopbarActionsContext } from "../components/layout/AppLayout";

// TECH: SSE (Server-Sent Events) hook for real-time streaming updates from the server.
// PLAIN: Lets the page receive live progress updates while a report is being created.
import { useSSE } from "../hooks/useSSE";

// TECH: DTO (data transfer object) types and Zod schema for runtime validation of artifacts.
// PLAIN: Defines the shape of data we expect from the server (so we don???t guess wrong).
import { ArtifactSchema, RunSchema, type Artifact, type ChatMessage, type Run } from "../types/dto";

// TECH: UI component that shows ???thinking / running / failed??? status for a run.
// PLAIN: A banner that tells you the report is being worked on and lets you stop/retry.
import { RunThinkingBanner } from "../components/run/RunThinkingBanner";

// TECH: Zod provides runtime schema validation (safer API responses).
// PLAIN: A ???data checker??? to confirm incoming data is shaped correctly.
import { z } from "zod";

// TECH: ReportSection is the UI-friendly structure of a report section: heading + content blocks.
// PLAIN: One part of the report (like ???Introduction???) with lines of text underneath it.
type ReportSection = {
  id: string;
  heading: string;
  content: Array<{
    text: string;
    citations?: number[];
    isBullet?: boolean;
  }>;
};

// TECH: Report is the full report object: title + multiple sections.
// PLAIN: The full report, made of a title and many sections.
type Report = {
  title: string;
  sections: ReportSection[];
};

// TECH: The possible terminal and non-terminal statuses for a server run.
// PLAIN: The ???job status??? showing whether the report is still working, done, or failed.
type ActiveRunStatus = "running" | "failed" | "succeeded" | "canceled";

// TECH: ActiveRun stores the currently running job state for the UI (progress banner).
// PLAIN: Information about the report job so we can show live progress on screen.
type ActiveRun = {
  runId: string;
  status: ActiveRunStatus;
  primaryText: string;
  secondaryText?: string;
  startedAt: string;
  error?: string;
};

// TECH: Schema for validating a list of artifacts returned by the server endpoint.
// PLAIN: A rule set that says ???the server must return a list of correctly shaped artifacts.???
const ArtifactsSchema = z.array(ArtifactSchema);

// TECH: Default report state when no report exists yet.
// PLAIN: A blank report shown before any content is generated.
const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};

// TECH: Default hosted LLM model name used if user doesn???t override.
// PLAIN: The default AI model chosen for generating the report.
const DEFAULT_HOSTED_MODEL = "arcee-ai/trinity-large-preview:free";
const CUSTOM_MODEL_VALUE = "__custom__";
const MODEL_OPTIONS = [
  { value: DEFAULT_HOSTED_MODEL, label: "Arcee Trinity Large Preview (free)" },
  { value: "tngtech/deepseek-r1t2-chimera:free", label: "DeepSeek R1T2 Chimera (free)" },
  { value: "xiaomi/mimo-v2-flash:free", label: "Xiaomi Mimo V2 Flash (free)" },
  { value: "openai/gpt-4o-mini", label: "OpenAI GPT-4o Mini" },
  { value: "anthropic/claude-3.5-sonnet", label: "Anthropic Claude 3.5 Sonnet" },
  { value: CUSTOM_MODEL_VALUE, label: "Custom..." }
];

// TECH (Function Summary): Generates a pseudo-unique ID using timestamp + random chunk.
// PLAIN (Function Summary): Makes a ???unique enough??? label so different sections don???t collide.
function generateId(): string {
  // TECH: Date.now() gives time in ms; random base36 string adds extra uniqueness.
  // PLAIN: Uses the current time plus a random bit so IDs don???t repeat.
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

// TECH (Function Summary): Generates a client-side message ID for idempotency/tracking.
// PLAIN (Function Summary): Creates a unique ID so the app can track this message reliably.
function generateClientMessageId(): string {
  // TECH: Prefer crypto.randomUUID() for strong uniqueness and collision resistance.
  // PLAIN: If the browser supports it, use the safest ???unique ID generator.???
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }

  // TECH: Fallback uses timestamp + random string when randomUUID is unavailable.
  // PLAIN: If the best option isn???t available, use a backup method.
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

// TECH (Function Summary): Build a stable storage key for a chat's report.
// PLAIN (Function Summary): Gives us a consistent place to save/load each chat's report.
function reportStorageKey(chatId: string): string {
  return `researchops_report:${chatId}`;
}

// TECH (Function Summary): Minimal runtime guard for report shape before using stored data.
// PLAIN (Function Summary): Make sure saved report data looks valid.
function isReportLike(value: unknown): value is Report {
  if (!value || typeof value !== "object") return false;
  const report = value as Report;
  if (typeof report.title !== "string" || !Array.isArray(report.sections)) return false;
  return report.sections.every((section) => {
    if (!section || typeof section !== "object") return false;
    if (typeof section.id !== "string" || typeof section.heading !== "string") return false;
    if (!Array.isArray(section.content)) return false;
    return section.content.every((item) => item && typeof item.text === "string");
  });
}

// TECH (Function Summary): Load saved report from localStorage for a specific chat.
// PLAIN (Function Summary): Restore the last report when you reopen a conversation.
function loadStoredReport(chatId: string): Report | null {
  try {
    const raw = window.localStorage.getItem(reportStorageKey(chatId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isReportLike(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

// TECH (Function Summary): Persist report to localStorage (or clear if empty).
// PLAIN (Function Summary): Save report so it shows up next time you open the chat.
function persistReport(chatId: string, report: Report): void {
  try {
    const key = reportStorageKey(chatId);
    if (report.sections.length === 0) {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(key, JSON.stringify(report));
  } catch {
    // ignore storage failures
  }
}

// TECH (Function Summary): Converts snake_case or kebab-case into a readable Title Case style.
// PLAIN (Function Summary): Makes machine-looking words readable for humans.
function titleCase(value: string): string {
  // TECH: Guard against empty/undefined-like strings.
  // PLAIN: If there is nothing to format, just return it.
  if (!value) return value;

  // TECH: Regex finds letters after start/_/- and uppercases them; also inserts spaces.
  // PLAIN: Turns things like "run_pipeline" into "run pipeline" with nicer capitalization.
  return value.replace(/(^|_|-)([a-z])/g, (_, sep, ch) => `${sep} ${ch.toUpperCase()}`).trim();
}

// TECH (Function Summary): Builds a final user-visible string from artifacts (prefer markdown).
// PLAIN (Function Summary): Picks the best report text from the output files the run created.
function buildFinalResponse(artifacts: Artifact[]): string {
  // TECH: Iterate in order to find first artifact with useful markdown/message fields.
  // PLAIN: Look through the results and pick the first meaningful text we find.
  for (const artifact of artifacts) {
    // TECH: Many systems store the final report in metadata.markdown.
    // PLAIN: Sometimes the report text is saved under ???markdown.???
    const md = artifact.metadata?.["markdown"];
    if (typeof md === "string" && md.trim()) return md.trim();

    // TECH: Some artifacts store text under metadata.message instead.
    // PLAIN: If it???s not markdown, it might be stored as a plain ???message.???
    const msg = artifact.metadata?.["message"];
    if (typeof msg === "string" && msg.trim()) return msg.trim();
  }

  // TECH: Fallback string when no artifact text is available.
  // PLAIN: A default message when the system finished but didn???t return text here.
  return "Run completed. Output is available in artifacts.";
}

/**
 * ??? Upgraded markdown parsing
 * Supports:
 * - Headers (##, ###)
 * - Paragraphs (multi-line)
 * - Bullets (-, *, +)+
 * - Numbered lists (1. 2. ...)
 * - Inline citations [1] [2] and footnote refs [^3]
 * - References with footnotes [^1]: ...
 * - Multi-line footnotes (indented continuations)
 */

// TECH (Function Summary): Extracts inline citation markers like [1] or [^2] and returns cleaned text + citation numbers.
// PLAIN (Function Summary): Removes citation tags from the sentence but remembers which citations were referenced.
function extractInlineCitations(input: string): { text: string; citations: number[] } {
  // TECH: Store parsed citation numbers as integers, later de-duplicated.
  // PLAIN: Keep a list of citation numbers we find.
  const citations: number[] = [];

  // TECH: Regex matches either standard citations [12] OR footnote-style citations [^12].
  // PLAIN: Looks for citation markers like ???[1]??? or ???[^1]??? in the text.
  const citationRegex = /\[(\d+)\]|\[\^(\d+)\]/g;

  // TECH: Replace citations with empty string, collecting numeric identifiers into citations[].
  // PLAIN: Remove the citation parts from the text but remember their numbers.
  const textWithoutCitations = input.replace(citationRegex, (_match, g1, g2) => {
    // TECH: g1 holds digits for [n], g2 holds digits for [^n].
    // PLAIN: One match group is used depending on which citation type was found.
    const numRaw = g1 ?? g2;

    // TECH: Convert to number and verify it???s valid.
    // PLAIN: Turn the number into a real numeric value.
    const num = Number(numRaw);
    if (!Number.isNaN(num)) citations.push(num);

    // TECH: Remove citation tokens from output text.
    // PLAIN: Don???t show the raw citation marker in the sentence.
    return "";
  });

  // TECH: Clean up spacing artifacts from removing citations: extra spaces, punctuation spacing.
  // PLAIN: Fix awkward spacing so the sentence still looks normal.
  const cleaned = textWithoutCitations
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();

  // TECH: De-duplicate citations while preserving first-seen order using a Set.
  // PLAIN: Remove repeated citation numbers so the badge list stays neat.
  const seen = new Set<number>();
  const uniq = citations.filter((n) => {
    if (seen.has(n)) return false;
    seen.add(n);
    return true;
  });

  // TECH: Return final cleaned text and unique citation list.
  // PLAIN: Send back the cleaned sentence plus the citations that belong to it.
  return { text: cleaned, citations: uniq };
}

// TECH (Function Summary): Detects if a line is a references/bibliography heading in markdown.
// PLAIN (Function Summary): Checks if a line means ???we are now in the references section.???
function isReferencesHeading(line: string): boolean {
  // TECH: Normalize whitespace and casing for tolerant matching.
  // PLAIN: Make the text easier to compare by ignoring spaces and capitalization.
  const normalized = line.trim().toLowerCase();

  // TECH: Explicit set of recognized headings.
  // PLAIN: Accept several common ways people label references.
  return (
    normalized === "## references" ||
    normalized === "## reference" ||
    normalized === "## bibliography" ||
    normalized === "## citations"
  );
}

// TECH (Function Summary): Parses a subset of markdown into structured report sections with bullets and citations.
// PLAIN (Function Summary): Turns the markdown output into report sections that the UI can display nicely.
function parseMarkdownToSections(markdown: string): ReportSection[] {
  // TECH: Collect all sections created from the markdown.
  // PLAIN: This will hold the final list of report sections.
  const sections: ReportSection[] = [];

  // TECH: Normalize Windows newlines to Unix and split into lines.
  // PLAIN: Break the big text into individual lines for easier reading.
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");

  // TECH: Track the section currently being built.
  // PLAIN: Keep track of which part of the report we???re currently filling in.
  let currentSection: ReportSection | null = null;

  // TECH: Buffer multiple lines into a single paragraph (markdown paragraphs can span lines).
  // PLAIN: Some paragraphs wrap across lines, so we gather them and treat them as one.
  let paragraphBuffer: string[] = [];

  // TECH: Keep track of the most recently added footnote reference item for multi-line continuation.
  // PLAIN: If a reference is split across lines, remember where to append extra text.
  let lastFootnoteIndex: number | null = null;

  // TECH (Function Summary): Ensures currentSection exists with the provided heading; creates it if missing.
  // PLAIN (Function Summary): Makes sure we always have a section to put text into.
  const ensureSection = (heading: string) => {
    // TECH: Only create a new section if none exists.
    // PLAIN: Don???t create duplicates if we already have a section.
    if (!currentSection) {
      currentSection = {
        id: generateId(),
        heading,
        content: []
      };
    }
  };

  // TECH (Function Summary): Pushes the currentSection into the output list if it exists, then clears it.
  // PLAIN (Function Summary): Finalizes a section and starts fresh for the next one.
  const pushSectionIfAny = () => {
    // TECH: Only push when there is an active section.
    // PLAIN: Only save a section if we actually have one.
    if (currentSection) {
      sections.push(currentSection);
      currentSection = null;
    }
  };

  // TECH (Function Summary): Converts buffered paragraph lines into a single content item in the current section.
  // PLAIN (Function Summary): Takes the paragraph we???ve been collecting and adds it to the report.
  const flushParagraph = () => {
    // TECH: A paragraph belongs to a section; do nothing if no section exists.
    // PLAIN: If we don???t know where to place the text, don???t add it.
    if (!currentSection) return;

    // TECH: If buffer is empty, nothing to flush.
    // PLAIN: If there???s no paragraph text saved up, we???re done.
    if (paragraphBuffer.length === 0) return;

    // TECH: Join buffered lines with spaces for a single paragraph sentence flow.
    // PLAIN: Combine multiple lines into a single paragraph.
    const rawText = paragraphBuffer.join(" ").trim();

    // TECH: Clear buffer since paragraph is being committed.
    // PLAIN: Reset so we can start collecting the next paragraph.
    paragraphBuffer = [];

    // TECH: Paragraph flush resets footnote continuation tracking.
    // PLAIN: If we ended a paragraph, we???re no longer continuing a footnote.
    lastFootnoteIndex = null;

    // TECH: If the paragraph becomes empty after trimming, skip.
    // PLAIN: Ignore blank lines that don???t contain real content.
    if (!rawText) return;

    // TECH: Extract citations and remove them from visible text.
    // PLAIN: Find citation numbers like [1] and keep them in a separate list.
    const { text, citations } = extractInlineCitations(rawText);

    // TECH: Prefer cleaned text, fallback to raw if extraction removed everything (rare but possible).
    // PLAIN: Use the cleaned sentence unless it accidentally became empty.
    const finalText = text || rawText;

    // TECH: Safety check to avoid pushing empty text blocks.
    // PLAIN: Don???t add empty content to the report.
    if (!finalText) return;

    // TECH: Push as a normal (non-bullet) paragraph item.
    // PLAIN: Add this as a regular paragraph line in the section.
    currentSection.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: false
    });
  };

  // TECH (Function Summary): Adds a bullet item to the current section, ensuring paragraph buffer is flushed first.
  // PLAIN (Function Summary): Adds a ???bullet point??? line to the report.
  const pushBullet = (raw: string) => {
    // TECH: Bullets should always have some section to go into, default to Live Report.
    // PLAIN: If we don???t have a section heading yet, put bullets into ???Live Report.???
    ensureSection("Live Report");

    // TECH: A bullet starts a new block, so flush any pending paragraph first.
    // PLAIN: Save any paragraph text before starting bullets.
    flushParagraph();

    // TECH: Extract citations from bullet text and store them separately.
    // PLAIN: Pull out citation numbers and keep the bullet text clean.
    const { text, citations } = extractInlineCitations(raw);
    const finalText = text || raw;

    // TECH: Non-null assertion because ensureSection guarantees currentSection exists.
    // PLAIN: We know the section exists because we just made sure it does.
    currentSection!.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: true
    });

    // TECH: Bullets are not footnote continuations.
    // PLAIN: A bullet resets any ???continuing reference??? behavior.
    lastFootnoteIndex = null;
  };

  // TECH (Function Summary): Adds a reference footnote item like ???[1] Source details...??? into a References section.
  // PLAIN (Function Summary): Adds a citation entry into the References list.
  const pushReferenceFootnote = (num: number, content: string) => {
    // TECH: Footnotes are stored under ???References??? section.
    // PLAIN: References go into a section named ???References.???
    ensureSection("References");

    // TECH: Footnotes are separate items, so flush pending paragraph first.
    // PLAIN: Save any paragraph text before adding a reference line.
    flushParagraph();

    // TECH: Format references consistently as ???[n] text???.
    // PLAIN: Show references in a standard numbered format.
    const formatted = `[${num}] ${content}`.trim();

    // TECH: Store references as bullet items so they render with a marker in the UI.
    // PLAIN: Treat references like a list item so it looks structured.
    currentSection!.content.push({
      text: formatted,
      isBullet: true
    });

    // TECH: Track this index so indented continuation lines can append to this reference.
    // PLAIN: Remember where this reference is so extra lines can be added to it.
    lastFootnoteIndex = currentSection!.content.length - 1;
  };

  // TECH: Main line-by-line markdown parser loop.
  // PLAIN: Go through the markdown line by line and decide what each line means.
  for (let i = 0; i < lines.length; i++) {
    // TECH: Default to empty string to avoid undefined.
    // PLAIN: Make sure we always handle a line even if something is missing.
    const line = lines[i] ?? "";

    // TECH: Detect section headers with ## or ### (not # which is treated as title).
    // PLAIN: If the line starts with ???##??? it means a new section heading.
    const headerMatch = line.match(/^(#{2,3})\s+(.+)$/);
    if (headerMatch) {
      // TECH: Close any pending paragraph before switching sections.
      // PLAIN: Finish the paragraph before starting a new section.
      flushParagraph();

      // TECH: Commit previous section (if any) to sections array.
      // PLAIN: Save the last section we were working on.
      pushSectionIfAny();

      // TECH: Create a new section based on header text.
      // PLAIN: Start a new report section using the header as its title.
      currentSection = {
        id: generateId(),
        heading: headerMatch[2].trim(),
        content: []
      };

      // TECH: Reset footnote continuation whenever a new heading starts.
      // PLAIN: New section means no reference line is being continued.
      lastFootnoteIndex = null;
      continue;
    }

    // TECH: Ignore top-level title line "# ..." because report title is handled elsewhere.
    // PLAIN: Skip the big title line since the report already has a title.
    if (/^#\s+/.test(line)) {
      continue;
    }

    // TECH: Special-case common reference section headings.
    // PLAIN: If the line says ???References,??? switch into the references section.
    if (isReferencesHeading(line)) {
      flushParagraph();
      pushSectionIfAny();
      currentSection = {
        id: generateId(),
        heading: "References",
        content: []
      };
      lastFootnoteIndex = null;
      continue;
    }

    // TECH: Horizontal rule can be used as a separator before references; treat it as reference section start.
    // PLAIN: A line with ???---??? often means ???next part starts now,??? so we treat it like References begin.
    if (line.trim() === "---") {
      flushParagraph();
      pushSectionIfAny();
      currentSection = {
        id: generateId(),
        heading: "References",
        content: []
      };
      lastFootnoteIndex = null;
      continue;
    }

    // TECH: Empty line ends a paragraph in markdown.
    // PLAIN: A blank line means the paragraph is finished.
    if (line.trim() === "") {
      flushParagraph();
      continue;
    }

    // TECH: Parse footnote definitions: [^1]: citation text.
    // PLAIN: Lines like ???[^1]: ...??? are reference entries.
    const footnoteMatch = line.match(/^\[\^(\d+)\]:\s*(.*)$/);
    if (footnoteMatch) {
      // TECH: Convert captured footnote number to integer.
      // PLAIN: Grab the reference number.
      const num = Number(footnoteMatch[1]);

      // TECH: Footnote body text is remainder of the line.
      // PLAIN: Everything after ???:??? is the reference content.
      const body = footnoteMatch[2] ?? "";

      // TECH: Store as a reference bullet line in ???References???.
      // PLAIN: Add this as a new reference item.
      pushReferenceFootnote(num, body);
      continue;
    }

    // TECH: Footnote continuation lines are indented (2+ spaces) and append to last footnote item.
    // PLAIN: If a reference continues on the next line with indentation, add it to the same reference.
    if (lastFootnoteIndex !== null && /^\s{2,}\S+/.test(line)) {
      // TECH: Trim indentation and append.
      // PLAIN: Remove leading spaces and add to the previous reference.
      const extra = line.trim();

      // TECH: Safely read the previously created reference item.
      // PLAIN: Get the last reference line we added.
      const item = currentSection?.content[lastFootnoteIndex];
      if (item) {
        item.text = `${item.text} ${extra}`.trim();
      }
      continue;
    }

    // TECH: Bullet syntax supports -, *, + at start.
    // PLAIN: Lines starting with a dash or star become bullet points.
    const bulletMatch = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bulletMatch) {
      pushBullet(bulletMatch[1] ?? "");
      continue;
    }

    // TECH: Numbered list support like "1. item" treated as bullets for consistent UI.
    // PLAIN: Lines starting with ???1.??? or ???2.??? become list items.
    const numberedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (numberedMatch) {
      pushBullet(numberedMatch[1] ?? "");
      continue;
    }

    // TECH: Normal text line belongs to a paragraph, possibly multi-line.
    // PLAIN: Regular lines are part of a paragraph.
    ensureSection("Live Report");
    paragraphBuffer.push(line.trim());
  }

  // TECH: Flush any last paragraph content at end of file.
  // PLAIN: Save whatever text was still being collected.
  flushParagraph();

  // TECH: Push last section (if any) at end of parsing.
  // PLAIN: Save the last section to the final list.
  pushSectionIfAny();

  // TECH: Remove empty sections so UI doesn't show headings with no content.
  // PLAIN: Don???t show empty sections in the report.
  return sections.filter((s) => s.content.length > 0);
}

// TECH (Function Summary): Derives a user-friendly run status update from an SSE event payload.
// PLAIN (Function Summary): Turns raw progress updates into readable ???what???s happening??? messages.
function deriveRunUpdate(event: { stage?: string; message?: string; payload?: Record<string, unknown> }) {
  // TECH: Defensive default payload object to avoid undefined access.
  // PLAIN: Make sure we always have a payload to read from.
  const payload = event.payload ?? {};

  // TECH: Some events store status in payload.status and others in payload.to_status.
  // PLAIN: The server may send the status under different names, so check both.
  const rawStatus = payload["status"] ?? payload["to_status"];
  const status = typeof rawStatus === "string" ? rawStatus : null;

  // TECH: primaryText is a short message shown prominently in the run banner.
  // PLAIN: This is the main line the user sees about progress.
  let primaryText = "Working";

  // TECH: secondaryText is extra context like step name or artifact type.
  // PLAIN: This is a smaller detail line under the main progress message.
  let secondaryText: string | undefined;

  // TECH: Interpret message conventions emitted by server for stage transitions.
  // PLAIN: Convert system messages into friendly progress labels.
  if (event.message?.startsWith("Starting stage:")) {
    primaryText = `Working on ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.message?.startsWith("Finished stage:")) {
    primaryText = `Finished ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.stage) {
    primaryText = `Processing ${titleCase(event.stage)}`;
  } else if (event.message) {
    primaryText = event.message;
  }

  // TECH: Prefer payload.step when available for more granular status updates.
  // PLAIN: If the server says which step it???s on, show that to the user.
  const step = payload["step"];
  if (typeof step === "string" && step.trim()) {
    secondaryText = `Step: ${step}`;
  } else {
    // TECH: Otherwise show artifact type as context if the server emits it.
    // PLAIN: If it???s creating a particular output, show which type it is.
    const artifactType = payload["artifact_type"];
    if (typeof artifactType === "string" && artifactType.trim()) {
      secondaryText = `Artifact: ${artifactType}`;
    }
  }

  // TECH: Return structured update for UI state application.
  // PLAIN: Send back the status and readable messages.
  return { status, primaryText, secondaryText };
}

// TECH (Function Summary): Maps action IDs to human-readable labels for display in the chat UI.
// PLAIN (Function Summary): Converts hidden action codes into friendly button text.
function formatActionLabel(actionId: string | null) {
  // TECH: Provide a fallback string for unknown/null actions.
  // PLAIN: If we don???t know what action it is, call it ???Action.???
  if (!actionId) return "Action";

  // TECH: Special-case known action IDs for best UX.
  // PLAIN: Give nicer names for common actions.
  if (actionId === "run_pipeline") return "Run research report";
  if (actionId === "quick_answer") return "Quick answer";

  // TECH: Default transformation: replace underscores with spaces.
  // PLAIN: Make ???snake_case??? look like normal words.
  return actionId.replace(/_/g, " ");
}

// TECH (Function Summary): Returns the user-visible message string for a chat message.
// PLAIN (Function Summary): Decides what text should appear in the chat bubble.
function displayMessageText(message: ChatMessage) {
  // TECH: Action messages are encoded and need conversion to a friendly label.
  // PLAIN: Some messages represent ???actions??? and must be shown as a readable name.
  if (message.type === "action") {
    // TECH: Prefer structured action_id from content_json; fallback to parsing content_text.
    // PLAIN: If the action ID is stored in a structured field, use it; otherwise extract it.
    const actionId =
      (message.content_json?.["action_id"] as string | undefined) ??
      message.content_text.replace("__ACTION__:", "").trim();

    // TECH: Present as a label rather than raw action string.
    // PLAIN: Show a human-friendly action name.
    return formatActionLabel(actionId || null);
  }

  // TECH: Default is plain message content text.
  // PLAIN: Normal messages just show what was written.
  return message.content_text;
}

// TECH (Function Summary): Normalizes markdown to reduce extra blank lines between list items.
// PLAIN (Function Summary): Cleans up list spacing so numbered items don't look too far apart.
function normalizeChatMarkdown(input: string) {
  if (!input) return input;
  return (
    input
      // Collapse excessive blank lines.
      .replace(/\n{3,}/g, "\n\n")
      // Remove blank lines between ordered list items like "1.\n\n2."
      .replace(/\n\s*\n(?=\d+\.)/g, "\n")
      // Remove blank lines between unordered list items like "- \n\n-"
      .replace(/\n\s*\n(?=[*-]\s)/g, "\n")
  );
}

const chatMarkdownComponents: Components = {
  h1: ({ children }) => <h1 className="mb-2 text-base font-semibold text-slate-100">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-sm font-semibold text-slate-100">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 text-sm font-medium text-slate-100">{children}</h3>,
  p: ({ children }) => <p className="mb-1 last:mb-0 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="ml-5 list-disc space-y-0">{children}</ul>,
  ol: ({ children }) => <ol className="ml-5 list-decimal space-y-0">{children}</ol>,
  li: ({ children }) => <li className="leading-snug [&>p]:m-0 [&>p]:leading-snug">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-slate-100">{children}</strong>,
  em: ({ children }) => <em className="italic text-slate-200">{children}</em>,
  code: ({ inline, children }) =>
    inline ? (
      <code className="rounded bg-slate-900 px-1 py-0.5 font-mono text-xs text-emerald-200">
        {children}
      </code>
    ) : (
      <code className="font-mono">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="mt-2 overflow-auto rounded-md bg-slate-900 p-3 text-xs text-slate-200">
      {children}
    </pre>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-emerald-300 underline underline-offset-2 hover:text-emerald-200"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-slate-600 pl-3 italic text-slate-300/90">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-700" />
};

// Citation badge component
// TECH (Function Summary): Renders a small styled badge for a citation number like [3].
// PLAIN (Function Summary): Shows a small green label with a citation number.
function CitationBadge({ number }: { number: number }) {
  return (
    // TECH: Tailwind styling creates a consistent pill badge; monospaced font emphasizes numeric marker.
    // PLAIN: Makes the citation look like a neat little tag next to the sentence.
    <span className="ml-1.5 inline-flex items-center justify-center rounded bg-emerald-500/15 px-2 py-0.5 font-mono text-xs font-semibold text-emerald-400">
      [{number}]
    </span>
  );
}

// Typing indicator
// TECH (Function Summary): Renders an animated dot indicator to show the assistant is ???typing??? (waiting for API).
// PLAIN (Function Summary): Shows bouncing dots so the user knows the system is working.
function TypingIndicator() {
  return (
    // TECH: Flex row with small bouncing circles; animationDelay staggers each dot bounce.
    // PLAIN: Three dots bounce one after another like messaging apps do.
    <div className="flex gap-1 py-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-2 w-2 animate-bounce rounded-full bg-emerald-500"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}

// Report section component
// TECH (Function Summary): Displays a single report section and supports inline editing of its content.
// PLAIN (Function Summary): Shows one report section and lets the user edit its text.
function ReportSectionView({
  section,
  onEdit,
  isHighlighted
}: {
  section: ReportSection;
  onEdit: (sectionId: string, content: string) => void;
  isHighlighted: boolean;
}) {
  // TECH: isEditing toggles between view mode and textarea edit mode.
  // PLAIN: Tracks whether we are currently editing this section.
  const [isEditing, setIsEditing] = useState(false);

  // TECH: editedContent holds the textarea value; initialized from current section content.
  // PLAIN: This stores what the user is typing while editing.
  const [editedContent, setEditedContent] = useState(section.content.map((c) => c.text).join("\n\n"));

  // TECH (Function Summary): Saves changes by calling parent callback and exits edit mode.
  // PLAIN (Function Summary): Applies the edits and returns to normal view.
  const handleSave = () => {
    // TECH: Notify parent of the new content; parent owns report state.
    // PLAIN: Tell the main page ???this section text changed.???
    onEdit(section.id, editedContent);

    // TECH: Exit editing UI after saving.
    // PLAIN: Stop showing the editor box.
    setIsEditing(false);
  };

  return (
    // TECH: Optional highlight animation for newly added content (pulse effect).
    // PLAIN: Briefly glow when a new section was just added.
    <div className={`mb-7 transition-all duration-300 ${isHighlighted ? "animate-pulse" : ""}`}>
      <div className="mb-4 flex items-center gap-3">
        <div className="h-6 w-1 rounded-sm bg-emerald-500" />
        <h3 className="font-mono text-base font-semibold tracking-wide text-emerald-400">{section.heading}</h3>
        {!isEditing && (
          <button
            // TECH: Clicking switches to edit mode and shows textarea + buttons.
            // PLAIN: Clicking ???Edit??? lets you change the section text.
            onClick={() => setIsEditing(true)}
            className="ml-auto flex items-center gap-1.5 rounded border border-slate-700 bg-transparent px-2 py-1 text-xs text-slate-500 transition-colors hover:border-slate-500 hover:text-slate-300"
          >
            <Edit3 className="h-3.5 w-3.5" />
            Edit
          </button>
        )}
      </div>

      {isEditing ? (
        <div className="pl-4">
          <textarea
            // TECH: Controlled input ensures React state is source of truth for content.
            // PLAIN: The text box always shows the latest typed text.
            value={editedContent}
            onChange={(e) => setEditedContent(e.target.value)}
            className="min-h-32 w-full resize-y rounded-lg border border-emerald-500/40 bg-slate-950 p-3 text-sm leading-relaxed text-slate-200 outline-none focus:border-emerald-500/60"
          />
          <div className="mt-3 flex justify-end gap-2">
            <button
              // TECH: Cancel discards unsaved edits by leaving edit mode (state remains, but UI returns).
              // PLAIN: Cancel stops editing without saving.
              onClick={() => setIsEditing(false)}
              className="rounded-md border border-slate-600 bg-transparent px-4 py-2 text-sm text-slate-400 transition-colors hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              // TECH: Save applies updates upstream via onEdit callback.
              // PLAIN: Save keeps your changes.
              onClick={handleSave}
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-slate-900 transition-colors hover:bg-emerald-400"
            >
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="pl-4">
          {section.content.map((item, idx) => (
            <div key={idx} className="mb-3 flex items-start">
              {item.isBullet && <span className="mr-3 mt-0.5 text-xs text-emerald-500">???</span>}
              <p className="flex-1 text-sm leading-relaxed text-slate-300">
                {item.text}
                {item.citations?.map((num) => (
                  <CitationBadge key={num} number={num} />
                ))}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Export modal
// TECH (Function Summary): Modal dialog that lets user choose export format (PDF/DOCX/MD/HTML).
// PLAIN (Function Summary): A pop-up window asking how you want to download your report.
function ExportModal({
  isOpen,
  onClose,
  onExport
}: {
  isOpen: boolean;
  onClose: () => void;
  onExport: (format: string) => void;
}) {
  // TECH: Conditional rendering prevents modal from existing in DOM when closed.
  // PLAIN: If the modal isn???t open, don???t show it.
  if (!isOpen) return null;

  // TECH: Static option list for rendering export choices.
  // PLAIN: The buttons you can pick from for downloading.
  const options = [
    { id: "pdf", label: "PDF Document", icon: "????", desc: "Best for sharing and printing" },
    { id: "docx", label: "Word Document", icon: "????", desc: "Editable in Microsoft Word" },
    { id: "md", label: "Markdown", icon: "????", desc: "Plain text with formatting" },
    { id: "html", label: "HTML", icon: "????", desc: "Web-ready format" }
  ];

  return (
    // TECH: Backdrop covers entire screen; clicking backdrop closes modal.
    // PLAIN: Dark overlay behind the popup; click outside to close.
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950" onClick={onClose}>
      <div
        // TECH: Stop click propagation so clicking inside the card doesn't close the modal.
        // PLAIN: Clicking inside the popup shouldn???t close it by accident.
        className="w-96 max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Export Report</h3>
        <div className="flex flex-col gap-3">
          {options.map((opt) => (
            <button
              key={opt.id}
              // TECH: onExport triggers the export process in parent component with selected format.
              // PLAIN: Clicking starts downloading in the chosen format.
              onClick={() => onExport(opt.id)}
              className="flex items-center gap-4 rounded-xl border border-slate-700 bg-slate-900 p-4 text-left transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10"
            >
              <span className="text-2xl">{opt.icon}</span>
              <div>
                <div className="text-sm font-medium text-slate-100">{opt.label}</div>
                <div className="mt-0.5 text-xs text-slate-500">{opt.desc}</div>
              </div>
            </button>
          ))}
        </div>
        <button
          // TECH: Close modal without exporting.
          // PLAIN: Cancel and go back.
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// Share modal
// TECH (Function Summary): Modal dialog that shows a share link and lets user copy it to clipboard.
// PLAIN (Function Summary): A popup that provides a link you can share with others.
function ShareModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  // TECH: copied state drives temporary UI feedback ("Copied!") after clipboard write.
  // PLAIN: Tracks if the link was copied so the button can confirm it.
  const [copied, setCopied] = useState(false);

  // TECH: Hard-coded share link placeholder; in production this likely comes from backend.
  // PLAIN: The link people can use to view the report.
  const shareLink = "https://researchops.studio/reports/shared-report";

  // TECH (Function Summary): Copies share link to clipboard and shows confirmation for 2 seconds.
  // PLAIN (Function Summary): Copies the link so the user can paste it elsewhere.
  const handleCopy = () => {
    // TECH WARNING: Clipboard API requires a secure context (HTTPS) and user gesture; can fail silently on some browsers.
    // PLAIN WARNING: Copy might not work in some browsers or insecure pages.
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // TECH: Do not render modal when closed.
  // PLAIN: Hide the popup when it???s not open.
  if (!isOpen) return null;

  return (
    // TECH: Backdrop click closes modal.
    // PLAIN: Clicking outside the popup closes it.
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950" onClick={onClose}>
      <div
        // TECH: Prevent inside clicks from closing modal.
        // PLAIN: Clicking inside shouldn???t close the popup.
        className="w-[420px] max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-5 text-lg font-semibold text-slate-100">Share Report</h3>
        <p className="mb-4 text-sm text-slate-400">Anyone with this link can view the report</p>
        <div className="flex gap-2 rounded-lg border border-slate-700 bg-slate-900 p-3">
          <input
            // TECH: Read-only input prevents edits while allowing easy selection/copy.
            // PLAIN: Shows the link so you can see it, but you can???t accidentally change it.
            type="text"
            value={shareLink}
            readOnly
            className="flex-1 border-none bg-transparent font-mono text-sm text-slate-200 outline-none"
          />
          <button
            // TECH: Button triggers clipboard write and toggles copied state.
            // PLAIN: Copies the link to your clipboard.
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
          // TECH: Close modal.
          // PLAIN: Finish and close the popup.
          onClick={onClose}
          className="mt-4 w-full rounded-lg border border-slate-600 bg-transparent py-3 text-sm text-slate-400 transition-colors hover:bg-slate-700"
        >
          Done
        </button>
      </div>
    </div>
  );
}

// TECH (Function Summary): Main page component that renders chat UI and a live report panel side-by-side.
// PLAIN (Function Summary): The main screen where you chat on the left and see the report appear on the right.
export function ChatViewPage() {
  // TECH: Read route params from URL; these identify current project and conversation.
  // PLAIN: Get which project and chat we???re looking at from the web address.
  const { projectId, chatId } = useParams();

  // TECH: useLocation provides access to navigation state (e.g., initialMessage passed from previous screen).
  // PLAIN: Lets this page read extra info passed when coming here.
  const location = useLocation();

  // TECH: useNavigate enables imperative navigation (back to project page, etc.).
  // PLAIN: Lets us jump to another page when a button is clicked.
  const navigate = useNavigate();

  // TECH: useOutletContext provides access to topbar action controls from AppLayout.
  // PLAIN: Lets this page put buttons in the top bar.
  const { setTopbarActions } = useOutletContext<TopbarActionsContext>();

  // TECH: Normalize project ID to empty string if undefined for hook usage.
  // PLAIN: Make sure we always have a string ID to use.
  const id = projectId ?? "";

  // TECH: Fetch project data; provides isLoading/isError/data.
  // PLAIN: Load the project details so we can show its name.
  const project = useProjectQuery(id);

  // TECH: Fetch up to 200 conversations for the project (pagination/limit provided by hook).
  // PLAIN: Load the list of chats so we can find the current one.
  const conversations = useChatConversationsQuery(id, 200);

  // TECH: Fetch messages using cursor pagination (infinite query).
  // PLAIN: Load the messages in this chat, page-by-page.
  const messagesQuery = useChatMessagesInfiniteQuery(chatId ?? "", 200);

  // TECH: Mutation for sending a message to the server (async).
  // PLAIN: A function that sends what the user typed.
  const sendChat = useSendChatMessageMutationInfinite(chatId ?? "", 200);

  // TECH: activeRun holds live status of background report job started by assistant.
  // PLAIN: Tracks whether the report is currently being generated.
  const [activeRun, setActiveRun] = useState<ActiveRun | null>(null);

  // TECH: Cancel and retry mutations depend on activeRun.runId; empty string if none.
  // PLAIN: Prepare buttons to stop or retry the report job.
  const cancelRun = useCancelRunMutation(activeRun?.runId ?? "");
  const retryRun = useRetryRunMutation(activeRun?.runId ?? "");

  // TECH: draft is controlled textarea value for the chat input.
  // PLAIN: Stores what the user is typing before sending.
  const [draft, setDraft] = useState("");

  // TECH: isTyping indicates we are waiting for server response to sendChat; drives typing indicator.
  // PLAIN: Shows a ???working??? animation so user knows something is happening.
  const [isTyping, setIsTyping] = useState(false);

  // TECH: selectedModel/customModel track dropdown vs custom model selection.
  // PLAIN: Lets the user pick a model from the list or type a custom one.
  const [selectedModel, setSelectedModel] = useState(DEFAULT_HOSTED_MODEL);
  const [customModel, setCustomModel] = useState("");

  // TECH: runPipelineArmed toggles auto-accepting research pipeline offers.
  // PLAIN: When on, the app auto-starts a research report if offered.
  const [runPipelineArmed, setRunPipelineArmed] = useState(false);

  // TECH: report stores the right-panel report structure.
  // PLAIN: Holds the generated report content that shows on the right side.
  const [report, setReport] = useState<Report>(EMPTY_REPORT);

  // TECH: reportChatIdRef tracks which chatId the report state currently corresponds to.
  // PLAIN: Prevents saving a report under the wrong conversation when switching chats.
  const reportChatIdRef = useRef<string | null>(null);

  // TECH: highlightedSection temporarily highlights newly added section for UX feedback.
  // PLAIN: Makes new content briefly stand out so user notices it.
  const [highlightedSection, setHighlightedSection] = useState<string | null>(null);

  // TECH: Controls visibility for export/share modals.
  // PLAIN: Tracks whether the popups are open.
  const [showExportModal, setShowExportModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);

  // TECH: exportNotification shows a temporary toast message for export status.
  // PLAIN: Shows a message like ???Exporting?????? or ???Downloaded!???
  const [exportNotification, setExportNotification] = useState<string | null>(null);

  // TECH: lastEventIdRef deduplicates SSE events by monotonic ID to avoid reprocessing on reconnect.
  // PLAIN: Remembers the latest progress update so we don???t apply the same update twice.
  const lastEventIdRef = useRef<number>(0);

  // TECH: debounceRef is used to throttle rapid SSE updates to reduce re-renders.
  // PLAIN: Prevents the screen from updating too rapidly and looking jittery.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // TECH: runStatusCheckRef throttles status lookups when SSE drops.
  // PLAIN: Avoids repeatedly polling the server if the stream fails.
  const runStatusCheckRef = useRef<number>(0);

  // TECH: messagesEndRef points to a dummy element at bottom of chat to scroll into view.
  // PLAIN: Helps auto-scroll the chat to the newest message.
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // TECH: initialMessage can be passed through navigation state to auto-send a first message.
  // PLAIN: Sometimes we arrive here with a message already chosen to send.
  const initialMessage = useMemo(() => {
    // TECH: location.state can be null/unknown type; guard before reading properties.
    // PLAIN: Make sure the extra data exists before using it.
    if (!location.state || typeof location.state !== "object") return null;

    // TECH: Type assertion to expected shape from navigation.
    // PLAIN: Treat the state like it might contain an initial message.
    const state = location.state as { initialMessage?: string };

    // TECH: Return string or null if missing.
    // PLAIN: Use it if present; otherwise there is no initial message.
    return state.initialMessage ?? null;
  }, [location.state]);

  // TECH: Prevents sending initial message multiple times (React effects can run more than once in dev).
  // PLAIN: Makes sure the auto-message is only sent once.
  const initialMessageSentRef = useRef(false);

  // TECH: Find the current chat object from the conversations list.
  // PLAIN: From all chats, pick the one matching the URL.
  const chat = useMemo(() => {
    const items = conversations.data?.items ?? [];
    return items.find((item) => item.id === chatId) ?? null;
  }, [conversations.data, chatId]);

  // TECH: Flatten paginated pages into one list for rendering.
  // PLAIN: Turn pages into a single message list.
  const messages = flattenInfiniteMessages(messagesQuery.data);

  // TECH: Build topbar actions for share/export.
  // PLAIN: Put Share and Export buttons in the header.
  const topbarActions = useMemo(
    () => (
      <div className="flex items-center gap-2">
        <Button
          type="button"
          onClick={() => setShowShareModal(true)}
          disabled={report.sections.length === 0}
        >
          Share
        </Button>
        <Button
          type="button"
          onClick={() => setShowExportModal(true)}
          disabled={report.sections.length === 0}
        >
          Export
        </Button>
      </div>
    ),
    [report.sections.length, setShowExportModal, setShowShareModal]
  );

  // TECH: Sync topbar actions when report state changes.
  // PLAIN: Keep header buttons in sync with this chat.
  useEffect(() => {
    setTopbarActions(topbarActions);
  }, [setTopbarActions, topbarActions]);

  // TECH: Clear topbar actions when leaving this page.
  // PLAIN: Remove chat-specific buttons on navigation.
  useEffect(() => () => setTopbarActions(null), [setTopbarActions]);

  // TECH: Restore saved report whenever the conversation changes.
  // PLAIN: When you open a chat, bring back its last report.
  useEffect(() => {
    if (!chatId) {
      reportChatIdRef.current = null;
      setReport(EMPTY_REPORT);
      return;
    }

    const stored = loadStoredReport(chatId);
    reportChatIdRef.current = chatId;
    setReport(stored ?? EMPTY_REPORT);
  }, [chatId]);

  // TECH: Persist report updates so reopening the chat shows the latest report.
  // PLAIN: Save report changes automatically.
  useEffect(() => {
    if (!chatId) return;
    if (reportChatIdRef.current !== chatId) return;
    persistReport(chatId, report);
  }, [chatId, report]);

  // TECH: Effect to auto-send initialMessage once when page loads with that state.
  // PLAIN: If we arrived with a pre-filled message, send it automatically.
  useEffect(() => {
    // TECH: Only run when initialMessage exists, chatId exists, and not already sent.
    // PLAIN: Only send once, and only if we actually have a message and a chat.
    if (!initialMessage || !chatId || initialMessageSentRef.current) return;

    // TECH: Mark sent before awaiting to avoid double-send due to re-renders.
    // PLAIN: Lock it immediately so it doesn???t send twice.
    initialMessageSentRef.current = true;

    // TECH: Fire-and-forget sendMessage; catch errors to avoid unhandled promise rejection.
    // PLAIN: Send it in the background; ignore failures here.
    void sendMessage(initialMessage).catch(() => {});

    // TECH: Clear navigation state so refresh/back doesn't re-send.
    // PLAIN: Remove the "auto send" flag after first use.
    navigate(location.pathname, { replace: true, state: {} });
  }, [initialMessage, chatId, location.pathname, navigate]);

  // Scroll to bottom when messages change
  // TECH: Auto-scroll chat window when a new message arrives (messages.length changes).
  // PLAIN: Keep the newest message visible automatically.
  useEffect(() => {
    // TECH: Use ref to scroll to the sentinel element at bottom.
    // PLAIN: Scroll to the invisible ???bottom marker.???
    const node = messagesEndRef.current;
    if (node && typeof node.scrollIntoView === "function") {
      node.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length]);

  // TECH: Setup SSE stream only when there is an activeRun; URL is run-specific.
  // PLAIN: Listen for live progress updates only while a report job is running.
  const sseEnabled = Boolean(activeRun?.runId && activeRun.status === "running");
  const sse = useSSE(
    activeRun?.runId ? `/runs/${encodeURIComponent(activeRun.runId)}/events` : null,
    sseEnabled
  );

  // TECH: Apply incoming SSE events to update activeRun UI and detect terminal status.
  // PLAIN: Update the ???progress banner??? as new updates arrive.
  useEffect(() => {
    // TECH: If no active run, there???s nothing to update.
    // PLAIN: If no job is running, ignore streaming updates.
    if (!activeRun) return;

    // TECH: If there are no SSE events yet, nothing to do.
    // PLAIN: If we haven???t received updates, don???t change anything.
    if (sse.events.length === 0) return;

    // TECH: Filter events to only those with ID greater than last processed to avoid duplicates.
    // PLAIN: Only handle brand new updates.
    const fresh = sse.events.filter((evt) => {
      // TECH: SSE hook includes an id field; default to 0 if missing.
      // PLAIN: Each update may have an identifier; use it if available.
      const idValue = (evt as { id?: number }).id ?? 0;

      // TECH: Skip events that were already applied.
      // PLAIN: Ignore repeats.
      if (idValue <= lastEventIdRef.current) return false;

      // TECH: Update last seen ID; ensures monotonic progress.
      // PLAIN: Remember the newest update number.
      lastEventIdRef.current = Math.max(lastEventIdRef.current, idValue);
      return true;
    });

    // TECH: If nothing fresh, stop.
    // PLAIN: If no new updates, do nothing.
    if (fresh.length === 0) return;

    // TECH: terminal indicates run ended; stored after scanning events.
    // PLAIN: Track if the job finished (success/fail/canceled).
    let terminal: ActiveRunStatus | null = null;

    // TECH: Preserve an error message if failure occurs.
    // PLAIN: Keep the reason if something went wrong.
    let terminalError: string | undefined;

    // TECH: nextPrimary/nextSecondary store the latest non-terminal status text.
    // PLAIN: Keep the newest progress message to display.
    let nextPrimary: string | undefined;
    let nextSecondary: string | undefined;

    // TECH: Process events in order, allowing later messages to override earlier ones.
    // PLAIN: Read each update and keep the most recent message.
    for (const evt of fresh) {
      const { status, primaryText, secondaryText } = deriveRunUpdate(evt);

      // TECH: Terminal statuses stop the run and trigger completion handling.
      // PLAIN: If the job is finished, we stop showing ???working.???
      if (status && ["succeeded", "failed", "canceled"].includes(status)) {
        terminal = status as ActiveRunStatus;

        // TECH: Capture error message from event for failed state.
        // PLAIN: Save the error text so we can show it.
        if (status === "failed") {
          terminalError = typeof evt.message === "string" ? evt.message : undefined;
        }
      } else {
        // TECH: For non-terminal updates, keep the most recent readable text.
        // PLAIN: Otherwise, update the progress message.
        nextPrimary = primaryText;
        nextSecondary = secondaryText;
      }
    }

    // TECH: Handle terminal state first so we don't show stale "running" UI.
    // PLAIN: If it finished, show the final status.
    if (terminal) {
      if (terminal === "failed") {
        // TECH: Fetch the run record to show the concrete failure reason.
        // PLAIN: Ask the server why it failed so the UI can show the real error.
        void hydrateRunFailure(activeRun.runId, terminalError);
      } else {
        // TECH: For succeeded/canceled, complete run flow (fetch artifacts, update report, cleanup).
        // PLAIN: If it finished successfully, add results to the report; if canceled, stop.
        void handleRunCompletion(terminal);
      }
      return;
    }

    // TECH: If no status message updates, do nothing.
    // PLAIN: If there???s no new text to show, leave it as is.
    if (!nextPrimary) return;

    // TECH: Debounce updates so high-frequency SSE doesn't cause excessive re-renders.
    // PLAIN: Prevent too many quick screen updates.
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              primaryText: nextPrimary ?? prev.primaryText,
              secondaryText: nextSecondary ?? prev.secondaryText,
              status: "running"
            }
          : prev
      );
    }, 120);
  }, [activeRun, sse.events]);

  // TECH: If SSE drops, check run status so the UI doesn't hang.
  // PLAIN: When live updates fail, ask the server if the run ended and show the error.
  useEffect(() => {
    if (!activeRun || activeRun.status !== "running") return;
    if (sse.state !== "error" && sse.state !== "closed") return;

    const now = Date.now();
    if (now - runStatusCheckRef.current < 2000) return;
    runStatusCheckRef.current = now;

    void hydrateRunFailure(activeRun.runId, sse.lastError ?? undefined);
  }, [activeRun, sse.state, sse.lastError]);

  // TECH (Function Summary): Handles end-of-run logic: fetches artifacts, parses markdown, updates report, resets run state.
  // PLAIN (Function Summary): When the job finishes, it grabs the final result and adds it into the report view.
  async function handleRunCompletion(status: ActiveRunStatus) {
    // TECH: Must have an activeRun to know runId.
    // PLAIN: If there???s no job, there???s nothing to finish.
    if (!activeRun) return;

    // TECH: Cache runId because activeRun might change during awaits.
    // PLAIN: Save the job ID so we keep using the same one.
    const runId = activeRun.runId;

    // TECH: If canceled, clear UI and reset event tracking.
    // PLAIN: If the user stopped it, remove the progress banner.
    if (status === "canceled") {
      setActiveRun(null);
      lastEventIdRef.current = 0;
      return;
    }

    // TECH: On success, fetch artifacts for this run from the server.
    // PLAIN: If it finished, download the result files from the system.
    if (status === "succeeded") {
      // TECH: API call expects Artifact[] response; schema validation protects against malformed data.
      // PLAIN: Ask the server for the run???s outputs, and make sure they look correct.
      const artifacts = await apiFetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`, {
        schema: ArtifactsSchema
      }).catch(() => [] as Artifact[]);

      // TECH: Build final response text from artifact metadata.
      // PLAIN: Pick the best text output to show in the report.
      const response = buildFinalResponse(artifacts);

      // Add sections to the report based on the response
      // TECH: Parse markdown into structured sections so the right panel can render consistently.
      // PLAIN: Convert the text into organized report sections.
      if (response && response !== "Run completed. Output is available in artifacts.") {
        const parsedSections = parseMarkdownToSections(response);

        // TECH: Only update report if parser produced sections with content.
        // PLAIN: Only add something if we actually got useful sections.
        if (parsedSections.length > 0) {
          // TECH: Append sections to existing report, preserving previous content.
          // PLAIN: Add new sections without deleting the old ones.
          setReport((prev) => ({
            ...prev,
            sections: [...prev.sections, ...parsedSections]
          }));

          // TECH: Highlight first newly inserted section for UX ???new content??? indication.
          // PLAIN: Briefly highlight the new section so you can spot it.
          const firstSection = parsedSections[0];
          if (firstSection) {
            setHighlightedSection(firstSection.id);
            setTimeout(() => setHighlightedSection(null), 2000);
          }
        }
      }
    }

    // TECH: Cleanup: clear active run and reset last event id so next run starts clean.
    // PLAIN: Reset the ???job running??? state so the UI goes back to normal.
    setActiveRun(null);
    lastEventIdRef.current = 0;
  }

  // TECH (Function Summary): Fetch run status and surface failures immediately in the UI.
  // PLAIN (Function Summary): Ask the server why the run failed and show that reason.
  async function hydrateRunFailure(runId: string, fallbackError?: string) {
    const run = await apiFetchJson(`/runs/${encodeURIComponent(runId)}`, {
      schema: RunSchema
    }).catch(() => null as Run | null);

    if (!run) {
      if (fallbackError) {
        setActiveRun((prev) =>
          prev
            ? {
                ...prev,
                status: "failed",
                primaryText: "Something went wrong",
                secondaryText: fallbackError,
                error: fallbackError
              }
            : prev
        );
      }
      return;
    }

    if (run.status === "failed") {
      const message = run.error_message ?? fallbackError ?? "The run failed.";
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              status: "failed",
              primaryText: "Something went wrong",
              secondaryText: message,
              error: message
            }
          : prev
      );
      return;
    }

    if (run.status === "succeeded" || run.status === "canceled") {
      void handleRunCompletion(run.status as ActiveRunStatus);
      return;
    }

    if (fallbackError) {
      setActiveRun((prev) =>
        prev
          ? {
              ...prev,
              secondaryText: fallbackError
            }
          : prev
      );
    }
  }

  // TECH (Function Summary): Sends a user message to backend, starts run tracking if assistant responds with run_started.
  // PLAIN (Function Summary): Sends the chat message and starts tracking the report job if one begins.
  async function sendMessage(text: string) {
    // TECH: Trim whitespace to avoid sending empty messages.
    // PLAIN: Don???t send blank messages.
    const trimmed = text.trim();
    if (!trimmed || !chatId) return;
    const isAction = trimmed.startsWith("__ACTION__:");
    const modelValue =
      selectedModel === CUSTOM_MODEL_VALUE ? customModel.trim() : selectedModel.trim();

    // TECH: Toggle typing state to show indicator and disable actions.
    // PLAIN: Show that the system is working on your message.
    setIsTyping(true);

    try {
      // TECH: Send message to backend via mutation. Expected response includes assistant_message.
      // PLAIN: Ask the server to process the message and produce a reply.
      const response = await sendChat.mutateAsync({
        conversation_id: chatId,
        project_id: id || undefined,
        message: trimmed,

        // TECH: Client message ID supports idempotency and reconciliation in distributed systems.
        // PLAIN: A unique ID helps prevent duplicates and improves tracking.
        client_message_id: generateClientMessageId(),

        // TECH: Specify provider and model; allows backend to route to hosted LLM.
        // PLAIN: Tell the system which AI model to use.
        llm_provider: "hosted",
        llm_model: modelValue ? modelValue : undefined,
        force_pipeline: runPipelineArmed && !isAction
      });

      // TECH: Assistant message can be a special type indicating a background run started.
      // PLAIN: The assistant might start a longer job to generate a report.
      const assistant = response.assistant_message;

      if (assistant?.type === "run_started") {
        // TECH: run_id is stored in content_json; validate it???s a string.
        // PLAIN: Get the job ID if one was created.
        const runId = assistant.content_json?.["run_id"];
        if (typeof runId === "string") {
          // TECH: Set activeRun so SSE starts and banner appears.
          // PLAIN: Show the ???job running??? indicator and start listening for progress.
          setActiveRun({
            runId,
            status: "running",
            primaryText: "Starting run...",
            startedAt: new Date().toISOString()
          });

          // TECH: Reset event ID tracking so we handle new run events from start.
          // PLAIN: Start progress tracking from zero for this new job.
          lastEventIdRef.current = 0;
        }
      }

    } finally {
      // TECH: Always clear typing indicator even if request fails.
      // PLAIN: Stop showing ???typing??? no matter what happens.
      setIsTyping(false);
    }
  }

  // TECH (Function Summary): Sends current draft message; clears draft on success; preserves draft on failure.
  // PLAIN (Function Summary): Sends what you typed, and clears the box if it worked.
  async function onSend() {
    // TECH: Trim to prevent whitespace-only messages.
    // PLAIN: Don???t send empty messages.
    const text = draft.trim();
    if (!text) return;

    try {
      // TECH: Await sendMessage so we know when it's done.
      // PLAIN: Send it and wait for the server to accept it.
      await sendMessage(text);

      // TECH: Clear input after successful send for UX.
      // PLAIN: Empty the text box after sending.
      setDraft("");
    } catch {
      // TECH: Intentionally keep draft for retry; swallowing error avoids UI crash.
      // PLAIN: If it fails, keep your message so you can try again.
    }
  }

  // TECH (Function Summary): Requests canceling the current run; updates banner status.
  // PLAIN (Function Summary): Stops the report job if it???s running.
  async function onAnswerNow() {
    // TECH: Only possible if a run exists.
    // PLAIN: If there???s no job running, there???s nothing to stop.
    if (!activeRun) return;

    try {
      // TECH: Cancel mutation triggers backend to stop work (best-effort).
      // PLAIN: Tell the server to stop generating the report.
      await cancelRun.mutateAsync();

      // TECH: Optimistically update banner to ???stopping??? for immediate feedback.
      // PLAIN: Immediately show ???stopping??? so the user sees something happen.
      setActiveRun((prev) => (prev ? { ...prev, primaryText: "Stopping run..." } : prev));
    } catch {
      // TECH: If cancel fails, clear run state anyway to unblock UI.
      // PLAIN: If stopping doesn???t work, remove the banner so the UI isn???t stuck.
      setActiveRun(null);
    }
  }

  // TECH (Function Summary): Retries the current run using retry mutation and resets banner text.
  // PLAIN (Function Summary): Tries the report job again if it failed.
  async function onRetry() {
    // TECH: Only retry when we have a run ID.
    // PLAIN: Can only retry if a job exists.
    if (!activeRun) return;

    try {
      // TECH: Ask backend to restart or re-queue the run.
      // PLAIN: Tell the server to try again.
      await retryRun.mutateAsync();

      // TECH: Reset UI state to running.
      // PLAIN: Show that the job is working again.
      setActiveRun((prev) =>
        prev ? { ...prev, status: "running", primaryText: "Retrying run", secondaryText: undefined } : prev
      );
    } catch {
      // TECH: no-op to avoid surfacing errors here; banner remains.
      // PLAIN: If retry fails, do nothing extra.
    }
  }

  // TECH (Function Summary): Updates the report by replacing the matching section with new plain text content.
  // PLAIN (Function Summary): Saves edits made to a specific report section.
  function handleSectionEdit(sectionId: string, newContent: string) {
    // TECH: Immutable update to preserve React state patterns; map replaces only the targeted section.
    // PLAIN: Update only the one section that was edited, leaving the rest unchanged.
    setReport((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, content: [{ text: newContent }] } : s))
    }));
  }

  // TECH (Function Summary): Clears the report after confirmation.
  // PLAIN (Function Summary): Deletes the report text from the right panel (with a safety prompt).
  function handleClear() {
    // TECH: window.confirm prevents accidental destructive action.
    // PLAIN: Ask ???are you sure???? before deleting content.
    if (window.confirm("Are you sure you want to clear the report?")) {
      setReport(EMPTY_REPORT);
      if (chatId) {
        try {
          window.localStorage.removeItem(reportStorageKey(chatId));
        } catch {
          // ignore storage failures
        }
      }
    }
  }

  // TECH (Function Summary): Handles export flow for multiple formats and shows notifications for progress/errors.
  // PLAIN (Function Summary): Downloads the report in the chosen format and shows a message about it.
  async function handleExport(format: string) {
    // TECH: Close modal immediately to return focus to main UI.
    // PLAIN: Hide the popup as soon as you choose an option.
    setShowExportModal(false);

    // TECH: Show progress toast message.
    // PLAIN: Tell the user export has started.
    setExportNotification(`Exporting as ${format.toUpperCase()}...`);

    try {
      // TECH: Build export filename using report title; omit extension for reuse.
      // PLAIN: Use the report???s title as the file name.
      const filename = `${report.title || "report"}`;

      // TECH: Branch by format; some are synchronous string generation, others are async binary creation.
      // PLAIN: Different file types are created in different ways.
      if (format === "md") {
        const content = generateMarkdown(report);
        downloadText(content, `${filename}.md`, "text/markdown");
      } else if (format === "html") {
        const content = generateHTML(report);
        downloadText(content, `${filename}.html`, "text/html");
      } else if (format === "pdf") {
        await generatePDF(report, filename);
      } else if (format === "docx") {
        await generateWord(report, filename);
      }

      // TECH: Success toast; auto-clear after 2 seconds.
      // PLAIN: Tell the user the download completed.
      setExportNotification(`Report downloaded as ${format.toUpperCase()}`);
      setTimeout(() => setExportNotification(null), 2000);
    } catch (error) {
      // TECH: Error toast includes error.message when available; auto-clear after 3 seconds.
      // PLAIN: If export failed, show why (if we know).
      setExportNotification(`Export failed: ${error instanceof Error ? error.message : "Unknown error"}`);
      setTimeout(() => setExportNotification(null), 3000);
    }
  }

  // TECH (Function Summary): Downloads a string as a file using Blob + object URL + temporary <a> click.
  // PLAIN (Function Summary): Turns text into a downloadable file and saves it to your computer.
  function downloadText(content: string, filename: string, mimeType: string) {
    // TECH: Blob wraps raw content with MIME type so the browser knows what it is.
    // PLAIN: Package the text into a real ???file-like??? object.
    const blob = new Blob([content], { type: mimeType });

    // TECH: Object URL provides a temporary local URL pointing to the Blob data.
    // PLAIN: Create a temporary link that points to the file data.
    const url = URL.createObjectURL(blob);

    // TECH: Create hidden anchor to trigger native download.
    // PLAIN: Make a temporary download link.
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;

    // TECH: Must be in DOM for some browsers to allow click download.
    // PLAIN: Some browsers require the link to be on the page.
    document.body.appendChild(a);
    a.click();

    // TECH: Cleanup anchor node after click.
    // PLAIN: Remove the temporary link.
    document.body.removeChild(a);

    // TECH: Revoke object URL to avoid memory leaks.
    // PLAIN: Free up memory after the download is started.
    URL.revokeObjectURL(url);
  }

  // TECH (Function Summary): Generates and downloads a PDF version of the report using jsPDF.
  // PLAIN (Function Summary): Creates a PDF file and downloads it.
  async function generatePDF(report: Report, filename: string) {
    // TECH: Create PDF document instance in memory.
    // PLAIN: Start a new blank PDF.
    const doc = new jsPDF();

    // TECH: Measure page dimensions for layout calculations.
    // PLAIN: Find out how big the PDF page is so text fits.
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();

    // TECH: Margin and width constraints for line wrapping.
    // PLAIN: Leave space around the edges so it looks clean.
    const margin = 20;
    const maxWidth = pageWidth - 2 * margin;

    // TECH: yPosition tracks current vertical cursor on page.
    // PLAIN: Keep track of where we are writing on the page.
    let yPosition = margin;

    // Title
    // TECH: Use larger bold font for report title.
    // PLAIN: Make the title big and bold.
    doc.setFontSize(20);
    doc.setFont("helvetica", "bold");
    doc.text(report.title, margin, yPosition);
    yPosition += 15;

    // Sections
    // TECH: Use smaller font for body; each section heading in bold.
    // PLAIN: Write section headings and content in a readable size.
    doc.setFontSize(11);

    report.sections.forEach((section) => {
      // TECH: Page break if near bottom before writing new section heading.
      // PLAIN: If we???re near the bottom, start a new page.
      if (yPosition > pageHeight - 30) {
        doc.addPage();
        yPosition = margin;
      }

      // TECH: Section heading style.
      // PLAIN: Section titles stand out.
      doc.setFont("helvetica", "bold");
      doc.setFontSize(14);
      doc.text(section.heading, margin, yPosition);
      yPosition += 10;

      // TECH: Reset font to normal for section body.
      // PLAIN: Body text should be normal, not bold.
      doc.setFont("helvetica", "normal");
      doc.setFontSize(11);

      section.content.forEach((item) => {
        // TECH: Start with the base text content.
        // PLAIN: Begin with the main sentence.
        let text = item.text;

        // TECH: Append citations as bracket markers; joins without spaces like [1][2].
        // PLAIN: Add citation numbers to the end so sources are visible.
        if (item.citations && item.citations.length > 0) {
          text += ` ${item.citations.map((c) => `[${c}]`).join("")}`;
        }

        // TECH: Render bullets with a leading bullet character.
        // PLAIN: Put a bullet dot in front of list items.
        if (item.isBullet) {
          text = `??? ${text}`;
        }

        // TECH: splitTextToSize handles line wrapping within maxWidth.
        // PLAIN: Break long sentences into lines that fit the page.
        const lines = doc.splitTextToSize(text, maxWidth);

        // TECH: Set line height for vertical spacing.
        // PLAIN: Decide how far apart each line should be.
        const lineHeight = 7;

        // TECH: Compute total height of this block.
        // PLAIN: Calculate how much space this paragraph will take.
        const totalHeight = lines.length * lineHeight;

        // TECH: Page break if this block would overflow bottom margin.
        // PLAIN: Start a new page if the text won???t fit here.
        if (yPosition + totalHeight > pageHeight - margin) {
          doc.addPage();
          yPosition = margin;
        }

        // TECH: Write each wrapped line and advance yPosition.
        // PLAIN: Draw the text line by line.
        lines.forEach((line: string) => {
          doc.text(line, margin, yPosition);
          yPosition += lineHeight;
        });

        // TECH: Add a small gap after each item.
        // PLAIN: Add a little spacing between paragraphs/bullets.
        yPosition += 3;
      });

      // TECH: Add extra spacing between sections.
      // PLAIN: Leave space before the next section.
      yPosition += 5;
    });

    // TECH: Trigger browser download with filename.
    // PLAIN: Save the PDF to your computer.
    doc.save(`${filename}.pdf`);
  }

  // TECH (Function Summary): Generates and downloads a Word document (.docx) version of the report using docx.
  // PLAIN (Function Summary): Creates a Word file of the report and downloads it.
  async function generateWord(report: Report, filename: string) {
    // TECH: Word document content is built from an array of Paragraph objects.
    // PLAIN: Build the Word file one paragraph at a time.
    const children: Paragraph[] = [];

    // TECH: Add title as Heading 1 with spacing after.
    // PLAIN: Put the report title at the top in a big heading style.
    children.push(
      new Paragraph({
        text: report.title,
        heading: HeadingLevel.HEADING_1,
        spacing: { after: 200 }
      })
    );

    // TECH: For each section, add Heading 2 and then content paragraphs/bullets.
    // PLAIN: Add section titles and their text beneath them.
    report.sections.forEach((section) => {
      children.push(
        new Paragraph({
          text: section.heading,
          heading: HeadingLevel.HEADING_2,
          spacing: { before: 200, after: 100 }
        })
      );

      section.content.forEach((item) => {
        // TECH: TextRuns represent segments of styled text within a paragraph.
        // PLAIN: A paragraph can contain multiple pieces of text with different styles.
        const runs: TextRun[] = [new TextRun(item.text)];

        // TECH: Append citations as superscript in green color for readability.
        // PLAIN: Show citation numbers slightly above the line like footnotes.
        if (item.citations && item.citations.length > 0) {
          runs.push(
            new TextRun({
              text: ` ${item.citations.map((c) => `[${c}]`).join("")}`,
              superScript: true,
              color: "10b981"
            })
          );
        }

        // TECH: bullet property makes Word render it as a bulleted list item.
        // PLAIN: If it???s a list item, show it as a bullet in Word.
        children.push(
          new Paragraph({
            children: runs,
            bullet: item.isBullet ? { level: 0 } : undefined,
            spacing: { after: 120 }
          })
        );
      });
    });

    // TECH: Create a Document object with a single section containing all paragraphs.
    // PLAIN: Assemble everything into one Word document.
    const doc = new Document({
      sections: [
        {
          properties: {},
          children
        }
      ]
    });

    // TECH: Convert document to Blob for download.
    // PLAIN: Turn the Word document into a downloadable file.
    const blob = await Packer.toBlob(doc);

    // TECH: file-saver triggers download with chosen filename.
    // PLAIN: Save the Word file to your computer.
    saveAs(blob, `${filename}.docx`);
  }

  // TECH (Function Summary): Converts report structure into Markdown text for exporting.
  // PLAIN (Function Summary): Turns the report into a plain text format that keeps headings and bullets.
  function generateMarkdown(report: Report): string {
    // TECH: Start with top-level markdown title.
    // PLAIN: Begin with the report title.
    let md = `# ${report.title}\n\n`;

    // TECH: Loop through sections and build markdown headings + items.
    // PLAIN: Add each section and its lines.
    report.sections.forEach((section) => {
      md += `## ${section.heading}\n\n`;
      section.content.forEach((item) => {
        // TECH: Bullets get "- " prefix; paragraphs do not.
        // PLAIN: Add a dash for bullet points.
        const prefix = item.isBullet ? "- " : "";

        // TECH: Base text content.
        // PLAIN: The sentence itself.
        let text = item.text;

        // TECH: Append citations as markdown bracket markers.
        // PLAIN: Add citation numbers at the end.
        if (item.citations && item.citations.length > 0) {
          const citationStr = item.citations.map((c) => `[${c}]`).join("");
          text += citationStr;
        }

        // TECH: Add spacing between items using blank line.
        // PLAIN: Leave an empty line so it reads nicely.
        md += `${prefix}${text}\n\n`;
      });
    });

    // TECH: Return full markdown document.
    // PLAIN: Give back the completed markdown text.
    return md;
  }

  // TECH (Function Summary): Converts report structure into a standalone HTML document string for exporting.
  // PLAIN (Function Summary): Creates a webpage version of the report you can open in a browser.
  function generateHTML(report: Report): string {
    // TECH WARNING: This function inserts report text directly into HTML without escaping, which can enable XSS if report content is untrusted.
    // PLAIN WARNING: If the report contains unsafe text, it could cause problems when opened as a webpage.
    let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${report.title}</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem;
      line-height: 1.6;
        color: #e0dde6;
      }
      h1 {
        color: #e0dde6;
        border-bottom: 2px solid #9580c4;
        padding-bottom: 0.5rem;
      }
      h2 {
        color: #8a8694;
        margin-top: 2rem;
      }
    p {
      margin: 1rem 0;
    }
    ul {
      margin: 1rem 0;
    }
    li {
      margin: 0.5rem 0;
    }
      sup {
        color: #9580c4;
        font-weight: 600;
      }
  </style>
</head>
<body>
  <h1>${report.title}</h1>
`;

    // TECH: Add each section to HTML with <h2> heading.
    // PLAIN: Add each section title to the webpage.
    report.sections.forEach((section) => {
      html += `  <h2>${section.heading}</h2>\n`;

      // TECH: Detect if any items are bullets to wrap them in a single <ul>.
      // PLAIN: If there are bullet points, we use a list.
      const hasBullets = section.content.some((item) => item.isBullet);
      if (hasBullets) {
        html += "  <ul>\n";
      }

      section.content.forEach((item) => {
        // TECH: Base text content.
        // PLAIN: The line of text to display.
        let text = item.text;

        // TECH: Citations rendered as <sup> markers.
        // PLAIN: Show citation numbers as small superscript numbers.
        if (item.citations && item.citations.length > 0) {
          const citationStr = item.citations.map((c) => `<sup>${c}</sup>`).join("");
          text += citationStr;
        }

        // TECH: Render bullet items as <li>, others as <p>; toggles <ul> boundaries when mixing.
        // PLAIN: Bullets become list items, normal lines become paragraphs.
        if (item.isBullet) {
          html += `    <li>${text}</li>\n`;
        } else {
          if (hasBullets) {
            html += "  </ul>\n";
          }
          html += `  <p>${text}</p>\n`;
          if (hasBullets) {
            html += "  <ul>\n";
          }
        }
      });

      // TECH: Close list if bullets were opened.
      // PLAIN: Finish the list section neatly.
      if (hasBullets) {
        html += "  </ul>\n";
      }
    });

    // TECH: Close HTML document.
    // PLAIN: Finish the webpage.
    html += `</body>
</html>`;

    return html;
  }

  // TECH: Loading state for project query; show spinner to avoid rendering incomplete UI.
  // PLAIN: While the project is loading, show a loading indicator.
  if (project.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading..." />
      </div>
    );
  }

  // TECH: Error state for project query; show error banner with message.
  // PLAIN: If the project can???t load, show an error message.
  if (project.isError) {
    return <ErrorBanner message={project.error instanceof Error ? project.error.message : "Failed to load project"} />;
  }

  // TECH: Extract loaded project data.
  // PLAIN: Get the project info we loaded.
  const p = project.data;
  if (!p) return null;

  // TECH: Loading state for conversations; show spinner until chat list is available.
  // PLAIN: While chats are loading, show a loading indicator.
  if (conversations.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading conversation..." />
      </div>
    );
  }

  // TECH: If chatId is not found in conversations list, show fallback UI.
  // PLAIN: If the chat doesn???t exist, show ???not found.???
  if (!chat) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-slate-400">Chat not found</div>
      </div>
    );
  }

  // TECH: Quick action presets that write into the draft input for convenience.
  // PLAIN: Shortcuts you can click to quickly ask common requests.
  const quickActions = ["Add conclusion", "Add recommendations", "Summarize findings", "Add references"];

  return (
    // TECH: Two-panel fixed layout; left is chat, right is report preview.
    // PLAIN: Split screen with chat on the left and report on the right.
    <div className="flex h-full min-h-0 bg-slate-950 text-slate-200">
      {/* Left Panel - Chat */}
      {/* TECH: Left panel is chat column with header, message list, quick actions, and input area. */}
      {/* PLAIN: This is where you talk to the assistant. */}
      <div className="flex w-[45%] min-h-0 flex-col border-r border-slate-800">
        {/* Chat Header */}
        {/* TECH: Header shows back navigation and chat/project metadata. */}
        {/* PLAIN: Top bar with a back button and the chat name. */}
        <div className="border-b border-slate-800 px-6 py-5">
          <div className="flex items-center gap-3">
            <button
              // TECH: Navigates back to the project page.
              // PLAIN: Takes you back to the project screen.
              type="button"
              onClick={() => navigate(`/projects/${id}`)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <h1 className="font-mono text-xl font-semibold text-slate-100">{chat.title}</h1>
              <p className="mt-1 text-sm text-slate-500">{p.name}</p>
            </div>
          </div>
        </div>

        {/* Messages */}
        {/* TECH: Scrollable message list; maps message DTOs to styled bubbles with special cases for offers/errors/run links. */}
        {/* PLAIN: All chat messages are shown here, like in a messaging app. */}
        <div className="flex-1 overflow-y-auto p-6">
          {messages.map((message) => {
            // TECH: Determine styling and behavior based on message role/type.
            // PLAIN: Decide how to display each message.
            const isUser = message.role === "user";
            const isOffer = message.type === "pipeline_offer";
            const isRunStarted = message.type === "run_started";
            const isError = message.type === "error";

            // TECH: Extract run ID for ???open run viewer??? link from run_started message JSON.
            // PLAIN: If a report job started, grab its ID so we can link to it.
            const runId = isRunStarted ? (message.content_json?.["run_id"] as string | undefined) : undefined;

            // TECH: Pipeline offer actions are stored in message.content_json.offer.actions.
            // PLAIN: Some messages include buttons with suggested actions.
            const offer = message.content_json?.["offer"];

            // TECH: Validate actions structure defensively (API shape can vary).
            // PLAIN: Only use action buttons if they are formatted correctly.
            const actions = Array.isArray((offer as { actions?: unknown[] } | undefined)?.actions)
              ? ((offer as { actions: Array<{ id?: string; label?: string }> }).actions ?? [])
              : [];

            return (
              <div key={message.id} className={`mb-4 flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                <div
                  // TECH: Bubble styling depends on user vs assistant vs error; also uses whitespace-pre-wrap to preserve newlines.
                  // PLAIN: The bubble looks different for you, the assistant, and errors.
                  className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-3.5 text-sm leading-relaxed ${
                    isUser
                      ? "rounded-br-sm border border-emerald-500/30 bg-emerald-500/15 text-slate-200"
                      : isError
                        ? "rounded-bl-sm border border-rose-500/40 bg-rose-500/10 text-rose-100"
                        : "rounded-bl-sm border border-slate-800 bg-slate-900 text-slate-200"
                  }`}
                >
                  {/* TECH: Render markdown for chat text; action messages use friendly labels. */}
                  {/* PLAIN: Show the message with formatting when possible. */}
                  {message.type === "action" ? (
                    <span>{displayMessageText(message)}</span>
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
                      {normalizeChatMarkdown(message.content_text)}
                    </ReactMarkdown>
                  )}

                  {/* TECH: If assistant started a run, show link to run viewer page. */}
                  {/* PLAIN: If a report job started, show a button to view its details. */}
                  {isRunStarted && runId ? (
                    <div className="mt-2">
                        <Link
                          to={`/runs/${encodeURIComponent(runId)}`}
                          className="inline-flex items-center gap-2 rounded-md border border-sky-500 bg-sky-500 px-2.5 py-1 text-xs text-slate-100 hover:bg-sky-500"
                        >
                        Open run viewer
                      </Link>
                    </div>
                  ) : null}
                </div>

                {/* TECH: Render action buttons for pipeline offers; clicking sends a special __ACTION__ message to backend. */}
                {/* PLAIN: Some assistant messages provide quick buttons you can click. */}
                {isOffer && actions.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {actions.map((action) => (
                      <button
                        key={action.id ?? action.label}
                        onClick={() => {
                          // TECH: Guard against missing action IDs to avoid sending invalid messages.
                          // PLAIN: If there???s no action code, do nothing.
                          if (!action.id) return;

                          // TECH: Send an encoded message; backend interprets __ACTION__ prefix as command.
                          // PLAIN: Send a special command message to trigger that action.
                          void sendMessage(`__ACTION__:${action.id}`);
                        }}
                        disabled={isTyping}
                        className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-200 transition-colors hover:border-emerald-500/60 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {action.label ?? formatActionLabel(action.id ?? null)}
                      </button>
                    ))}
                  </div>
                ) : null}

                {/* TECH: Timestamp rendering; uses locale formatting with 24-hour time and seconds. */}
                {/* PLAIN: Shows when each message was sent. */}
                <div className="mt-1.5 font-mono text-xs text-slate-500">
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                    hour12: false
                  })}
                </div>
              </div>
            );
          })}

          {/* TECH: Show typing indicator when a message is being sent/processed. */}
          {/* PLAIN: Animated dots show the system is working. */}
          {isTyping && (
            <div className="inline-block rounded-2xl rounded-bl-sm border border-slate-800 bg-slate-900 px-4 py-3.5">
              <TypingIndicator />
            </div>
          )}

          {/* TECH: If a run is active, show run status banner and action buttons based on status. */}
          {/* PLAIN: Show progress of the report generation and allow stopping/retrying. */}
          {activeRun && (
            <div className="mt-4">
              <RunThinkingBanner
                primaryText={activeRun.primaryText}
                secondaryText={activeRun.secondaryText}
                status={activeRun.status}
                onAnswerNow={activeRun.status === "running" ? onAnswerNow : undefined}
                onRetry={activeRun.status === "failed" ? onRetry : undefined}
              />
            </div>
          )}

          {/* TECH: Sentinel element to scrollIntoView for auto-scrolling. */}
          {/* PLAIN: Invisible marker at the bottom of the chat. */}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick Actions */}
        {/* TECH: Quick action chips fill the draft input for faster prompting. */}
        {/* PLAIN: Click a suggestion to automatically fill the message box. */}
        <div className="flex flex-wrap gap-2 px-6 pb-3">
          {quickActions.map((action) => (
            <button
              key={action}
              // TECH: Set draft text to the selected action template.
              // PLAIN: Put this suggestion into the message box.
              onClick={() => setDraft(action)}
              className="rounded-full border border-slate-700 bg-slate-900 px-3.5 py-2 text-xs text-slate-400 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10 hover:text-emerald-400"
            >
              {action}
            </button>
          ))}
        </div>

        {/* Input */}
        {/* TECH: Input area with model selector and textarea; Enter sends, Shift+Enter creates newline. */}
        {/* PLAIN: Where you type your message and choose the AI model. */}
        <div className="border-t border-slate-800 px-6 py-4">
          <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-slate-400">
            <span>LLM model</span>
            <div className="flex flex-1 flex-wrap items-center gap-2">
              <select
                // TECH: Dropdown of known models; custom option opens manual input.
                // PLAIN: Pick a model from the list.
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="min-w-[220px] rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
              >
                {MODEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              {selectedModel === CUSTOM_MODEL_VALUE ? (
                <input
                  // TECH: Manual entry for custom model id.
                  // PLAIN: Type a model id if it's not in the list.
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder="Enter model id"
                  className="min-w-[220px] flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200 focus:border-emerald-500/50 focus:outline-none"
                />
              ) : null}
            </div>
            <button
              type="button"
              aria-pressed={runPipelineArmed}
              onClick={() => setRunPipelineArmed((prev) => !prev)}
              className={`rounded-full border px-3.5 py-2 text-xs transition-colors ${
                runPipelineArmed
                  ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-200"
                  : "border-slate-700 bg-slate-900 text-slate-400 hover:border-emerald-500/30 hover:text-emerald-300"
              }`}
            >
              Run research report
            </button>
          </div>

          <div className="flex items-end gap-3">
            <textarea
              // TECH: Controlled textarea stores current user draft; rows={1} with resize-none mimics chat input.
              // PLAIN: This is the message box where you type.
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // TECH: Enter submits; Shift+Enter inserts newline. Prevent default to avoid newline on send.
                // PLAIN: Press Enter to send; press Shift+Enter for a new line.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void onSend();
                }
              }}
              placeholder="Ask a question or request a report..."
              rows={1}
              className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900 px-4 py-3.5 text-sm text-slate-200 outline-none transition-colors focus:border-emerald-500/50"
            />
            <button
              // TECH: Click send triggers onSend; disabled unless valid draft and not busy.
              // PLAIN: Sends your message.
              onClick={() => void onSend()}
              disabled={!draft.trim() || isTyping}
              className={`flex h-12 w-12 items-center justify-center rounded-xl transition-colors ${
                draft.trim() && !isTyping
                  ? "bg-emerald-500 text-slate-900 hover:bg-emerald-400"
                  : "cursor-not-allowed bg-emerald-500/30 text-slate-500"
              }`}
            >
              <Send className="h-5 w-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Right Panel - Report */}
      {/* TECH: Right panel displays the live report and related actions (export/clear/share). */}
      {/* PLAIN: This is where your report appears and where you can download/share it. */}
      <div className="flex w-[55%] min-h-0 flex-col bg-slate-950">
        {/* Report Header */}
        {/* TECH: Shows report title and a status pill that reflects whether a run is active. */}
        {/* PLAIN: Top bar showing ???Live Report??? and whether it???s ready or processing. */}
        <div className="flex items-center justify-between border-b border-slate-800 px-8 py-5">
          <h2 className="font-mono text-xl font-semibold text-slate-100">Live Report</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-400">
              <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
              {activeRun ? "PROCESSING" : "READY"}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        {/* TECH: Report-level actions; disabled when report is empty to prevent meaningless exports/shares. */}
        {/* PLAIN: Buttons to download, clear, or share the report once it exists. */}
        <div className="flex gap-3 border-b border-slate-800 px-8 py-4">
          <button
            // TECH: Open export modal; disabled if no sections.
            // PLAIN: Choose how to download the report.
            onClick={() => setShowExportModal(true)}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Download className="h-4 w-4" />
            Export
          </button>
          <button
            // TECH: Clear report content; disabled if report is empty.
            // PLAIN: Delete the report text from the screen.
            onClick={handleClear}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
          <button
            // TECH: Open share modal; disabled if report is empty.
            // PLAIN: Show a share link for the report.
            onClick={() => setShowShareModal(true)}
            disabled={report.sections.length === 0}
            className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm font-medium text-slate-200 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-600"
          >
            <Share2 className="h-4 w-4" />
            Share
          </button>
          <div className="ml-auto">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-500">
              <Sparkles className="h-5 w-5" />
            </div>
          </div>
        </div>

        {/* Report Content */}
        {/* TECH: Conditional rendering shows empty-state when no report sections exist; otherwise renders each section. */}
        {/* PLAIN: If there???s no report yet, show a placeholder; otherwise show the report. */}
        <div className="flex-1 overflow-y-auto p-8">
          {report.sections.length === 0 ? (
            <div className="py-20 text-center text-slate-500">
              <div className="mb-4 text-5xl opacity-50">????</div>
              <p className="text-sm">Your report will appear here</p>
              <p className="mt-2 text-xs text-slate-600">Start a conversation to generate content</p>
            </div>
          ) : (
            report.sections.map((section) => (
              <ReportSectionView
                key={section.id}
                section={section}
                onEdit={handleSectionEdit}
                isHighlighted={highlightedSection === section.id}
              />
            ))
          )}
        </div>
      </div>

      {/* Modals */}
      {/* TECH: ExportModal and ShareModal are controlled components; rendered based on state booleans. */}
      {/* PLAIN: Popups that appear when needed. */}
      <ExportModal isOpen={showExportModal} onClose={() => setShowExportModal(false)} onExport={handleExport} />
      <ShareModal isOpen={showShareModal} onClose={() => setShowShareModal(false)} />

      {/* Export Notification */}
      {/* TECH: Toast notification shows export progress/result; disappears after timer in handleExport. */}
      {/* PLAIN: Small message popup in the corner about downloading status. */}
      {exportNotification && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2.5 rounded-xl border border-emerald-500/30 bg-slate-900 px-5 py-3.5 text-sm font-medium text-emerald-400 shadow-xl">
          <Download className="h-4 w-4" />
          {exportNotification}
        </div>
      )}
    </div>
  );
}



