import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { diffImageUrl, type Flag, type Job } from "../api";
import { placeItem, rebuildPairs, slotsFromPairs, combineNext, splitRights, canCombineNext, rightsOf, slotsEqual, type Slot } from "../playlist";
import { useLayout } from "../nav";
import { isPreviewVideo } from "./PreviewGrid";
import { ValidationPanel } from "./ValidationPanel";

type Pair = {
  index: number;
  number: number;
  leftIndex?: number | null;
  rightIndex?: number | null;
  rightIndexes?: number[];
  leftNumber?: number | null;
  rightNumber?: number | null;
  rightNumbers?: number[];
  leftSkipped?: boolean;
  rightSkipped?: boolean;
  leftText?: string;
  rightText?: string;
  leftMarkup?: string;
  rightMarkup?: string;
  leftPng?: string;
  rightPng?: string;
  rightPngs?: (string | undefined)[];
  heatPng?: string;
  missing?: string;
  sameType?: boolean;
  score?: number;
  flags?: Flag[];
};

export type DiffResult = {
  leftPath?: string;
  rightPath?: string;
  leftLabel: string;
  rightLabel: string;
  sameType?: boolean;
  phase?: string;
  leftPngs: string[];
  rightPngs: string[];
  heatPngs: string[];
  leftCatalog?: { index: number; number: number; skipped?: boolean; png?: string | null; text?: string }[];
  rightCatalog?: { index: number; number: number; skipped?: boolean; png?: string | null; text?: string }[];
  pairs: Pair[];
  flags: Flag[];
};

function present(job: Job, label: string): boolean {
  return !job.artifacts?.missing?.includes(label);
}

function pickPng(named: string | undefined): string | undefined {
  return named;
}

function pairKey(pair: Pair): string {
  const rights = pair.rightIndexes?.length ? pair.rightIndexes.join("-") : String(pair.rightIndex);
  return `${pair.index}-${pair.leftIndex}-${rights}-${pair.leftNumber}-${pair.rightNumber}`;
}

function cap(label: string, number?: number | null, skipped?: boolean): string {
  if (number == null) return `No ${label}`;
  return skipped ? `${label} ${number} (skipped)` : `${label} ${number}`;
}

const SPLIT_KEY = "obed-edom.diff.split.v2";

function loadSplit(fallback: number): number {
  try {
    const raw = sessionStorage.getItem(SPLIT_KEY);
    const n = raw ? Number(raw) : NaN;
    if (Number.isFinite(n) && n >= 20 && n <= 85) return n;
  } catch {
    /* ignore */
  }
  return fallback;
}

function defaultSplit(): number {
  return 50;
}

function PairSplit({ pct, onPct }: { pct: number; onPct: (n: number) => void }) {
  return (
    <div
      className="pair-split"
      role="separator"
      aria-orientation="vertical"
      aria-valuemin={20}
      aria-valuemax={85}
      aria-valuenow={Math.round(pct)}
      aria-label="Resize comparison"
      onPointerDown={(event) => {
        event.preventDefault();
        event.stopPropagation();
        const parent = event.currentTarget.parentElement?.getBoundingClientRect();
        if (!parent?.width) return;
        const startX = event.clientX;
        const startPct = pct;
        const onMove = (ev: PointerEvent) => {
          onPct(Math.min(85, Math.max(20, startPct + ((ev.clientX - startX) / parent.width) * 100)));
        };
        const onUp = () => {
          document.body.classList.remove("dragging-split");
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
        };
        document.body.classList.add("dragging-split");
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
      }}
    />
  );
}

function ExpandIcon({ collapse }: { collapse?: boolean }) {
  return (
    <svg className="icon-expand" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      {collapse ? (
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          d="M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6"
        />
      ) : (
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"
        />
      )}
    </svg>
  );
}

function isWideDeck(label: string): boolean {
  return /\b(LW|GW|LED|FW)\b/i.test(label);
}

function scrollParent(el: Element): HTMLElement {
  let node = el.parentElement;
  while (node) {
    const style = getComputedStyle(node);
    if (/(auto|scroll)/.test(`${style.overflow}${style.overflowY}`) && node.scrollHeight > node.clientHeight + 1) {
      return node;
    }
    node = node.parentElement;
  }
  return (document.scrollingElement || document.documentElement) as HTMLElement;
}

function SlideSlot({
  job,
  side,
  png,
  label,
  crop,
  draggable,
  onOpen,
  onDragStart,
}: {
  job: Job;
  side: "left" | "right";
  png?: string;
  label: string;
  crop?: boolean;
  draggable?: boolean;
  onOpen: (src: string) => void;
  onDragStart?: () => void;
}) {
  const artifact = side === "left" ? "left previews" : "right previews";
  const src = png && present(job, artifact) ? diffImageUrl(job.id, side, png) : "";
  return (
    <div
      className={`slide-slot${crop ? " crop-center" : " dsk-frame"}`}
      draggable={Boolean(draggable && src)}
      onDragStart={(event) => {
        if (!draggable) return;
        event.dataTransfer.setData("text/plain", side);
        event.dataTransfer.effectAllowed = "move";
        onDragStart?.();
      }}
    >
      <div className="cap">{label}</div>
      {src ? (
        isPreviewVideo(png || src) ? (
          <video src={src} muted playsInline preload="metadata" onClick={() => onOpen(src)} />
        ) : (
          <img src={src} alt={label} onClick={() => onOpen(src)} />
        )
      ) : (
        <div className="slide-ph">{label}</div>
      )}
    </div>
  );
}

export function DiffResultView({
  job,
  onOpen,
  onRunChecks,
  checking,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRunChecks?: (slots: Slot[]) => void;
  checking?: boolean;
}) {
  const result = (job.result || null) as DiffResult | null;
  const { focusMode, setFocusMode } = useLayout();
  const [slots, setSlots] = useState<Slot[]>([]);
  const [selected, setSelected] = useState(0);
  const [split, setSplit] = useState<number | null>(() => {
    const n = loadSplit(Number.NaN);
    return Number.isFinite(n) ? n : null;
  });
  const [dragging, setDragging] = useState<{ side: "left" | "right"; index: number } | null>(null);
  const stackRef = useRef<HTMLDivElement>(null);
  const selectedTopRef = useRef<number | null>(null);

  useEffect(() => {
    if (!result?.pairs) return;
    setSlots(slotsFromPairs(result.pairs));
    setSelected(0);
  }, [job.id, result?.phase]);

  const pairs = useMemo(() => {
    if (!result) return [];
    if (result.leftCatalog && result.rightCatalog && slots.length) {
      const applyChecks = result.phase === "checked" && slotsEqual(slots, slotsFromPairs(result.pairs));
      return rebuildPairs(slots, result.leftCatalog, result.rightCatalog, result.leftLabel, result.rightLabel).map(
        (pair, i) => ({
          ...pair,
          flags: applyChecks ? result.pairs[i]?.flags || [] : [],
          heatPng: applyChecks ? result.pairs[i]?.heatPng : undefined,
        })
      );
    }
    return result.pairs;
  }, [result, slots]);

  useLayoutEffect(() => {
    const before = selectedTopRef.current;
    if (before == null) return;
    selectedTopRef.current = null;
    const row = stackRef.current?.querySelector(".diff-row.on");
    if (!row) return;
    const scroller = scrollParent(row);
    scroller.scrollTop += row.getBoundingClientRect().top - before;
  }, [split]);

  if (job.status === "error") return <p className="err">{job.error}</p>;
  if (!result || (job.status !== "done" && !checking)) return null;

  const phase = result.phase || "checked";
  const matching = phase !== "checked";
  const canEdit = Boolean(result.leftCatalog && result.rightCatalog);
  const deckFlags = matching ? [] : (result.flags || []).filter((flag) => flag.category !== "diff");
  const leftWide = isWideDeck(result.leftLabel);
  const rightWide = isWideDeck(result.rightLabel);
  const pairLayout = leftWide && rightWide ? "lw-lw" : leftWide ? "lw-dsk" : rightWide ? "dsk-lw" : "dsk-dsk";
  const leftPct = split ?? defaultSplit();

  function setSplitPct(next: number) {
    const row = stackRef.current?.querySelector(".diff-row.on");
    if (row) selectedTopRef.current = row.getBoundingClientRect().top;
    setSplit(next);
    try {
      sessionStorage.setItem(SPLIT_KEY, String(Math.round(next)));
    } catch {
      /* ignore */
    }
  }

  function onDropRow(row: number) {
    if (!dragging) return;
    setSlots((current) => placeItem(current, dragging.side, dragging.index, row));
    setSelected(row);
    setDragging(null);
  }

  return (
    <>
        {canEdit && (
          <p className="note playlist-note">
            {phase === "visual"
              ? "Folders are listed in file order. Drag a slide onto another row to pair it. Combine next DSK when one wall holds two graphics."
              : matching
                ? "First pass matched these pairs. Drag a slide onto another row to fix it. If one wall holds two DSK verses, Combine next DSK. Deck order stays. Then run checks."
                : "Checks are on the confirmed pairs. You can still rearrange, combine, and run checks again."}
          </p>
        )}
        <div className="playlist-bar">
          <div className="actions playlist-controls">
            {canEdit && onRunChecks && (
              <button className="btn run-checks" type="button" disabled={checking} onClick={() => onRunChecks(slots)}>
                Run checks
              </button>
            )}
            <button
              className="btn secondary icon-btn"
              type="button"
              title={focusMode ? "Exit maximise" : "Maximise"}
              aria-label={focusMode ? "Exit maximise" : "Maximise"}
              onClick={() => setFocusMode(!focusMode)}
            >
              <ExpandIcon collapse={focusMode} />
            </button>
          </div>
        </div>
      <div className="diff-stack" ref={stackRef}>
        {pairs.map((pair, row) => {
          const issues = pair.flags || [];
          const rightIndexes = pair.rightIndexes?.length ? pair.rightIndexes : pair.rightIndex != null ? [pair.rightIndex] : [];
          const rightPngs = pair.rightPngs?.length ? pair.rightPngs : [pair.rightPng];
          const rightNumbers = pair.rightNumbers?.length ? pair.rightNumbers : [pair.rightNumber];
          const combined = rightIndexes.length > 1;
          return (
            <article
              key={pairKey(pair)}
              className={`diff-row${selected === row ? " on" : ""}${combined ? " combined" : ""}`}
              id={`pair-${pair.index}`}
              onClick={() => setSelected(row)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                onDropRow(row);
              }}
            >
              <div
                className={`pair-slides ${pairLayout}${combined ? " combined" : ""}`}
                style={{ ["--split-left" as string]: `${leftPct}%` }}
              >
                <SlideSlot
                  job={job}
                  side="left"
                  png={pickPng(pair.leftPng)}
                  label={cap(result.leftLabel, pair.leftNumber, pair.leftSkipped)}
                  crop={leftWide}
                  draggable={pair.leftIndex != null}
                  onOpen={onOpen}
                  onDragStart={() => pair.leftIndex != null && setDragging({ side: "left", index: pair.leftIndex })}
                />
                <PairSplit pct={leftPct} onPct={setSplitPct} />
                {combined ? (
                  <div className="dsk-stack">
                    {rightIndexes.map((index, i) => (
                      <SlideSlot
                        key={`r-${index}`}
                        job={job}
                        side="right"
                        png={pickPng(rightPngs[i])}
                        label={cap(result.rightLabel, rightNumbers[i], false)}
                        crop={rightWide}
                        draggable
                        onOpen={onOpen}
                        onDragStart={() => setDragging({ side: "right", index })}
                      />
                    ))}
                  </div>
                ) : (
                  <SlideSlot
                    job={job}
                    side="right"
                    png={pickPng(pair.rightPng)}
                    label={cap(result.rightLabel, pair.rightNumber, pair.rightSkipped)}
                    crop={rightWide}
                    draggable={pair.rightIndex != null}
                    onOpen={onOpen}
                    onDragStart={() => pair.rightIndex != null && setDragging({ side: "right", index: pair.rightIndex })}
                  />
                )}
              </div>
              {canEdit && (canCombineNext(slots, row) || rightsOf(slots[row] || {}).length > 1) && (
                <div className="row-acts">
                  {canCombineNext(slots, row) && (
                    <button
                      className="btn combine"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setSlots((current) => combineNext(current, row));
                      }}
                    >
                      Combine next {result.rightLabel}
                    </button>
                  )}
                  {rightsOf(slots[row] || {}).length > 1 && (
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setSlots((current) => splitRights(current, row));
                      }}
                    >
                      Split {result.rightLabel}s
                    </button>
                  )}
                </div>
              )}
              {issues.length > 0 && (
                <div className="pair-issues">
                  {issues.map((flag, i) => (
                    <div key={`${flag.category}-${i}`} className={`flag ${flag.severity}`}>
                      <div className="meta">{flag.severity}</div>
                      {flag.message}
                    </div>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
      {deckFlags.length > 0 && <ValidationPanel flags={deckFlags} />}
    </>
  );
}
