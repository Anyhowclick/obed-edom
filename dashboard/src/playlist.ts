export const MAX_COMBINED_RIGHTS = 2;

export type Slot = {
  leftIndex: number | null;
  rightIndex?: number | null;
  rightIndexes: number[];
  score?: number;
};

export type CatalogSlide = {
  index: number;
  number: number;
  skipped?: boolean;
  png?: string | null;
  text?: string;
};

type Placed = { index: number; row: number };

export function rightsOf(slot: { rightIndexes?: number[] | null; rightIndex?: number | null }): number[] {
  if (Array.isArray(slot.rightIndexes) && slot.rightIndexes.length) {
    return slot.rightIndexes.filter((index): index is number => index != null);
  }
  if (slot.rightIndex != null) return [slot.rightIndex];
  return [];
}

export function serializeSlot(slot: Slot): { leftIndex: number | null; rightIndex: number | null; rightIndexes: number[] } {
  const rightIndexes = rightsOf(slot);
  return {
    leftIndex: slot.leftIndex,
    rightIndex: rightIndexes[0] ?? null,
    rightIndexes,
  };
}

export function slotsFromPairs(
  pairs: { leftIndex?: number | null; rightIndex?: number | null; rightIndexes?: number[] | null; score?: number }[]
): Slot[] {
  return pairs.map((pair) => {
    const rightIndexes = rightsOf(pair);
    return {
      leftIndex: pair.leftIndex ?? null,
      rightIndex: rightIndexes[0] ?? null,
      rightIndexes,
      score: pair.score,
    };
  });
}

export function slotsEqual(a: Slot[], b: Slot[]): boolean {
  if (a.length !== b.length) return false;
  return a.every(
    (slot, i) => slot.leftIndex === b[i].leftIndex && rightsOf(slot).join(",") === rightsOf(b[i]).join(",")
  );
}

function positions(slots: Slot[], side: "left" | "right"): Placed[] {
  const out: Placed[] = [];
  slots.forEach((slot, row) => {
    if (side === "left") {
      if (slot.leftIndex != null) out.push({ index: slot.leftIndex, row });
      return;
    }
    for (const index of rightsOf(slot)) out.push({ index, row });
  });
  return out;
}

function fromPositions(left: Placed[], right: Placed[]): Slot[] {
  const max = Math.max(-1, ...left.map((item) => item.row), ...right.map((item) => item.row));
  const rows: Slot[] = Array.from({ length: max + 1 }, () => ({
    leftIndex: null,
    rightIndex: null,
    rightIndexes: [],
  }));
  for (const item of left) rows[item.row].leftIndex = item.index;
  for (const item of right) rows[item.row].rightIndexes.push(item.index);
  return rows
    .filter((row) => row.leftIndex != null || row.rightIndexes.length)
    .map((row) => ({ ...row, rightIndex: row.rightIndexes[0] ?? null }));
}

function setSide(slots: Slot[], side: "left" | "right", next: Placed[]): Slot[] {
  const left = side === "left" ? next : positions(slots, "left");
  const right = side === "right" ? next : positions(slots, "right");
  return fromPositions(left, right);
}

/** Insert a gap at `fromRow` in one column; that column's later slides move down. Deck order is kept. */
export function shiftColumn(slots: Slot[], side: "left" | "right", fromRow: number, dir: -1 | 1): Slot[] {
  if (fromRow < 0 || fromRow >= slots.length) return slots;
  const items = positions(slots, side);
  if (dir === 1) {
    return setSide(
      slots,
      side,
      items.map((item) => (item.row >= fromRow ? { index: item.index, row: item.row + 1 } : item))
    );
  }
  const here = items.find((item) => item.row === fromRow);
  const later = items.filter((item) => item.row > fromRow);
  if (here) {
    const prev = items.filter((item) => item.row < here.row).pop();
    const floor = prev ? prev.row + 1 : 0;
    if (here.row <= floor) return slots;
    return setSide(
      slots,
      side,
      items.map((item) => (item.row >= here.row ? { index: item.index, row: item.row - 1 } : item))
    );
  }
  if (!later.length) return slots;
  const prev = items.filter((item) => item.row < fromRow).pop();
  const floor = prev ? prev.row + 1 : 0;
  return setSide(
    slots,
    side,
    items.map((item) => {
      if (item.row <= fromRow) return item;
      return { index: item.index, row: Math.max(item.row - 1, floor) };
    })
  );
}

/** Drop a slide onto a row. Neighbors keep deck order; later items ripple down if needed. */
export function placeItem(slots: Slot[], side: "left" | "right", slideIndex: number, targetRow: number): Slot[] {
  const items = positions(slots, side);
  const order = items.findIndex((item) => item.index === slideIndex);
  if (order < 0) return slots;
  const prevRow = order > 0 ? items[order - 1].row : -1;
  const canShare = side === "right" && prevRow >= 0;
  const floor = canShare ? prevRow : prevRow + 1;
  let row = Math.max(floor, Math.max(0, targetRow));
  if (side === "right") {
    const occupying = items.filter((item, i) => i !== order && item.row === row).length;
    if (occupying >= MAX_COMBINED_RIGHTS) row = Math.max(row + 1, prevRow + 1);
  }
  return setSide(
    slots,
    side,
    items.map((item, i) => {
      if (i < order) return item;
      if (i === order) return { index: item.index, row };
      return { index: item.index, row: Math.max(item.row, row + (i - order)) };
    })
  );
}

export function combineNext(slots: Slot[], row: number): Slot[] {
  if (row < 0 || row >= slots.length - 1) return slots;
  const here = slots[row];
  const next = slots[row + 1];
  const hereRights = rightsOf(here);
  const nextRights = rightsOf(next);
  if (here.leftIndex == null || hereRights.length !== 1 || nextRights.length < 1) return slots;
  if (hereRights.length >= MAX_COMBINED_RIGHTS) return slots;
  const [taken, ...rest] = nextRights;
  const copy = slots.map((slot) => ({ ...slot, rightIndexes: [...rightsOf(slot)] }));
  copy[row] = {
    ...copy[row],
    rightIndexes: [...hereRights, taken],
    rightIndex: hereRights[0],
  };
  if (rest.length || copy[row + 1].leftIndex != null) {
    copy[row + 1] = { ...copy[row + 1], rightIndexes: rest, rightIndex: rest[0] ?? null };
  } else {
    copy.splice(row + 1, 1);
  }
  return copy;
}

export function canCombineNext(slots: Slot[], row: number): boolean {
  if (row < 0 || row >= slots.length - 1) return false;
  const here = slots[row];
  const next = slots[row + 1];
  return here.leftIndex != null && rightsOf(here).length === 1 && rightsOf(next).length >= 1;
}

export function splitRights(slots: Slot[], row: number): Slot[] {
  if (row < 0 || row >= slots.length) return slots;
  const hereRights = rightsOf(slots[row]);
  if (hereRights.length < 2) return slots;
  const [first, ...rest] = hereRights;
  const copy = slots.map((slot) => ({ ...slot, rightIndexes: [...rightsOf(slot)] }));
  copy[row] = { ...copy[row], rightIndexes: [first], rightIndex: first };
  copy.splice(row + 1, 0, { leftIndex: null, rightIndex: rest[0] ?? null, rightIndexes: rest, score: 0 });
  return copy;
}

export function rebuildPairs(
  slots: Slot[],
  leftCatalog: CatalogSlide[],
  rightCatalog: CatalogSlide[],
  leftLabel: string,
  rightLabel: string
) {
  const left = new Map(leftCatalog.map((slide) => [slide.index, slide]));
  const right = new Map(rightCatalog.map((slide) => [slide.index, slide]));
  return slots.map((slot, i) => {
    const ls = slot.leftIndex == null ? undefined : left.get(slot.leftIndex);
    const rightIndexes = rightsOf(slot).filter((index) => right.has(index));
    const rights = rightIndexes.map((index) => right.get(index)!);
    const rs = rights[0];
    return {
      index: i,
      number: i + 1,
      leftIndex: ls ? slot.leftIndex : null,
      rightIndex: rs ? rightIndexes[0] : null,
      rightIndexes,
      leftNumber: ls?.number ?? null,
      rightNumber: rs?.number ?? null,
      rightNumbers: rights.map((slide) => slide.number),
      leftSkipped: Boolean(ls?.skipped),
      rightSkipped: rights.some((slide) => slide.skipped),
      leftPng: ls?.png || undefined,
      rightPng: rs?.png || undefined,
      rightPngs: rights.map((slide) => slide.png || undefined),
      leftText: ls?.text || "",
      rightText: rights.map((slide) => slide.text || "").join("\n"),
      score: slot.score || 0,
      missing: !ls ? leftLabel : !rs ? rightLabel : undefined,
      flags: [],
    };
  });
}
