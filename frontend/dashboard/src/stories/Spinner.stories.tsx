import type { Meta, StoryObj } from "@storybook/react";
import { Spinner } from "../components/ui/Spinner";

const meta: Meta<typeof Spinner> = {
  title: "UI/Spinner",
  component: Spinner,
  tags: ["autodocs"],
};
export default meta;

type Story = StoryObj<typeof Spinner>;

export const Default: Story = {};
export const WithLabel: Story = { args: { label: "Loading..." } };
export const Small: Story = { args: { size: "sm", label: "Please wait" } };
