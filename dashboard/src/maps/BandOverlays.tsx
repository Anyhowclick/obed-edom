import type { ObjectCorner } from "./objects";
import { objectBoxStyle } from "./types";

type Box = { x: number; y: number; w: number; h: number };

type Props = {
  splitCg: boolean;
  fullWall: boolean;
  exportCg: boolean;
  cgLeft: number;
  cgWidth: number;
  cgSnapped: boolean;
  box: Box | null;
  k: number;
  bandTop: number;
  onCgPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
  onCgPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
  onCgPointerUp: (event: React.PointerEvent<HTMLElement>) => void;
  onHandlePointerDown: (corner: ObjectCorner) => (event: React.PointerEvent<HTMLDivElement>) => void;
  onHandlePointerMove: (event: React.PointerEvent<HTMLDivElement>) => void;
  onHandlePointerUp: (event: React.PointerEvent<HTMLDivElement>) => void;
};

const CORNERS: ObjectCorner[] = ["nw", "ne", "sw", "se"];

/** Renders after `.maps-map-inner` as a sibling in `.maps-map-band` so the object box/handles
 * paint above the CG/LW crop overlay (both are band-local: `k`/`bandTop` map authored coords the
 * same way the inner transform does, see objectBoxStyle). */
export function BandOverlays({
  splitCg,
  fullWall,
  exportCg,
  cgLeft,
  cgWidth,
  cgSnapped,
  box,
  k,
  bandTop,
  onCgPointerDown,
  onCgPointerMove,
  onCgPointerUp,
  onHandlePointerDown,
  onHandlePointerMove,
  onHandlePointerUp,
}: Props) {
  return (
    <>
      <div className="maps-crop-overlay">
        {splitCg ? (
          <div className="maps-crop-frame cg">
            <span className="maps-crop-cg-label">CG</span>
          </div>
        ) : fullWall ? (
          <div className="maps-crop-frame fw">
            <span className="maps-crop-fw-label">FW</span>
          </div>
        ) : (
          <div className="maps-crop-frame center" style={{ inset: 0 }} />
        )}
        {exportCg && !splitCg && (
          <div
            className={`maps-crop-cg${cgSnapped ? " snapped" : ""}`}
            style={{ left: `${cgLeft}%`, width: `${cgWidth}%` }}
            onPointerDown={onCgPointerDown}
            onPointerMove={onCgPointerMove}
            onPointerUp={onCgPointerUp}
            onPointerCancel={onCgPointerUp}
          >
            <span className="maps-crop-cg-label">CG</span>
          </div>
        )}
      </div>
      {cgSnapped && <div className="maps-snap-guide" />}
      {box && (
        <div className="maps-object-layer">
          <div className="maps-object-box" style={objectBoxStyle(box, k, bandTop)}>
            {CORNERS.map((corner) => (
              <div
                key={corner}
                className={`maps-object-handle ${corner}`}
                onPointerDown={onHandlePointerDown(corner)}
                onPointerMove={onHandlePointerMove}
                onPointerUp={onHandlePointerUp}
                onPointerCancel={onHandlePointerUp}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
}
