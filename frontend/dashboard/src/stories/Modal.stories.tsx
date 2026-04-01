import type { Meta, StoryObj } from "@storybook/react";
import { Modal } from "../components/ui/Modal";

const meta: Meta<typeof Modal> = {
  title: "UI/Modal",
  component: Modal,
  tags: ["autodocs"],
  args: {
    open: true,
    title: "Example Modal",
    onClose: () => {},
    children: <p className="text-sm text-slate-300">Modal body content goes here.</p>,
  },
};
export default meta;

type Story = StoryObj<typeof Modal>;

export const Default: Story = {};
export const Closed: Story = { args: { open: false } };
