const UPSTREAM_HOST = "tiles.openfreemap.org";

export function proxyOpenFreeMapUrl(url: string): string {
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.hostname === UPSTREAM_HOST) {
      return `/api/maps/tiles${parsed.pathname}${parsed.search}`;
    }
  } catch {
    /* keep the original URL */
  }
  return url;
}

export function mapsTransformRequest(url: string): { url: string } {
  return { url: proxyOpenFreeMapUrl(url) };
}
