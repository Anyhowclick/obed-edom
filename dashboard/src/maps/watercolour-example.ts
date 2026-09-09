import { buildWatercolourStyle, installPatterns, watercolourPatterns } from "./watercolourStyle";

export async function useWatercolourStyle(map: { setStyle(style: object): void; once(event: string, callback: () => void): void; hasImage(id: string): boolean; addImage(id: string, image: ImageData, options?: object): void }, base: object): Promise<void> {
  const { style } = buildWatercolourStyle(base as never, {
    sourceUrl: "https://tiles.openfreemap.org/planet",
    glyphsUrl: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  });
  await new Promise<void>((resolve) => {
    map.once("style.load", () => {
      installPatterns(map, watercolourPatterns());
      resolve();
    });
    map.setStyle(style);
  });
}
