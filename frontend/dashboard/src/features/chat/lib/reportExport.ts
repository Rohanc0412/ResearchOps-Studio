import jsPDF from "jspdf";
import { Document, HeadingLevel, Packer, Paragraph, TextRun } from "docx";
import { saveAs } from "file-saver";

import type { Report } from "../types";

export async function exportReport(report: Report, format: string) {
  const filename = `${report.title || "report"}`;

  if (format === "md") {
    const content = generateMarkdown(report);
    downloadText(content, `${filename}.md`, "text/markdown");
    return;
  }

  if (format === "html") {
    const content = generateHTML(report);
    downloadText(content, `${filename}.html`, "text/html");
    return;
  }

  if (format === "pdf") {
    await generatePDF(report, filename);
    return;
  }

  if (format === "docx") {
    await generateWord(report, filename);
  }
}

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

async function generatePDF(report: Report, filename: string) {
  const doc = new jsPDF();
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 20;
  const maxWidth = pageWidth - 2 * margin;
  let yPosition = margin;

  doc.setFontSize(20);
  doc.setFont("helvetica", "bold");
  doc.text(report.title, margin, yPosition);
  yPosition += 15;

  doc.setFontSize(11);

  report.sections.forEach((section) => {
    if (yPosition > pageHeight - 30) {
      doc.addPage();
      yPosition = margin;
    }

    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.text(section.heading, margin, yPosition);
    yPosition += 10;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(11);

    section.content.forEach((item) => {
      let text = item.text;
      if (item.citations && item.citations.length > 0) {
        text += ` ${item.citations.map((citation) => `[${citation}]`).join("")}`;
      }
      if (item.isBullet) {
        text = `* ${text}`;
      }

      const lines = doc.splitTextToSize(text, maxWidth);
      const lineHeight = 7;
      const totalHeight = lines.length * lineHeight;

      if (yPosition + totalHeight > pageHeight - margin) {
        doc.addPage();
        yPosition = margin;
      }

      lines.forEach((line: string) => {
        doc.text(line, margin, yPosition);
        yPosition += lineHeight;
      });

      yPosition += 3;
    });

    yPosition += 5;
  });

  doc.save(`${filename}.pdf`);
}

async function generateWord(report: Report, filename: string) {
  const children: Paragraph[] = [
    new Paragraph({
      text: report.title,
      heading: HeadingLevel.HEADING_1,
      spacing: { after: 200 }
    })
  ];

  report.sections.forEach((section) => {
    children.push(
      new Paragraph({
        text: section.heading,
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 200, after: 100 }
      })
    );

    section.content.forEach((item) => {
      const runs: TextRun[] = [new TextRun(item.text)];
      if (item.citations && item.citations.length > 0) {
        runs.push(
          new TextRun({
            text: ` ${item.citations.map((citation) => `[${citation}]`).join("")}`,
            superScript: true,
            color: "10b981"
          })
        );
      }

      children.push(
        new Paragraph({
          children: runs,
          bullet: item.isBullet ? { level: 0 } : undefined,
          spacing: { after: 120 }
        })
      );
    });
  });

  const doc = new Document({
    sections: [
      {
        properties: {},
        children
      }
    ]
  });

  const blob = await Packer.toBlob(doc);
  saveAs(blob, `${filename}.docx`);
}

function generateMarkdown(report: Report): string {
  let markdown = `# ${report.title}\n\n`;
  report.sections.forEach((section) => {
    markdown += `## ${section.heading}\n\n`;
    section.content.forEach((item) => {
      const prefix = item.isBullet ? "- " : "";
      let text = item.text;
      if (item.citations && item.citations.length > 0) {
        text += item.citations.map((citation) => `[${citation}]`).join("");
      }
      markdown += `${prefix}${text}\n\n`;
    });
  });
  return markdown;
}

function generateHTML(report: Report): string {
  let html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${report.title}</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
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

  report.sections.forEach((section) => {
    html += `  <h2>${section.heading}</h2>\n`;
    const hasBullets = section.content.some((item) => item.isBullet);
    if (hasBullets) html += "  <ul>\n";

    section.content.forEach((item) => {
      let text = item.text;
      if (item.citations && item.citations.length > 0) {
        text += item.citations.map((citation) => `<sup>${citation}</sup>`).join("");
      }

      if (item.isBullet) {
        html += `    <li>${text}</li>\n`;
      } else {
        if (hasBullets) html += "  </ul>\n";
        html += `  <p>${text}</p>\n`;
        if (hasBullets) html += "  <ul>\n";
      }
    });

    if (hasBullets) html += "  </ul>\n";
  });

  html += `</body>
</html>`;
  return html;
}
