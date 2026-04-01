import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ErrorBanner } from "../components/ui/ErrorBanner";

describe("ErrorBanner", () => {
  it("renders the message", () => {
    render(<ErrorBanner message="Unable to load data" />);
    expect(screen.getByText("Unable to load data")).toBeInTheDocument();
  });

  it("renders default title", () => {
    render(<ErrorBanner message="Error" />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders custom title", () => {
    render(<ErrorBanner title="Network error" message="Unable to connect" />);
    expect(screen.getByText("Network error")).toBeInTheDocument();
    expect(screen.getByText("Unable to connect")).toBeInTheDocument();
  });

  it("has alert role for screen readers", () => {
    render(<ErrorBanner message="Error" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
