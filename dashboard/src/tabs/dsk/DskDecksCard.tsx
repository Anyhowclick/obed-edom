import { useState, type DragEvent } from "react";
import type { ChosenFile } from "../../api";
import { resolveDroppedKeynote } from "../../dropPath";

function folderOf(path: string): string {
  const idx = path.lastIndexOf("/");
  return idx > 0 ? path.slice(0, idx) : path;
}

type Props = {
  dskTemplate: ChosenFile | null;
  templateError: string | null;
  onChooseTemplate: () => void;
  onTemplatePath: (path: string) => void;
  onForgetTemplate: () => void;
  referenceDeck: ChosenFile | null;
  onChooseReference: () => void;
  onReferencePath: (path: string) => void;
  onClearReference: () => void;
  onDropError: (message: string) => void;
};

/** Merges the DSK template + reference deck wells into one "DSK decks" card. */
export function DskDecksCard({
  dskTemplate,
  templateError,
  onChooseTemplate,
  onTemplatePath,
  onForgetTemplate,
  referenceDeck,
  onChooseReference,
  onReferencePath,
  onClearReference,
  onDropError,
}: Props) {
  const [templateOver, setTemplateOver] = useState(false);
  const [referenceOver, setReferenceOver] = useState(false);
  const errorId = "dsk-template-error";
  const describedBy = templateError ? errorId : undefined;

  async function handleDrop(e: DragEvent, onPath: (path: string) => void, setOver: (v: boolean) => void) {
    e.preventDefault();
    setOver(false);
    const resolved = await resolveDroppedKeynote(e.dataTransfer);
    if ("path" in resolved) {
      onPath(resolved.path);
      return;
    }
    onDropError(resolved.error);
  }

  return (
    <div className="col well-tone-dsk">
      <div className="well dsk dsk-decks">
        <strong>DSK decks</strong>
        <div
          className={`dsk-deck-row${templateOver ? " over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setTemplateOver(true);
          }}
          onDragLeave={() => setTemplateOver(false)}
          onDrop={(e) => void handleDrop(e, onTemplatePath, setTemplateOver)}
        >
          <div className="dsk-deck-row-label">DSK template</div>
          {dskTemplate ? (
            <>
              <p className="dsk-deck-row-name">
                {dskTemplate.name}
                <span className="dsk-deck-badge">default</span>
              </p>
              <p className="dsk-deck-row-path">{folderOf(dskTemplate.path)}</p>
              <div className="actions">
                <button
                  className="btn secondary"
                  type="button"
                  aria-label="Change DSK template"
                  aria-describedby={describedBy}
                  onClick={onChooseTemplate}
                >
                  Change
                </button>
                <button className="btn secondary" type="button" aria-label="Forget DSK template" onClick={onForgetTemplate}>
                  Forget
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="note">
                Optional. Used only when neither the wall deck nor the reference deck has a transparent
                Blank Black layout, or when text verses are reformatted. Remembered on this Mac, shared
                with Sermon Base Generator.
              </p>
              <div className="actions">
                <button
                  className="btn secondary"
                  type="button"
                  aria-describedby={describedBy}
                  onClick={onChooseTemplate}
                >
                  Choose on this Mac
                </button>
              </div>
            </>
          )}
          {templateError ? (
            <p className="field-error" id={errorId} role="alert">
              {templateError}
            </p>
          ) : null}
        </div>
        <div
          className={`dsk-deck-row${referenceOver ? " over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setReferenceOver(true);
          }}
          onDragLeave={() => setReferenceOver(false)}
          onDrop={(e) => void handleDrop(e, onReferencePath, setReferenceOver)}
        >
          <div className="dsk-deck-row-label">Reference deck</div>
          <p className="note">Optional. A finished DSK deck to measure the video band from.</p>
          {referenceDeck ? (
            <>
              <p className="dsk-deck-row-name">{referenceDeck.name}</p>
              <div className="actions">
                <button className="btn secondary" type="button" aria-label="Clear reference deck" onClick={onClearReference}>
                  Clear
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="dsk-deck-row-name muted">Standard video band</p>
              <div className="actions">
                <button className="btn secondary" type="button" aria-label="Choose reference deck" onClick={onChooseReference}>
                  Choose
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
