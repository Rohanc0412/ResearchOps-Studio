import React from "react";
import {
  Document,
  Page,
  Text,
  View,
  StyleSheet,
  pdf,
} from "@react-pdf/renderer";
import { Document as DocxDocument, HeadingLevel, Packer, Paragraph, TextRun } from "docx";
import { saveAs } from "file-saver";

import type { Report, ReportSection } from "../types";

// ─── Palette ────────────────────────────────────────────────────────────────
const ACCENT   = "#9580c4";
const BANNER   = "#120d2a";
const BODY     = "#2a2448";
const MUTED    = "#7a6fa0";
const LIGHT    = "#f0ecff";
const HEADING  = "#1a1030";

// ─── Styles ─────────────────────────────────────────────────────────────────
const S = StyleSheet.create({
  page: {
    fontFamily: "Helvetica",
    backgroundColor: "#ffffff",
    paddingTop: 20,
    paddingBottom: 52,
  },

  // Banner
  bannerOuter: {
    backgroundColor: BANNER,
    borderBottomWidth: 3,
    borderBottomColor: ACCENT,
    marginTop: -20, // pull banner flush to page top edge on page 1
  },
  bannerAccent: {
    position: "absolute",
    top: 0,
    left: 0,
    bottom: 0,
    width: 5,
    backgroundColor: ACCENT,
  },
  bannerInner: {
    paddingLeft: 48,
    paddingRight: 40,
    paddingTop: 22,
    paddingBottom: 18,
  },
  bannerLabel: {
    fontSize: 7,
    fontFamily: "Helvetica-Bold",
    color: ACCENT,
    marginBottom: 7,
  },
  bannerTitle: {
    fontSize: 18,
    fontFamily: "Helvetica-Bold",
    color: LIGHT,
    lineHeight: 1.3,
    marginBottom: 10,
  },
  bannerDate: {
    fontSize: 8,
    color: MUTED,
  },

  // Content
  content: {
    paddingHorizontal: 40,
    paddingTop: 14,
  },

  // Section
  section: {
    marginBottom: 14,
  },
  sectionHeading: {
    fontSize: 13,
    fontFamily: "Helvetica-Bold",
    color: HEADING,
    marginBottom: 2,
  },
  headingRule: {
    borderBottomWidth: 0.6,
    borderBottomColor: ACCENT,
    marginBottom: 6,
  },

  // Body text
  paragraph: {
    fontSize: 10.5,
    color: BODY,
    lineHeight: 1.5,
    marginBottom: 4,
  },
  bulletRow: {
    flexDirection: "row",
    marginBottom: 3,
  },
  bulletDot: {
    width: 14,
    fontSize: 10.5,
    color: ACCENT,
  },
  bulletText: {
    flex: 1,
    fontSize: 10.5,
    color: BODY,
    lineHeight: 1.5,
  },
  citeInline: {
    fontSize: 8,
    fontFamily: "Helvetica-Bold",
    color: ACCENT,
  },

  // Footer (fixed = repeats on every page)
  footer: {
    position: "absolute",
    bottom: 18,
    left: 40,
    right: 40,
    borderTopWidth: 0.3,
    borderTopColor: ACCENT,
    paddingTop: 5,
    flexDirection: "row",
    justifyContent: "space-between",
  },
  footerText: {
    fontSize: 7.5,
    color: MUTED,
  },
});

type CitedTextStyle = typeof S.paragraph | typeof S.bulletText;

// ─── Helpers ─────────────────────────────────────────────────────────────────
function CitedText({
  text,
  citations,
  style,
}: {
  text: string;
  citations?: number[];
  style: CitedTextStyle;
}) {
  const cite =
    citations && citations.length > 0
      ? "  [" + citations.join("][") + "]"
      : "";
  return (
    <Text style={style}>
      {text}
      {cite ? <Text style={S.citeInline}>{cite}</Text> : null}
    </Text>
  );
}

function SectionBlock({ section }: { section: ReportSection }) {
  return (
    <View style={S.section}>
      <Text style={S.sectionHeading}>{section.heading}</Text>
      <View style={S.headingRule} />
      {section.content.map((item, i) =>
        item.isBullet ? (
          <View key={i} style={S.bulletRow}>
            <Text style={S.bulletDot}>•</Text>
            <CitedText
              text={item.text}
              citations={item.citations}
              style={S.bulletText}
            />
          </View>
        ) : (
          <CitedText
            key={i}
            text={item.text}
            citations={item.citations}
            style={S.paragraph}
          />
        )
      )}
    </View>
  );
}

function ReportDocument({ report }: { report: Report }) {
  const dateStr = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <Document>
      <Page size="A4" style={S.page}>
        {/* Footer — fixed renders on every page */}
        <View style={S.footer} fixed>
          <Text style={S.footerText}>ResearchOps Studio</Text>
          <Text
            style={S.footerText}
            render={({ pageNumber, totalPages }) =>
              `Page ${pageNumber} of ${totalPages}`
            }
          />
        </View>

        {/* Banner */}
        <View style={S.bannerOuter}>
          <View style={S.bannerAccent} />
          <View style={S.bannerInner}>
            <Text style={S.bannerLabel}>RESEARCH  REPORT</Text>
            <Text style={S.bannerTitle}>{report.title}</Text>
            <Text style={S.bannerDate}>{dateStr}</Text>
          </View>
        </View>

        {/* Body */}
        <View style={S.content}>
          {report.sections.map((section) => (
            <SectionBlock key={section.id} section={section} />
          ))}
        </View>
      </Page>
    </Document>
  );
}

// ─── Public API ──────────────────────────────────────────────────────────────
export async function exportReport(report: Report, format: string) {
  const filename = report.title || "report";

  if (format === "md") {
    downloadText(generateMarkdown(report), `${filename}.md`, "text/markdown");
    return;
  }

  if (format === "html") {
    downloadText(generateHTML(report), `${filename}.html`, "text/html");
    return;
  }

  if (format === "pdf") {
    const blob = await pdf(<ReportDocument report={report} />).toBlob();
    saveAs(blob, `${filename}.pdf`);
    return;
  }

  if (format === "docx") {
    await generateWord(report, filename);
  }
}

// ─── Utilities ───────────────────────────────────────────────────────────────
function downloadText(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

async function generateWord(report: Report, filename: string) {
  const children: Paragraph[] = [
    new Paragraph({
      text: report.title,
      heading: HeadingLevel.HEADING_1,
      spacing: { after: 200 },
    }),
  ];

  report.sections.forEach((section) => {
    children.push(
      new Paragraph({
        text: section.heading,
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 200, after: 100 },
      })
    );

    section.content.forEach((item) => {
      const runs: TextRun[] = [new TextRun(item.text)];
      if (item.citations && item.citations.length > 0) {
        runs.push(
          new TextRun({
            text: ` ${item.citations.map((c) => `[${c}]`).join("")}`,
            superScript: true,
            color: "10b981",
          })
        );
      }
      children.push(
        new Paragraph({
          children: runs,
          bullet: item.isBullet ? { level: 0 } : undefined,
          spacing: { after: 120 },
        })
      );
    });
  });

  const doc = new DocxDocument({
    sections: [{ properties: {}, children }],
  });

  const blob = await Packer.toBlob(doc);
  saveAs(blob, `${filename}.docx`);
}

function generateMarkdown(report: Report): string {
  let md = `# ${report.title}\n\n`;
  report.sections.forEach((section) => {
    md += `## ${section.heading}\n\n`;
    section.content.forEach((item) => {
      const prefix = item.isBullet ? "- " : "";
      let text = item.text;
      if (item.citations && item.citations.length > 0) {
        text += item.citations.map((c) => `[${c}]`).join("");
      }
      md += `${prefix}${text}\n\n`;
    });
  });
  return md;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function linkifyText(text: string): string {
  const escaped = escapeHtml(text);
  return escaped
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, (_, label, url) => `<a href="${url}">${label}</a>`)
    .replace(/(?<!href=")(https?:\/\/[^\s<,)"]+)/g, (url) => `<a href="${url}">${url}</a>`);
}

function generateHTML(report: Report): string {
  const dateStr = new Date().toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const isRefsSection = (heading: string) =>
    /^references?$|^bibliography$|^citations?$/i.test(heading.trim());

  let sectionsHtml = "";
  let sectionIdx = 0;

  report.sections.forEach((section) => {
    const isRefs = isRefsSection(section.heading);

    if (isRefs) {
      sectionsHtml += `  <section class="references">\n`;
      sectionsHtml += `    <h2>${escapeHtml(section.heading)}</h2>\n`;
      sectionsHtml += `    <ol>\n`;
      section.content.forEach((item) => {
        const cleaned = item.text.replace(/^\[\d+\]\s*/, "");
        sectionsHtml += `      <li>${linkifyText(cleaned)}</li>\n`;
      });
      sectionsHtml += `    </ol>\n`;
      sectionsHtml += `  </section>\n`;
      return;
    }

    sectionIdx++;
    sectionsHtml += `  <section>\n`;
    sectionsHtml += `    <h2><span class="section-num">${sectionIdx}.</span> ${escapeHtml(section.heading)}</h2>\n`;

    const hasBullets = section.content.some((item) => item.isBullet);
    if (hasBullets) sectionsHtml += "    <ul>\n";

    section.content.forEach((item) => {
      const cites =
        item.citations && item.citations.length > 0
          ? item.citations.map((c) => `<sup class="cite">${c}</sup>`).join("")
          : "";
      const body = `${escapeHtml(item.text)}${cites}`;

      if (item.isBullet) {
        sectionsHtml += `      <li>${body}</li>\n`;
      } else {
        if (hasBullets) sectionsHtml += "    </ul>\n";
        sectionsHtml += `    <p>${body}</p>\n`;
        if (hasBullets) sectionsHtml += "    <ul>\n";
      }
    });

    if (hasBullets) sectionsHtml += "    </ul>\n";
    sectionsHtml += `  </section>\n`;
  });

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${escapeHtml(report.title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0e0a1e; --bg-card: #160f2e; --bg-refs: #110d26;
      --accent: #9580c4; --accent-dim: #6b5a9a;
      --text: #ddd8ee; --text-muted: #9490a8; --border: #2a2050; --link: #b39ddb;
    }
    body { background: var(--bg); color: var(--text); font-family: "Inter", sans-serif; font-size: 16px; line-height: 1.75; }
    .banner { background: #120d2a; border-left: 5px solid var(--accent); border-bottom: 3px solid var(--accent); padding: 2.5rem 3rem 2rem; }
    .banner .label { font-size: 0.65rem; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent); margin-bottom: 0.75rem; }
    .banner h1 { font-family: "Crimson Pro", Georgia, serif; font-size: clamp(1.4rem, 3.5vw, 2.2rem); font-weight: 700; color: #f0ecff; line-height: 1.25; max-width: 72ch; }
    .banner .date { margin-top: 1.1rem; font-size: 0.78rem; color: var(--text-muted); }
    .content { max-width: 820px; margin: 0 auto; padding: 2rem 2rem 4rem; }
    section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 1.75rem 2rem; margin-bottom: 1.25rem; }
    section h2 { font-family: "Crimson Pro", Georgia, serif; font-size: 1.2rem; font-weight: 600; color: #f0ecff; padding-bottom: 0.6rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); }
    .section-num { color: var(--accent); margin-right: 0.3em; }
    p { margin-bottom: 0.8rem; } p:last-child { margin-bottom: 0; }
    ul { padding-left: 1.4rem; margin: 0.5rem 0; } li { margin-bottom: 0.4rem; }
    sup.cite { color: var(--accent); font-weight: 600; font-size: 0.7em; margin-left: 1px; }
    section.references { background: var(--bg-refs); border-color: var(--accent-dim); }
    section.references h2 { color: var(--accent); border-bottom-color: var(--accent-dim); }
    section.references ol { padding-left: 1.6rem; }
    section.references li { font-size: 0.82rem; color: var(--text-muted); line-height: 1.6; margin-bottom: 0.55rem; }
    section.references a { color: var(--link); text-decoration: none; word-break: break-all; }
    section.references a:hover { text-decoration: underline; }
    footer { text-align: center; font-size: 0.72rem; color: var(--text-muted); border-top: 1px solid var(--border); padding: 1.25rem 2rem; }
    @media print {
      body { background: #fff; color: #111; }
      .banner { background: #f5f3ff; } .banner h1 { color: #1a1030; }
      section { background: #fff; border-color: #ddd; } section h2 { color: #1a1030; }
    }
  </style>
</head>
<body>
  <div class="banner">
    <div class="label">Research Report</div>
    <h1>${escapeHtml(report.title)}</h1>
    <div class="date">${dateStr}</div>
  </div>
  <div class="content">
${sectionsHtml}  </div>
  <footer>Generated by ResearchOps Studio</footer>
</body>
</html>`;
}
