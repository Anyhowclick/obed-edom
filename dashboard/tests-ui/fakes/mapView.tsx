import { act } from "@testing-library/react";
import { forwardRef, useImperativeHandle } from "react";
import { vi } from "vitest";
import type { MapsCamera } from "../../src/maps/types";

export type ViewLogEntry = { type: string; props?: Record<string, unknown>; args?: unknown };

export function createMapViewFake() {
  const viewLog: ViewLogEntry[] = [];
  let latestProps: Record<string, unknown> = {};
  // Matches fakes/doc.ts's makeCamera() default so writeCameraInto (which reads this fake's
  // tracked camera back into the doc) is a no-op unless a test explicitly commits a new camera.
  let camera: MapsCamera = { lat: 1.3, lon: 103.8, zoom: 12, bearing: 0, pitch: 0 };
  let idleDeferred: { promise: Promise<void>; resolve: () => void } | null = null;

  function holdIdle() {
    let resolve!: () => void;
    const promise = new Promise<void>((r) => {
      resolve = r;
    });
    idleDeferred = { promise, resolve };
  }

  function releaseIdle() {
    idleDeferred?.resolve();
    idleDeferred = null;
  }

  const jumpTo = vi.fn((cam: MapsCamera) => {
    camera = cam;
    viewLog.push({ type: "jumpTo", args: cam });
  });
  const easeTo = vi.fn(async (cam: MapsCamera, durationMs: number) => {
    camera = cam;
    viewLog.push({ type: "easeTo", args: { cam, durationMs } });
  });
  const flyTo = vi.fn(async (cam: MapsCamera) => {
    camera = cam;
    viewLog.push({ type: "flyTo", args: cam });
  });
  const animateHop = vi.fn(async (opts: Record<string, unknown>) => {
    camera = opts.to as MapsCamera;
    viewLog.push({ type: "animateHop", args: opts });
  });
  const stop = vi.fn(() => viewLog.push({ type: "stop" }));
  const getCamera = vi.fn(() => camera);
  const getCgCamera = vi.fn((cgShiftX: number) => ({ ...camera, lon: camera.lon + cgShiftX }));
  const captureBlob = vi.fn(async () => new Blob(["thumb"]));
  const capturePreviewBlob = vi.fn(async () => new Blob(["preview"]));
  const waitUntilIdle = vi.fn(async () => {
    if (idleDeferred) await idleDeferred.promise;
  });
  const resize = vi.fn();

  function emitCameraCommit(cam: MapsCamera) {
    camera = cam;
    const handler = latestProps.onCameraCommit as ((c: MapsCamera) => void) | undefined;
    act(() => handler?.(cam));
  }

  function emitObjectMove(id: string, lat: number, lon: number) {
    const handler = latestProps.onMoveObject as ((id: string, lat: number, lon: number) => void) | undefined;
    act(() => handler?.(id, lat, lon));
  }

  function emitObjectCommit() {
    const handler = latestProps.onObjectCommit as (() => void) | undefined;
    act(() => handler?.());
  }

  function emitCgShift(dx: number) {
    const handler = latestProps.onCgShift as ((dx: number) => void) | undefined;
    act(() => handler?.(dx));
  }

  function emitPreviewAbort() {
    const handler = latestProps.onPreviewAbort as (() => void) | undefined;
    act(() => handler?.());
  }

  function emitToggleCountry(adm0: string) {
    const handler = latestProps.onToggleCountry as ((adm0: string) => void) | undefined;
    act(() => handler?.(adm0));
  }

  const MapView = forwardRef<unknown, Record<string, unknown>>(function MapViewFake(props, ref) {
    latestProps = props;
    viewLog.push({ type: "render", props });
    useImperativeHandle(ref, () => ({
      jumpTo,
      easeTo,
      flyTo,
      animateHop,
      stop,
      getCamera,
      getCgCamera,
      captureBlob,
      capturePreviewBlob,
      waitUntilIdle,
      resize,
    }));
    return <div data-testid="mapview" />;
  });

  return {
    MapView,
    viewLog,
    jumpTo,
    easeTo,
    flyTo,
    animateHop,
    stop,
    getCamera,
    getCgCamera,
    captureBlob,
    capturePreviewBlob,
    waitUntilIdle,
    resize,
    holdIdle,
    releaseIdle,
    getLatestProps: () => latestProps,
    emit: {
      cameraCommit: emitCameraCommit,
      objectMove: emitObjectMove,
      objectCommit: emitObjectCommit,
      cgShift: emitCgShift,
      previewAbort: emitPreviewAbort,
      toggleCountry: emitToggleCountry,
    },
  };
}

export type MapViewFake = ReturnType<typeof createMapViewFake>;
