import type { Components } from "react-markdown";

import type { ChatMessage } from "../../../types/dto";

export function formatActionLabel(actionId: string | null) {
  if (!actionId) return "Action";
  if (actionId === "run_pipeline") return "Run research report";
  if (actionId === "quick_answer") return "Quick answer";
  return actionId.replace(/_/g, " ");
}

export function displayMessageText(message: ChatMessage) {
  if (message.type === "action") {
    const actionId =
      (message.content_json?.["action_id"] as string | undefined) ??
      message.content_text.replace("__ACTION__:", "").trim();
    return formatActionLabel(actionId || null);
  }

  return message.content_text;
}

export function normalizeChatMarkdown(input: string) {
  if (!input) return input;

  let normalized = input.replace(/\r\n/g, "\n");
  normalized = normalizeListMarkers(normalized);
  normalized = normalizeStandaloneTitles(normalized);
  normalized = normalizeOutlineMarkdown(normalized);

  return normalized
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n\s*\n(?=\s{0,3}(?:[*-]|\d+\.)\s)/g, "\n");
}

function normalizeListMarkers(input: string) {
  const lines = input.split("\n");
  const normalized: string[] = [];
  let insideFence = false;
  const unicodeBulletPattern = /^(\s*)[\u2022\u25CF\u25E6\u25AA\u2023\u00B7]\s+(.*)$/u;

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (trimmed.startsWith("```")) {
      insideFence = !insideFence;
      normalized.push(rawLine);
      continue;
    }

    if (insideFence) {
      normalized.push(rawLine);
      continue;
    }

    const bulletMatch = rawLine.match(unicodeBulletPattern);
    if (bulletMatch) {
      normalized.push(`${bulletMatch[1]}- ${bulletMatch[2]}`);
      continue;
    }

    const numericParenMatch = rawLine.match(/^(\s*)(\d+)\)\s+(.*)$/);
    if (numericParenMatch) {
      normalized.push(`${numericParenMatch[1]}${numericParenMatch[2]}. ${numericParenMatch[3]}`);
      continue;
    }

    normalized.push(rawLine);
  }

  return normalized.join("\n");
}

function normalizeStandaloneTitles(input: string) {
  const lines = input.split("\n");
  const normalized: string[] = [];
  let insideFence = false;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i] ?? "";
    const trimmed = rawLine.trim();

    if (trimmed.startsWith("```")) {
      insideFence = !insideFence;
      normalized.push(rawLine);
      continue;
    }

    if (
      insideFence ||
      !trimmed ||
      !trimmed.endsWith(":") ||
      isMarkdownBlock(trimmed) ||
      !isLikelyStandaloneTitle(trimmed, findNextNonEmptyLine(lines, i + 1))
    ) {
      normalized.push(rawLine);
      continue;
    }

    normalized.push(`### ${trimmed.slice(0, -1).trim()}`);
  }

  return normalized.join("\n");
}

function normalizeOutlineMarkdown(input: string) {
  const lines = input.split("\n");
  const normalized: string[] = [];
  let insideFence = false;
  let insideNumberedSection = false;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i] ?? "";
    const trimmed = rawLine.trim();

    if (trimmed.startsWith("```")) {
      insideFence = !insideFence;
      insideNumberedSection = false;
      normalized.push(rawLine);
      continue;
    }

    if (insideFence) {
      normalized.push(rawLine);
      continue;
    }

    if (isNumberedSectionHeader(trimmed)) {
      insideNumberedSection = true;
      normalized.push(normalizeNumberedHeader(trimmed));
      continue;
    }

    if (insideNumberedSection) {
      if (!trimmed) {
        normalized.push("");
        continue;
      }

      if (isTopLevelBoundary(trimmed, findNextNonEmptyLine(lines, i + 1))) {
        insideNumberedSection = false;
      } else if (/^[-*]\s+/.test(trimmed) || isContinuationLine(trimmed)) {
        normalized.push(`   ${trimmed}`);
        continue;
      } else {
        insideNumberedSection = false;
      }
    }

    normalized.push(rawLine);
  }

  return normalized.join("\n");
}

function findNextNonEmptyLine(lines: string[], startIndex: number) {
  for (let i = startIndex; i < lines.length; i++) {
    const trimmed = lines[i]?.trim();
    if (trimmed) return trimmed;
  }
  return null;
}

function isMarkdownBlock(line: string) {
  return (
    /^#{1,6}\s+/.test(line) ||
    /^>\s?/.test(line) ||
    /^[-*+]\s+/.test(line) ||
    /^\d+\.\s+/.test(line) ||
    /^```/.test(line) ||
    /^\|/.test(line) ||
    /^([-*_]){3,}\s*$/.test(line)
  );
}

function isLikelyStandaloneTitle(line: string, nextNonEmptyLine: string | null) {
  if (!nextNonEmptyLine) return false;
  if (line.length > 90) return false;
  if (/[,.!?;]$/.test(line)) return false;
  if (!/:\s*$/.test(line)) return false;
  if (!looksLikeTitleCase(line.slice(0, -1).trim())) return false;
  return isMarkdownBlock(nextNonEmptyLine) || isNumberedSectionHeader(nextNonEmptyLine);
}

function looksLikeTitleCase(value: string) {
  const words = value
    .split(/\s+/)
    .map((word) => word.replace(/^[("'`]+|[)"'`:.,]+$/g, ""))
    .filter(Boolean);

  if (words.length < 2 || words.length > 12) return false;

  const connectorWords = new Set([
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
    "with"
  ]);

  const significantWords = words.filter((word) => !connectorWords.has(word.toLowerCase()));
  if (significantWords.length === 0) return false;

  const titleCasedCount = significantWords.filter((word) => /^[A-Z0-9(]/.test(word)).length;
  return titleCasedCount / significantWords.length >= 0.6;
}

function isNumberedSectionHeader(line: string) {
  return /^\d+[.)]\s+.+:\s*$/.test(line.replace(/\*\*/g, ""));
}

function normalizeNumberedHeader(line: string) {
  return line.replace(/^(\d+)\)\s+/, "$1. ");
}

function isTopLevelBoundary(line: string, nextNonEmptyLine: string | null) {
  return (
    /^#{1,6}\s+/.test(line) ||
    /^>\s?/.test(line) ||
    /^```/.test(line) ||
    /^\|/.test(line) ||
    /^([-*_]){3,}\s*$/.test(line) ||
    isNumberedSectionHeader(line) ||
    isLikelyStandaloneTitle(line, nextNonEmptyLine)
  );
}

function isContinuationLine(line: string) {
  return !isMarkdownBlock(line);
}

export const chatMarkdownComponents: Components = {
  h1: ({ children }) => <h1 className="mb-1.5 text-base font-semibold text-slate-100">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-1.5 text-sm font-semibold text-slate-100">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1.5 text-sm font-medium text-slate-100">{children}</h3>,
  p: ({ children }) => <p className="mb-1.5 last:mb-0 leading-[1.5]">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 ml-5 list-disc space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 ml-5 list-decimal space-y-1">{children}</ol>,
  li: ({ children }) => (
    <li className="leading-[1.45] marker:text-slate-400 [&>p]:m-0 [&>p]:leading-[1.45] [&>ul]:mt-1 [&>ol]:mt-1">
      {children}
    </li>
  ),
  strong: ({ children }) => <strong className="font-semibold text-slate-100">{children}</strong>,
  em: ({ children }) => <em className="italic text-slate-200">{children}</em>,
  code: (props) => {
    const inline = "inline" in props ? Boolean((props as { inline?: boolean }).inline) : false;
    const { children } = props;

    return inline ? (
      <code className="rounded bg-slate-900 px-1 py-0.5 font-mono text-xs text-emerald-200">
        {children}
      </code>
    ) : (
      <code className="font-mono">{children}</code>
    );
  },
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
