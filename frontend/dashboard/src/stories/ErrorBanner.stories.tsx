import type { Meta, StoryObj } from "@storybook/react";
import { ErrorBanner } from "../components/ui/ErrorBanner";

const meta: Meta<typeof ErrorBanner> = {
  title: "UI/ErrorBanner",
  component: ErrorBanner,
  tags: ["autodocs"],
  args: { message: "Something unexpected happened. Please try again." },
};
export default meta;

type Story = StoryObj<typeof ErrorBanner>;

export const Default: Story = {};
export const CustomTitle: Story = {
  args: { title: "Network error", message: "Unable to reach the server." },
};
