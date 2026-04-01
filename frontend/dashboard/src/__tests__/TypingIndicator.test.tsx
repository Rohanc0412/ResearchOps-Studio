import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { TypingIndicator } from "../features/chat/components/TypingIndicator";

describe("TypingIndicator", () => {
  it("has status role", () => {
    render(<TypingIndicator />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("has accessible label", () => {
    render(<TypingIndicator />);
    expect(screen.getByRole("status", { name: "Assistant is typing" })).toBeInTheDocument();
  });

  it("renders screen-reader text", () => {
    render(<TypingIndicator />);
    expect(screen.getByText("Assistant is typing")).toBeInTheDocument();
  });
});
