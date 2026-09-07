import { useEffect, useMemo, useRef, useState } from "react";
import {
  bootstrapMapsCsv,
  bootstrapMapsPinsCsv,
  downloadMapsSession,
  exportMaps,
  cancelMapsExport,
  fetchMapsExportPlan,
  geocodeMaps,
  listJobs,
  loadMapsSession,
  pollJob,
  postMapsFrame,
  postMapsPng,
  prefetchMapsTiles,
  previewUrl,
  saveMapsState,
  startMaps,
  type Job,
} from "../api";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingOverlay } from "../components/PreviewGrid";
import { useRunNav } from "../nav";
import { MAPS_INSPECTOR_KEY, MAPS_SIDE_PANELS_KEY, useSessionToggle } from "../prefs";
import { useCurrentJob } from "../sessions";
import { AeScrub } from "../maps/AeScrub";
import { captureExportRaster } from "../maps/captureExport";
import { autoCruiseZoom, cameraAtHop, captureFlyFrames } from "../maps/captureFly";
import { CountryCachePicker } from "../maps/CountryCache";
import { HopTimeline } from "../maps/HopTimeline";
import { MorphGates } from "../maps/MorphGates";
import { MapView, type MapViewHandle } from "../maps/MapView";
import { admin0Name, loadAdmin0 } from "../maps/overlays";
import { stampOsm } from "../maps/stampOsm";
import { STYLE_SWATCHES } from "../maps/styles";
import {
  CG_SHIFT_MAX,
  DEFAULT_HIDDEN_LAYERS,
  HOP_LABELS,
  LAYER_FILTERS,
  MAX_LAT,
  authoredSurfaceWidth,
  captureWidth,
  slideForAudience,
  clampCgShift,
  clampZoom,
  coerceHopKinds,
  documentFromResult,
  minZoomForView,
  worldCopyWarning,
  nextPinId,
  nextSlideId,
  suggestedHopKind,
  type MapsCamera,
  type MapsAudience,
  type MapsChurch,
  type MapsDocument,
  type MapsEasing,
  type MapsHopKind,
  type MapsLayerFilterId,
  type MapsLink,
  type MapsPinKind,
  type MapsSlide,
  type MapsStyleId,
} from "../maps/types";

const HOP_TIPS: Record<MapsHopKind, string> = {
  morph: "Magic Move: Keynote pan/zoom of a shared plate. Same map style, same bearing, no 3D, zoom change ≤ 2. Region highlights must match; panning off-screen is fine.",
  movie: "Movie: rendered fly when pitch, bearing changes, 3D buildings, or the shared plate is too large. Use any combination of zoom out, move, and zoom in.",
  dissolve: "Dissolve: Keynote crossfade of the two stills, using the duration below.",
  cut: "Cut: instant switch. No Keynote transition.",
};

type InspectorTab = "properties" | "pins" | "animation" | "export";

const INSPECTOR_TABS: { id: InspectorTab; label: string }[] = [
  { id: "properties", label: "Properties" },
  { id: "pins", label: "Pins" },
  { id: "animation", label: "Animation" },
  { id: "export", label: "Export" },
];

function IconPlay() {
  return (
    <svg className="maps-icon filled" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function IconTrash() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M7 7h10M9.5 7V6a1.5 1.5 0 0 1 1.5-1.5h2A1.5 1.5 0 0 1 14.5 6v1M8 7l.7 12.5h6.6L16 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconLibrary() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M16.5 4.5v15" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function IconLayers() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 4.2 21 8.5 12 12.8 3 8.5 12 4.2z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M5.2 12.2 12 15.5l6.8-3.3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.2 16.2 12 19.5l6.8-3.3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconRelief() {
  return (
    <svg className="maps-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 17 8.5 8l4 6.5L15 10l6 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function cloneSlide(slide: MapsSlide, id: string): MapsSlide {
  return {
    ...slide,
    id,
    churches: [],
    stillPng: undefined,
    cg: slide.cg
      ? {
          ...slide.cg,
          camera: { ...slide.cg.camera },
          highlights: [...slide.cg.highlights],
          churches: [],
          stillPng: undefined,
          movieMov: undefined,
        }
      : undefined,
    cgShiftX: slide.cgShiftX,
    cgShiftY: 0,
    includeSidePanels: slide.includeSidePanels === true,
  };
}

function linkBetween(links: MapsLink[], from: string, to: string): MapsLink | undefined {
  return links.find((link) => link.from === from && link.to === to);
}

export function MapsTab() {
  const { openRun, clearOpenRun } = useRunNav();
  const { job: opened, error: openError } = useCurrentJob("maps");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeAudience, setActiveAudience] = useState<MapsAudience>("lw");
  const [selectedPin, setSelectedPin] = useState<string | null>(null);
  const [selectedPins, setSelectedPins] = useState<string[]>([]);
  const [renamingSlide, setRenamingSlide] = useState<{ id: string; title: string } | null>(null);
  const [inspTab, setInspTab] = useState<InspectorTab>("properties");
  const [previewing, setPreviewing] = useState(false);
  const [previewView, setPreviewView] = useState<MapsSlide | null>(null);
  const [dissolveFrame, setDissolveFrame] = useState<{ url: string; fading: boolean; duration: number } | null>(null);
  const [exporting, setExporting] = useState(false);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const mapRef = useRef<MapViewHandle | null>(null);
  const jobRef = useRef<Job | null>(null);
  const docRef = useRef<MapsDocument | null>(null);
  const activeRef = useRef<string | null>(null);
  const activeAudienceRef = useRef<MapsAudience>("lw");
  const previewingRef = useRef(false);
  const exportingRef = useRef(false);
  const previewAbort = useRef(false);
  const previewRun = useRef(0);
  const exportAbort = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const saveInFlight = useRef<Promise<Job> | null>(null);
  const cachePrefetches = useRef<Set<Promise<void>>>(new Set());
  const csvInput = useRef<HTMLInputElement | null>(null);
  const csvMode = useRef<"append" | "replace" | "pins">("append");
  const sessionInput = useRef<HTMLInputElement | null>(null);
  const savedCamera = useRef<MapsCamera | null>(null);
  const dissolveUrl = useRef<string | null>(null);
  const [navW, setNavW] = useState(() => {
    const raw = Number(window.localStorage.getItem("obed-edom.maps.navW"));
    return Number.isFinite(raw) && raw >= 160 ? Math.min(420, raw) : 220;
  });
  const navDrag = useRef<{ x: number; w: number } | null>(null);
  const [sidePanels, setSidePanels] = useSessionToggle(MAPS_SIDE_PANELS_KEY, true);
  const [inspectorOpen, setInspectorOpen] = useSessionToggle(MAPS_INSPECTOR_KEY, true);
  const [layersOpen, setLayersOpen] = useState(false);
  const layersRef = useRef<HTMLDivElement | null>(null);
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const addMenuRef = useRef<HTMLDivElement | null>(null);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const sessionMenuRef = useRef<HTMLDivElement | null>(null);
  const [namesTick, setNamesTick] = useState(0);

  useEffect(() => {
    void loadAdmin0().then(() => setNamesTick((n) => n + 1));
  }, []);

  const doc = documentFromResult(job?.result as Record<string, unknown> | undefined);
  jobRef.current = job;
  docRef.current = doc;
  activeRef.current = activeId;
  activeAudienceRef.current = activeAudience;
  previewingRef.current = previewing;

  const slides = doc?.slides || [];
  const active = slides.find((s) => s.id === activeId) || slides[0] || null;
  const activeView = active ? slideForAudience(active, activeAudience) : null;
  const activeHiddenLayers = activeView?.hiddenLayers ?? doc?.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS;
  const activeHillshade = activeView?.hillshade === true;
  const renderedView = previewView || activeView;
  const renderedAuthoredWidth = previewView
    ? authoredSurfaceWidth(previewView, activeAudience)
    : activeAudience === "cg" && active?.cg
      ? 1920
      : sidePanels
        ? 7680
        : 3840;
  const renderedSidePanels = previewView ? previewView.includeSidePanels === true : sidePanels;
  const activeIndex = active ? slides.findIndex((s) => s.id === active.id) : -1;
  const outgoing = useMemo(() => {
    if (!doc || !active || activeIndex < 0 || activeIndex >= slides.length - 1) return null;
    const to = slides[activeIndex + 1];
    return linkBetween(doc.links, active.id, to.id) || null;
  }, [doc, active, activeIndex, slides]);

  useEffect(() => {
    if (opened) {
      setJob(opened);
      const next = documentFromResult(opened.result);
      setActiveId((id) => id || next?.slides[0]?.id || null);
    }
  }, [opened]);

  useEffect(() => {
    if (openRun?.feature === "maps") return;
    let cancelled = false;
    listJobs("maps")
      .then((jobs) => {
        if (cancelled) return;
        const done = jobs.find((item) => item.status === "done");
        if (done) {
          setJob(done);
          const next = documentFromResult(done.result);
          setActiveId((id) => id || next?.slides[0]?.id || null);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, [openRun]);

  useEffect(() => {
    if (slides.length && !slides.some((s) => s.id === activeId)) {
      setActiveId(slides[0].id);
    }
  }, [slides, activeId]);

  useEffect(() => {
    if (activeAudience === "cg" && !active?.cg) {
      activeAudienceRef.current = "lw";
      setActiveAudience("lw");
    }
  }, [active, activeAudience]);

  useEffect(() => {
    setSelectedPins([]);
  }, [activeId, activeAudience]);

  useEffect(() => {
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      if (dissolveUrl.current) URL.revokeObjectURL(dissolveUrl.current);
      void flushAndSave(true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    mapRef.current?.resize();
  }, [inspectorOpen, navW]);

  useEffect(() => {
    if (!layersOpen) return;
    function onDoc(event: PointerEvent) {
      if (layersRef.current && !layersRef.current.contains(event.target as Node)) setLayersOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setLayersOpen(false);
    }
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [layersOpen]);

  useEffect(() => {
    if (!addMenuOpen && !sessionMenuOpen) return;
    function onDoc(event: PointerEvent) {
      if (addMenuRef.current && !addMenuRef.current.contains(event.target as Node)) setAddMenuOpen(false);
      if (sessionMenuRef.current && !sessionMenuRef.current.contains(event.target as Node)) setSessionMenuOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setAddMenuOpen(false);
        setSessionMenuOpen(false);
      }
    }
    document.addEventListener("pointerdown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [addMenuOpen, sessionMenuOpen]);

  const locked = job?.status === "queued" || job?.status === "running" || previewing || exporting || sessionBusy;

  function onNavResizeStart(event: React.PointerEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    navDrag.current = { x: event.clientX, w: navW };
  }

  function onNavResizeMove(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = navDrag.current;
    if (!drag) return;
    const next = Math.min(420, Math.max(160, drag.w + event.clientX - drag.x));
    setNavW(next);
    window.localStorage.setItem("obed-edom.maps.navW", String(next));
    mapRef.current?.resize();
  }

  function onNavResizeEnd(event: React.PointerEvent<HTMLButtonElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    navDrag.current = null;
    mapRef.current?.resize();
  }

  function applyLocalDoc(next: MapsDocument) {
    const currentJob = jobRef.current;
    if (!currentJob) return;
    const coerced = coerceHopKinds(next);
    docRef.current = coerced;
    setJob({ ...currentJob, result: { ...(currentJob.result || {}), ...coerced } });
    return coerced;
  }

  function mergeServerMeta(updated: Job) {
    const currentJob = jobRef.current;
    const local = docRef.current;
    if (!currentJob || !local) {
      setJob(updated);
      return;
    }
    setJob({
      ...updated,
      id: currentJob.id,
      result: { ...(updated.result || {}), ...local },
    });
  }

  function patchDoc(next: MapsDocument) {
    const coerced = applyLocalDoc(next);
    if (coerced) scheduleSave(coerced);
  }

  function scheduleSave(next: MapsDocument, immediate = false) {
    const currentJob = jobRef.current;
    if (!currentJob) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    const scheduledId = currentJob.id;
    const run = () => {
      saveTimer.current = null;
      if (jobRef.current?.id !== scheduledId) return;
      const request = saveMapsState(scheduledId, coerceHopKinds(docRef.current || next));
      saveInFlight.current = request;
      void request
        .then((updated) => {
          if (jobRef.current?.id !== scheduledId) return;
          mergeServerMeta(updated);
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)))
        .finally(() => {
          if (saveInFlight.current === request) saveInFlight.current = null;
        });
    };
    if (immediate) run();
    else saveTimer.current = window.setTimeout(run, 500);
  }

  async function persistCurrentState() {
    if (saveTimer.current) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    if (saveInFlight.current) await saveInFlight.current;
    const currentJob = jobRef.current;
    if (!currentJob || !docRef.current) return;
    const slideId = activeRef.current;
    if (slideId) writeCameraInto(slideId);
    const current = docRef.current;
    if (!current) return;
    const updated = await saveMapsState(currentJob.id, coerceHopKinds(current));
    mergeServerMeta(updated);
  }

  function writeCameraInto(slideId: string): MapsDocument | null {
    const current = docRef.current;
    if (!current) return null;
    const cam = mapRef.current?.getCamera();
    if (!cam) return current;
    const slidesNext = current.slides.map((slide) => {
      if (slide.id !== slideId) return slide;
      return activeAudienceRef.current === "cg" && slide.cg ? { ...slide, cg: { ...slide.cg, camera: cam } } : { ...slide, camera: cam };
    });
    return applyLocalDoc({ ...current, slides: slidesNext }) ?? current;
  }

  async function captureThumb(slideId: string) {
    const currentJob = jobRef.current;
    if (!currentJob) return;
    const audience = activeAudienceRef.current;
    const blob = await mapRef.current?.captureBlob();
    if (!blob) return;
    const slide = docRef.current?.slides.find((s) => s.id === slideId);
    const hillshade = (slide ? slideForAudience(slide, audience) : null)?.hillshade === true;
    const stamped = await stampOsm(blob, hillshade);
    const updated = await postMapsPng(currentJob.id, stamped, { kind: "thumb", slideId, audience });
    const stored = (updated.result?.slides as Array<{ id?: string; stillPng?: string; cg?: { stillPng?: string } }> | undefined)?.find((s) => s.id === slideId);
    const still = audience === "cg" ? stored?.cg?.stillPng : stored?.stillPng;
    const local = docRef.current;
    if (!local || !still) return;
    const files = (updated.result?.previewFiles as { maps?: string[] } | undefined) || {};
    const next = {
      ...local,
      slides: local.slides.map((slide) => {
        if (slide.id !== slideId) return slide;
        return audience === "cg" && slide.cg ? { ...slide, cg: { ...slide.cg, stillPng: still } } : { ...slide, stillPng: still };
      }),
    };
    docRef.current = next;
    setJob({
      ...currentJob,
      id: currentJob.id,
      result: { ...(currentJob.result || {}), ...next, previewFiles: files.maps ? files : currentJob.result?.previewFiles },
    });
  }

  async function flushAndSave(immediate = true) {
    const id = activeRef.current;
    if (!id || previewingRef.current) return;
    const next = writeCameraInto(id);
    await captureThumb(id);
    if (next && jobRef.current) scheduleSave(next, immediate);
  }

  async function selectSlide(nextId: string, opts?: { flush?: boolean; audience?: MapsAudience }) {
    const target = docRef.current?.slides.find((slide) => slide.id === nextId);
    const requestedAudience = opts?.audience ?? activeAudienceRef.current;
    const nextAudience: MapsAudience = requestedAudience === "cg" && target?.cg ? "cg" : "lw";
    if (nextId === activeRef.current && nextAudience === activeAudienceRef.current) return;
    if (previewingRef.current) stopPreview(true);
    const prev = activeRef.current;
    if (prev && opts?.flush !== false) {
      const next = writeCameraInto(prev);
      await captureThumb(prev);
      if (next && jobRef.current) scheduleSave(docRef.current || next, true);
    }
    activeRef.current = nextId;
    activeAudienceRef.current = nextAudience;
    setActiveId(nextId);
    setActiveAudience(nextAudience);
    setSelectedPin(null);
    setSelectedPins([]);
    if (target) mapRef.current?.jumpTo(slideForAudience(target, nextAudience).camera);
  }

  async function createDeck() {
    setError(null);
    try {
      await persistCurrentState();
      clearOpenRun();
      setSelectedPin(null);
      setSelectedPins([]);
      setRenamingSlide(null);
      const created = await startMaps();
      setJob(created);
      const done = await pollJob(created.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
      const next = documentFromResult(done.result);
      setActiveId(next?.slides[0]?.id || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function onCameraCommit(camera: MapsCamera) {
    const current = docRef.current;
    const id = activeRef.current;
    if (!current || !id || previewingRef.current) return;
    const slidesNext = current.slides.map((slide) => {
      if (slide.id !== id) return slide;
      return activeAudienceRef.current === "cg" && slide.cg ? { ...slide, cg: { ...slide.cg, camera } } : { ...slide, camera };
    });
    patchDoc({ ...current, slides: slidesNext });
  }

  function updateActive(partial: Partial<MapsSlide>) {
    const current = docRef.current;
    const id = activeRef.current;
    if (!current || !id) return;
    patchDoc({
      ...current,
      slides: current.slides.map((slide) => {
        if (slide.id !== id) return slide;
        if (activeAudienceRef.current === "cg" && slide.cg) {
          const { cg, cgShiftX, cgShiftY, includeSidePanels, id: _id, title, ...render } = partial;
          return { ...slide, ...(title === undefined ? {} : { title }), cg: { ...slide.cg, ...render } };
        }
        return { ...slide, ...partial };
      }),
    });
  }

  function splitCg() {
    if (!active) return;
    const source = slideForAudience(active, "lw");
    const camera = mapRef.current?.getCgCamera(active.cgShiftX) || { ...source.camera };
    updateActive({
      cg: {
        camera,
        style: source.style,
        highlights: [...source.highlights],
        churches: source.churches.map((church) => ({ ...church })),
      },
    });
    activeAudienceRef.current = "cg";
    setActiveAudience("cg");
    requestAnimationFrame(() => mapRef.current?.jumpTo(camera));
  }

  function mergeCg() {
    if (!active) return;
    const current = docRef.current;
    if (!current) return;
    patchDoc({ ...current, slides: current.slides.map((slide) => (slide.id === active.id ? { ...slide, cg: undefined } : slide)) });
    activeAudienceRef.current = "lw";
    setActiveAudience("lw");
    requestAnimationFrame(() => mapRef.current?.jumpTo(active.camera));
  }

  function setSlideStyle(style: MapsStyleId) {
    updateActive({ style });
  }

  function toggleHiddenLayer(id: MapsLayerFilterId) {
    const has = activeHiddenLayers.includes(id);
    updateActive({ hiddenLayers: has ? activeHiddenLayers.filter((item) => item !== id) : [...activeHiddenLayers, id] });
  }

  function toggleCachedCountry(code: string, nextSelected: string[]) {
    const current = docRef.current;
    if (!current) return;
    patchDoc({ ...current, cachedCountries: nextSelected });
    const adding = nextSelected.some((item) => item.toUpperCase() === code.toUpperCase());
    if (!adding) return;
    const prefetch: Promise<void> = prefetchMapsTiles({ countries: [code], maxzoom: 8 })
      .then((stats) => {
        setLogs((prev) => [...prev, `Cached ${code}: ${stats.cached + stats.fetched} tiles.`]);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        cachePrefetches.current.delete(prefetch);
      });
    cachePrefetches.current.add(prefetch);
  }

  function addSlide() {
    const current = docRef.current;
    if (!current || !active || locked) return;
    const created = cloneSlide(active, nextSlideId(current.slides));
    const index = current.slides.findIndex((s) => s.id === active.id);
    const slidesNext = [...current.slides.slice(0, index + 1), created, ...current.slides.slice(index + 1)];
    const links = restitch(slidesNext, current.links);
    const next = { ...current, slides: slidesNext, links };
    patchDoc(next);
    void (async () => {
      await flushAndSave(true);
      setActiveId(created.id);
      mapRef.current?.jumpTo(created.camera);
    })();
  }

  function restitch(nextSlides: MapsSlide[], prevLinks: MapsLink[]): MapsLink[] {
    const links: MapsLink[] = [];
    for (let i = 0; i < nextSlides.length - 1; i++) {
      const from = nextSlides[i];
      const to = nextSlides[i + 1];
      const existing = prevLinks.find((link) => link.from === from.id && link.to === to.id);
      links.push(
        existing || {
          from: from.id,
          to: to.id,
          kind: suggestedHopKind(from, to),
          duration: 1.2,
          playWithoutClick: false,
        }
      );
    }
    return links;
  }

  function removeSlide() {
    const current = docRef.current;
    if (!current || !active || current.slides.length < 2 || locked) return;
    if (!window.confirm(`Remove slide “${active.title}”?`)) return;
    const slidesNext = current.slides.filter((s) => s.id !== active.id);
    const links = restitch(slidesNext, current.links);
    const fallback = slidesNext[Math.max(0, activeIndex - 1)] || slidesNext[0];
    patchDoc({ ...current, slides: slidesNext, links });
    const audience: MapsAudience = activeAudienceRef.current === "cg" && fallback.cg ? "cg" : "lw";
    activeRef.current = fallback.id;
    activeAudienceRef.current = audience;
    setActiveId(fallback.id);
    setActiveAudience(audience);
    setSelectedPin(null);
    setSelectedPins([]);
    mapRef.current?.jumpTo(slideForAudience(fallback, audience).camera);
  }

  function setHop(partial: Partial<MapsLink>, opts?: { dropRoute?: boolean; resetFly?: boolean; dropFlyZoom?: boolean }) {
    const current = docRef.current;
    if (!current || !outgoing) return;
    patchDoc({
      ...current,
      links: current.links.map((link) => {
        if (link.from !== outgoing.from || link.to !== outgoing.to) return link;
        const next: MapsLink = { ...link, ...partial };
        if (next.kind !== "movie" || opts?.dropRoute) delete next.route;
        if (next.kind !== "movie") {
          delete next.easing;
          delete next.easeIn;
          delete next.easeOut;
          delete next.flyZoom;
        } else if (opts?.resetFly) {
          delete next.easeIn;
          delete next.easeOut;
          delete next.flyZoom;
        } else if (opts?.dropFlyZoom) {
          delete next.flyZoom;
        }
        return next;
      }),
    });
  }

  function openPin(id: string) {
    setSelectedPin(id);
    setInspTab("properties");
  }

  function beginSlideRename(slide: MapsSlide) {
    if (!locked) setRenamingSlide({ id: slide.id, title: slide.title });
  }

  function commitSlideRename() {
    const pending = renamingSlide;
    setRenamingSlide(null);
    if (!pending || locked) return;
    const nextTitle = pending.title.trim();
    if (!nextTitle) return;
    const current = docRef.current;
    if (!current) return;
    const existing = current.slides.find((slide) => slide.id === pending.id);
    if (!existing || existing.title === nextTitle) return;
    patchDoc({ ...current, slides: current.slides.map((slide) => (slide.id === pending.id ? { ...slide, title: nextTitle } : slide)) });
  }

  function slideTitleControl(slide: MapsSlide) {
    if (renamingSlide?.id === slide.id) {
      return (
        <input
          className="maps-thumb-title-input"
          value={renamingSlide.title}
          aria-label={`Slide title for ${slide.title}`}
          autoFocus
          disabled={locked}
          onChange={(event) => setRenamingSlide((pending) => (pending?.id === slide.id ? { ...pending, title: event.target.value } : pending))}
          onBlur={commitSlideRename}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") setRenamingSlide(null);
          }}
        />
      );
    }
    return (
      <button
        type="button"
        className="maps-thumb-label maps-thumb-title"
        disabled={locked}
        title="Select slide (double-click to rename)"
        aria-label={`Select slide ${slide.title} (double-click to rename)`}
        onClick={() => void selectSlide(slide.id)}
        onDoubleClick={() => beginSlideRename(slide)}
      >
        {slide.title}
      </button>
    );
  }

  function togglePinSelection(id: string, checked: boolean) {
    setSelectedPins((ids) => (checked ? [...new Set([...ids, id])] : ids.filter((item) => item !== id)));
  }

  function updateSelectedPins(partial: Partial<MapsChurch>) {
    if (!activeView || selectedPins.length === 0) return;
    const selected = new Set(selectedPins);
    updateActive({ churches: activeView.churches.map((church) => (selected.has(church.id) ? { ...church, ...partial } : church)) });
  }

  function deleteSelectedPins() {
    if (!activeView || selectedPins.length === 0 || locked) return;
    if (!window.confirm(`Remove ${selectedPins.length} selected pin${selectedPins.length === 1 ? "" : "s"}?`)) return;
    const selected = new Set(selectedPins);
    updateActive({ churches: activeView.churches.filter((church) => !selected.has(church.id)) });
    if (selectedPin && selected.has(selectedPin)) setSelectedPin(null);
    setSelectedPins([]);
  }

  async function search() {
    const q = query.trim();
    if (!q) return;
    try {
      const hit = await geocodeMaps(q);
      const camera = hit.camera as MapsCamera;
      mapRef.current?.flyTo(camera);
      onCameraCommit(camera);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function clearDissolveFrame(ownerUrl?: string) {
    if (ownerUrl && dissolveUrl.current !== ownerUrl) {
      URL.revokeObjectURL(ownerUrl);
      return;
    }
    if (dissolveUrl.current) URL.revokeObjectURL(dissolveUrl.current);
    dissolveUrl.current = null;
    setDissolveFrame(null);
  }

  async function applyPreviewView(view: MapsSlide, run = previewRun.current) {
    setPreviewView(view);
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    if (previewAbort.current || previewRun.current !== run) return;
    mapRef.current?.jumpTo(view.camera);
    await new Promise((resolve) => window.setTimeout(resolve, 75));
    if (!previewAbort.current && previewRun.current === run) await mapRef.current?.waitUntilIdle(view.style);
    if (activeAudienceRef.current !== "cg" || view.cg || previewAbort.current || previewRun.current !== run) return;
    const camera = mapRef.current?.getCgCamera(view.cgShiftX);
    if (!camera) return;
    setPreviewView({
      ...view,
      camera,
      cg: { camera, style: view.style, highlights: view.highlights, churches: view.churches },
    });
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    if (previewAbort.current || previewRun.current !== run) return;
    mapRef.current?.jumpTo(camera);
    await new Promise((resolve) => window.setTimeout(resolve, 75));
    if (!previewAbort.current && previewRun.current === run) await mapRef.current?.waitUntilIdle(view.style);
  }

  async function previewLink(link: MapsLink, from: MapsSlide, to: MapsSlide) {
    const run = previewRun.current;
    const audience = activeAudienceRef.current;
    const fromView = slideForAudience(from, audience);
    const toView = slideForAudience(to, audience);
    if (link.kind === "cut") {
      await applyPreviewView(toView, run);
      return;
    }
    if (link.kind === "dissolve") {
      const blob = await mapRef.current?.capturePreviewBlob();
      if (!blob || previewAbort.current || previewRun.current !== run) return;
      clearDissolveFrame();
      const url = URL.createObjectURL(blob);
      dissolveUrl.current = url;
      setDissolveFrame({ url, fading: false, duration: link.duration });
      await applyPreviewView(toView, run);
      if (previewAbort.current || previewRun.current !== run) return;
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      setDissolveFrame({ url, fading: true, duration: link.duration });
      await new Promise((resolve) => window.setTimeout(resolve, Math.max(0, link.duration * 1000)));
      clearDissolveFrame(url);
      return;
    }
    if (link.kind === "movie") {
      await mapRef.current?.animateHop({
        from: fromView.camera,
        to: toView.camera,
        durationMs: link.duration * 1000,
        easing: link.easing,
        routePoints: link.route?.points,
        flyZoom: link.flyZoom,
        easeIn: link.easeIn,
        easeOut: link.easeOut,
        width: Math.max(authoredSurfaceWidth(from, audience), authoredSurfaceWidth(to, audience)),
      });
      if (!previewAbort.current && previewRun.current === run) await applyPreviewView(toView, run);
      return;
    }
    await mapRef.current?.easeTo(toView.camera, link.duration * 1000);
    if (!previewAbort.current && previewRun.current === run) await applyPreviewView(toView, run);
  }

  async function playHop(fromIndex: number, restore: boolean) {
    const current = docRef.current;
    if (!current || fromIndex < 0 || fromIndex >= current.slides.length - 1 || exportingRef.current) return;
    const from = current.slides[fromIndex];
    const to = current.slides[fromIndex + 1];
    const link = linkBetween(current.links, from.id, to.id);
    if (!link) return;
    previewRun.current += 1;
    previewAbort.current = false;
    savedCamera.current = mapRef.current?.getCamera() || from.camera;
    setPreviewing(true);
    await previewLink(link, from, to);
    if (previewAbort.current) return;
    if (restore) stopPreview(true);
    else setPreviewing(false);
  }

  function stopPreview(restore: boolean) {
    previewRun.current += 1;
    previewAbort.current = true;
    mapRef.current?.stop();
    setPreviewing(false);
    setPreviewView(null);
    clearDissolveFrame();
    if (restore && savedCamera.current) mapRef.current?.jumpTo(savedCamera.current);
    savedCamera.current = null;
  }

  async function playFromHere() {
    const current = docRef.current;
    if (!current || activeIndex < 0 || exportingRef.current) return;
    previewRun.current += 1;
    previewAbort.current = false;
    savedCamera.current = mapRef.current?.getCamera() || current.slides[activeIndex].camera;
    setPreviewing(true);
    for (let i = activeIndex; i < current.slides.length - 1; i++) {
      if (previewAbort.current) return;
      const from = current.slides[i];
      const to = current.slides[i + 1];
      const link = linkBetween(current.links, from.id, to.id);
      if (!link) continue;
      await previewLink(link, from, to);
    }
    if (previewAbort.current) return;
    setPreviewing(false);
    savedCamera.current = null;
    const last = current.slides[current.slides.length - 1];
    setPreviewView(null);
    await selectSlide(last.id, { flush: false, audience: activeAudienceRef.current });
  }

  async function onCsv(file: File, mode: "append" | "replace" | "pins") {
    if (!job) return;
    setError(null);
    if (mode !== "append") {
      setSelectedPin(null);
      setSelectedPins([]);
      setRenamingSlide(null);
    }
    try {
      await persistCurrentState();
      const started = mode === "pins" && active
        ? await bootstrapMapsPinsCsv(job.id, file, active.id, activeAudience)
        : await bootstrapMapsCsv(job.id, file, mode === "replace");
      setJob(started);
      const done = await pollJob(started.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveSession() {
    const currentJob = jobRef.current;
    if (!currentJob || sessionBusy) return;
    setError(null);
    setSessionBusy(true);
    try {
      await Promise.all([...cachePrefetches.current]);
      if (saveTimer.current) {
        window.clearTimeout(saveTimer.current);
        saveTimer.current = null;
      }
      if (saveInFlight.current) await saveInFlight.current;
      const slideId = activeRef.current;
      if (slideId) {
        writeCameraInto(slideId);
        await captureThumb(slideId);
      }
      const current = docRef.current;
      if (current) {
        const updated = await saveMapsState(currentJob.id, coerceHopKinds(current));
        mergeServerMeta(updated);
      }
      const { blob, filename } = await downloadMapsSession(currentJob.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSessionBusy(false);
    }
  }

  async function loadSession(file: File) {
    if (sessionBusy) return;
    setError(null);
    setSessionBusy(true);
    try {
      if (saveTimer.current) {
        window.clearTimeout(saveTimer.current);
        saveTimer.current = null;
      }
      if (saveInFlight.current) await saveInFlight.current;
      let target = jobRef.current;
      if (!target) {
        const started = await startMaps();
        target = await pollJob(started.id, (tick) => setJob(tick));
      }
      const loaded = await loadMapsSession(target.id, file);
      const next = documentFromResult(loaded.result);
      const firstId = next?.slides[0]?.id || null;
      setJob(loaded);
      if (next) docRef.current = next;
      activeRef.current = firstId;
      activeAudienceRef.current = "lw";
      setActiveId(firstId);
      setActiveAudience("lw");
      setSelectedPin(null);
      setSelectedPins([]);
      setRenamingSlide(null);
      setPreviewView(null);
      if (firstId && next) requestAnimationFrame(() => mapRef.current?.jumpTo(next.slides[0].camera));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSessionBusy(false);
    }
  }

  async function onExport() {
    if (exportingRef.current) return;
    const currentJob = jobRef.current;
    if (!currentJob) return;
    if (currentJob.status === "queued" || currentJob.status === "running") return;
    if (previewingRef.current) stopPreview(true);
    exportAbort.current = false;
    exportingRef.current = true;
    setExporting(true);
    setError(null);
    setLogs((prev) => [...prev, "Exporting maps…"]);
    const throwIfCancelled = () => {
      if (exportAbort.current) throw new Error("Export cancelled.");
    };
    try {
      await flushAndSave(true);
      throwIfCancelled();
      const id = jobRef.current?.id;
      if (!id) throw new Error("Maps job is gone");
      const plan = await fetchMapsExportPlan(id);
      throwIfCancelled();
      const local = docRef.current;
      if (!local) throw new Error("Maps document is not loaded");
      const next = coerceHopKinds({ ...local, links: plan.links as MapsLink[] });
      applyLocalDoc(next);
      await saveMapsState(id, next).then((updated) => mergeServerMeta(updated));
      throwIfCancelled();
      for (const still of plan.stills) {
        throwIfCancelled();
        const blob = await captureExportRaster({
          width: still.width || 3840,
          height: still.height || 1080,
          camera: still.camera,
          styleId: still.style as MapsSlide["style"],
          highlights: still.highlights,
          hiddenLayers: (still.hiddenLayers as MapsLayerFilterId[] | undefined) ?? DEFAULT_HIDDEN_LAYERS,
          hillshade: (still.hillshade as boolean | undefined) === true,
          isCancelled: () => exportAbort.current,
        });
        throwIfCancelled();
        await postMapsPng(id, blob, { kind: "still", slideId: still.slideId });
      }
      for (const plate of plan.plates) {
        throwIfCancelled();
        const blob = await captureExportRaster({
          width: plate.plateW,
          height: plate.plateH,
          camera: plate.camera,
          styleId: plate.style as MapsSlide["style"],
          highlights: plate.highlights,
          hiddenLayers: (plate.hiddenLayers as MapsLayerFilterId[] | undefined) ?? DEFAULT_HIDDEN_LAYERS,
          hillshade: (plate.hillshade as boolean | undefined) === true,
          isCancelled: () => exportAbort.current,
        });
        throwIfCancelled();
        await postMapsPng(id, blob, { kind: "plate", plateId: plate.plateId });
      }
      if (plan.cg) {
        for (const still of plan.cg.stills) {
          throwIfCancelled();
          const blob = await captureExportRaster({
            width: still.width || 1920,
            height: still.height || 1080,
            camera: still.camera,
            styleId: still.style as MapsSlide["style"],
            highlights: still.highlights,
            hiddenLayers: (still.hiddenLayers as MapsLayerFilterId[] | undefined) ?? DEFAULT_HIDDEN_LAYERS,
            hillshade: (still.hillshade as boolean | undefined) === true,
            isCancelled: () => exportAbort.current,
          });
          throwIfCancelled();
          await postMapsPng(id, blob, { kind: "still", slideId: still.slideId, audience: "cg" });
        }
        for (const plate of plan.cg.plates) {
          throwIfCancelled();
          const blob = await captureExportRaster({
            width: plate.plateW,
            height: plate.plateH,
            camera: plate.camera,
            styleId: plate.style as MapsSlide["style"],
            highlights: plate.highlights,
            hiddenLayers: (plate.hiddenLayers as MapsLayerFilterId[] | undefined) ?? DEFAULT_HIDDEN_LAYERS,
            hillshade: (plate.hillshade as boolean | undefined) === true,
            isCancelled: () => exportAbort.current,
          });
          throwIfCancelled();
          await postMapsPng(id, blob, { kind: "plate", plateId: plate.plateId, audience: "cg" });
        }
      }
      const slidesById = new Map((docRef.current?.slides || []).map((slide) => [slide.id, slide]));
      for (const link of docRef.current?.links || []) {
        if (link.kind !== "movie") continue;
        throwIfCancelled();
        const from = slidesById.get(link.from);
        const to = slidesById.get(link.to);
        if (!from || !to) continue;
        const width = Math.max(captureWidth(from), captureWidth(to));
        const height = 1080;
        const fps = 30;
        const count = Math.max(2, Math.round(link.duration * fps));
        const cameras = Array.from({ length: count }, (_, i) =>
          cameraAtHop(from.camera, to.camera, i / (count - 1), {
            easing: link.easing,
            routePoints: link.route?.points,
            flyZoom: link.flyZoom,
            easeIn: link.easeIn,
            easeOut: link.easeOut,
            duration: link.duration,
            width,
          })
        );
        setLogs((prev) => [...prev, `Prefetching tiles for ${from.id} → ${to.id}…`]);
        try {
          throwIfCancelled();
          const stats = await prefetchMapsTiles({ cameras, width, height, maxzoom: 14, terrain: from.hillshade === true });
          setLogs((prev) => [...prev, `Cached ${stats.cached + stats.fetched} / ${stats.tiles} tiles (${stats.failed} failed).`]);
        } catch (err) {
          if (exportAbort.current) throw err;
          setLogs((prev) => [...prev, `Tile prefetch skipped: ${err instanceof Error ? err.message : String(err)}`]);
        }
        throwIfCancelled();
        setLogs((prev) => [...prev, `Rendering movie ${from.id} → ${to.id}…`]);
        await captureFlyFrames({
          width,
          height,
          from: from.camera,
          to: to.camera,
          styleId: from.style,
          highlights: from.highlights,
          hiddenLayers: from.hiddenLayers ?? local.hiddenLayers,
          hillshade: from.hillshade === true,
          churches: from.churches,
          numberPins: true,
          duration: link.duration,
          fps: 30,
          easing: link.easing,
          routePoints: link.route?.points,
          flyZoom: link.flyZoom,
          easeIn: link.easeIn,
          easeOut: link.easeOut,
          isCancelled: () => exportAbort.current,
          onFrame: async (blob, i, n) => {
            if (exportAbort.current) throw new Error("Export cancelled.");
            await postMapsFrame(id, blob, { slideId: from.id, index: i, count: n, fps: 30 });
          },
        });
      }
      if (plan.cg) {
        const affected = new Set(plan.cg.affectedSlideIds || []);
        const cgLinks = plan.cg.links as MapsLink[];
        for (const link of cgLinks) {
          if (link.kind !== "movie" || (!affected.has(link.from) && !affected.has(link.to))) continue;
          throwIfCancelled();
          const baseFrom = slidesById.get(link.from);
          const baseTo = slidesById.get(link.to);
          if (!baseFrom || !baseTo) continue;
          const from = slideForAudience(baseFrom, "cg");
          const to = slideForAudience(baseTo, "cg");
          const width = Math.max(
            authoredSurfaceWidth(baseFrom, "cg"),
            authoredSurfaceWidth(baseTo, "cg")
          );
          const cropFromX = (width - 1920) / 2 + (baseFrom.cg ? 0 : baseFrom.cgShiftX);
          const cropToX = (width - 1920) / 2 + (baseTo.cg ? 0 : baseTo.cgShiftX);
          const fps = 30;
          const count = Math.max(2, Math.round(link.duration * fps));
          const cameras = Array.from({ length: count }, (_, i) =>
            cameraAtHop(from.camera, to.camera, i / (count - 1), {
              easing: link.easing,
              routePoints: link.route?.points,
              flyZoom: link.flyZoom,
              easeIn: link.easeIn,
              easeOut: link.easeOut,
              duration: link.duration,
              width,
            })
          );
          try {
            await prefetchMapsTiles({ cameras, width, height: 1080, maxzoom: 14, terrain: from.hillshade === true });
          } catch (err) {
            if (exportAbort.current) throw err;
          }
          throwIfCancelled();
          await captureFlyFrames({
            width,
            height: 1080,
            from: from.camera,
            to: to.camera,
            styleId: from.style,
            highlights: from.highlights,
            hiddenLayers: from.hiddenLayers ?? local.hiddenLayers,
            hillshade: from.hillshade === true,
            churches: from.churches,
            numberPins: true,
            duration: link.duration,
            fps,
            easing: link.easing,
            routePoints: link.route?.points,
            flyZoom: link.flyZoom,
            easeIn: link.easeIn,
            easeOut: link.easeOut,
            outputCrop: {
              width: 1920,
              height: 1080,
              fromX: cropFromX,
              toX: cropToX,
            },
            isCancelled: () => exportAbort.current,
            onFrame: async (blob, i, n) => {
              if (exportAbort.current) throw new Error("Export cancelled.");
              await postMapsFrame(id, blob, { slideId: from.id, index: i, count: n, fps, audience: "cg" });
            },
          });
        }
      }
      throwIfCancelled();
      const latest = docRef.current;
      const started = await exportMaps(id, {
        exportLw: latest?.exportLw,
        exportCg: latest?.exportCg,
        exportDsk: latest?.exportDsk,
      });
      setJob(started);
      const done = await pollJob(started.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      }, () => exportAbort.current, () => cancelMapsExport(started.id));
      setJob(done);
      if (done.status === "error") {
        if (exportAbort.current && done.error === "Export cancelled.") {
          setLogs((prev) => [...prev, "Export cancelled."]);
        } else {
          setError(done.error || "Export failed");
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (exportAbort.current || msg === "Export cancelled.") {
        setLogs((prev) => [...prev, "Export cancelled."]);
      } else {
        setError(msg);
      }
    } finally {
      exportingRef.current = false;
      setExporting(false);
    }
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (previewingRef.current) stopPreview(true);
      if (exportingRef.current) exportAbort.current = true;
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      exportAbort.current = true;
    };
  }, []);

  const pin = activeView?.churches.find((c) => c.id === selectedPin) || null;
  const nextSlide = outgoing && activeIndex >= 0 ? slides[activeIndex + 1] : null;
  const nextView = nextSlide ? slideForAudience(nextSlide, activeAudience) : null;
  const suggested = outgoing && active && nextSlide ? suggestedHopKind(active, nextSlide) : "morph";
  const morphOk = suggested === "morph";
  const cruiseAuto =
    activeView && nextView
      ? autoCruiseZoom(
          activeView.camera,
          nextView.camera,
          Math.max(authoredSurfaceWidth(active!, activeAudience), authoredSurfaceWidth(nextSlide!, activeAudience))
        )
      : 0;
  const zoomFloor = minZoomForView();
  const wrapWarn = activeView ? worldCopyWarning(activeView.camera.zoom) : null;

  if (!job) {
    return (
      <div>
        <h1>Maps</h1>
        <p className="lede">Author LED-wall cameras, then export Keynote stills. Nothing is created until you start a deck.</p>
        <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
        <button className="btn" type="button" disabled={sessionBusy} onClick={() => void createDeck()}>
          New map deck
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={sessionBusy}
          onClick={() => sessionInput.current?.click()}
        >
          Load map session + cache…
        </button>
        <input
          ref={sessionInput}
          type="file"
          accept=".obedmaps,.zip,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void loadSession(file);
          }}
        />
      </div>
    );
  }

  return (
    <div className="maps-tab">
      <div className="maps-chrome">
      <div className="maps-toolbar">
        <div className="maps-deck-actions" ref={addMenuRef}>
          <button
            className="btn secondary"
            type="button"
            disabled={locked}
            aria-expanded={addMenuOpen}
            aria-haspopup="true"
            aria-label="Add"
            title="Add"
            onClick={() => setAddMenuOpen((open) => !open)}
          >
            ＋
          </button>
          {addMenuOpen && (
            <div className="maps-deck-actions-menu" role="group" aria-label="Add">
              <button
                type="button"
                onClick={() => {
                  setAddMenuOpen(false);
                  void createDeck();
                }}
              >
                New map deck
              </button>
              <button
                type="button"
                onClick={() => {
                  setAddMenuOpen(false);
                  csvMode.current = "append";
                  csvInput.current?.click();
                }}
              >
                Add slides from CSV…
              </button>
              <button
                type="button"
                disabled={!active}
                onClick={() => {
                  setAddMenuOpen(false);
                  csvMode.current = "pins";
                  csvInput.current?.click();
                }}
              >
                Add pins to this view from CSV…
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!window.confirm("Replace the whole deck from a CSV? Existing slides will be discarded.")) return;
                  setAddMenuOpen(false);
                  csvMode.current = "replace";
                  csvInput.current?.click();
                }}
              >
                Replace deck from CSV…
              </button>
            </div>
          )}
        </div>
        <div className="maps-deck-actions" ref={sessionMenuRef}>
          <button
            className="btn secondary"
            type="button"
            disabled={locked}
            aria-expanded={sessionMenuOpen}
            aria-haspopup="true"
            onClick={() => setSessionMenuOpen((open) => !open)}
          >
            Session ▾
          </button>
          {sessionMenuOpen && (
            <div className="maps-deck-actions-menu" role="group" aria-label="Session">
              <button
                type="button"
                onClick={() => {
                  setSessionMenuOpen(false);
                  void saveSession();
                }}
              >
                Save session + cache…
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!window.confirm("Load a saved map session? The current deck will be replaced; cached tiles from the session will be added to this cache.")) return;
                  setSessionMenuOpen(false);
                  sessionInput.current?.click();
                }}
              >
                Load session + cache…
              </button>
            </div>
          )}
        </div>
        <input
          ref={csvInput}
          type="file"
          accept=".csv,text/csv"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            const mode = csvMode.current;
            csvMode.current = "append";
            if (file) void onCsv(file, mode);
          }}
        />
        <input
          ref={sessionInput}
          type="file"
          accept=".obedmaps,.zip,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void loadSession(file);
          }}
        />
        <form
          className="maps-search"
          onSubmit={(event) => {
            event.preventDefault();
            void search();
          }}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search a place, @lat,lng, or maps URL"
            disabled={locked}
          />
        </form>
        <button
          className={`btn secondary toggle${sidePanels ? " on" : ""}`}
          type="button"
          aria-pressed={sidePanels}
          title="Show the full 7680×1080 wall instead of the centre"
          disabled={activeAudience === "cg" || locked}
          onClick={() => setSidePanels(!sidePanels)}
        >
          {sidePanels ? "Center wall only" : "Show side panels"}
        </button>
        <button
          className={`btn secondary icon-btn${inspectorOpen ? " on" : ""}`}
          type="button"
          title={inspectorOpen ? "Hide inspector" : "Show inspector"}
          aria-label={inspectorOpen ? "Hide inspector" : "Show inspector"}
          aria-pressed={inspectorOpen}
          onClick={() => setInspectorOpen(!inspectorOpen)}
        >
          <IconLibrary />
        </button>
        <span className="note">{job.id}</span>
      </div>
      <div className="maps-stylebar">
        <div className="maps-swatches" role="group" aria-label="Map style">
          {STYLE_SWATCHES.map((swatch) => (
            <button
              key={swatch.id}
              type="button"
              title={swatch.label}
              className={`maps-swatch${(activeView?.style || doc?.defaultStyle) === swatch.id ? " active" : ""}`}
              style={{ background: swatch.color }}
              disabled={locked}
              onClick={() => setSlideStyle(swatch.id)}
            />
          ))}
        </div>
        <div className="maps-layers" ref={layersRef}>
          <button
            className={`btn secondary icon-btn maps-layers-btn${layersOpen || activeHiddenLayers.length ? " on" : ""}`}
            type="button"
            aria-expanded={layersOpen}
            aria-haspopup="true"
            title={activeHiddenLayers.length ? `${activeHiddenLayers.length} layers hidden` : "Map layers"}
            aria-label={activeHiddenLayers.length ? `Map layers, ${activeHiddenLayers.length} hidden` : "Map layers"}
            onClick={() => setLayersOpen((open) => !open)}
          >
            <IconLayers />
            {activeHiddenLayers.length ? <span className="maps-layers-count">{activeHiddenLayers.length}</span> : null}
          </button>
          {layersOpen && (
            <div className="maps-layers-menu" role="group" aria-label="Hide map layers">
              {LAYER_FILTERS.map((item) => {
                const hidden = activeHiddenLayers.includes(item.id);
                return (
                  <label key={item.id} className="maps-layers-item">
                    <input
                      type="checkbox"
                      checked={!hidden}
                      disabled={locked}
                      onChange={() => toggleHiddenLayer(item.id)}
                    />
                    {item.label}
                  </label>
                );
              })}
            </div>
          )}
        </div>
        <button
          type="button"
          className={`btn secondary icon-btn maps-relief-btn${activeHillshade ? " on" : ""}`}
          title={activeHillshade ? "Relief on" : "Relief off"}
          aria-label="Terrain relief"
          aria-pressed={activeHillshade}
          disabled={locked}
          onClick={() => updateActive({ hillshade: !activeHillshade })}
        >
          <IconRelief />
        </button>
        <CountryCachePicker
          selected={doc?.cachedCountries || []}
          disabled={locked}
          onToggle={toggleCachedCountry}
        />
      </div>
      </div>
      <ErrorNotice message={error || openError} onDismiss={error ? () => setError(null) : undefined} />
      <ErrorNotice message={job.error} />

      <div
        className="maps-stage"
        style={{ gridTemplateColumns: inspectorOpen ? `${navW}px 8px minmax(0, 1fr) 312px` : `${navW}px 8px minmax(0, 1fr)` }}
      >
        <div className="maps-nav">
          {slides.map((slide, index) => {
            const next = slides[index + 1];
            const hop = next ? linkBetween(doc?.links || [], slide.id, next.id) : null;
            const src = slide.stillPng && job.id ? previewUrl(job.id, "maps", slide.stillPng) : "";
            const cgSrc = slide.cg?.stillPng && job.id ? previewUrl(job.id, "maps", slide.cg.stillPng) : "";
            return (
              <div key={slide.id}>
                {slide.cg ? (
                  <div className="maps-thumb-card">
                    <div className="maps-thumb-pair">
                      <button
                        type="button"
                        className={`maps-thumb maps-thumb-half${slide.id === active?.id && activeAudience === "lw" ? " active" : ""}`}
                        disabled={locked}
                        title={sidePanels || slide.includeSidePanels ? "Full wall (FW)" : "LED wall (LW)"}
                        onClick={() => void selectSlide(slide.id, { audience: "lw" })}
                      >
                        {src ? <img src={`${src}?t=${job.updatedAt || ""}`} alt="" /> : <span className="note">{sidePanels || slide.includeSidePanels ? "FW" : "LW"}</span>}
                        <span className="maps-thumb-view-label">{sidePanels || slide.includeSidePanels ? "FW" : "LW"}</span>
                      </button>
                      <button
                        type="button"
                        className={`maps-thumb maps-thumb-half${slide.id === active?.id && activeAudience === "cg" ? " active" : ""}`}
                        disabled={locked}
                        title="Independent CG"
                        onClick={() => void selectSlide(slide.id, { audience: "cg" })}
                      >
                        {cgSrc ? <img src={`${cgSrc}?t=${job.updatedAt || ""}`} alt="" /> : <span className="note">CG</span>}
                        <span className="maps-thumb-view-label">CG</span>
                      </button>
                    </div>
                    {slideTitleControl(slide)}
                  </div>
                ) : (
                  <div className="maps-thumb-card">
                    <button
                      type="button"
                      className={`maps-thumb${slide.id === active?.id ? " active" : ""}${slide.includeSidePanels ? " fw" : " lw"}`}
                      disabled={locked}
                      title={slide.includeSidePanels ? "Full wall render (side panels)" : "Centre wall (LW)"}
                      onClick={() => void selectSlide(slide.id, { audience: "lw" })}
                    >
                      {src ? <img src={`${src}?t=${job.updatedAt || ""}`} alt="" /> : <span className="note">{slide.title}</span>}
                    </button>
                    {slideTitleControl(slide)}
                  </div>
                )}
                {hop && (
                  <div className="maps-gutter">
                    <span className="maps-gutter-line" />
                    <button
                      type="button"
                      className="maps-gutter-kind"
                      disabled={locked}
                      title={`${HOP_TIPS[hop.kind]} Open animation settings.`}
                      aria-label={`Open ${HOP_LABELS[hop.kind]} animation for ${slide.title}`}
                      onClick={() => {
                        setSelectedPin(null);
                        setSelectedPins([]);
                        setInspTab("animation");
                        void selectSlide(slide.id);
                      }}
                    >
                      {HOP_LABELS[hop.kind]}
                    </button>
                    {hop.kind !== "cut" && (
                      <button
                        type="button"
                        className="btn secondary maps-gutter-play"
                        disabled={locked}
                        title="Play hop"
                        aria-label={`Play ${HOP_LABELS[hop.kind]}`}
                        onClick={() => void playHop(index, true)}
                      >
                        <IconPlay />
                      </button>
                    )}
                    <span className="maps-gutter-line" />
                  </div>
                )}
              </div>
            );
          })}
          <div className="maps-nav-actions">
            <button className="btn secondary" type="button" onClick={addSlide} disabled={locked}>
              +
            </button>
            <button className="btn maps-delete" type="button" onClick={removeSlide} disabled={locked || slides.length < 2} title="Delete slide" aria-label="Delete slide">
              <IconTrash />
            </button>
          </div>
        </div>
        <button
          type="button"
          className="maps-split"
          aria-label="Resize slide list"
          onPointerDown={onNavResizeStart}
          onPointerMove={onNavResizeMove}
          onPointerUp={onNavResizeEnd}
          onPointerCancel={onNavResizeEnd}
        />
        <div className="maps-center">
          {active && (
            <>
              <MapView
                ref={mapRef}
                camera={renderedView?.camera || active.camera}
                styleId={renderedView?.style || active.style}
                highlights={renderedView?.highlights || active.highlights}
                churches={renderedView?.churches || active.churches}
                numberPins={outgoing?.kind === "movie"}
                crop={doc?.crop || "center+cg"}
                sidePanels={renderedSidePanels}
                exportCg={doc?.exportCg !== false && !active.cg}
                hiddenLayers={renderedView?.hiddenLayers ?? doc?.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS}
                hillshade={renderedView?.hillshade === true}
                cgShiftX={activeAudience === "cg" ? 0 : active.cgShiftX}
                authoredWidth={renderedAuthoredWidth}
                previewing={previewing}
                selectedPinId={selectedPin}
                onCameraCommit={onCameraCommit}
                onToggleCountry={(adm0) => {
                  if (!activeView) return;
                  const has = activeView.highlights.includes(adm0);
                  updateActive({ highlights: has ? activeView.highlights.filter((h) => h !== adm0) : [...activeView.highlights, adm0] });
                }}
                onAddPin={(lat, lon) => {
                  if (!activeView) return;
                  const church: MapsChurch = {
                    id: nextPinId(activeView.churches),
                    name: "Pin",
                    lat,
                    lon,
                    kind: "dropPin",
                    color: "#c44a42",
                  };
                  updateActive({ churches: [...activeView.churches, church] });
                  openPin(church.id);
                }}
                onSelectPin={(id) => {
                  if (id) openPin(id);
                  else setSelectedPin(null);
                }}
                onEditPin={(id) => {
                  if (!activeView) return;
                  const church = activeView.churches.find((c) => c.id === id);
                  if (!church) return;
                  const name = window.prompt("Pin name", church.name);
                  if (name == null) return;
                  updateActive({ churches: activeView.churches.map((c) => (c.id === id ? { ...c, name } : c)) });
                }}
                onCgShift={(dx) => updateActive(clampCgShift(dx, 0))}
                onPreviewAbort={() => stopPreview(true)}
              />
              {dissolveFrame && (
                <img
                  className={`maps-dissolve-frame${dissolveFrame.fading ? " fading" : ""}`}
                  src={dissolveFrame.url}
                  alt=""
                  style={{ transitionDuration: `${dissolveFrame.duration}s` }}
                />
              )}
              <label className="maps-zoom-slider">
                <span>Zoom</span>
                <input
                  type="range"
                  min={zoomFloor}
                  max={22}
                  step={0.1}
                  value={Number.isFinite(activeView?.camera.zoom) ? activeView!.camera.zoom : zoomFloor}
                  disabled={locked}
                  onChange={(event) => {
                    if (!activeView) return;
                    const camera = { ...activeView.camera, zoom: Number(event.target.value) };
                    updateActive({ camera });
                    mapRef.current?.jumpTo(camera);
                  }}
                  onPointerUp={() => void flushAndSave(true)}
                />
              </label>
            </>
          )}
        </div>

        {inspectorOpen && (
        <div className="maps-inspector">
          <div className="maps-insp-tabs" role="tablist" aria-label="Inspector">
            {INSPECTOR_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={inspTab === tab.id}
                className={`maps-insp-tab${inspTab === tab.id ? " active" : ""}`}
                onClick={() => setInspTab(tab.id)}
              >
                {tab.label}
                {tab.id === "pins" && (activeView?.churches.length || 0) > 0 && (
                  <span className="maps-insp-count">{activeView?.churches.length}</span>
                )}
              </button>
            ))}
          </div>
          {active && (
            <div className="maps-insp-body">
              {inspTab === "properties" && pin && (
                <>
                  <button className="maps-insp-back" type="button" onClick={() => setSelectedPin(null)}>
                    ← Camera
                  </button>
                  <div className="cap">Pin</div>
                  <label>
                    Name:
                    <input
                      value={pin.name}
                      disabled={locked}
                      onChange={(event) =>
                        updateActive({ churches: (activeView?.churches || []).map((c) => (c.id === pin.id ? { ...c, name: event.target.value } : c)) })
                      }
                    />
                  </label>
                  <label>
                    Kind:
                    <select
                      value={pin.kind}
                      disabled={locked}
                      onChange={(event) =>
                        updateActive({
                          churches: (activeView?.churches || []).map((c) => (c.id === pin.id ? { ...c, kind: event.target.value as MapsPinKind } : c)),
                        })
                      }
                    >
                      <option value="dot">Dot</option>
                      <option value="dropPin">Drop pin</option>
                    </select>
                  </label>
                  <label>
                    Colour:
                    <input
                      type="color"
                      value={pin.color}
                      disabled={locked}
                      onChange={(event) =>
                        updateActive({ churches: (activeView?.churches || []).map((c) => (c.id === pin.id ? { ...c, color: event.target.value } : c)) })
                      }
                    />
                  </label>
                  <label className="maps-check">
                    <input
                      type="checkbox"
                      checked={pin.showLabel !== false}
                      disabled={locked}
                      onChange={(event) =>
                        updateActive({ churches: (activeView?.churches || []).map((c) => (c.id === pin.id ? { ...c, showLabel: event.target.checked } : c)) })
                      }
                    />
                    Show label on map
                  </label>
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={locked}
                    onClick={() => {
                      updateActive({ churches: (activeView?.churches || []).filter((c) => c.id !== pin.id) });
                      setSelectedPin(null);
                      setSelectedPins((ids) => ids.filter((id) => id !== pin.id));
                    }}
                  >
                    Remove pin
                  </button>
                </>
              )}
              {inspTab === "properties" && !pin && (
                <>
                  <div className="cap">Viewport</div>
                  {active.cg ? (
                    <div className="seg">
                      <button
                        type="button"
                        className={activeAudience === "lw" ? "on" : ""}
                        disabled={locked}
                        onClick={() => void selectSlide(active.id, { audience: "lw" })}
                      >
                        {sidePanels || active.includeSidePanels ? "FW" : "LW"}
                      </button>
                      <button
                        type="button"
                        className={activeAudience === "cg" ? "on" : ""}
                        disabled={locked}
                        onClick={() => void selectSlide(active.id, { audience: "cg" })}
                      >
                        CG
                      </button>
                      <button type="button" disabled={locked} onClick={mergeCg}>
                        Merge CG
                      </button>
                    </div>
                  ) : (
                    <button className="btn secondary" type="button" disabled={locked} onClick={splitCg}>
                      Split CG viewport
                    </button>
                  )}
                  <div className="cap">Camera</div>
                  <label>
                    Title:
                    <input value={active.title} disabled={locked} onChange={(event) => updateActive({ title: event.target.value })} />
                  </label>
                  <AeScrub
                    label="Latitude"
                    value={activeView?.camera.lat ?? 0}
                    min={-MAX_LAT}
                    max={MAX_LAT}
                    step={0.01}
                    digits={4}
                    disabled={locked}
                    onChange={(lat) => {
                      if (!activeView) return;
                      const camera = { ...activeView.camera, lat };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Longitude"
                    value={activeView?.camera.lon ?? 0}
                    min={-180}
                    max={180}
                    step={0.01}
                    digits={4}
                    disabled={locked}
                    onChange={(lon) => {
                      if (!activeView) return;
                      const camera = { ...activeView.camera, lon };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Zoom"
                    value={activeView?.camera.zoom ?? zoomFloor}
                    min={zoomFloor}
                    max={22}
                    step={0.1}
                    slider
                    disabled={locked}
                    onChange={(zoom) => {
                      if (!activeView) return;
                      const camera = { ...activeView.camera, zoom: clampZoom(zoom, zoomFloor) };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  {wrapWarn && <p className="maps-wrap-note">{wrapWarn}</p>}
                  <AeScrub
                    label="Pitch"
                    value={activeView?.camera.pitch ?? 0}
                    min={0}
                    max={60}
                    step={1}
                    digits={0}
                    disabled={locked}
                    onChange={(pitch) => {
                      if (!activeView) return;
                      const camera = { ...activeView.camera, pitch };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Bearing"
                    value={activeView?.camera.bearing ?? 0}
                    min={-180}
                    max={180}
                    step={1}
                    digits={0}
                    disabled={locked}
                    onChange={(bearing) => {
                      if (!activeView) return;
                      const camera = { ...activeView.camera, bearing };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  {activeAudience === "lw" && (
                    <>
                      <AeScrub
                        label="CG shift X"
                        value={active.cgShiftX}
                        min={-CG_SHIFT_MAX}
                        max={CG_SHIFT_MAX}
                        step={1}
                        digits={0}
                        disabled={locked || doc?.exportCg === false}
                        onChange={(dx) => updateActive(clampCgShift(dx, 0))}
                        onCommit={() => void flushAndSave(true)}
                      />
                      <label className="maps-check" title="Off (default) captures the 3840×1080 LED centre so Keynote side-panel art can show. On fills the 7680×1080 wall.">
                        <input
                          type="checkbox"
                          checked={active.includeSidePanels === true}
                          disabled={locked}
                          onChange={(event) => updateActive({ includeSidePanels: event.target.checked })}
                        />
                        Include side panels for render
                      </label>
                    </>
                  )}
                  {(activeView?.highlights.length || 0) > 0 && (
                    <div className="maps-hl">
                      <div className="cap">Orange countries</div>
                      <div className="maps-hl-list">
                        {(activeView?.highlights || []).map((code) => (
                          <button
                            key={`${code}-${namesTick}`}
                            className="maps-hl-chip"
                            type="button"
                            disabled={locked}
                            title="Remove highlight"
                            onClick={() =>
                              updateActive({ highlights: (activeView?.highlights || []).filter((item) => item !== code) })
                            }
                          >
                            {admin0Name(code)}
                            <span aria-hidden="true">×</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
              {inspTab === "pins" && (
                <>
                  {(activeView?.churches.length || 0) === 0 ? (
                    <p className="note">Shift-click the map to add a pin. Double-click a pin to rename it.</p>
                  ) : (
                    <>
                      <div className="maps-pin-bulk" role="group" aria-label="Selected pins">
                        <span className="note">{selectedPins.length ? `${selectedPins.length} selected` : "Select pins"}</span>
                        <button className="btn secondary" type="button" disabled={locked || selectedPins.length === 0} onClick={() => updateSelectedPins({ showLabel: true })}>
                          Show labels
                        </button>
                        <button className="btn secondary" type="button" disabled={locked || selectedPins.length === 0} onClick={() => updateSelectedPins({ showLabel: false })}>
                          Hide labels
                        </button>
                        <button className="btn maps-delete maps-pin-bulk-delete" type="button" disabled={locked || selectedPins.length === 0} onClick={deleteSelectedPins} title="Delete selected pins" aria-label="Delete selected pins">
                          <IconTrash />
                        </button>
                      </div>
                      <div className="maps-pin-list">
                        {(activeView?.churches || []).map((church) => (
                          <div key={church.id} className={`maps-pin-row${selectedPin === church.id ? " active" : ""}`}>
                            <label className="maps-pin-select" aria-label={`Select ${church.name}`}>
                              <input
                                type="checkbox"
                                checked={selectedPins.includes(church.id)}
                                disabled={locked}
                                onChange={(event) => togglePinSelection(church.id, event.target.checked)}
                              />
                            </label>
                            <button type="button" className="maps-pin-open" disabled={locked} onClick={() => openPin(church.id)}>
                              <span className="maps-pin-swatch" style={{ background: church.color }} />
                              <span className="maps-pin-name">{church.name}</span>
                              {church.showLabel === false && <span className="maps-pin-hidden">Hidden</span>}
                            </button>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
              {inspTab === "animation" && !outgoing && (
                <p className="note">Last slide — no hop to the next shot.</p>
              )}
              {inspTab === "animation" && outgoing && (
                <div className="maps-hop">
                  <div className="cap">Hop to next</div>
                  {(["morph", "movie", "dissolve", "cut"] as MapsHopKind[]).map((kind) => (
                    <label key={kind} className="maps-check" title={HOP_TIPS[kind]}>
                      <input
                        type="radio"
                        checked={outgoing.kind === kind}
                        disabled={locked || (kind === "morph" && !morphOk)}
                        onChange={() => setHop({ kind, easing: kind === "movie" ? outgoing.easing : undefined })}
                      />
                      {HOP_LABELS[kind]}
                    </label>
                  ))}
                  {nextView && activeView && <MorphGates from={activeView} to={nextView} />}
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={locked}
                    onClick={() =>
                      setHop(
                        { kind: suggested, easing: suggested === "movie" ? outgoing.easing || "ease-in-out" : undefined },
                        { dropRoute: true, resetFly: true }
                      )
                    }
                  >
                    Reset hop
                  </button>
                  <AeScrub
                    label="Duration"
                    value={outgoing.duration}
                    min={0.15}
                    max={10}
                    step={0.1}
                    disabled={locked}
                    onChange={(duration) => {
                      const prev = Math.max(0.15, outgoing.duration);
                      if (outgoing.kind === "movie" && (outgoing.easeIn != null || outgoing.easeOut != null)) {
                        const scale = duration / prev;
                        setHop({
                          duration,
                          easeIn: (outgoing.easeIn ?? prev * 0.25) * scale,
                          easeOut: (outgoing.easeOut ?? prev * 0.25) * scale,
                        });
                        return;
                      }
                      setHop({ duration });
                    }}
                  />
                  <label className="maps-check">
                    <input
                      type="checkbox"
                      checked={outgoing.playWithoutClick}
                      disabled={locked}
                      onChange={(event) => setHop({ playWithoutClick: event.target.checked })}
                    />
                    Play without a click
                  </label>
                  {outgoing.kind === "movie" && (
                    <>
                      <HopTimeline
                        duration={outgoing.duration}
                        easeIn={outgoing.easeIn}
                        easeOut={outgoing.easeOut}
                        disabled={locked}
                        onChange={(next) => setHop(next)}
                        onCommit={() => void flushAndSave(true)}
                      />
                      <AeScrub
                        label="Cruise zoom"
                        value={outgoing.flyZoom ?? cruiseAuto}
                        min={zoomFloor}
                        max={22}
                        step={0.1}
                        slider
                        disabled={locked}
                        onChange={(flyZoom) => setHop({ flyZoom })}
                      />
                      {outgoing.flyZoom != null && (
                        <button className="btn secondary" type="button" disabled={locked} onClick={() => setHop({}, { dropFlyZoom: true })}>
                          Auto cruise zoom
                        </button>
                      )}
                      <label>
                        Move easing:
                        <select
                          value={outgoing.easing || "ease-in-out"}
                          disabled={locked}
                          onChange={(event) => setHop({ easing: event.target.value as MapsEasing })}
                        >
                          <option value="ease-in-out">ease-in-out</option>
                          <option value="linear">linear</option>
                          <option value="ease-in">ease-in</option>
                          <option value="ease-out">ease-out</option>
                        </select>
                      </label>
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={locked || (activeView?.churches.length || 0) < 2}
                        onClick={() =>
                          setHop({
                            route: { points: (activeView?.churches || []).map((church) => ({ lat: church.lat, lon: church.lon })) },
                          })
                        }
                      >
                        Use pins as route
                      </button>
                      {outgoing.route?.points && outgoing.route.points.length >= 2 && (
                        <button
                          className="btn secondary"
                          type="button"
                          disabled={locked}
                          title="Clear route"
                          onClick={() => setHop({}, { dropRoute: true })}
                        >
                          Route: {outgoing.route.points.length} pts
                        </button>
                      )}
                      <button
                        className="btn secondary"
                        type="button"
                        disabled={locked}
                        onClick={() => void playHop(activeIndex, true)}
                      >
                        <IconPlay />
                        Play hop
                      </button>
                    </>
                  )}
                  <button className="btn secondary" type="button" disabled={locked} onClick={() => void playFromHere()}>
                    <IconPlay />
                    Play from here
                  </button>
                </div>
              )}
              {inspTab === "export" && (
                <div>
                  <div className="cap">Export to Keynote</div>
                  <label className="maps-check">
                    <input
                      type="checkbox"
                      checked={doc?.exportLw !== false}
                      disabled={locked}
                      onChange={(event) => {
                        if (!doc) return;
                        const exportLw = event.target.checked;
                        const exportCg = !exportLw && !doc.exportCg && !doc.exportDsk ? true : doc.exportCg;
                        patchDoc({ ...doc, exportLw, exportCg });
                      }}
                    />
                    LED wall (7680×1080)
                  </label>
                  <label className="maps-check">
                    <input
                      type="checkbox"
                      checked={doc?.exportCg !== false}
                      disabled={locked}
                      onChange={(event) => {
                        if (!doc) return;
                        const exportCg = event.target.checked;
                        const exportLw = !exportCg && !doc.exportLw && !doc.exportDsk ? true : doc.exportLw;
                        patchDoc({ ...doc, exportLw, exportCg });
                      }}
                    />
                    CG (1920×1080)
                  </label>
                  <label className="maps-check">
                    <input
                      type="checkbox"
                      checked={doc?.exportDsk === true}
                      disabled={locked}
                      onChange={(event) => {
                        if (!doc) return;
                        const exportDsk = event.target.checked;
                        const exportLw = !exportDsk && !doc.exportLw && !doc.exportCg ? true : doc.exportLw;
                        patchDoc({ ...doc, exportLw, exportDsk });
                      }}
                    />
                    DSK lower third (1920×1080)
                  </label>
                  <button className="btn" type="button" disabled={locked} onClick={() => void onExport()}>
                    Export
                  </button>
                  {exporting ? (
                    <button className="btn secondary" type="button" onClick={() => { exportAbort.current = true; }}>
                      Cancel
                    </button>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </div>
        )}
      </div>
      {(exporting || job?.status === "queued" || job?.status === "running") && (
        <LoadingOverlay
          title="Working…"
          logs={logs}
          onCancel={exporting ? () => { exportAbort.current = true; } : undefined}
        />
      )}
    </div>
  );
}
