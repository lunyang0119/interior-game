import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const page = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  build: {
    outDir: "../server/static",
    emptyOutDir: true,
    target: "es2020",
    // Phaser alone is ~1.2 MB: keep it in its own chunk so a redeploy of our code leaves the engine cached
    // in the browser (and the "chunk larger than 500 kB" note stops firing for our bundle).
    rolldownOptions: {
      // multipage: the room game at / and the train minigame at /train/ (served by FastAPI StaticFiles html=True)
      input: { main: page("./index.html"), train: page("./train/index.html") },
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
