import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Changes on every build. The persisted query cache is keyed on this, so a
// deploy that changes any response shape discards snapshots written by the
// previous build instead of replaying them into code that no longer expects
// them — see lib/queryPersistence.js.
const BUILD_ID = process.env.VITE_BUILD_ID ?? Date.now().toString(36);

export default defineConfig({
  define: {
    "import.meta.env.VITE_BUILD_ID": JSON.stringify(BUILD_ID),
  },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The backend serves the API; the SPA is a separate origin in development.
    // Proxying keeps the client's fetch paths identical in dev and production,
    // where the API is same-origin under SERVE_SPA.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 600,
  },
});
