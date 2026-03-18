import type { Report } from "./types";

export const DEFAULT_HOSTED_MODEL = "arcee-ai/trinity-large-preview:free";
export const CUSTOM_MODEL_VALUE = "__custom__";

export const MODEL_OPTIONS = [
  { value: DEFAULT_HOSTED_MODEL, label: "Arcee Trinity Large Preview (free)" },
  { value: "tngtech/deepseek-r1t2-chimera:free", label: "DeepSeek R1T2 Chimera (free)" },
  { value: "xiaomi/mimo-v2-flash:free", label: "Xiaomi Mimo V2 Flash (free)" },
  { value: "openai/gpt-4o-mini", label: "OpenAI GPT-4o Mini" },
  { value: "anthropic/claude-3.5-sonnet", label: "Anthropic Claude 3.5 Sonnet" },
  { value: CUSTOM_MODEL_VALUE, label: "Custom..." }
];

export const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};
