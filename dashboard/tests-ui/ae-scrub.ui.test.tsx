import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AeScrub, DraftNumberInput } from "../src/maps/AeScrub";

function LatitudeField({ initial = 1.29004 }: { initial?: number }) {
  const [value, setValue] = useState(initial);
  return (
    <AeScrub
      label="Latitude"
      value={value}
      min={-90}
      max={90}
      step={0.01}
      digits={4}
      onChange={setValue}
    />
  );
}

describe("AeScrub typing", () => {
  it("keeps each typed digit instead of reformatting with toFixed", () => {
    render(<LatitudeField />);
    const input = screen.getByLabelText("Latitude:");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "1" } });
    expect(input).toHaveValue("1");
    fireEvent.change(input, { target: { value: "12" } });
    expect(input).toHaveValue("12");
    fireEvent.change(input, { target: { value: "12." } });
    expect(input).toHaveValue("12.");
    fireEvent.change(input, { target: { value: "12.34" } });
    expect(input).toHaveValue("12.34");
    fireEvent.blur(input);
    expect(input).toHaveValue("12.3400");
  });

  it("does not snap a trailing decimal to 1.0000", () => {
    render(<LatitudeField />);
    const input = screen.getByLabelText("Latitude:");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "1." } });
    expect(input).toHaveValue("1.");
    fireEvent.change(input, { target: { value: "1.2" } });
    expect(input).toHaveValue("1.2");
  });

  it("does not scrub on a click with sub-threshold movement", () => {
    const onChange = vi.fn();
    render(
      <AeScrub label="Zoom" value={3.4} min={0} max={22} step={0.1} onChange={onChange} />
    );
    const input = screen.getByLabelText("Zoom:");
    fireEvent.pointerDown(input, { clientX: 40, pointerId: 1 });
    fireEvent.pointerMove(input, { clientX: 42, pointerId: 1 });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("DraftNumberInput", () => {
  it("lets a multi-digit integer be typed without collapsing to the first digit", () => {
    function SizeField() {
      const [value, setValue] = useState(120);
      return <DraftNumberInput aria-label="Size" value={value} min={24} max={4000} onChange={setValue} />;
    }
    render(<SizeField />);
    const input = screen.getByLabelText("Size");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "2" } });
    expect(input).toHaveValue("2");
    fireEvent.change(input, { target: { value: "24" } });
    expect(input).toHaveValue("24");
    fireEvent.change(input, { target: { value: "240" } });
    expect(input).toHaveValue("240");
    fireEvent.blur(input);
    expect(input).toHaveValue("240");
  });

  it("rounds a fractional stroke count to an integer before emitting", () => {
    const onChange = vi.fn();
    function StrokesField() {
      const [value, setValue] = useState(4);
      return (
        <DraftNumberInput
          aria-label="Strokes"
          value={value}
          min={2}
          max={24}
          digits={0}
          onChange={(strokes) => {
            onChange(strokes);
            setValue(strokes);
          }}
        />
      );
    }
    render(<StrokesField />);
    const input = screen.getByLabelText("Strokes");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "3.5" } });
    expect(onChange).toHaveBeenCalledWith(4);
    expect(onChange.mock.calls.every(([value]) => Number.isInteger(value))).toBe(true);
    fireEvent.blur(input);
    expect(input).toHaveValue("4");
  });
});
