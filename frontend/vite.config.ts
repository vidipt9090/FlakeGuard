import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The UI is served by flakeguard/app/api.py in production, so the build goes
// to frontend/dist and the dev server proxies /api to that same process.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
