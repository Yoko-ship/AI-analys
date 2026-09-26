import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: "frontend",
  base: "/",
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
    // The public proxy's legacy .js route times out while the origin is healthy.
    // Emit standard ES-module filenames so every chunk uses the working route.
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name]-[hash].mjs",
        chunkFileNames: "assets/[name]-[hash].mjs",
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
