import { useEffect, useRef, useState } from "react";

const SCRUB_THRESHOLD_PX = 4;

function formatValue(value: number, places: number): string {
  return Number.isFinite(value) ? value.toFixed(places) : "";
}

function quantize(value: number, places: number): number {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
}

function parseDraft(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "" || trimmed === "-" || trimmed === "+" || trimmed === "." || trimmed === "-." || trimmed === "+.") {
    return null;
  }
  if (!/^[+-]?\d*\.?\d*$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function DraftNumberInput({
  value,
  min,
  max,
  digits,
  disabled = false,
  className,
  "aria-label": ariaLabel,
  onChange,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  digits?: number;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
  onChange: (value: number) => void;
  onCommit?: () => void;
}) {
  const places = digits ?? 0;
  const { text, handlers } = useNumberDraft({ value, min, max, places, disabled, onChange, onCommit });
  return (
    <input
      className={className}
      aria-label={ariaLabel}
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      value={text}
      disabled={disabled}
      {...handlers}
    />
  );
}

function useNumberDraft({
  value,
  min,
  max,
  places,
  disabled,
  onChange,
  onCommit,
}: {
  value: number;
  min: number;
  max: number;
  places: number;
  disabled: boolean;
  onChange: (value: number) => void;
  onCommit?: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const draftRef = useRef<string | null>(null);
  const typedValue = useRef<number | null>(null);

  function clamp(n: number) {
    return Math.min(max, Math.max(min, quantize(n, places)));
  }

  function writeDraft(next: string | null) {
    draftRef.current = next;
    setDraft(next);
  }

  function emit(n: number) {
    const next = clamp(n);
    typedValue.current = next;
    onChange(next);
    return next;
  }

  useEffect(() => {
    if (draft === null) return;
    if (typedValue.current != null && Object.is(value, typedValue.current)) return;
    writeDraft(formatValue(value, places));
    typedValue.current = null;
  }, [value, places, draft]);

  function commit() {
    const current = draftRef.current;
    if (current !== null) {
      const n = parseDraft(current);
      if (n !== null) onChange(clamp(n));
    }
    writeDraft(null);
    typedValue.current = null;
    onCommit?.();
  }

  return {
    text: draft ?? formatValue(value, places),
    clamp,
    emit,
    commit,
    writeDraft,
    handlers: {
      onFocus: () => {
        if (disabled) return;
        writeDraft(formatValue(value, places));
      },
      onChange: (event: { target: { value: string } }) => {
        const raw = event.target.value;
        writeDraft(raw);
        const n = parseDraft(raw);
        if (n !== null) emit(n);
      },
      onBlur: commit,
    },
  };
}

export function AeScrub({
  label,
  value,
  min,
  max,
  step = 0.1,
  decimals,
  digits,
  slider = false,
  disabled = false,
  onChange,
  onCommit,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  decimals?: number;
  digits?: number;
  slider?: boolean;
  disabled?: boolean;
  onChange: (value: number) => void;
  onCommit?: () => void;
}) {
  const places = digits ?? decimals ?? 2;
  const drag = useRef<{ x: number; value: number; scrubbing: boolean } | null>(null);
  const { text, clamp, emit, commit, writeDraft, handlers } = useNumberDraft({
    value,
    min,
    max,
    places,
    disabled,
    onChange,
    onCommit,
  });

  return (
    <label className={`ae-scrub${slider ? " has-slider" : ""}`}>
      <span>{label}:</span>
      {slider && (
        <input
          type="range"
          className="ae-scrub-slider"
          min={min}
          max={max}
          step={step}
          value={Number.isFinite(value) ? value : min}
          disabled={disabled}
          onChange={(event) => onChange(clamp(Number(event.target.value)))}
          onPointerUp={() => onCommit?.()}
        />
      )}
      <input
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        value={text}
        disabled={disabled}
        onFocus={handlers.onFocus}
        onChange={handlers.onChange}
        onBlur={handlers.onBlur}
        onPointerDown={(event) => {
          if (disabled) return;
          drag.current = { x: event.clientX, value, scrubbing: false };
        }}
        onPointerMove={(event) => {
          const start = drag.current;
          if (!start || disabled) return;
          const dx = event.clientX - start.x;
          if (!start.scrubbing) {
            if (Math.abs(dx) < SCRUB_THRESHOLD_PX) return;
            start.scrubbing = true;
            (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
            writeDraft(null);
          }
          emit(start.value + dx * step);
        }}
        onPointerUp={() => {
          const wasScrubbing = drag.current?.scrubbing;
          drag.current = null;
          if (wasScrubbing) commit();
        }}
      />
    </label>
  );
}
