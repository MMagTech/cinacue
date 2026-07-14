import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output is written straight into the backend's static directory so a
// single FastAPI process serves the compiled SPA. Relative base keeps asset
// URLs working regardless of the mount path / reverse proxy prefix.
//
// emptyOutDir is false because some mounts disallow deleting existing files;
// asset filenames are content-hashed, and the Docker build uses a clean stage,
// so stale files never cause incorrect output.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../app/static",
    emptyOutDir: false,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
