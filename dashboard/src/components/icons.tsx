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

export function IconLibrary({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M16.5 4.5v15" />
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

export function IconGlobe({ className }: IconProps) {
  return (
    <svg {...base} className={cls(className)}>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M3.8 12h16.4M12 3.8c2.4 2.6 3.6 5.4 3.6 8.2s-1.2 5.6-3.6 8.2c-2.4-2.6-3.6-5.4-3.6-8.2s1.2-5.6 3.6-8.2z" />
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
