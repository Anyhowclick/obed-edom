import { resolveDrop, type ChosenFile } from "./api";

function fileUrlToPath(url: string): string {
  try {
    const parsed = new URL(url);
    return decodeURIComponent(parsed.pathname);
  } catch {
    return decodeURIComponent(url.replace(/^file:\/\//, ""));
  }
}

export function pathsFromDataTransfer(dt: DataTransfer): string[] {
  const raw = dt.getData("text/uri-list") || dt.getData("text/plain") || "";
  const out: string[] = [];
  for (const line of raw.split(/\r?\n/)) {
    const text = line.trim();
    if (!text || text.startsWith("#")) continue;
    if (text.startsWith("file://")) out.push(fileUrlToPath(text));
    else if (text.startsWith("/")) out.push(text);
  }
  return out;
}

export async function resolveDroppedFolder(dt: DataTransfer): Promise<ChosenFile | { error: string }> {
  const urls = pathsFromDataTransfer(dt);
  const fromUrl = urls[0];
  if (fromUrl) {
    const folder = folderFromDroppedPath(fromUrl);
    return { path: folder, name: folder.split("/").pop() || folder };
  }
  const files = [...dt.files];
  for (const file of files) {
    const native = (file as File & { path?: string }).path;
    if (native) {
      const folder = folderFromDroppedPath(native);
      return { path: folder, name: folder.split("/").pop() || folder };
    }
  }
  const named = files[0];
  if (!named) {
    return { error: "Could not read that folder — use Choose on this Mac." };
  }
  try {
    const resolved = await resolveDrop(named.name, named.size);
    return { path: folderFromDroppedPath(resolved.path), name: folderFromDroppedPath(resolved.path).split("/").pop() || resolved.name };
  } catch (err) {
    return {
      error: err instanceof Error ? err.message : "Could not read that folder — use Choose on this Mac.",
    };
  }
}

function folderFromDroppedPath(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  if (/\.(png|jpe?g|webp|gif|tif|tiff)$/i.test(trimmed)) {
    return trimmed.replace(/\/[^/]+$/, "") || trimmed;
  }
  return trimmed;
}

export async function resolveDroppedKeynote(dt: DataTransfer): Promise<ChosenFile | { error: string }> {
  const urls = pathsFromDataTransfer(dt);
  const fromUrl = urls.find((p) => p.toLowerCase().endsWith(".key")) || urls[0];
  if (fromUrl) {
    return { path: fromUrl, name: fromUrl.split("/").pop() || fromUrl };
  }
  const files = [...dt.files];
  for (const file of files) {
    const native = (file as File & { path?: string }).path;
    if (native) {
      return { path: native, name: file.name };
    }
  }
  const named = files.find((f) => f.name.toLowerCase().endsWith(".key")) || files[0];
  if (!named) {
    return {
      error: "Keynote packages often hide the path — use Choose on this Mac.",
    };
  }
  try {
    return await resolveDrop(named.name, named.size);
  } catch (err) {
    return {
      error:
        err instanceof Error
          ? err.message
          : "Keynote packages often hide the path — use Choose on this Mac.",
    };
  }
}
