import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../server/static",
    emptyOutDir: true,
    target: "es2020",
    // Phaser alone is ~1.2 MB: keep it in its own chunk so a redeploy of our code leaves the engine cached
    // in the browser (and the "chunk larger than 500 kB" note stops firing for our bundle).
    rolldownOptions: {
      output: {
        codeSplitting: { groups: [{ name: "phaser", test: /node_modules[\/]phaser/ }] },
      },
    },
    chunkSizeWarningLimit: 1500,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
