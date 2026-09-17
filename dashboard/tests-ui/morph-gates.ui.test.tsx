import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MorphGates } from "../src/maps/MorphGates";
import { makeSlide } from "./fakes/doc";

describe("MorphGates highlight pills", () => {
  it("shows only the mismatched region pills", () => {
    const from = makeSlide({
      highlights: ["IDN", "A1:IDN+KA"],
      highlightColours: { IDN: "#0a84ff", "A1:IDN+KA": "#f5d90a" },
    });
    const to = makeSlide({
      id: "s2",
      title: "Slide 2",
      highlights: ["IDN", "A1:IDN+SB"],
      highlightColours: { IDN: "#0a84ff", "A1:IDN+SB": "#f5d90a" },
    });
    render(<MorphGates from={from} to={to} />);
    expect(screen.getByText("IDN+KA")).toBeInTheDocument();
    expect(screen.getByText("IDN+SB")).toBeInTheDocument();
    expect(screen.queryByText("IDN")).not.toBeInTheDocument();
  });

  it("shows colour-changed pills for the same region", () => {
    const from = makeSlide({
      highlights: ["IDN"],
      highlightColours: { IDN: "#0a84ff" },
    });
    const to = makeSlide({
      id: "s2",
      title: "Slide 2",
      highlights: ["IDN"],
      highlightColours: { IDN: "#f5d90a" },
    });
    render(<MorphGates from={from} to={to} />);
    expect(screen.getAllByText("IDN")).toHaveLength(2);
  });
});
