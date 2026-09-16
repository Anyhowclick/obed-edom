import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColourPicker } from "../src/maps/ColourPicker";
import { isHighlightHex, normaliseHighlightColour } from "../src/maps/highlight";
import { DEFAULT_SAVED_COLOUR, loadSavedColours, writeSavedColours } from "../src/maps/savedColours";

beforeEach(() => {
  localStorage.clear();
});

describe("ColourPicker", () => {
  it("starts with default orange and can add and remove colours", () => {
    const onColour = vi.fn();
    const onText = vi.fn();
    const onCommit = vi.fn();
    const { rerender } = render(
      <ColourPicker colour="#112233" text="#112233" onColour={onColour} onText={onText} onCommit={onCommit} />
    );

    expect(screen.getByRole("button", { name: DEFAULT_SAVED_COLOUR })).toBeInTheDocument();
    expect(screen.queryByLabelText("Name it")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save colour" }));
    expect(loadSavedColours()).toEqual([DEFAULT_SAVED_COLOUR, "#112233"]);

    rerender(
      <ColourPicker colour="#e8772a" text="#e8772a" onColour={onColour} onText={onText} onCommit={onCommit} />
    );
    fireEvent.click(screen.getByRole("button", { name: "#112233" }));
    expect(onColour).toHaveBeenCalledWith("#112233");

    fireEvent.click(screen.getByRole("button", { name: "Remove #112233" }));
    expect(loadSavedColours()).toEqual([DEFAULT_SAVED_COLOUR]);
  });

  it("exposes no-fill as a swatch, not a checkbox", () => {
    const onNone = vi.fn();
    render(
      <ColourPicker
        colour="#e8772a"
        text="#e8772a"
        allowNone
        onColour={() => undefined}
        onText={() => undefined}
        onNone={onNone}
        onCommit={() => undefined}
      />
    );
    expect(screen.queryByRole("checkbox", { name: "No fill" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "No fill" }));
    expect(onNone).toHaveBeenCalled();
  });

  it("can switch and save a colour while no-fill is active", () => {
    const onColour = vi.fn();
    const onCommit = vi.fn();
    render(
      <ColourPicker
        colour="#112233"
        text="#112233"
        none
        allowNone
        onColour={onColour}
        onText={() => undefined}
        onCommit={onCommit}
      />
    );

    expect(screen.getByLabelText("Highlight colour hex")).toHaveAttribute("placeholder", "No fill");
    expect(screen.getByLabelText("Highlight colour hex")).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: "Save colour" }));
    expect(loadSavedColours()).toEqual([DEFAULT_SAVED_COLOUR, "#112233"]);

    fireEvent.click(screen.getByRole("button", { name: DEFAULT_SAVED_COLOUR }));
    expect(onColour).toHaveBeenCalledWith(DEFAULT_SAVED_COLOUR);
    expect(onCommit).toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Highlight colour"), { target: { value: "#00aaff" } });
    expect(onColour).toHaveBeenCalledWith("#00aaff");
  });

  it("keeps a hex draft while typing through a 3-digit prefix", async () => {
    const user = userEvent.setup();
    const onText = vi.fn();
    render(
      <ColourPicker colour="#c44a42" text="#c44a42" onColour={() => undefined} onText={onText} onCommit={() => undefined} />
    );
    const hex = screen.getByLabelText("Highlight colour hex");
    await user.clear(hex);
    expect(hex).toHaveValue("");
    await user.type(hex, "#112");
    expect(hex).toHaveValue("#112");
    expect(onText).not.toHaveBeenCalled();
    await user.type(hex, "233");
    expect(hex).toHaveValue("#112233");
    expect(onText).toHaveBeenCalledWith("#112233");
  });

  it("applies a typed hex while no-fill is selected on a controlled parent", async () => {
    const user = userEvent.setup();
    const applied: string[] = [];
    function Parent() {
      const [colour, setColour] = useState("#e8772a");
      const [text, setText] = useState("#e8772a");
      const [none, setNone] = useState(true);
      return (
        <ColourPicker
          colour={colour}
          text={text}
          none={none}
          allowNone
          onColour={(value) => {
            setColour(value);
            setText(value);
            setNone(false);
            applied.push(value);
          }}
          onText={(value) => {
            setText(value);
            if (isHighlightHex(value)) setColour(normaliseHighlightColour(value));
          }}
          onNone={() => setNone(true)}
          onCommit={() => undefined}
        />
      );
    }

    render(<Parent />);
    const hex = screen.getByLabelText("Highlight colour hex");
    expect(hex).toHaveValue("");
    await user.type(hex, "#112233");
    expect(hex).toHaveValue("#112233");
    expect(applied).toEqual([]);
    await user.tab();
    expect(applied).toEqual(["#112233"]);
    expect(hex).toHaveValue("#112233");
    expect(screen.getByRole("button", { name: "No fill" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("savedColours", () => {
  it("reads hexes from older named saves and drops duplicates", () => {
    localStorage.setItem("obed-edom.maps.savedColours", JSON.stringify([{ hex: "#112233", name: "Old" }, "#112233"]));
    expect(loadSavedColours()).toEqual(["#112233"]);
    writeSavedColours(["#112233", "#112233"]);
    expect(loadSavedColours()).toEqual(["#112233"]);
  });
});
