import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Spinner } from "../components/ui/Spinner";

describe("Spinner", () => {
  it("renders with default aria-label Loading", () => {
    render(<Spinner />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("renders custom label text", () => {
    render(<Spinner label="Please wait" />);
    expect(screen.getByText("Please wait")).toBeInTheDocument();
  });

  it("sets aria-label from label prop", () => {
    render(<Spinner label="Fetching data" />);
    expect(screen.getByRole("status", { name: "Fetching data" })).toBeInTheDocument();
  });
});
