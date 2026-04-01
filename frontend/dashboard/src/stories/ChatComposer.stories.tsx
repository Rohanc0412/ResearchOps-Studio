import type { Meta, StoryObj } from "@storybook/react";
import { ChatComposer } from "../features/chat/components/ChatComposer";
import { MODEL_OPTIONS, CUSTOM_MODEL_VALUE, DEFAULT_HOSTED_MODEL } from "../features/chat/constants";

const meta: Meta<typeof ChatComposer> = {
  title: "Chat/ChatComposer",
  component: ChatComposer,
  tags: ["autodocs"],
  args: {
    draft: "",
    isTyping: false,
    runPipelineArmed: false,
    selectedModel: DEFAULT_HOSTED_MODEL,
    customModel: "",
    modelOptions: MODEL_OPTIONS,
    customModelValue: CUSTOM_MODEL_VALUE,
    onDraftChange: () => {},
    onSend: () => {},
    onQuickAction: () => {},
    onTogglePipeline: () => {},
    onSelectedModelChange: () => {},
    onCustomModelChange: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof ChatComposer>;

export const Default: Story = {};
export const WithDraft: Story = { args: { draft: "What are the latest trends in AI?" } };
export const PipelineArmed: Story = { args: { runPipelineArmed: true } };
export const Typing: Story = { args: { isTyping: true } };
