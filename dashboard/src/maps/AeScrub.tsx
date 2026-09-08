import { useRef } from "react";

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
  const drag = useRef<{ x: number; value: number } | null>(null);

  function clamp(n: number) {
    return Math.min(max, Math.max(min, n));
  }

  function commit() {
    onCommit?.();
  }

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
          onPointerUp={commit}
        />
      )}
      <input
        value={Number.isFinite(value) ? value.toFixed(places) : ""}
        disabled={disabled}
        onChange={(event) => {
          const n = Number(event.target.value);
          if (!Number.isNaN(n)) onChange(clamp(n));
        }}
        onBlur={commit}
        onPointerDown={(event) => {
          if (disabled) return;
          (event.target as HTMLElement).setPointerCapture(event.pointerId);
          drag.current = { x: event.clientX, value };
        }}
        onPointerMove={(event) => {
          if (!drag.current || disabled) return;
          onChange(clamp(drag.current.value + (event.clientX - drag.current.x) * step));
        }}
        onPointerUp={() => {
          drag.current = null;
          commit();
        }}
      />
    </label>
  );
}
