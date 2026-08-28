import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { diffImageUrl, type Flag, type Job } from "../api";
import { placeItem, rebuildPairs, slotsFromPairs, combineNext, splitRights, canCombineNext, rightsOf, shiftColumn, slotsEqual, type Slot } from "../playlist";
import { useLayout } from "../nav";
import type { OutlineRow } from "../outline";
import { SHOW_INFO_KEY, SIDE_PANELS_KEY, useSessionToggle } from "../prefs";
import { OutlineStrip } from "./OutlineStrip";
import { isPreviewVideo } from "./PreviewGrid";
import { SlideFindings } from "./SlideFindings";
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
  outlineRow?: OutlineRow | null;
};

export type DiffResult = {
  leftPath?: string;
  rightPath?: string;
  outlinePath?: string | null;
  leftLabel: string;
  rightLabel: string;
  leftDeck?: string;
  rightDeck?: string;
  sameType?: boolean;
  phase?: string;
  leftPngs: string[];
  rightPngs: string[];
  heatPngs: string[];
  leftCatalog?: { index: number; number: number; skipped?: boolean; png?: string | null; text?: string }[];
  rightCatalog?: { index: number; number: number; skipped?: boolean; png?: string | null; text?: string }[];
  pairs: Pair[];
  flags: Flag[];
  outlineFlags?: Flag[];
  rows?: OutlineRow[];
  reuse?: { used?: boolean; carried: number; changed: number; added: number; removed: number; source?: string };
};

function flagOnPair(flag: Flag, pair: Pair): boolean {
  if (flag.slide == null) return false;
  const deck = (flag.deck || "").toLowerCase();
  // Outline findings count paragraphs, not slides, so the fallback below would
  // match them against unrelated slide numbers.
  if (deck === "outline") return false;
  const rights = pair.rightNumbers?.length ? pair.rightNumbers : pair.rightNumber != null ? [pair.rightNumber] : [];
  if (deck === "lw" || deck === "left") return pair.leftNumber === flag.slide;
  if (deck === "dsk" || deck === "right") return rights.includes(flag.slide);
  return pair.leftNumber === flag.slide || rights.includes(flag.slide);
}

const SEVERITY_RANK: Record<string, number> = { error: 0, warning: 1, info: 2, success: 3 };

function deckSlideLabel(flag: Flag, leftLabel: string, rightLabel: string): string {
  const deck = (flag.deck || "").toLowerCase();
  const name = deck === "lw" || deck === "left" ? leftLabel : deck === "dsk" || deck === "right" ? rightLabel : flag.deck || "";
  return flag.slide != null ? `${name} slide ${flag.slide}`.trim() : name;
}

/**
 * Collapse the same finding raised once per deck within a pair into one card.
 * `compare_inspects` validates each deck separately, so a wrong-reference passage
 * lands as e.g. (rule, lw 54) and (rule, dsk 37); grouped on the live pair they
 * re-separate for free when the pair is split. The merged label is built from the
 * members' own deck/slide, not the pair's, so a 2-DSK pair where only one slide
 * tripped reads that one slide.
 */
function mergeDuplicateFindings(issues: Flag[], leftLabel: string, rightLabel: string): Flag[] {
  const groups = new Map<string, Flag[]>();
  const order: string[] = [];
  for (const flag of issues) {
    const key = `${flag.rule || flag.title || ""}\u0000${flag.message}`;
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)!.push(flag);
  }
  const out: Flag[] = [];
  for (const key of order) {
    const members = groups.get(key)!;
    const distinct = new Map<string, Flag>();
    for (const member of members) distinct.set(`${(member.deck || "").toLowerCase()}\u0000${member.slide}`, member);
    if (distinct.size <= 1) {
      out.push(...members);
      continue;
    }
    const primary = [...members].sort((a, b) => (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9))[0];
    const location = [...distinct.values()].map((member) => deckSlideLabel(member, leftLabel, rightLabel)).join(" + ");
    out.push({ ...primary, location, evidence: members.find((member) => member.evidence)?.evidence });
  }
  return out;
}

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

function PairSplit({
  pct,
  onPct,
  onActivate,
}: {
  pct: number;
  onPct: (n: number, rowEl?: HTMLElement | null) => void;
  onActivate?: () => void;
}) {
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
        onActivate?.();
        const parent = event.currentTarget.parentElement?.getBoundingClientRect();
        const rowEl = event.currentTarget.closest(".diff-row") as HTMLElement | null;
        if (!parent?.width) return;
        const startX = event.clientX;
        const startPct = pct;
        const onMove = (ev: PointerEvent) => {
          onPct(Math.min(85, Math.max(20, startPct + ((ev.clientX - startX) / parent.width) * 100)), rowEl);
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
  wide,
  draggable,
  onOpen,
  onDragStart,
}: {
  job: Job;
  side: "left" | "right";
  png?: string;
  label: string;
  crop?: boolean;
  wide?: boolean;
  draggable?: boolean;
  onOpen: (src: string) => void;
  onDragStart?: () => void;
}) {
  const artifact = side === "left" ? "left previews" : "right previews";
  const src = png && present(job, artifact) ? diffImageUrl(job.id, side, png) : "";
  return (
    <div
      className={`slide-slot${crop ? (wide ? " full-wall" : " crop-center") : " dsk-frame"}`}
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
  onSaveSlots,
  onStartFresh,
  checking,
}: {
  job: Job;
  onOpen: (src: string) => void;
  onRunChecks?: (slots: Slot[]) => void;
  onSaveSlots?: (slots: Slot[]) => void | Promise<void>;
  onStartFresh?: () => void;
  checking?: boolean;
}) {
  const result = (job.result || null) as DiffResult | null;
  const { focusMode, setFocusMode } = useLayout();
  const [showInfo, setShowInfo] = useSessionToggle(SHOW_INFO_KEY, false);
  const [sidePanels, setSidePanels] = useSessionToggle(SIDE_PANELS_KEY, false);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [selected, setSelected] = useState(0);
  const [split, setSplit] = useState<number | null>(() => {
    const n = loadSplit(Number.NaN);
    return Number.isFinite(n) ? n : null;
  });
  const [dragging, setDragging] = useState<{ side: "left" | "right"; index: number } | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [saving, setSaving] = useState(false);
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
          outlineRow: result.pairs[i]?.outlineRow,
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
  const rawDeck = matching ? [] : (result.flags || []).filter((flag) => flag.category !== "diff");
  const deckFlags = rawDeck.filter((flag) => !pairs.some((pair) => flagOnPair(flag, pair)));
  // Cue-grammar findings are about the script, so they sit under the pairs
  // rather than competing with them.
  const outlineFlags = result.outlineFlags || [];
  const leftWide = isWideDeck(result.leftLabel);
  const rightWide = isWideDeck(result.rightLabel);
  const pairLayout = leftWide && rightWide ? "lw-lw" : leftWide ? "lw-dsk" : rightWide ? "dsk-lw" : "dsk-dsk";
  const leftPct = split ?? defaultSplit();

  function setSplitPct(next: number, rowEl?: HTMLElement | null) {
    const row = rowEl || (stackRef.current?.querySelector(".diff-row.on") as HTMLElement | null);
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

  async function handleSave() {
    if (!onSaveSlots) return;
    setSaving(true);
    try {
      await onSaveSlots(slots);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
        {result.reuse?.used !== false && result.reuse && (result.reuse.carried > 0 || result.reuse.added > 0) && (
          <div className="reuse-banner">
            <span>
              Reused {result.reuse.carried} pairing{result.reuse.carried === 1 ? "" : "s"} from an earlier run.
              {result.reuse.changed ? ` ${result.reuse.changed} slide${result.reuse.changed === 1 ? "" : "s"} changed.` : ""}
              {result.reuse.added ? ` ${result.reuse.added} added.` : ""}
              {result.reuse.removed ? ` ${result.reuse.removed} removed.` : ""}
            </span>
            {onStartFresh && (
              <button className="btn secondary" type="button" disabled={checking} onClick={onStartFresh}>
                Start fresh
              </button>
            )}
          </div>
        )}
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
            {canEdit && onSaveSlots && (
              <button
                className={`btn save-pairing${savedFlash ? " saved" : ""}`}
                type="button"
                disabled={checking || saving}
                onClick={() => void handleSave()}
              >
                {savedFlash ? "Pairing saved!" : "Save pairing"}
              </button>
            )}
            {(leftWide || rightWide) && (
              <button
                className={`btn secondary toggle${sidePanels ? " on" : ""}`}
                type="button"
                aria-pressed={sidePanels}
                title="Show the full 7680×1080 wall instead of the 3840×1080 center"
                onClick={() => setSidePanels(!sidePanels)}
              >
                {sidePanels ? "Center wall only" : "Show side panels"}
              </button>
            )}
            <button
              className={`btn secondary toggle${showInfo ? " on" : ""}`}
              type="button"
              aria-pressed={showInfo}
              title="Info findings are notes rather than problems"
              onClick={() => setShowInfo(!showInfo)}
            >
              {showInfo ? "Hide info findings" : "Show info findings"}
            </button>
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
          const extra = rawDeck.filter(
            (flag) =>
              flagOnPair(flag, pair) &&
              !(pair.flags || []).some(
                (own) => own.rule === flag.rule && own.slide === flag.slide && own.message === flag.message
              )
          );
          const issues = mergeDuplicateFindings([...(pair.flags || []), ...extra], result.leftLabel, result.rightLabel);
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
                  wide={sidePanels}
                  draggable={pair.leftIndex != null}
                  onOpen={onOpen}
                  onDragStart={() => pair.leftIndex != null && setDragging({ side: "left", index: pair.leftIndex })}
                />
                <PairSplit pct={leftPct} onPct={setSplitPct} onActivate={() => setSelected(row)} />
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
                        wide={sidePanels}
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
                    wide={sidePanels}
                    draggable={pair.rightIndex != null}
                    onOpen={onOpen}
                    onDragStart={() => pair.rightIndex != null && setDragging({ side: "right", index: pair.rightIndex })}
                  />
                )}
              </div>
              {canEdit && slots[row] && (
                <div className="row-acts">
                  {canCombineNext(slots, row) && (
                    <button
                      className="btn consolidate"
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
                      className="btn separate"
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setSlots((current) => splitRights(current, row));
                      }}
                    >
                      Split {result.rightLabel}s
                    </button>
                  )}
                  <button
                    className="btn consolidate"
                    type="button"
                    disabled={shiftColumn(slots, "right", row, -1) === slots}
                    title={`Move this and later ${result.rightLabel} slides up one, from this slide`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSlots((current) => shiftColumn(current, "right", row, -1));
                    }}
                  >
                    Shift {result.rightLabel} ↑
                  </button>
                  <button
                    className="btn separate"
                    type="button"
                    title={`Move this and later ${result.rightLabel} slides down one, from this slide`}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSlots((current) => shiftColumn(current, "right", row, 1));
                    }}
                  >
                    Shift {result.rightLabel} ↓
                  </button>
                </div>
              )}
              {pair.outlineRow && (
                <OutlineStrip
                  row={pair.outlineRow}
                  holds={
                    pair.outlineRow.tags.length === 1
                      ? /^dsk/i.test(pair.outlineRow.tags[0])
                        ? result.leftLabel
                        : result.rightLabel
                      : undefined
                  }
                />
              )}
              {issues.length > 0 && (
                <SlideFindings flags={issues} jobId={job.id} showInfo={showInfo} onOpen={onOpen} />
              )}
            </article>
          );
        })}
      </div>
      {deckFlags.length > 0 && (
        <ValidationPanel
          flags={deckFlags}
          jobId={job.id}
          onOpen={onOpen}
          showInfo={showInfo}
          onShowInfo={setShowInfo}
          title="Deck-wide findings"
        />
      )}
      {outlineFlags.length > 0 && (
        <ValidationPanel
          flags={outlineFlags}
          jobId={job.id}
          onOpen={onOpen}
          showInfo={showInfo}
          onShowInfo={setShowInfo}
          title="Outline findings"
        />
      )}
    </>
  );
}
