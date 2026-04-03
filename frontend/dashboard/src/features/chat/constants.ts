import type { Report } from "./types";

export const DEFAULT_HOSTED_MODEL = "gpt-4.1-mini";
export const CUSTOM_MODEL_VALUE = "__custom__";

export const MODEL_OPTIONS = [
  { value: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
  { value: "qwen/qwen3.6-plus:free", label: "Qwen 3.6 Plus (free)" },
  { value: "openai/gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "openai/gpt-4o", label: "GPT-4o" },
  { value: "anthropic/claude-3.5-sonnet", label: "Claude 3.5 Sonnet" },
  { value: "anthropic/claude-3.5-haiku", label: "Claude 3.5 Haiku" },
  { value: "google/gemini-2.5-flash", label: "Gemini 2.5 Flash" },
  { value: "meta-llama/llama-3.3-70b-instruct", label: "Llama 3.3 70B" },
  { value: "arcee-ai/trinity-large-preview:free", label: "Arcee Trinity (free)" },
  { value: "tngtech/deepseek-r1t2-chimera:free", label: "DeepSeek R1T2 (free)" },
  { value: CUSTOM_MODEL_VALUE, label: "Custom..." }
];

export const EMPTY_REPORT: Report = {
  title: "Live Report",
  sections: []
};
