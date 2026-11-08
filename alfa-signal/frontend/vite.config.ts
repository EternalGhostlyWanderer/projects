import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // Запросы /api из dev-сервера уходят на backend (uvicorn на :8000).
    proxy: {
      "/api": process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
});
