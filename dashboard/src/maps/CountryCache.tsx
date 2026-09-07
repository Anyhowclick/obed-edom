import { useEffect, useMemo, useRef, useState } from "react";
import { loadAdmin0 } from "./overlays";

export const PINNED_CACHE_COUNTRIES = ["PHL", "IND", "IDN", "MYS"] as const;

type CountryRow = { code: string; name: string };

function sortCacheCountries(rows: CountryRow[]): CountryRow[] {
  const pin = new Map<string, number>(PINNED_CACHE_COUNTRIES.map((code, index) => [code, index]));
  return [...rows].sort((a, b) => {
    const pa = pin.get(a.code);
    const pb = pin.get(b.code);
    if (pa != null && pb != null) return pa - pb;
    if (pa != null) return -1;
    if (pb != null) return 1;
    return a.name.localeCompare(b.name);
  });
}

function IconGlobe() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8.2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path
        d="M3.8 12h16.4M12 3.8c2.4 2.6 3.6 5.4 3.6 8.2s-1.2 5.6-3.6 8.2c-2.4-2.6-3.6-5.4-3.6-8.2s1.2-5.6 3.6-8.2z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function CountryCachePicker({
  selected,
  disabled,
  onToggle,
}: {
  selected: string[];
  disabled?: boolean;
  onToggle: (code: string, nextSelected: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [rows, setRows] = useState<CountryRow[]>([]);
  const root = useRef<HTMLDivElement | null>(null);
  const picked = useMemo(() => new Set(selected.map((code) => code.toUpperCase())), [selected]);

  useEffect(() => {
    void loadAdmin0().then((admin) => {
      if (!admin) return;
      const next: CountryRow[] = [];
      const seen = new Set<string>();
      for (const feat of admin.features) {
        const code = String(feat.properties?.ADM0_A3 || "").toUpperCase();
        const name = String(feat.properties?.NAME || "").trim();
        if (!code || !name || seen.has(code)) continue;
        seen.add(code);
        next.push({ code, name });
      }
      setRows(sortCacheCountries(next));
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    function onDoc(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const q = filter.trim().toLowerCase();
  const visible = q
    ? rows.filter((row) => row.name.toLowerCase().includes(q) || row.code.toLowerCase().includes(q))
    : rows;
  const pinnedSet = new Set<string>(PINNED_CACHE_COUNTRIES);
  const pinned = visible.filter((row) => pinnedSet.has(row.code));
  const rest = visible.filter((row) => !pinnedSet.has(row.code));

  function toggle(code: string) {
    const has = picked.has(code);
    const next = has ? selected.filter((item) => item.toUpperCase() !== code) : [...selected, code];
    onToggle(code, next);
  }

  return (
    <div className="maps-layers" ref={root}>
      <button
        className={`btn secondary icon-btn maps-layers-btn${open || selected.length ? " on" : ""}`}
        type="button"
        aria-expanded={open}
        aria-haspopup="true"
        title={selected.length ? `Tile cache · ${selected.length} countries` : "Countries to cache"}
        aria-label={selected.length ? `Tile cache, ${selected.length} countries` : "Countries to cache"}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <IconGlobe />
        {selected.length ? <span className="maps-layers-count">{selected.length}</span> : null}
      </button>
      {open && (
        <div className="maps-layers-menu maps-cache-menu" role="group" aria-label="Countries to cache">
          <input
            className="maps-cache-search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Find a country"
            disabled={disabled}
          />
          <p className="note maps-cache-hint">Pins PH · IN · ID · MY first. Checking a country prefetches its low-zoom tiles.</p>
          {(q ? visible : [...pinned, ...rest]).length === 0 && <p className="note">No matches.</p>}
          {!q &&
            pinned.map((row) => (
              <label key={row.code} className="maps-layers-item">
                <input
                  type="checkbox"
                  checked={picked.has(row.code)}
                  disabled={disabled}
                  onChange={() => toggle(row.code)}
                />
                {row.name}
              </label>
            ))}
          {!q && pinned.length > 0 && rest.length > 0 && <hr className="maps-cache-rule" />}
          {(q ? visible : rest).map((row) => (
            <label key={row.code} className="maps-layers-item">
              <input
                type="checkbox"
                checked={picked.has(row.code)}
                disabled={disabled}
                onChange={() => toggle(row.code)}
              />
              {row.name}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
