import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

/** MapLibre v6 parses tiles in a separate ESM worker; Vite must be given that URL. */
setWorkerUrl(workerUrl);
