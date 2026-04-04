import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ChatComposer } from "../features/chat/components/ChatComposer";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE, DEFAULT_HOSTED_MODEL } from "../features/chat/constants";

const defaultProps = {
  draft: "",
  isTyping: false,
  runPipelineArmed: false,
  selectedModel: DEFAULT_HOSTED_MODEL,
  customModel: "",
  modelOptions: MODEL_OPTIONS,
  customModelValue: CUSTOM_MODEL_VALUE,
  onDraftChange: vi.fn(),
  onSend: vi.fn(),
  onQuickAction: vi.fn(),
  onTogglePipeline: vi.fn(),
  onSelectedModelChange: vi.fn(),
  onCustomModelChange: vi.fn(),
};

describe("ChatComposer", () => {
  it("uses GPT-5 Nano as the default hosted model", () => {
    expect(DEFAULT_HOSTED_MODEL).toBe("gpt-5-nano");
    expect(
      MODEL_OPTIONS.some(
        (option) =>
          option.value === DEFAULT_HOSTED_MODEL && option.label === "GPT-4.1 Mini",
      ),
    ).toBe(true);
  });

  it("renders the message textarea with label", () => {
    render(<ChatComposer {...defaultProps} />);
    expect(screen.getByRole("textbox", { name: "Message input" })).toBeInTheDocument();
  });

  it("renders the model select with label", () => {
    render(<ChatComposer {...defaultProps} />);
    expect(screen.getByRole("combobox", { name: "LLM model" })).toBeInTheDocument();
  });

  it("calls onDraftChange when typing", async () => {
    const onDraftChange = vi.fn();
    render(<ChatComposer {...defaultProps} onDraftChange={onDraftChange} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Message input" }), "hello");
    expect(onDraftChange).toHaveBeenCalled();
  });

  it("calls onSend when send button clicked", async () => {
    const onSend = vi.fn();
    render(<ChatComposer {...defaultProps} draft="some text" onSend={onSend} />);
    await userEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSend).toHaveBeenCalledOnce();
  });

  it("send button is disabled when draft is empty", () => {
    render(<ChatComposer {...defaultProps} draft="" />);
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("calls onTogglePipeline when pipeline button clicked", async () => {
    const onTogglePipeline = vi.fn();
    render(<ChatComposer {...defaultProps} onTogglePipeline={onTogglePipeline} />);
    await userEvent.click(screen.getByTestId("pipeline-toggle"));
    expect(onTogglePipeline).toHaveBeenCalledOnce();
  });

  it("pipeline button shows armed state", () => {
    render(<ChatComposer {...defaultProps} runPipelineArmed />);
    expect(screen.getByTestId("pipeline-toggle")).toHaveAttribute("aria-pressed", "true");
  });

  it("calls onQuickAction when quick action clicked", async () => {
    const onQuickAction = vi.fn();
    render(<ChatComposer {...defaultProps} onQuickAction={onQuickAction} />);
    await userEvent.click(screen.getByRole("button", { name: "Add conclusion" }));
    expect(onQuickAction).toHaveBeenCalledWith("Add conclusion");
  });
});
