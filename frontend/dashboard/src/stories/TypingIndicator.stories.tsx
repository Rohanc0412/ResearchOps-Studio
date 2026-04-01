import type { Meta, StoryObj } from "@storybook/react";
import { TypingIndicator } from "../features/chat/components/TypingIndicator";

const meta: Meta<typeof TypingIndicator> = {
  title: "Chat/TypingIndicator",
  component: TypingIndicator,
  tags: ["autodocs"],
};
export default meta;

type Story = StoryObj<typeof TypingIndicator>;

export const Default: Story = {};
