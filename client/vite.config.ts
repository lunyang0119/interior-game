import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../server/static",
    emptyOutDir: true,
    target: "es2020",
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
