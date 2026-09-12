/* One icon family: 24-grid, 1.8 stroke, round caps, sized by --icon-size. */
type IconProps = { className?: string };

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

function cls(...names: (string | undefined)[]): string {
  return ["ui-icon", ...names].filter(Boolean).join(" ");
}

export function IconPlus({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconCaret({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M7 10l5 5 5-5" />
    </svg>
  );
}

export function IconPlay({ className }: IconProps) {
  return (
    <svg {...base} className={cls("filled", className)}>
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

export function IconTrash({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M7 7h10M9.5 7V6a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 6v1M8 7l.7 12.5h6.6L16 7" />
    </svg>
  );
}

export function IconTick({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

export function IconPanelRight({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M16.5 4.5v15" />
      <rect className="fill-on" x="16.5" y="4.5" width="4" height="15" />
    </svg>
  );
}

export function IconLayers({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M12 4.2 21 8.5 12 12.8 3 8.5 12 4.2z" />
      <path d="M5.2 12.2 12 15.5l6.8-3.3" />
      <path d="M5.2 16.2 12 19.5l6.8-3.3" />
    </svg>
  );
}

export function IconRelief({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M3 17 8.5 8l4 6.5L15 10l6 7" />
    </svg>
  );
}

export function IconLabel({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M4 8h11l4 4-4 4H4z" />
    </svg>
  );
}

export function IconLabelOff({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M4 8h11l4 4-4 4H4z" />
      <path d="M4 20 20 4" />
    </svg>
  );
}

export function IconCopy({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="8.5" y="8.5" width="11" height="11" rx="1.5" />
      <path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
    </svg>
  );
}

export function IconPaste({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="5.5" y="5.5" width="13" height="15" rx="1.5" />
      <rect x="9" y="3.5" width="6" height="3.5" rx="1" />
    </svg>
  );
}

export function IconPasteSlides({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="3.5" y="5.5" width="11" height="14" rx="1.5" />
      <rect x="7" y="3.5" width="4" height="3" rx="0.8" />
      <path d="M15.5 12h5M17.5 9.5 20.5 12l-3 2.5" />
    </svg>
  );
}

export function IconTiles({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16" />
      <rect className="fill-on" x="4" y="4" width="5.3" height="5.3" />
    </svg>
  );
}

export function IconOpen({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M14 4h6v6M20 4 10 14M10 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-4" />
    </svg>
  );
}

export function IconFolder({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l1.6 2H19.5A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5z" />
    </svg>
  );
}

export function IconExpand({ className, collapse }: IconProps & { collapse?: boolean }) {
  return (
    <svg {...base} className={cls(className)}>
      <path d={collapse ? "M9 3v6H3M15 3v6h6M9 21v-6H3M15 21v-6h6" : "M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"} />
    </svg>
  );
}

export function IconFilter({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M4 5.5h16l-6.2 7.3v5.4l-3.6 1.8v-7.2z" />
    </svg>
  );
}

export function IconPencil({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z" />
    </svg>
  );
}

export function IconClose({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

export function IconChevronLeft({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M14.5 6l-6 6 6 6" />
    </svg>
  );
}

export function IconArrowLeft({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M19 12H5M11 6l-6 6 6 6" />
    </svg>
  );
}

/* Circular arrow back to a start bar — not undo's plain circular arrow. */
export function IconRevert({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M17.7 2.8v3.6h-3.6" />
      <path d="M3 9v6" />
    </svg>
  );
}

export function IconDot({ className }: IconProps) {
  return (
    <svg {...base} className={cls("filled", className)}>
      <circle cx="12" cy="12" r="4.5" />
    </svg>
  );
}

export function IconDropPin({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M12 21s6.5-6.1 6.5-10.2A6.5 6.5 0 0 0 5.5 10.8C5.5 14.9 12 21 12 21z" />
      <circle cx="12" cy="10.5" r="2.3" />
    </svg>
  );
}

export function IconLandmark({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <path d="M3.5 10 12 4.5l8.5 5.5" />
      <path d="M6 10.5v8M10 10.5v8M14 10.5v8M18 10.5v8" />
      <path d="M4 19.5h16" />
    </svg>
  );
}

/* The watercolour toolbar keeps its 16 grid; 1.2 is the same optical weight
   as 1.8 on the 24 grid. */
export const TOOL_ICONS: Record<string, JSX.Element> = {
  rect: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2.5" y="3.5" width="11" height="9" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="2.4 2" />
    </svg>
  ),
  pen: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 12 3 6 7 3 12 5 13 10" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="3" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  ),
  magnetic: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M2.5 4 3 9.5 8 12.5 13 8" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M11 10.5v2a1.7 1.7 0 0 0 3.4 0v-2" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M11 10.5h1.1M13.3 10.5h1.1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  wand: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 13 10 6.5" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M11 3v2.2M13.8 5.8H11.6M12.6 2.4l-1.6 1.6M9.9 5.1l-1.6 1.6" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  magnifier: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="6.8" cy="6.8" r="4" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M9.7 9.7 13 13" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M6.8 5.1v3.4M5.1 6.8h3.4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  compare: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 2.5v11" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6 8 4.7 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.3 6.9 4 8l1.3 1.1M10 8h1.3M10.7 6.9 12 8l-1.3 1.1" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  reset: <IconRevert />,
  undo: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.5 8A4.5 4.5 0 1 0 5.2 4.4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.6 2.6 5.1 4.9 7.4 5.3" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  redo: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M12.5 8A4.5 4.5 0 1 1 10.8 4.4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M10.4 2.6 10.9 4.9 8.6 5.3" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  keep: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 5.5v5M5.5 8h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
  remove: (
    <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M5.5 8h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
};
