import { useEffect, useRef, useState } from "react";
import { chooseFolder, getSettings, putSettings, type Settings } from "../api";
import { ErrorNotice } from "../components/ErrorNotice";
import { refreshDefaultExportDir, refreshHighlightColour } from "../prefs";
import { DEFAULT_HIGHLIGHT_COLOUR, normaliseHighlightColour } from "../maps/highlight";

const COLOUR_DEBOUNCE_MS = 250;

export function SettingsTab() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [colourText, setColourText] = useState("");
  const colourDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingColourRef = useRef<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((next) => {
        setSettings(next);
        setColourText(next.highlightColour);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    return () => {
      if (colourDebounceRef.current) {
        clearTimeout(colourDebounceRef.current);
        colourDebounceRef.current = null;
        if (pendingColourRef.current !== null) commitColourValue(pendingColourRef.current);
      }
    };
  }, []);

  async function update(next: Partial<Settings>) {
    setError(null);
    setSaved(false);
    try {
      const written = await putSettings(next);
      setSettings(written);
      setColourText(written.highlightColour);
      setSaved(true);
      if (next.defaultExportDir !== undefined) refreshDefaultExportDir();
      if (next.highlightColour !== undefined) refreshHighlightColour();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function commitColourValue(value: string) {
    if (colourDebounceRef.current) {
      clearTimeout(colourDebounceRef.current);
      colourDebounceRef.current = null;
    }
    pendingColourRef.current = null;
    const trimmed = value.trim();
    const hex = trimmed.startsWith("#") ? trimmed.slice(1) : trimmed;
    const valid = /^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$/.test(hex);
    const colour = valid ? normaliseHighlightColour(value) : DEFAULT_HIGHLIGHT_COLOUR;
    setColourText(colour);
    if (colour === settings?.highlightColour) return;
    void update({ highlightColour: colour });
  }

  function commitColourText() {
    commitColourValue(colourText);
  }

  function scheduleColourCommit(value: string) {
    setColourText(value);
    if (colourDebounceRef.current) clearTimeout(colourDebounceRef.current);
    pendingColourRef.current = value;
    colourDebounceRef.current = setTimeout(() => {
      colourDebounceRef.current = null;
      commitColourValue(value);
    }, COLOUR_DEBOUNCE_MS);
  }

  const threshold = Math.round((settings?.reuseThreshold ?? 0.6) * 100);

  return (
    <div className="settings-tab">
      <h1>Settings</h1>
      <p className="lede">
        Hot reload reuses pairings and exported previews when you open the same decks or folders
        again. Turn either off, or raise the match threshold, if a re-export should always start
        fresh.
      </p>
      <ErrorNotice message={error} onDismiss={() => setError(null)} />
      {!settings ? (
        <p className="muted">Loading…</p>
      ) : (
        <div className="settings-card">
          <label className="settings-row">
            <input
              type="checkbox"
              checked={settings.reusePairings}
              onChange={(event) => update({ reusePairings: event.target.checked })}
            />
            <span>Reuse saved pairings when the same decks or folders are opened again</span>
          </label>
          <label className="settings-row">
            <input
              type="checkbox"
              checked={settings.reusePreviews}
              onChange={(event) => update({ reusePreviews: event.target.checked })}
            />
            <span>Skip Keynote export when the .key content hash is unchanged</span>
          </label>
          <label className="settings-block">
            <span>
              Start fresh when fewer than {threshold}% of slides still match
            </span>
            <input
              type="range"
              min={30}
              max={95}
              step={5}
              value={threshold}
              onChange={(event) => update({ reuseThreshold: Number(event.target.value) / 100 })}
            />
          </label>
          <label className="settings-block">
            <span>Default export destination for finished decks, PDFs, and photos</span>
            <div className="settings-row">
              <span className="muted">{settings.defaultExportDir || "output/ (default)"}</span>
              <button
                className="btn secondary"
                type="button"
                onClick={async () => {
                  try {
                    const chosen = await chooseFolder("Choose a default export folder");
                    await update({ defaultExportDir: chosen.path });
                  } catch (err) {
                    setError(err instanceof Error ? err.message : String(err));
                  }
                }}
              >
                Choose…
              </button>
              {settings.defaultExportDir && (
                <button className="btn secondary" type="button" onClick={() => update({ defaultExportDir: "" })}>
                  Use output/
                </button>
              )}
            </div>
          </label>
          <label className="settings-block">
            <span>Highlight colour for selected countries and regions</span>
            <div className="settings-row">
              <input
                type="color"
                value={normaliseHighlightColour(colourText || settings.highlightColour)}
                onChange={(event) => scheduleColourCommit(event.target.value)}
                onBlur={commitColourText}
                aria-label="Highlight colour"
              />
              <input
                type="text"
                value={colourText}
                onChange={(event) => setColourText(event.target.value)}
                onBlur={commitColourText}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitColourText();
                }}
                aria-label="Highlight colour hex"
              />
            </div>
          </label>
          {saved && <p className="ok">Saved.</p>}
        </div>
      )}
    </div>
  );
}
