// Vite config for the Omni UI. Also carries the vitest config so the whole
// front end builds and tests from one file — no parallel config to drift.
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // Two windows, two entries: the main app and the M5 dictation pill
  // overlay (src-tauri loads pill.html into the "pill" window).
  build: {
    rollupOptions: {
      // Relative to the config root; plain strings keep node typings out.
      input: {
        main: "./index.html",
        pill: "./pill.html",
      },
    },
  },

  // Tauri expects a fixed dev port (see src-tauri/tauri.conf.json devUrl).
  // strictPort fails fast instead of silently moving — the shell would
  // otherwise load a blank window pointing at the wrong port.
  server: {
    port: 1420,
    strictPort: true,
  },
  // Keep terminal output visible alongside `tauri dev` logs.
  clearScreen: false,

  test: {
    environment: "jsdom",
    // CSS is irrelevant to these tests and tokens.css is design-agent-owned;
    // never let a missing/changed stylesheet fail logic tests.
    css: false,
  },
});
