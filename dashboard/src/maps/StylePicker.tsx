import { useEffect, useRef, useState } from "react";
import type { MapsStyleId } from "./types";
import { MAP_STYLE_REGISTRY, STYLE_SWATCHES } from "./styles";
import { nextGridIndex } from "./stylePickerNav";
import { IconCaret } from "../components/icons";

const COLS = 3;

const STYLE_OPTIONS = STYLE_SWATCHES.map((swatch) => {
  const entry = MAP_STYLE_REGISTRY.find((item) => item.id === swatch.id);
  return { id: swatch.id, label: swatch.label, color: swatch.color, attribution: entry?.attribution || "" };
});

export function StylePicker({ value, disabled, onChange }: { value: MapsStyleId; disabled?: boolean; onChange: (id: MapsStyleId) => void }) {
  const [open, setOpen] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const tileRefs = useRef<(HTMLDivElement | null)[]>([]);

  const selectedIndex = Math.max(0, STYLE_OPTIONS.findIndex((option) => option.id === value));
  const selected = STYLE_OPTIONS[selectedIndex];

  useEffect(() => {
    if (!open) return;
    function onDoc(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    tileRefs.current[focusIndex]?.focus();
  }, [open, focusIndex]);

  function openPicker() {
    setFocusIndex(selectedIndex);
    setOpen(true);
  }

  function commit(id: MapsStyleId) {
    onChange(id);
    setOpen(false);
    triggerRef.current?.focus();
  }

  function onGridKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const next = nextGridIndex(focusIndex, event.key, STYLE_OPTIONS.length, COLS);
    if (next !== focusIndex) {
      event.preventDefault();
      setFocusIndex(next);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commit(STYLE_OPTIONS[focusIndex].id);
    }
  }

  const focused = STYLE_OPTIONS[focusIndex] || selected;

  return (
    <div className="style-picker" ref={rootRef}>
      <button
        type="button"
        className="btn secondary style-picker-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Map style: ${selected.label}`}
        disabled={disabled}
        ref={triggerRef}
        onClick={() => (open ? setOpen(false) : openPicker())}
      >
        <img className="style-picker-thumb" src={`/style-thumbs/${value}.png`} alt="" />
        {selected.label}
        <IconCaret />
      </button>
      {open && (
        <div className="style-picker-pop">
          <div
            className="style-picker-grid"
            role="listbox"
            aria-label="Map style"
            onKeyDown={onGridKeyDown}
          >
            {STYLE_OPTIONS.map((option, index) => (
              <div
                key={option.id}
                role="option"
                id={`style-picker-tile-${option.id}`}
                data-id={option.id}
                aria-selected={option.id === value}
                tabIndex={index === focusIndex ? 0 : -1}
                className="style-picker-tile"
                ref={(el) => { tileRefs.current[index] = el; }}
                onClick={() => commit(option.id)}
              >
                <img src={`/style-thumbs/${option.id}.png`} alt="" />
                <span>{option.label}</span>
              </div>
            ))}
          </div>
          <p className="style-picker-attrib">{focused.attribution}</p>
        </div>
      )}
    </div>
  );
}
