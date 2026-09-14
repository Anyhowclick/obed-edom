import { useCallback, useLayoutEffect, useRef } from "react";

export type SlidingSegOption = {
  id: string;
  label: string;
  className?: string;
};

/** Matches `--tabs-dur` on `.seg.seg-slide`. Resize snaps while this is
 *  in-flight yank the pill back (Countries → Regions grew a sibling note). */
const TABS_MS = 250;

/** Write the active tab's box onto the pill. `animate: false` suspends the
 *  CSS transition (first paint / resize) so the pill snaps before paint. */
function writePill(pill: HTMLElement, tab: HTMLElement, animate: boolean): boolean {
  if (tab.offsetWidth === 0) return false;
  if (!animate) pill.style.transition = "none";
  pill.style.transform = `translateX(${tab.offsetLeft}px)`;
  pill.style.width = `${tab.offsetWidth}px`;
  pill.style.visibility = "visible";
  if (!animate) {
    void pill.offsetWidth;
    pill.style.transition = "";
  }
  return true;
}

export function SlidingSeg({
  value,
  options,
  onChange,
  disabled,
  className,
  ariaLabel,
}: {
  value: string;
  options: SlidingSegOption[];
  onChange: (id: string) => void;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const pillRef = useRef<HTMLSpanElement>(null);
  const readyRef = useRef(false);
  const valueRef = useRef(value);
  const animUntilRef = useRef(0);
  const settleRef = useRef(0);

  const place = useCallback((animate: boolean, id = valueRef.current) => {
    const pill = pillRef.current;
    const bar = barRef.current;
    const tab = bar?.querySelector<HTMLElement>(`[data-seg-opt="${CSS.escape(id)}"]`);
    if (!pill || !tab) return false;
    return writePill(pill, tab, animate);
  }, []);

  const animateTo = useCallback((tab: HTMLElement, id: string) => {
    const pill = pillRef.current;
    if (!pill) return;
    writePill(pill, tab, true);
    valueRef.current = id;
    animUntilRef.current = performance.now() + TABS_MS;
    window.clearTimeout(settleRef.current);
    settleRef.current = window.setTimeout(() => {
      if (place(false)) readyRef.current = true;
    }, TABS_MS);
  }, [place]);

  useLayoutEffect(() => {
    if (valueRef.current === value && readyRef.current) return;
    const animate = readyRef.current && valueRef.current !== value;
    valueRef.current = value;
    if (place(animate)) readyRef.current = true;
  }, [place, value]);

  useLayoutEffect(() => {
    const bar = barRef.current;
    if (!bar || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (performance.now() < animUntilRef.current) return;
      if (place(false)) readyRef.current = true;
    });
    ro.observe(bar);
    return () => {
      ro.disconnect();
      window.clearTimeout(settleRef.current);
    };
  }, [place]);

  return (
    <div
      ref={barRef}
      className={`seg seg-slide${className ? ` ${className}` : ""}`}
      role="tablist"
      aria-label={ariaLabel}
    >
      <span ref={pillRef} className="seg-slide-ind" data-seg-id={value} aria-hidden="true" />
      {options.map((option) => {
        const selected = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="tab"
            data-seg-opt={option.id}
            aria-selected={selected}
            className={`${option.className || ""} ${selected ? "on" : ""}`.trim()}
            disabled={disabled}
            onClick={(event) => {
              if (option.id !== valueRef.current && readyRef.current) {
                animateTo(event.currentTarget, option.id);
              }
              onChange(option.id);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
