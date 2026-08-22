import type { Flag } from "./api";

/** One cue in the outline, as the operator wrote it. */
export type OutlineCue = {
  tag: string;
  deck: "lw" | "dsk";
  start: number;
  end: number;
  row: number;
};

/** One slide advance: the cues that trigger it and the words it calls. */
export type OutlineRow = {
  index: number;
  tags: string[];
  lw?: string | null;
  dsk?: string | null;
  paragraph: number;
  script: string;
};

export type OutlineParagraph = {
  index: number;
  number: number;
  text: string;
  cues: OutlineCue[];
  row?: number | null;
};

export type OutlineResult = {
  kind?: string;
  path?: string;
  name?: string;
  lwCues?: number;
  dskCues?: number;
  paragraphs?: OutlineParagraph[];
  rows?: OutlineRow[];
  outlineFlags?: Flag[];
  outlineReport?: string | null;
};

/** Findings raised against the outline rather than against a slide. */
export function isOutlineFlag(flag: Flag): boolean {
  return (flag.deck || "").toLowerCase() === "outline";
}

export function rowsByIndex(rows: OutlineRow[] | undefined): Map<number, OutlineRow> {
  const out = new Map<number, OutlineRow>();
  for (const row of rows || []) out.set(row.index, row);
  return out;
}
