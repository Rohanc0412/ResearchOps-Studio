import { generateId } from "./ids";
import type { ReportSection } from "../types";

export function extractInlineCitations(input: string): { text: string; citations: number[] } {
  const citations: number[] = [];
  const citationRegex = /\[(\d+)\]|\[\^(\d+)\]/g;

  const textWithoutCitations = input.replace(citationRegex, (_match, g1, g2) => {
    const numRaw = g1 ?? g2;
    const num = Number(numRaw);
    if (!Number.isNaN(num)) citations.push(num);
    return "";
  });

  const cleaned = textWithoutCitations
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1")
    .trim();

  const seen = new Set<number>();
  const uniq = citations.filter((n) => {
    if (seen.has(n)) return false;
    seen.add(n);
    return true;
  });

  return { text: cleaned, citations: uniq };
}

function isReferencesHeading(line: string): boolean {
  const normalized = line.trim().toLowerCase();
  return (
    normalized === "## references" ||
    normalized === "## reference" ||
    normalized === "## bibliography" ||
    normalized === "## citations"
  );
}

export function extractReportTitle(markdown: string): string | null {
  for (const line of markdown.replace(/\r\n/g, "\n").split("\n")) {
    const m = line.match(/^#\s+(.+)$/);
    if (m) return (m[1] ?? "").trim() || null;
  }
  return null;
}

export function parseMarkdownToSections(markdown: string): ReportSection[] {
  const sections: ReportSection[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  let currentSection: ReportSection | null = null;
  let paragraphBuffer: string[] = [];
  let lastFootnoteIndex: number | null = null;

  const ensureSection = (heading: string) => {
    if (!currentSection) {
      currentSection = {
        id: generateId(),
        heading,
        content: []
      };
    }
  };

  const pushSectionIfAny = () => {
    if (currentSection) {
      sections.push(currentSection);
      currentSection = null;
    }
  };

  const flushParagraph = () => {
    if (!currentSection || paragraphBuffer.length === 0) return;

    const rawText = paragraphBuffer.join(" ").trim();
    paragraphBuffer = [];
    lastFootnoteIndex = null;
    if (!rawText) return;

    const { text, citations } = extractInlineCitations(rawText);
    const finalText = text || rawText;
    if (!finalText) return;

    currentSection.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: false
    });
  };

  const pushBullet = (raw: string) => {
    ensureSection("Live Report");
    flushParagraph();

    const { text, citations } = extractInlineCitations(raw);
    const finalText = text || raw;
    currentSection!.content.push({
      text: finalText,
      citations: citations.length > 0 ? citations : undefined,
      isBullet: true
    });
    lastFootnoteIndex = null;
  };

  const pushReferenceFootnote = (num: number, content: string) => {
    ensureSection("References");
    flushParagraph();
    currentSection!.content.push({
      text: `[${num}] ${content}`.trim(),
      isBullet: true
    });
    lastFootnoteIndex = currentSection!.content.length - 1;
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    const headerMatch = line.match(/^(#{2,3})\s+(.+)$/);
    if (headerMatch) {
      flushParagraph();
      pushSectionIfAny();
      currentSection = {
        id: generateId(),
        heading: (headerMatch[2] ?? "").trim(),
        content: []
      };
      lastFootnoteIndex = null;
      continue;
    }

    if (/^#\s+/.test(line)) continue;

    if (isReferencesHeading(line) || line.trim() === "---") {
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

    if (line.trim() === "") {
      flushParagraph();
      continue;
    }

    const footnoteMatch = line.match(/^\[\^(\d+)\]:\s*(.*)$/);
    if (footnoteMatch) {
      pushReferenceFootnote(Number(footnoteMatch[1]), footnoteMatch[2] ?? "");
      continue;
    }

    if (lastFootnoteIndex !== null && /^\s{2,}\S+/.test(line)) {
      const extra = line.trim();
      const item = currentSection?.content[lastFootnoteIndex];
      if (item) item.text = `${item.text} ${extra}`.trim();
      continue;
    }

    const bulletMatch = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bulletMatch) {
      pushBullet(bulletMatch[1] ?? "");
      continue;
    }

    const numberedMatch = line.match(/^\s*\d+\.\s+(.*)$/);
    if (numberedMatch) {
      pushBullet(numberedMatch[1] ?? "");
      continue;
    }

    ensureSection("Live Report");
    paragraphBuffer.push(line.trim());
  }

  flushParagraph();
  pushSectionIfAny();
  return sections.filter((section) => section.content.length > 0);
}
