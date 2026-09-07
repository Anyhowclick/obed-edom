import { useEffect, useMemo, useRef, useState } from "react";
import {
  bootstrapMapsCsv,
  exportMaps,
  fetchMapsExportPlan,
  geocodeMaps,
  listJobs,
  pollJob,
  postMapsFrame,
  postMapsPng,
  prefetchMapsTiles,
  previewUrl,
  saveMapsState,
  startMaps,
  type Job,
} from "../api";
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
  WORLD_MIN_ZOOM,
  captureWidth,
  clampCgShift,
  coerceHopKinds,
  documentFromResult,
  nextPinId,
  nextSlideId,
  suggestedHopKind,
  type MapsCamera,
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
  morph: "Magic Move: Keynote pan/zoom of a shared plate. Same map style, no 3D, zoom change ≤ 1. Region highlights must match; panning off-screen is fine.",
  movie: "Movie: rendered fly when pitch, bearing, 3D buildings, or a zoom jump > 1. Three phases: zoom out, move, zoom in.",
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

function cloneSlide(slide: MapsSlide, id: string): MapsSlide {
  return {
    ...slide,
    id,
    churches: [],
    stillPng: undefined,
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
  const [selectedPin, setSelectedPin] = useState<string | null>(null);
  const [inspTab, setInspTab] = useState<InspectorTab>("properties");
  const [previewing, setPreviewing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const mapRef = useRef<MapViewHandle | null>(null);
  const jobRef = useRef<Job | null>(null);
  const docRef = useRef<MapsDocument | null>(null);
  const activeRef = useRef<string | null>(null);
  const previewingRef = useRef(false);
  const exportingRef = useRef(false);
  const previewAbort = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const csvInput = useRef<HTMLInputElement | null>(null);
  const csvMode = useRef<"append" | "replace">("append");
  const savedCamera = useRef<MapsCamera | null>(null);
  const [navW, setNavW] = useState(() => {
    const raw = Number(window.localStorage.getItem("obed-edom.maps.navW"));
    return Number.isFinite(raw) && raw >= 160 ? Math.min(420, raw) : 220;
  });
  const navDrag = useRef<{ x: number; w: number } | null>(null);
  const [sidePanels, setSidePanels] = useSessionToggle(MAPS_SIDE_PANELS_KEY, true);
  const [inspectorOpen, setInspectorOpen] = useSessionToggle(MAPS_INSPECTOR_KEY, true);
  const [layersOpen, setLayersOpen] = useState(false);
  const layersRef = useRef<HTMLDivElement | null>(null);
  const [namesTick, setNamesTick] = useState(0);

  useEffect(() => {
    void loadAdmin0().then(() => setNamesTick((n) => n + 1));
  }, []);

  const doc = documentFromResult(job?.result as Record<string, unknown> | undefined);
  jobRef.current = job;
  docRef.current = doc;
  activeRef.current = activeId;
  previewingRef.current = previewing;

  const slides = doc?.slides || [];
  const active = slides.find((s) => s.id === activeId) || slides[0] || null;
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
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      void flushAndSave(true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    mapRef.current?.resize();
  }, [sidePanels, inspectorOpen, navW]);

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

  const locked = job?.status === "queued" || job?.status === "running" || previewing || exporting;

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
      void saveMapsState(scheduledId, coerceHopKinds(docRef.current || next))
        .then((updated) => {
          if (jobRef.current?.id !== scheduledId) return;
          mergeServerMeta(updated);
        })
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
    };
    if (immediate) run();
    else saveTimer.current = window.setTimeout(run, 500);
  }

  function writeCameraInto(slideId: string): MapsDocument | null {
    const current = docRef.current;
    if (!current) return null;
    const cam = mapRef.current?.getCamera();
    if (!cam) return current;
    const slidesNext = current.slides.map((slide) => (slide.id === slideId ? { ...slide, camera: cam } : slide));
    return applyLocalDoc({ ...current, slides: slidesNext }) ?? current;
  }

  async function captureThumb(slideId: string) {
    const currentJob = jobRef.current;
    if (!currentJob) return;
    const blob = await mapRef.current?.captureBlob();
    if (!blob) return;
    const stamped = await stampOsm(blob);
    const updated = await postMapsPng(currentJob.id, stamped, { kind: "thumb", slideId });
    const still = (updated.result?.slides as Array<{ id?: string; stillPng?: string }> | undefined)?.find((s) => s.id === slideId)?.stillPng;
    const local = docRef.current;
    if (!local || !still) return;
    const files = (updated.result?.previewFiles as { maps?: string[] } | undefined) || {};
    const next = {
      ...local,
      slides: local.slides.map((slide) => (slide.id === slideId ? { ...slide, stillPng: still } : slide)),
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

  async function selectSlide(nextId: string, opts?: { flush?: boolean }) {
    if (nextId === activeRef.current) return;
    if (previewingRef.current) stopPreview(true);
    const prev = activeRef.current;
    if (prev && opts?.flush !== false) {
      const next = writeCameraInto(prev);
      await captureThumb(prev);
      if (next && jobRef.current) scheduleSave(docRef.current || next, true);
    }
    setActiveId(nextId);
    setSelectedPin(null);
    const slide = docRef.current?.slides.find((s) => s.id === nextId);
    if (slide) mapRef.current?.jumpTo(slide.camera);
  }

  async function createDeck() {
    setError(null);
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    clearOpenRun();
    const created = await startMaps();
    setJob(created);
    const done = await pollJob(created.id, (tick) => {
      setLogs(tick.logs);
      setJob(tick);
    });
    setJob(done);
    const next = documentFromResult(done.result);
    setActiveId(next?.slides[0]?.id || null);
  }

  function onCameraCommit(camera: MapsCamera) {
    const current = docRef.current;
    const id = activeRef.current;
    if (!current || !id || previewingRef.current) return;
    const slidesNext = current.slides.map((slide) => (slide.id === id ? { ...slide, camera } : slide));
    patchDoc({ ...current, slides: slidesNext });
  }

  function updateActive(partial: Partial<MapsSlide>) {
    const current = docRef.current;
    const id = activeRef.current;
    if (!current || !id) return;
    patchDoc({
      ...current,
      slides: current.slides.map((slide) => (slide.id === id ? { ...slide, ...partial } : slide)),
    });
  }

  function setDeckStyle(style: MapsStyleId) {
    const current = docRef.current;
    if (!current) return;
    patchDoc({
      ...current,
      defaultStyle: style,
      slides: current.slides.map((slide) => ({ ...slide, style })),
    });
  }

  function toggleHiddenLayer(id: MapsLayerFilterId) {
    const current = docRef.current;
    if (!current) return;
    const hidden = current.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS;
    const has = hidden.includes(id);
    patchDoc({
      ...current,
      hiddenLayers: has ? hidden.filter((item) => item !== id) : [...hidden, id],
    });
  }

  function toggleCachedCountry(code: string, nextSelected: string[]) {
    const current = docRef.current;
    if (!current) return;
    patchDoc({ ...current, cachedCountries: nextSelected });
    const adding = nextSelected.some((item) => item.toUpperCase() === code.toUpperCase());
    if (!adding) return;
    void prefetchMapsTiles({ countries: [code], maxzoom: 8 })
      .then((stats) => {
        setLogs((prev) => [...prev, `Cached ${code}: ${stats.cached + stats.fetched} tiles.`]);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
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
    setActiveId(fallback.id);
    mapRef.current?.jumpTo(fallback.camera);
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

  async function previewLink(link: MapsLink, from: MapsSlide, to: MapsSlide) {
    if (link.kind === "cut" || link.kind === "dissolve") {
      await new Promise((r) => setTimeout(r, link.duration * 1000));
      if (!previewAbort.current) mapRef.current?.jumpTo(to.camera);
      return;
    }
    if (link.kind === "movie") {
      await mapRef.current?.animateHop({
        from: from.camera,
        to: to.camera,
        durationMs: link.duration * 1000,
        easing: link.easing,
        routePoints: link.route?.points,
        flyZoom: link.flyZoom,
        easeIn: link.easeIn,
        easeOut: link.easeOut,
      });
      return;
    }
    await mapRef.current?.easeTo(to.camera, link.duration * 1000);
  }

  async function playHop(fromIndex: number, restore: boolean) {
    const current = docRef.current;
    if (!current || fromIndex < 0 || fromIndex >= current.slides.length - 1 || exportingRef.current) return;
    const from = current.slides[fromIndex];
    const to = current.slides[fromIndex + 1];
    const link = linkBetween(current.links, from.id, to.id);
    if (!link) return;
    previewAbort.current = false;
    savedCamera.current = mapRef.current?.getCamera() || from.camera;
    setPreviewing(true);
    await previewLink(link, from, to);
    if (previewAbort.current) return;
    if (restore) stopPreview(true);
    else setPreviewing(false);
  }

  function stopPreview(restore: boolean) {
    previewAbort.current = true;
    mapRef.current?.stop();
    setPreviewing(false);
    if (restore && savedCamera.current) mapRef.current?.jumpTo(savedCamera.current);
    savedCamera.current = null;
  }

  async function playFromHere() {
    const current = docRef.current;
    if (!current || activeIndex < 0 || exportingRef.current) return;
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
    await selectSlide(last.id, { flush: false });
  }

  async function onCsv(file: File, replace: boolean) {
    if (!job) return;
    setError(null);
    try {
      const started = await bootstrapMapsCsv(job.id, file, replace);
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

  async function onExport() {
    if (exportingRef.current) return;
    const currentJob = jobRef.current;
    if (!currentJob) return;
    if (currentJob.status === "queued" || currentJob.status === "running") return;
    if (previewingRef.current) stopPreview(true);
    exportingRef.current = true;
    setExporting(true);
    setError(null);
    setLogs((prev) => [...prev, "Exporting maps…"]);
    try {
      await flushAndSave(true);
      const id = jobRef.current?.id;
      if (!id) throw new Error("Maps job is gone");
      const plan = await fetchMapsExportPlan(id);
      const local = docRef.current;
      if (!local) throw new Error("Maps document is not loaded");
      const next = coerceHopKinds({ ...local, links: plan.links as MapsLink[] });
      applyLocalDoc(next);
      await saveMapsState(id, next).then((updated) => mergeServerMeta(updated));
      for (const still of plan.stills) {
        const blob = await captureExportRaster({
          width: still.width || 3840,
          height: still.height || 1080,
          camera: still.camera,
          styleId: still.style as MapsSlide["style"],
          highlights: still.highlights,
          hiddenLayers: local.hiddenLayers,
        });
        await postMapsPng(id, blob, { kind: "still", slideId: still.slideId });
      }
      for (const plate of plan.plates) {
        const blob = await captureExportRaster({
          width: plate.plateW,
          height: plate.plateH,
          camera: plate.camera,
          styleId: plate.style as MapsSlide["style"],
          highlights: plate.highlights,
          hiddenLayers: local.hiddenLayers,
        });
        await postMapsPng(id, blob, { kind: "plate", plateId: plate.plateId });
      }
      const slidesById = new Map((docRef.current?.slides || []).map((slide) => [slide.id, slide]));
      for (const link of docRef.current?.links || []) {
        if (link.kind !== "movie") continue;
        const from = slidesById.get(link.from);
        const to = slidesById.get(link.to);
        if (!from || !to) continue;
        const width = captureWidth(from);
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
          })
        );
        setLogs((prev) => [...prev, `Prefetching tiles for ${from.id} → ${to.id}…`]);
        try {
          const stats = await prefetchMapsTiles({ cameras, width, height, maxzoom: 14 });
          setLogs((prev) => [...prev, `Cached ${stats.cached + stats.fetched} / ${stats.tiles} tiles (${stats.failed} failed).`]);
        } catch (err) {
          setLogs((prev) => [...prev, `Tile prefetch skipped: ${err instanceof Error ? err.message : String(err)}`]);
        }
        setLogs((prev) => [...prev, `Rendering movie ${from.id} → ${to.id}…`]);
        await captureFlyFrames({
          width,
          height,
          from: from.camera,
          to: to.camera,
          styleId: from.style,
          highlights: from.highlights,
          hiddenLayers: local.hiddenLayers,
          duration: link.duration,
          fps: 30,
          easing: link.easing,
          routePoints: link.route?.points,
          flyZoom: link.flyZoom,
          easeIn: link.easeIn,
          easeOut: link.easeOut,
          onFrame: (blob, i, n) => postMapsFrame(id, blob, { slideId: from.id, index: i, count: n, fps: 30 }).then(() => undefined),
        });
      }
      const latest = docRef.current;
      const started = await exportMaps(id, { exportLw: latest?.exportLw, exportCg: latest?.exportCg });
      setJob(started);
      const done = await pollJob(started.id, (tick) => {
        setLogs(tick.logs);
        setJob(tick);
      });
      setJob(done);
      if (done.status === "error") setError(done.error || "Export failed");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      exportingRef.current = false;
      setExporting(false);
    }
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && previewingRef.current) stopPreview(true);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pin = active?.churches.find((c) => c.id === selectedPin) || null;
  const nextSlide = outgoing && activeIndex >= 0 ? slides[activeIndex + 1] : null;
  const suggested = outgoing && active && nextSlide ? suggestedHopKind(active, nextSlide) : "morph";
  const morphOk = suggested === "morph";
  const movieOk = suggested !== "cut";
  const cruiseAuto = active && nextSlide ? autoCruiseZoom(active.camera, nextSlide.camera) : WORLD_MIN_ZOOM;

  if (!job) {
    return (
      <div>
        <h1>Maps</h1>
        <p className="lede">Author LED-wall cameras, then export Keynote stills. Nothing is created until you start a deck.</p>
        {(error || openError) && <p className="err">{error || openError}</p>}
        <button className="btn" type="button" onClick={() => void createDeck()}>
          New map deck
        </button>
      </div>
    );
  }

  return (
    <div className="maps-tab">
      <div className="maps-chrome">
      <div className="maps-toolbar">
        <button className="btn secondary" type="button" onClick={() => void createDeck()} disabled={locked}>
          New map deck
        </button>
        <button
          className="btn secondary"
          type="button"
          onClick={() => {
            csvMode.current = "append";
            csvInput.current?.click();
          }}
          disabled={locked}
        >
          New slides from CSV…
        </button>
        <button
          className="btn secondary"
          type="button"
          disabled={locked}
          onClick={() => {
            if (!window.confirm("Replace the whole deck from a CSV? Existing slides will be discarded.")) return;
            csvMode.current = "replace";
            csvInput.current?.click();
          }}
        >
          Replace deck from CSV…
        </button>
        <input
          ref={csvInput}
          type="file"
          accept=".csv,text/csv"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            const replace = csvMode.current === "replace";
            csvMode.current = "append";
            if (file) void onCsv(file, replace);
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
              className={`maps-swatch${(doc?.defaultStyle || active?.style) === swatch.id ? " active" : ""}`}
              style={{ background: swatch.color }}
              disabled={locked}
              onClick={() => setDeckStyle(swatch.id)}
            />
          ))}
        </div>
        <div className="maps-layers" ref={layersRef}>
          <button
            className={`btn secondary icon-btn maps-layers-btn${layersOpen || (doc?.hiddenLayers.length || 0) ? " on" : ""}`}
            type="button"
            aria-expanded={layersOpen}
            aria-haspopup="true"
            title={(doc?.hiddenLayers.length || 0) ? `${doc?.hiddenLayers.length} layers hidden` : "Map layers"}
            aria-label={(doc?.hiddenLayers.length || 0) ? `Map layers, ${doc?.hiddenLayers.length} hidden` : "Map layers"}
            onClick={() => setLayersOpen((open) => !open)}
          >
            <IconLayers />
            {(doc?.hiddenLayers.length || 0) ? <span className="maps-layers-count">{doc?.hiddenLayers.length}</span> : null}
          </button>
          {layersOpen && (
            <div className="maps-layers-menu" role="group" aria-label="Hide map layers">
              {LAYER_FILTERS.map((item) => {
                const hidden = doc?.hiddenLayers.includes(item.id) || false;
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
        <CountryCachePicker
          selected={doc?.cachedCountries || []}
          disabled={locked}
          onToggle={toggleCachedCountry}
        />
      </div>
      </div>
      {(error || openError) && <p className="err">{error || openError}</p>}
      {job.error && <p className="err">{job.error}</p>}

      <div
        className="maps-stage"
        style={{ gridTemplateColumns: inspectorOpen ? `${navW}px 8px minmax(0, 1fr) 312px` : `${navW}px 8px minmax(0, 1fr)` }}
      >
        <div className="maps-nav">
          {slides.map((slide, index) => {
            const next = slides[index + 1];
            const hop = next ? linkBetween(doc?.links || [], slide.id, next.id) : null;
            const src = slide.stillPng && job.id ? previewUrl(job.id, "maps", slide.stillPng) : "";
            return (
              <div key={slide.id}>
                <button
                  type="button"
                  className={`maps-thumb${slide.id === active?.id ? " active" : ""}${slide.includeSidePanels ? " fw" : " lw"}`}
                  disabled={locked}
                  title={slide.includeSidePanels ? "Full wall render (side panels)" : "Centre wall (LW)"}
                  onClick={() => void selectSlide(slide.id)}
                >
                  {src ? <img src={`${src}?t=${job.updatedAt || ""}`} alt="" /> : <span className="note">{slide.title}</span>}
                  <span className="maps-thumb-label">{slide.title}</span>
                </button>
                {hop && (
                  <div className="maps-gutter">
                    <span className="maps-gutter-line" />
                    <span className="maps-gutter-kind" title={HOP_TIPS[hop.kind]}>
                      {HOP_LABELS[hop.kind]}
                    </span>
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
                camera={active.camera}
                styleId={active.style}
                highlights={active.highlights}
                churches={active.churches}
                numberPins={outgoing?.kind === "movie"}
                crop={doc?.crop || "center+cg"}
                sidePanels={sidePanels}
                exportCg={doc?.exportCg !== false}
                hiddenLayers={doc?.hiddenLayers ?? DEFAULT_HIDDEN_LAYERS}
                cgShiftX={active.cgShiftX}
                previewing={previewing}
                selectedPinId={selectedPin}
                onCameraCommit={onCameraCommit}
                onToggleCountry={(adm0) => {
                  const has = active.highlights.includes(adm0);
                  updateActive({ highlights: has ? active.highlights.filter((h) => h !== adm0) : [...active.highlights, adm0] });
                }}
                onAddPin={(lat, lon) => {
                  const church: MapsChurch = {
                    id: nextPinId(active.churches),
                    name: "Pin",
                    lat,
                    lon,
                    kind: "dropPin",
                    color: "#c44a42",
                  };
                  updateActive({ churches: [...active.churches, church] });
                  openPin(church.id);
                }}
                onSelectPin={(id) => {
                  if (id) openPin(id);
                  else setSelectedPin(null);
                }}
                onEditPin={(id) => {
                  const church = active.churches.find((c) => c.id === id);
                  if (!church) return;
                  const name = window.prompt("Pin name", church.name);
                  if (name == null) return;
                  updateActive({ churches: active.churches.map((c) => (c.id === id ? { ...c, name } : c)) });
                }}
                onCgShift={(dx) => updateActive(clampCgShift(dx, 0))}
                onPreviewAbort={() => stopPreview(true)}
              />
              <label className="maps-zoom-slider">
                <span>Zoom</span>
                <input
                  type="range"
                  min={WORLD_MIN_ZOOM}
                  max={22}
                  step={0.1}
                  value={Number.isFinite(active.camera.zoom) ? active.camera.zoom : WORLD_MIN_ZOOM}
                  disabled={locked}
                  onChange={(event) => {
                    const camera = { ...active.camera, zoom: Number(event.target.value) };
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
                {tab.id === "pins" && (active?.churches.length || 0) > 0 && (
                  <span className="maps-insp-count">{active?.churches.length}</span>
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
                        updateActive({ churches: active.churches.map((c) => (c.id === pin.id ? { ...c, name: event.target.value } : c)) })
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
                          churches: active.churches.map((c) => (c.id === pin.id ? { ...c, kind: event.target.value as MapsPinKind } : c)),
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
                        updateActive({ churches: active.churches.map((c) => (c.id === pin.id ? { ...c, color: event.target.value } : c)) })
                      }
                    />
                  </label>
                  <button
                    className="btn secondary"
                    type="button"
                    disabled={locked}
                    onClick={() => {
                      updateActive({ churches: active.churches.filter((c) => c.id !== pin.id) });
                      setSelectedPin(null);
                    }}
                  >
                    Remove pin
                  </button>
                </>
              )}
              {inspTab === "properties" && !pin && (
                <>
                  <div className="cap">Camera</div>
                  <label>
                    Title:
                    <input value={active.title} disabled={locked} onChange={(event) => updateActive({ title: event.target.value })} />
                  </label>
                  <AeScrub
                    label="Latitude"
                    value={active.camera.lat}
                    min={-MAX_LAT}
                    max={MAX_LAT}
                    step={0.01}
                    digits={4}
                    disabled={locked}
                    onChange={(lat) => {
                      const camera = { ...active.camera, lat };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Longitude"
                    value={active.camera.lon}
                    min={-180}
                    max={180}
                    step={0.01}
                    digits={4}
                    disabled={locked}
                    onChange={(lon) => {
                      const camera = { ...active.camera, lon };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Zoom"
                    value={active.camera.zoom}
                    min={WORLD_MIN_ZOOM}
                    max={22}
                    step={0.1}
                    slider
                    disabled={locked}
                    onChange={(zoom) => {
                      const camera = { ...active.camera, zoom };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Pitch"
                    value={active.camera.pitch}
                    min={0}
                    max={60}
                    step={1}
                    digits={0}
                    disabled={locked}
                    onChange={(pitch) => {
                      const camera = { ...active.camera, pitch };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
                  <AeScrub
                    label="Bearing"
                    value={active.camera.bearing}
                    min={-180}
                    max={180}
                    step={1}
                    digits={0}
                    disabled={locked}
                    onChange={(bearing) => {
                      const camera = { ...active.camera, bearing };
                      updateActive({ camera });
                      mapRef.current?.jumpTo(camera);
                    }}
                    onCommit={() => void flushAndSave(true)}
                  />
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
                  {active.highlights.length > 0 && (
                    <div className="maps-hl">
                      <div className="cap">Orange countries</div>
                      <div className="maps-hl-list">
                        {active.highlights.map((code) => (
                          <button
                            key={`${code}-${namesTick}`}
                            className="maps-hl-chip"
                            type="button"
                            disabled={locked}
                            title="Remove highlight"
                            onClick={() =>
                              updateActive({ highlights: active.highlights.filter((item) => item !== code) })
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
                  {active.churches.length === 0 ? (
                    <p className="note">Shift-click the map to add a pin. Double-click a pin to rename it.</p>
                  ) : (
                    <div className="maps-pin-list">
                      {active.churches.map((church) => (
                        <button
                          key={church.id}
                          type="button"
                          className={`maps-pin-row${selectedPin === church.id ? " active" : ""}`}
                          disabled={locked}
                          onClick={() => openPin(church.id)}
                        >
                          <span className="maps-pin-swatch" style={{ background: church.color }} />
                          <span className="maps-pin-name">{church.name}</span>
                        </button>
                      ))}
                    </div>
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
                        disabled={locked || (kind === "morph" && !morphOk) || (kind === "movie" && !movieOk)}
                        onChange={() => setHop({ kind, easing: kind === "movie" ? outgoing.easing : undefined })}
                      />
                      {HOP_LABELS[kind]}
                    </label>
                  ))}
                  {nextSlide && <MorphGates from={active} to={nextSlide} />}
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
                        min={WORLD_MIN_ZOOM}
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
                        disabled={locked || (active?.churches.length || 0) < 2}
                        onClick={() =>
                          setHop({
                            route: { points: (active?.churches || []).map((church) => ({ lat: church.lat, lon: church.lon })) },
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
                        const exportCg = exportLw ? doc.exportCg : true;
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
                        const exportLw = exportCg ? doc.exportLw : true;
                        patchDoc({ ...doc, exportLw, exportCg });
                      }}
                    />
                    CG (1920×1080)
                  </label>
                  <button className="btn" type="button" disabled={locked} onClick={() => void onExport()}>
                    Export
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
        )}
      </div>
      {(exporting || job?.status === "queued" || job?.status === "running") && (
        <LoadingOverlay title="Working…" logs={logs} />
      )}
    </div>
  );
}
