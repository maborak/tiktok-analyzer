import { defineConfig } from "vite";
import electron from "vite-plugin-electron";

const esmPreloadOutput = {
  build: {
    rollupOptions: {
      external: ["electron"],
      output: {
        format: "es" as const,
        entryFileNames: "[name].mjs",
        chunkFileNames: "[name].mjs",
      },
    },
  },
};

export default defineConfig({
  // Pin the (unused) renderer dev server to a fixed, off-the-beaten-path
  // port. This Electron client has no renderer of its own — it just loads
  // the framework `frontend/`'s URL — but vite-plugin-electron always
  // starts a Vite dev server. Pin it so it can never collide with the
  // frontend's port (5173 / 9021 / whatever the user picks).
  server: {
    port: 9099,
    strictPort: true,
  },
  plugins: [
    electron([
      // Main process
      { entry: "electron/main.ts" },
      // Preload for the framework's web app — exposes window.api.*
      {
        entry: "electron/preload.ts",
        onstart(args) {
          args.reload();
        },
        vite: esmPreloadOutput,
      },
      // Bridge preload that runs INSIDE the hidden TikTok BrowserWindow
      {
        entry: "electron/tiktok-bridge.ts",
        onstart(args) {
          args.reload();
        },
        vite: esmPreloadOutput,
      },
    ]),
  ],
  build: {
    outDir: "dist",
  },
});
