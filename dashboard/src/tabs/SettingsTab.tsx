import { useEffect, useState } from "react";
import { chooseFolder, getSettings, putSettings, type Settings } from "../api";
import { ErrorNotice } from "../components/ErrorNotice";

export function SettingsTab() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  async function update(next: Partial<Settings>) {
    setError(null);
    setSaved(false);
    try {
      const written = await putSettings(next);
      setSettings(written);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
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
                <button type="button" onClick={() => update({ defaultExportDir: "" })}>
                  Use output/
                </button>
              )}
            </div>
          </label>
          {saved && <p className="ok">Saved.</p>}
        </div>
      )}
    </div>
  );
}
