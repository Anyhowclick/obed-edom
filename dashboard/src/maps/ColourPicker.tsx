import { useEffect, useState } from "react";
import { IconClose, IconNoFill, IconPlus, IconTick } from "../components/icons";
import { isHighlightHex, normaliseHighlightColour } from "./highlight";
import { addSavedColour, removeSavedColour, useSavedColours } from "./savedColours";

export function ColourPicker({
  colour,
  text,
  none = false,
  allowNone = false,
  disabled = false,
  colourLabel = "Highlight colour",
  hexLabel = "Highlight colour hex",
  onColour,
  onText,
  onNone,
  onCommit,
}: {
  colour: string;
  text: string;
  none?: boolean;
  allowNone?: boolean;
  disabled?: boolean;
  colourLabel?: string;
  hexLabel?: string;
  onColour: (value: string) => void;
  onText: (value: string) => void;
  onNone?: () => void;
  onCommit: () => void;
}) {
  const [saved, setSaved] = useSavedColours();
  const [hexDirty, setHexDirty] = useState(false);
  const currentHex = isHighlightHex(colour || text) ? normaliseHighlightColour(colour || text) : "";
  const canAdd = Boolean(currentHex) && !saved.includes(currentHex);

  useEffect(() => {
    setHexDirty(false);
  }, [none, colour]);

  function pick(hex: string) {
    if (disabled) return;
    onColour(hex);
    onCommit();
  }

  function addCurrent() {
    if (disabled || !canAdd || !currentHex) return;
    setSaved(addSavedColour(saved, currentHex));
  }

  function remove(hex: string) {
    if (disabled) return;
    setSaved(removeSavedColour(saved, hex));
  }

  return (
    <div className="maps-colour">
      <div className="maps-colour-row">
        <span className={`maps-colour-well${none ? " none" : ""}`}>
          <input
            type="color"
            value={currentHex || "#e8772a"}
            disabled={disabled}
            aria-label={colourLabel}
            onChange={(event) => {
              onColour(event.target.value);
              onCommit();
            }}
            onClick={() => {
              if (!none || disabled || !currentHex) return;
              onColour(currentHex);
              onCommit();
            }}
          />
          {none && (
            <span className="maps-colour-swatch none" aria-hidden="true">
              <IconNoFill />
            </span>
          )}
        </span>
        <input
          type="text"
          value={none && !hexDirty ? "" : text}
          disabled={disabled}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          placeholder={none ? "No fill" : "#e8772a"}
          aria-label={hexLabel}
          onChange={(event) => {
            setHexDirty(true);
            onText(event.target.value);
          }}
          onBlur={() => {
            if (none && !hexDirty) return;
            if (none && !isHighlightHex(text)) return;
            onCommit();
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            if (none && !isHighlightHex(text)) return;
            onCommit();
          }}
        />
      </div>
      <div className="maps-swatches" role="group" aria-label="Saved colours">
        {saved.map((hex) => {
          const active = !none && currentHex === hex;
          return (
            <div key={hex} className={`maps-swatch-wrap${active ? " active" : ""}`}>
              <button
                type="button"
                aria-pressed={active}
                className={`maps-swatch${active ? " active" : ""}`}
                style={{ background: hex }}
                title={hex}
                aria-label={hex}
                disabled={disabled}
                onClick={() => pick(hex)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  remove(hex);
                }}
              >
                {active && <IconTick />}
              </button>
              <button
                type="button"
                className="maps-swatch-remove"
                aria-label={`Remove ${hex}`}
                disabled={disabled}
                onClick={() => remove(hex)}
              >
                <IconClose />
              </button>
            </div>
          );
        })}
        <button
          type="button"
          className="maps-swatch add"
          title="Save colour"
          aria-label="Save colour"
          disabled={disabled || !canAdd}
          onClick={addCurrent}
        >
          <IconPlus />
        </button>
        {allowNone && (
          <button
            type="button"
            aria-pressed={none}
            className={`maps-swatch none${none ? " active" : ""}`}
            title="No fill"
            aria-label="No fill"
            disabled={disabled}
            onClick={() => {
              if (disabled) return;
              onNone?.();
            }}
          >
            <IconNoFill />
          </button>
        )}
      </div>
    </div>
  );
}
