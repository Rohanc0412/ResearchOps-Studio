import type { Report } from "./types";

export const DEFAULT_HOSTED_MODEL = "openai/gpt-4o-mini";
export const CUSTOM_MODEL_VALUE = "__custom__";

export const MODEL_OPTIONS = [
  { value: "openai/gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "openai/gpt-4o", label: "GPT-4o" },
  { value: "anthropic/claude-3.5-sonnet", label: "Claude 3.5 Sonnet" },
  { value: "anthropic/claude-3.5-haiku", label: "Claude 3.5 Haiku" },
  { value: "google/gemini-2.0-flash-001", label: "Gemini 2.0 Flash" },
  { value: "meta-llama/llama-3.3-70b-instruct", label: "Llama 3.3 70B" },
  { value: "arcee-ai/trinity-large-preview:free", label: "Arcee Trinity (free)" },
  { value: "tngtech/deepseek-r1t2-chimera:free", label: "DeepSeek R1T2 (free)" },
  { value: CUSTOM_MODEL_VALUE, label: "Custom..." }
];

export const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};
