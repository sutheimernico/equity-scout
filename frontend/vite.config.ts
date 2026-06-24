import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base "./" → relative asset URLs so FastAPI can serve the built dist/ from "/".
// proxy → during `npm run dev`, /api calls are forwarded to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});
