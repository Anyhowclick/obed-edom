export function loupeCorner(x: number, y: number, w: number, h: number): "tl" | "tr" | "bl" | "br" {
  const left = x <= w / 2;
  const top = y <= h / 2;
  if (top && left) return "br";
  if (top && !left) return "bl";
  if (!top && left) return "tr";
  return "tl";
}
