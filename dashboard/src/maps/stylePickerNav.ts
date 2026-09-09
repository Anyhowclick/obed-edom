export function nextGridIndex(index: number, key: string, count: number, cols: number): number {
  if (count <= 0) return 0;
  switch (key) {
    case "ArrowRight":
      return (index + 1 + count) % count;
    case "ArrowLeft":
      return (index - 1 + count) % count;
    case "ArrowDown": {
      const next = index + cols;
      return next <= count - 1 ? next : index;
    }
    case "ArrowUp": {
      const next = index - cols;
      return next >= 0 ? next : index;
    }
    case "Home":
      return 0;
    case "End":
      return count - 1;
    default:
      return index;
  }
}
