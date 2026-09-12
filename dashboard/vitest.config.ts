import { defineConfig, mergeConfig } from "vite";
import viteConfig from "./vite.config";

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      setupFiles: ["./tests-ui/setup.ts"],
      include: ["tests-ui/**/*.test.tsx"],
      clearMocks: true,
    },
  })
);
